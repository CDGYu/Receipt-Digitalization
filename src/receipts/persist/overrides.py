"""Operator-editable system settings, stored in the database and applied live.

**The problem this solves.** Every tuning knob the system has -- the
auto-approve threshold, who receipts should be addressed to, the spend ceiling
-- lives in ``.env`` and is read into :class:`~config.settings.Settings` at
process start. Changing one means editing a file and restarting, which a
non-developer operator cannot reasonably do. This module lets a curated,
*safe* subset of those knobs be changed from the review UI and take effect on
the running system, with no file edit and no restart.

**Why the database and not ``.env``.** ``.env`` is the wrong home for a
UI-editable value for three concrete reasons found by reading how settings are
consumed (not guessed):

1. The API reads ``get_settings()`` **once at boot** and freezes the result on
   ``app.state.settings``; a ``.env`` edit would be invisible to it until a
   restart. The database, read per request, is not.
2. ``.env`` holds secrets and boot-critical values (``SESSION_SECRET``,
   ``DATABASE_URL``, ``REDIS_URL``) that must never be editable from a web form.
   A database allow-list can exclude them by construction.
3. Two writers to ``.env`` (this UI and a developer's editor) is two sources of
   truth that drift. One database table with the file as the untouched default
   layer underneath it does not.

So this follows the pattern the processing mode already established
(:mod:`receipts.persist.app_settings`): the value lives in the ``app_settings``
table, and an overlay function rewrites a ``Settings`` copy at read time. The
worker rebuilds its settings **per receipt**, so a change is live on the next
receipt; the API applies the overlay **per request**, so a change shows on the
next page load. Neither needs a restart.

**The allow-list is the security boundary.** Only fields named in
:data:`EDITABLE` can be read or written here. Everything else -- every secret,
every value baked into the engine or the session middleware at boot -- is
untouchable through this path, so a bug or a crafted request cannot reach them.
Each editable field carries its own type and a plain-language label and help
string, because the audience is an operator, not a developer reading field
names.

Conventions inherited from the repository layer (ADR-0006), identical to
``users.py`` and ``app_settings.py``: store functions take an explicit
``Session`` first, **the caller commits**, and a bad value raises ``ValueError``
at the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import Settings

from .models import AppSetting

__all__ = [
    "EDITABLE",
    "OVERRIDE_PREFIX",
    "EditableSetting",
    "apply_overrides",
    "clear_override",
    "coerce_value",
    "get_overrides",
    "list_effective",
    "set_override",
]

#: Every override row's key is this prefix plus the ``Settings`` field name, so
#: the general settings never collide with the processing-mode key (or any
#: future singleton) in the shared ``app_settings`` table, and a reader can tell
#: an override row from anything else by its key alone.
OVERRIDE_PREFIX = "override:"


@dataclass(frozen=True)
class EditableSetting:
    """One operator-editable knob: which ``Settings`` field, and how to show it.

    ``field`` is the exact :class:`~config.settings.Settings` attribute name, so
    the value is applied with ``model_copy(update={field: value})`` and validated
    by pydantic against that field's real type -- there is no second type
    declaration here to drift from the model. ``kind`` is the coarse shape the UI
    renders (a checkbox, a number box, a text box); ``label`` and ``help`` are
    the plain-language text a non-developer reads instead of the field name.

    ``group`` clusters related knobs on the screen. ``minimum``/``maximum`` are
    advisory bounds the UI can hint with; the authoritative validation is still
    pydantic building a trial ``Settings``.
    """

    field: str
    label: str
    help: str
    kind: str  # "decimal" | "int" | "bool" | "text" | "model"
    group: str
    minimum: str | None = None
    maximum: str | None = None


#: The allow-list. Deliberately small and deliberately *safe*: every field here
#: is one the worker reads fresh per receipt (so a change is live) and none is a
#: secret or a value baked into the process at boot. Adding a field is a
#: decision to expose it -- boot-critical and secret fields are excluded by
#: their absence, which is the security boundary this module rests on.
EDITABLE: tuple[EditableSetting, ...] = (
    EditableSetting(
        field="auto_approve_threshold",
        label="Auto-approve confidence",
        help=(
            "How sure the system must be before it approves a receipt without a "
            "person checking it. Higher means fewer receipts are auto-approved but "
            "the ones that are, are safer. A value between 0 and 1 (e.g. 0.95)."
        ),
        kind="decimal",
        group="Approval",
        minimum="0",
        maximum="1",
    ),
    EditableSetting(
        field="review_threshold",
        label="Send-to-review confidence",
        help=(
            "Below this confidence a receipt is set aside for a person to review "
            "rather than approved. Should be lower than the auto-approve value. A "
            "value between 0 and 1 (e.g. 0.75)."
        ),
        kind="decimal",
        group="Approval",
        minimum="0",
        maximum="1",
    ),
    EditableSetting(
        field="expected_buyer_name",
        label="Your business name",
        help=(
            "The name your receipts should be addressed to. When set, the system "
            "flags receipts whose “sold to” name does not match. Leave blank to "
            "turn that check off."
        ),
        kind="text",
        group="Your business",
    ),
    EditableSetting(
        field="expected_buyer_tax_id",
        label="Your tax ID",
        help=(
            "Your business's tax identification number, checked against the "
            "receipt the same way as the name above. Leave blank to turn the "
            "check off."
        ),
        kind="text",
        group="Your business",
    ),
    EditableSetting(
        field="default_currency",
        label="Default currency",
        help=(
            "The currency to assume when a receipt does not state one (e.g. PHP, "
            "USD). Leave blank to make no assumption."
        ),
        kind="text",
        group="Your business",
    ),
    EditableSetting(
        field="max_cost_usd_per_receipt",
        label="Spending limit per receipt (USD)",
        help=(
            "The most the online service may spend reading a single receipt before "
            "the system stops and sends it for review instead. Set to 0 to remove "
            "the limit. Only matters when the online service is used."
        ),
        kind="decimal",
        group="Cost & speed",
        minimum="0",
    ),
    EditableSetting(
        field="consistency_enabled",
        label="Double-check handwritten receipts",
        help=(
            "Reads each handwritten receipt several times and compares the results "
            "to catch misread numbers. More accurate on hard receipts, but slower "
            "and more expensive on exactly those receipts."
        ),
        kind="bool",
        group="Accuracy",
    ),
    EditableSetting(
        field="consistency_runs",
        label="How many times to re-read",
        help=(
            "When double-checking is on, how many independent reads to compare. "
            "Three is the usual choice. Higher is more thorough but slower. Has no "
            "effect unless double-checking is on."
        ),
        kind="int",
        group="Accuracy",
        minimum="2",
    ),
    EditableSetting(
        field="max_repair_attempts",
        label="Retry attempts on errors",
        help=(
            "When a receipt's numbers do not add up, how many times to ask the "
            "model to fix its reading before giving up and sending it for review."
        ),
        kind="int",
        group="Accuracy",
        minimum="0",
    ),
    # The four model ids. Editable because switching to a newly pulled Ollama
    # model should not need a developer or a restart -- the worker rebuilds its
    # settings per receipt, so a change here is live on the next one. They sit in
    # their own "Models" group with a warning because they are the highest-impact
    # knobs in the file: a name that does not match a model the provider actually
    # serves makes every receipt fail extraction and land in review until it is
    # corrected, where a wrong threshold merely shifts the approval rate. The
    # provider validates the name, not this layer -- there is no way from here to
    # know what Ollama has pulled -- so the help points a reader at `ollama list`.
    #
    # "Local" and "online" match the processing-mode picker's language rather than
    # "primary/fallback": the mode overlay runs AFTER these overrides, so it reads
    # whatever model id is set here and then decides which rung(s) run. The two
    # controls are complementary -- these say *which* models, the mode says which
    # of them are used.
    EditableSetting(
        field="vlm_model_extract",
        label="Reading model (this computer)",
        help=(
            "The model this computer uses to read receipts. Must exactly match a "
            "model the provider has available — for local Ollama, run “ollama "
            "list” to see the names. A wrong name makes every receipt fail and go "
            "to review."
        ),
        kind="model",
        group="Models (advanced)",
    ),
    EditableSetting(
        field="vlm_model_triage",
        label="Sorting model (this computer)",
        help=(
            "The model this computer uses to first look at a receipt and decide "
            "how to handle it. Same rules as the reading model above; leave blank "
            "to reuse the reading model for this step too."
        ),
        kind="model",
        group="Models (advanced)",
    ),
    EditableSetting(
        field="vlm_model_extract_fallback",
        label="Reading model (online service)",
        help=(
            "The online model used to read a receipt when this computer is too "
            "slow or cannot read it (Hybrid mode), or for every receipt (Online "
            "mode). Leave blank if there is no online service set up."
        ),
        kind="model",
        group="Models (advanced)",
    ),
    EditableSetting(
        field="vlm_model_triage_fallback",
        label="Sorting model (online service)",
        help=(
            "The online model used to sort a receipt when this computer is too "
            "slow (Hybrid mode). Leave blank to keep sorting on this computer."
        ),
        kind="model",
        group="Models (advanced)",
    ),
)

#: Field name -> its :class:`EditableSetting`, for O(1) allow-list checks.
_BY_FIELD: dict[str, EditableSetting] = {item.field: item for item in EDITABLE}


def _key_for(field: str) -> str:
    return f"{OVERRIDE_PREFIX}{field}"


def coerce_value(field: str, raw: str) -> Any:
    """Turn a stored/received string into the type ``field`` expects.

    Values live in the DB as text (the ``app_settings.value`` column is
    ``Text``) and arrive from the UI as JSON strings, but ``Settings`` types them
    as ``Decimal``/``int``/``bool``/``str``. This is the one place that mapping
    lives. It raises ``ValueError`` -- not a pydantic error -- on text that
    cannot be the field's type, so the message names the field in operator terms.

    ``Decimal`` never goes through ``float`` (ADR-0001): a threshold parsed as a
    float would reintroduce exactly the rounding drift the money path exists to
    avoid.
    """
    item = _BY_FIELD.get(field)
    if item is None:
        raise ValueError(f"{field!r} is not an editable setting")

    text = raw.strip()
    if item.kind in ("text", "model"):
        # A blank field means "unset" -- the same as never having set it, which
        # turns the associated check off (text) or falls back to the .env value
        # (model). Stored as empty; applied as None. `model` coerces exactly like
        # `text` -- a model id is a plain string the provider validates, not this
        # layer -- and is only a distinct kind so the UI can group and warn about
        # it (a wrong name makes every receipt fail extraction, unlike a wrong
        # threshold).
        return text or None
    if item.kind == "bool":
        lowered = text.lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"{item.label!r} must be true or false, not {raw!r}")
    if item.kind == "int":
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(f"{item.label!r} must be a whole number, not {raw!r}") from exc
    if item.kind == "decimal":
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{item.label!r} must be a number, not {raw!r}") from exc
    # Unreachable: `kind` is fixed by EDITABLE, which only uses the four above.
    raise ValueError(f"unknown setting kind {item.kind!r}")  # pragma: no cover


def get_overrides(session: Session) -> dict[str, str]:
    """Every stored override, as ``{field: stored_string}``.

    Reads only rows whose key carries :data:`OVERRIDE_PREFIX` and whose field is
    still in the allow-list -- a row left behind by a removed field is ignored
    rather than applied, so shrinking :data:`EDITABLE` cannot resurrect a value
    the code no longer understands.
    """
    rows = session.scalars(
        select(AppSetting).where(AppSetting.key.startswith(OVERRIDE_PREFIX))
    )
    result: dict[str, str] = {}
    for row in rows:
        field = row.key[len(OVERRIDE_PREFIX) :]
        if field in _BY_FIELD:
            result[field] = row.value
    return result


def set_override(session: Session, field: str, raw: str, *, updated_by: str | None = None) -> Any:
    """Store one override after checking it against the real ``Settings`` type.

    Flushes; does not commit. Raises ``ValueError`` for a field outside the
    allow-list, for text that cannot be coerced to the field's type, and for a
    value the field's own pydantic validation rejects (a negative count, a
    threshold that is not a number). Returns the coerced value on success.

    The validation is a *trial* ``Settings`` build -- ``model_copy(update=...)``
    with just this field -- so the rule that decides "valid" is the model's own,
    never a copy of it here that could drift. A blank text value clears the check
    and is stored as an empty string, which reads back as ``None``.
    """
    if field not in _BY_FIELD:
        raise ValueError(f"{field!r} is not an editable setting")

    item = _BY_FIELD[field]
    value = coerce_value(field, raw)

    # Validate against the model itself, so the rule that decides "valid" is
    # pydantic's own and there is no second copy of it here to drift.
    try:
        _validate_field(field, value)
    except ValidationError as exc:
        raise ValueError(_first_message(exc)) from exc

    # The model types several of these as a plain ``int``/``Decimal`` with no
    # range, so pydantic accepts a negative retry count or a threshold above 1.
    # The advisory bounds are the operator-facing rule, and here they are
    # enforced rather than merely hinted, because a nonsensical threshold is
    # exactly the kind of change this UI exists to make safe.
    _check_bounds(item, value)

    stored = "" if value is None else str(value)
    key = _key_for(field)
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=stored, updated_by=updated_by))
    else:
        row.value = stored
        row.updated_by = updated_by
    session.flush()
    return value


def _validate_field(field: str, value: Any) -> None:
    """Raise ``pydantic.ValidationError`` if ``value`` is not valid for ``field``.

    Constructs a trial ``Settings`` with only this field set -- which forces
    pydantic to validate its type and constraints -- rather than
    ``model_copy``, which does not re-validate. ``_env_file=None`` keeps the
    trial from reading ``.env`` and failing on some *other* field the operator
    has not touched, so the only thing under test is this one value.
    """
    Settings(_env_file=None, **{field: value})


def _check_bounds(item: EditableSetting, value: Any) -> None:
    """Enforce an editable setting's advisory ``minimum``/``maximum``.

    Raises ``ValueError`` in operator terms. Skips ``None`` (a cleared text
    field has no magnitude) and any field with no bound declared. Bounds are
    compared as ``Decimal`` so an ``int`` and a ``Decimal`` field share one code
    path and neither goes through ``float``.
    """
    if value is None or isinstance(value, bool):
        return
    if item.minimum is None and item.maximum is None:
        # Nothing to check, and the value may not even be numeric (a text field).
        return
    magnitude = Decimal(str(value))
    if item.minimum is not None and magnitude < Decimal(item.minimum):
        raise ValueError(f"{item.label!r} must be at least {item.minimum}")
    if item.maximum is not None and magnitude > Decimal(item.maximum):
        raise ValueError(f"{item.label!r} must be at most {item.maximum}")


def _first_message(exc: ValidationError) -> str:
    """The first human-usable line from a pydantic error, or a generic fallback."""
    errors = exc.errors()
    if errors and isinstance(errors[0].get("msg"), str):
        return errors[0]["msg"]
    return "invalid value"


def clear_override(session: Session, field: str) -> None:
    """Remove one override so the field falls back to its ``.env``/default value.

    Flushes; does not commit. A field with no row is already at its default, so
    clearing it is a no-op rather than an error -- the same forgiving shape
    ``set`` has.
    """
    if field not in _BY_FIELD:
        raise ValueError(f"{field!r} is not an editable setting")
    row = session.get(AppSetting, _key_for(field))
    if row is not None:
        session.delete(row)
        session.flush()


def apply_overrides(settings: Settings, overrides: dict[str, str]) -> Settings:
    """Return a copy of ``settings`` with every valid override applied.

    The overlay the run paths and the API use. A stored value that no longer
    coerces (a field's type changed under an old row, say) is skipped rather
    than raising: an unreadable preference must never stop a receipt from being
    processed or a page from loading. ``overrides`` is what
    :func:`get_overrides` returned, so its keys are already allow-listed.
    """
    if not overrides:
        return settings
    update: dict[str, Any] = {}
    for field, raw in overrides.items():
        item = _BY_FIELD.get(field)
        if item is None:
            continue
        try:
            value = coerce_value(field, raw)
        except ValueError:
            continue
        # A blank `model` override must NOT overwrite the configured model with
        # `None` -- that would build a rung with no model and fail every receipt.
        # Blank means "unset the override", i.e. fall back to the .env value, so
        # it is skipped here. (Through the route a blank already deletes the row;
        # this guards a blank string that reaches the overlay by any path.) A
        # blank `text` field is different: `None` there is the intended "off",
        # so it still applies.
        if item.kind == "model" and value is None:
            continue
        update[field] = value
    if not update:
        return settings
    return settings.model_copy(update=update)


def list_effective(session: Session, settings: Settings) -> list[dict[str, Any]]:
    """Every editable setting with its current effective value, for the UI.

    One row per :data:`EDITABLE` entry, in declaration order, carrying the
    plain-language label/help, the field's coarse kind and group, the value now
    in force (the override if one is stored, else the ``.env``/default from
    ``settings``), the underlying default, and whether the value came from an
    override or the default. That last flag is what lets the UI show a "reset to
    default" affordance only where there is something to reset.
    """
    overrides = get_overrides(session)
    rows: list[dict[str, Any]] = []
    for item in EDITABLE:
        overridden = item.field in overrides
        if overridden:
            try:
                effective = coerce_value(item.field, overrides[item.field])
            except ValueError:
                overridden = False
                effective = getattr(settings, item.field)
        else:
            effective = getattr(settings, item.field)
        default = getattr(settings, item.field)
        rows.append(
            {
                "field": item.field,
                "label": item.label,
                "help": item.help,
                "kind": item.kind,
                "group": item.group,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "value": _json_scalar(effective),
                "default": _json_scalar(default),
                "source": "override" if overridden else "default",
            }
        )
    return rows


def _json_scalar(value: Any) -> Any:
    """A settings value as a JSON-safe scalar of shape ``str | bool | None``.

    ``bool`` stays a real boolean (the UI renders a checkbox); ``None`` stays
    ``None`` (a blank text field). Everything else -- ``Decimal`` and ``int`` --
    becomes a *string*: a decimal must never cross the wire as a JSON number a
    float could corrupt (ADR-0001), and an int is typed into a text box anyway,
    so a single string path matches what both the response model and the
    frontend declare.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    # Everything non-boolean is sent as a string: a Decimal must not become a
    # JSON number (ADR-0001), and an int is edited as text in the form anyway,
    # so one string path keeps the wire shape `str | bool | None` -- the type
    # the response model and the frontend both declare.
    return str(value)

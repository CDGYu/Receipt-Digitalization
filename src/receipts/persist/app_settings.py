"""Operator-editable runtime settings, and the one that exists today: the
processing mode (pure-local, pure-cloud, hybrid).

**Why a module and not just a column read.** The processing mode is the first
knob the operator can change *while the system runs* rather than at deploy time,
so it has two halves that have to agree: a persisted value (the ``app_settings``
row) and a transformation of :class:`~config.settings.Settings` that turns that
value into the model rungs the extract ladder actually builds. Keeping both here
means the DB token and its meaning are owned in one place -- the same shape
:mod:`receipts.persist.users` uses for roles, where the DB stores a string and
this layer validates it.

Conventions inherited from the repository layer (ADR-0006), identical to
``users.py``: every store function takes an explicit ``Session`` first, **the
caller commits**, and a bad argument raises ``ValueError`` at the boundary.

The mode maps onto the existing ladder (``extract.clients.factory``) by
*rewriting the settings*, not by reaching into the factory. That factory has one
construction site every runner shares, and its docstrings repeatedly record what
goes wrong when a second path is wired separately. So this module never builds a
client; it hands ``make_extract_ladder`` a ``Settings`` whose model fields
already describe the rungs the mode wants:

* ``hybrid`` -- unchanged. The local model is the primary rung and the cloud
  model is its fallback, which is exactly what a configured
  ``VLM_MODEL_EXTRACT_FALLBACK`` already produces.
* ``local`` -- drop both fallback models. With no fallback the ladder is a
  single local rung and never escalates to the cloud (``_build_ladder``'s
  ``escalates = bool(fallback_model)``).
* ``cloud`` -- promote the cloud (fallback) model into the primary field and
  drop the fallback. The ladder is then a single rung that talks to the cloud
  model, with no local attempt at all.

**Cloud mode needs a cloud model to promote.** When ``local`` is the only model
configured (no ``*_fallback``), asking for ``cloud`` cannot invent an endpoint,
so :func:`apply_processing_mode` leaves the local model in place rather than
clearing it and producing a ladder with no rungs at all. That is the honest
degradation: a deployment that never configured a cloud tier gets local
behaviour whichever of local/hybrid/cloud it picks, and the UI advertises which
modes are actually distinct via :func:`available_modes`.
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from config.settings import Settings

from .models import AppSetting

__all__ = [
    "PROCESSING_MODES",
    "PROCESSING_MODE_KEY",
    "DEFAULT_PROCESSING_MODE",
    "MODE_HYBRID",
    "MODE_LOCAL",
    "MODE_CLOUD",
    "apply_processing_mode",
    "available_modes",
    "get_processing_mode",
    "set_processing_mode",
    "settings_for_run",
]

MODE_LOCAL = "local"
MODE_CLOUD = "cloud"
MODE_HYBRID = "hybrid"

#: The three modes, in the order the UI offers them: the everyday default first,
#: then the two pure ends.
PROCESSING_MODES: tuple[str, ...] = (MODE_HYBRID, MODE_LOCAL, MODE_CLOUD)

#: The ``app_settings.key`` this module owns.
PROCESSING_MODE_KEY = "processing_mode"

#: What an un-configured deployment gets. Hybrid is the behaviour the ladder
#: already produces when both a local and a cloud model are configured, so
#: choosing it as the default changes nothing for an existing deployment that
#: has never touched this setting -- the setting is inert until someone picks
#: something else.
DEFAULT_PROCESSING_MODE = MODE_HYBRID


def _validated_mode(mode: str) -> str:
    if mode not in PROCESSING_MODES:
        raise ValueError(
            f"unknown processing mode {mode!r}; expected one of {sorted(PROCESSING_MODES)}"
        )
    return mode


def get_processing_mode(session: Session) -> str:
    """The stored processing mode, or :data:`DEFAULT_PROCESSING_MODE` if unset.

    A missing row is not an error: it is the state of every deployment that has
    never opened the setting, and the honest answer for it is the default rather
    than a raise. A row holding a value this build no longer recognises (a
    downgrade after a future mode was added, say) also degrades to the default
    rather than propagating a token the ladder cannot map.
    """
    row = session.get(AppSetting, PROCESSING_MODE_KEY)
    if row is None or row.value not in PROCESSING_MODES:
        return DEFAULT_PROCESSING_MODE
    return row.value


def set_processing_mode(session: Session, mode: str, *, updated_by: str | None = None) -> str:
    """Store the processing mode. Flushes; does not commit. ``ValueError`` on a bad value.

    Upserts the singleton row: the first write inserts it, later writes update
    the value and ``updated_by`` in place. ``updated_by`` names the account that
    made the change so the switch is attributable -- ``None`` is allowed for a
    machine or CLI caller that has no session user.
    """
    mode = _validated_mode(mode)
    row = session.get(AppSetting, PROCESSING_MODE_KEY)
    if row is None:
        row = AppSetting(key=PROCESSING_MODE_KEY, value=mode, updated_by=updated_by)
        session.add(row)
    else:
        row.value = mode
        row.updated_by = updated_by
    session.flush()
    return mode


def available_modes(settings: Settings) -> tuple[str, ...]:
    """Which modes are *distinct* for this deployment's model configuration.

    All three are always offered, but they only differ when both a local and a
    cloud model are configured. With no ``*_fallback`` model there is no cloud
    tier to switch to, so ``local``, ``cloud`` and ``hybrid`` would all build the
    same single local rung -- and offering a ``cloud`` radio that silently keeps
    running local would be a control that lies. The UI uses this to disable the
    modes that would be no-ops and to explain why.

    A cloud tier is "configured" when either pass names a fallback model, which
    is the same signal ``_build_ladder`` reads to decide whether the ladder
    escalates.
    """
    has_cloud = bool(settings.vlm_model_extract_fallback or settings.vlm_model_triage_fallback)
    if has_cloud:
        return PROCESSING_MODES
    return (MODE_LOCAL,)


def settings_for_run(
    settings: Settings, session_factory: Callable[[], Session]
) -> Settings:
    """``settings`` with the stored processing mode already applied.

    The one call the run paths make: ``worker.build_deps``,
    ``cli.cmd_process`` and ``cli.cmd_reprocess`` each build their extract
    ladder from a ``Settings``, and each should honour the operator's saved
    mode. Rather than repeat "open a session, read the mode, apply it" at three
    sites -- the exact shape that lets one drift from the others (the factory's
    docstrings record what that costs) -- they call this once.

    It opens its own short-lived session from ``session_factory`` and never
    writes, so it commits nothing. A read that fails (no ``app_settings`` table
    yet on a database migrated only to an older head, say) is not allowed to
    stop a worker from starting: the mode falls back to the default, which is
    ``hybrid`` -- the unchanged pre-feature behaviour -- so a run is never
    blocked on this preference being readable.

    **It also applies the operator's saved system-setting overrides** (the
    threshold, the buyer identity, the cost ceiling -- see
    :mod:`receipts.persist.overrides`), because those are exactly the values
    ``process_receipt`` reads off the ``Settings`` it is handed, and the worker
    calls this per receipt. So a change an admin makes in the UI is live on the
    next receipt with no restart, through the same one seam the mode uses. The
    overlay is applied first and the mode second, so the mode's model-field
    rewrite always wins over any (deliberately non-editable) model field.
    """
    from .overrides import apply_overrides, get_overrides

    try:
        with session_factory() as session:
            mode = get_processing_mode(session)
            overrides = get_overrides(session)
    except Exception:
        mode = DEFAULT_PROCESSING_MODE
        overrides = {}
    return apply_processing_mode(apply_overrides(settings, overrides), mode)


def apply_processing_mode(settings: Settings, mode: str) -> Settings:
    """Return a copy of ``settings`` whose model fields describe ``mode``'s rungs.

    This is the whole of how a mode reaches the extract ladder: the three real
    call sites (``worker.build_deps``, ``cli.cmd_process``, ``cli.cmd_reprocess``)
    read the stored mode and pass ``apply_processing_mode(settings, mode)`` to
    ``make_extract_ladder`` instead of the raw settings. The factory is untouched
    -- it still just reads which model fields are set -- so there is no second
    construction path to drift.

    ``ValueError`` on an unrecognised mode: a caller that reads the mode from the
    DB gets a validated token from :func:`get_processing_mode`, but a caller that
    passes a literal should fail loudly rather than silently fall through to
    hybrid.

    See the module docstring for the mapping and for why ``cloud`` degrades to
    the local model when no cloud tier is configured.
    """
    mode = _validated_mode(mode)

    if mode == MODE_HYBRID:
        return settings

    if mode == MODE_LOCAL:
        # Drop both fallbacks: a ladder with no fallback is a single local rung
        # that never escalates. The primary tool flags are already the local
        # ones, so nothing else moves.
        return settings.model_copy(
            update={
                "vlm_model_extract_fallback": None,
                "vlm_model_triage_fallback": None,
            }
        )

    # MODE_CLOUD: the cloud model becomes the sole rung. Promote the fallback
    # model into the primary field, and carry the fallback's tool flag with it
    # so the promoted rung is configured the way the cloud rung would have been.
    # When no cloud model is configured the promotion is a no-op (`or` keeps the
    # local model), which is the honest degradation the module docstring
    # describes -- never a cleared primary that would build a rungless ladder.
    return settings.model_copy(
        update={
            "vlm_model_extract": settings.vlm_model_extract_fallback
            or settings.vlm_model_extract,
            "vlm_model_triage": settings.vlm_model_triage_fallback
            or settings.vlm_model_triage
            or settings.vlm_model_extract_fallback
            or settings.vlm_model_extract,
            "vlm_model_extract_fallback": None,
            "vlm_model_triage_fallback": None,
            # The promoted primary should use the cloud rung's tool decision, not
            # the local one. `vlm_use_tools_fallback` is the flag the cloud rung
            # read; move it onto the process-wide default so `resolve_use_tools`
            # picks it up for the now-primary rung. `vlm_use_tools_triage` is a
            # local-granite guard (ISSUE-001) and must not survive onto a cloud
            # primary, so it is cleared.
            "vlm_use_tools": settings.vlm_use_tools_fallback
            if settings.vlm_use_tools_fallback is not None
            else settings.vlm_use_tools,
            "vlm_use_tools_triage": None,
        }
    )

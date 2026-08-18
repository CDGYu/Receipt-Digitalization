# ADR 0002 — VLM provider abstraction + env-based runtime config

**Status:** Accepted

## Context

The pipeline must run against hosted models (Claude, OpenAI, Gemini-via-OpenAI)
and local OpenAI-compatible servers (vLLM/Ollama), stay vendor-agnostic (SPEC
§4, §14.3), and remain fully testable offline with no network or API key.

## Decision

- All model calls go through the `VLMClient` protocol; vendor SDK code lives
  **only** under `src/receipts/extract/clients/`.
- Runtime config is `config/settings.py` (`pydantic-settings`, reads the SPEC
  §17 env vars, e.g. `VLM_PROVIDER`, `VLM_API_KEY`, `VLM_MODEL_EXTRACT`,
  `VLM_BASE_URL`). Money-magnitude settings are `Decimal` (ADR-0001).
- `extract/clients/factory.py::make_client(settings)` maps `VLM_PROVIDER` to a
  concrete client: `fake` → `FakeVLMClient`; `anthropic` → `AnthropicVLMClient`;
  `openai`/`vllm`/`ollama`/`openai_compat` → `OpenAICompatClient`. Vendor SDKs
  (`anthropic`, `openai`) are **optional extras** imported lazily inside their
  branch, so importing the package never requires an SDK.
- `VLM_BASE_URL` overrides the per-provider default endpoint (so a local
  `localhost:11435/v1` server is honored); falls back to the provider default.
- `FakeVLMClient` replays scripted responses → the whole pipeline + `run_eval`
  path is exercised offline (all 292 tests need no network).

## Consequences

- `python -m eval.run_baseline` requires a real provider; the response-less
  default `fake` provider is refused early with an actionable hint.
- **Deferred:** `vllm`/`ollama` currently still require `VLM_API_KEY` (usually a
  placeholder), and `VLM_BASE_URL` is ignored for `anthropic`.

## References

SPEC §4 (stack), §14.3 (client interface), §17 (config); ADR-0005.

## Correction (2026-08-18) — tool-use is still the rule, with one measured exception

**The rule stands.** Schema-constrained tool-use remains how structured output
is obtained. It was measured working on 2026-08-18 against `gemma4:cloud`
through this very abstraction: `finish_reason: tool_calls`, a well-formed
`tool_calls` array, arguments parsed into the requested schema.

**The exception is `granite3.2-vision:2b`, and it is per model, not per
principle.** Measured the same day (`docs/KNOWN_ISSUES.md` ISSUE-001 has the
tables and the anti-vacuity checks): the shim **accepts** a `tools` payload — the
long-recorded fear of a hard 400 does not reproduce — and the extraction comes
back **identical** with tools on or off. But triage loses
`merchant_name_guess`, which `merchants.registry.lookup` keys off, so enabling
tool-use silently disables ADR-0043's hint-retrieval path. **Off is correct for
this model**, and for a reason that is neither of the two previously written
beside `_TOOLS_OFF_BY_DEFAULT`.

This is not a softening. A 2.5B model that reads nothing either way is not
evidence against schema-constrained output; it is evidence about that model.

### The constraint this exposes, which the tier work must solve

**`_TOOLS_OFF_BY_DEFAULT` is keyed on the PROVIDER, and the exception is per
model.** `granite3.2-vision:2b` and `gemma4:cloud` are both provider `ollama`,
so one `VLM_USE_TOOLS` cannot say "off for the local model, on for the cloud
one". Under the two-tier design ISSUE-001 step 5 calls for, that is a real
defect in the knob's granularity rather than a preference.

**Deliberately not fixed here.** Widening the key to `(provider, model)`, or
moving the decision into the tier that selects the client, is a design choice
that belongs with the escalation ADR — which does not exist yet. Recorded so
that work starts from a measured constraint instead of rediscovering it.

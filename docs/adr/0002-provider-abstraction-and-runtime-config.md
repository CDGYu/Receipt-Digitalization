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

# LLM providers

Active Graph ships two concrete `LLMProvider` implementations.
Both expose identical Protocol surface — `complete()`,
`estimate_cost()`, `count_tokens()` — so a runtime swapping one for
the other doesn't reshape any call site. Choose by the model family
you want; everything else is the same.

```python
from activegraph import Graph, Runtime
from activegraph.llm import AnthropicProvider, OpenAIProvider

rt = Runtime(Graph(), llm_provider=AnthropicProvider())  # or:
rt = Runtime(Graph(), llm_provider=OpenAIProvider())
```

## Installing

Pick one of three extras. They install cleanly and don't conflict.

```bash
pip install "activegraph[anthropic]"   # AnthropicProvider only
pip install "activegraph[openai]"      # OpenAIProvider only
pip install "activegraph[llm]"         # both providers
```

The `[openai]` extra also pulls in `tiktoken` so client-side token
counting is accurate; see the count_tokens row below for what
happens when tiktoken is missing.

## API keys

Both providers read their API key from the environment, never from
code or a checked-in config:

```bash
export ANTHROPIC_API_KEY='...'
export OPENAI_API_KEY='...'
```

Override the env-var name via the `api_key_env=` constructor kwarg
if you need a different one (per-environment key rotation, for
example).

## Side-by-side

| Aspect | `AnthropicProvider` | `OpenAIProvider` |
| --- | --- | --- |
| Default model family | `claude-sonnet-4-5` (set on `@llm_behavior`) | `gpt-4o` family |
| API key env | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` |
| SDK | `anthropic>=0.40` | `openai>=1.0` |
| Structured output | Instruction-based: schema + example instance embedded in the system prompt by [`build_system_prompt`](api/index.md); provider parses JSON out of the response via the shared `parse_structured_response` helper | Same path. Native `response_format={"type":"json_schema",...}` mode is a v1.1 candidate |
| `count_tokens()` | Server-side via `messages.count_tokens` (1 roundtrip per call when `budget.max_cost_usd` is set and no cache hit) | Client-side via `tiktoken` when available; char/4 heuristic fallback with a one-time debug log if tiktoken is missing |
| Tool use | Supported (`Tool.to_definition()` emits Anthropic shape) | **Not supported in v1.0.1.** A non-empty `tools=` raises `LLMBehaviorError(reason="llm.network_error")` with a v1.1 pointer. Tool-shape translation is a scheduled v1.1 item |
| Exception mapping | `llm.rate_limited` on 429-shaped errors; `llm.network_error` for everything else (timeouts, connection errors, **auth failures**) | Same mapping |
| Pricing | Family-prefix lookup; override with `pricing=` kwarg | Family-prefix lookup; override with `pricing=` kwarg |

## Mixing with [`RecordedLLMProvider`](api/index.md)

The fixture-backed provider is provider-agnostic: fixtures are keyed
by prompt-content hash, and the model name (`claude-…` or `gpt-…`)
is part of the hash input. Fixtures recorded against one provider
replay against `RecordedLLMProvider` regardless of which live
provider you switch to next.

```python
from activegraph.llm import RecordingLLMProvider, OpenAIProvider

inner = OpenAIProvider()
provider = RecordingLLMProvider(inner, fixtures_dir="tests/fixtures/llm")
```

`RecordingLLMProvider` wraps either concrete provider the same way.
Record once against a live key, commit the fixtures, run tests
against `RecordedLLMProvider` thereafter.

## Writing a custom provider

`LLMProvider` is a runtime-checkable `Protocol`. Any class with the
three methods is a provider — no inheritance required, no
registration step:

```python
from decimal import Decimal
from activegraph.llm import LLMMessage, LLMResponse, LLMProvider

class MyProvider:
    def complete(self, *, system, messages, model, max_tokens,
                 temperature, top_p, output_schema, timeout_seconds,
                 tools=None) -> LLMResponse:
        ...

    def estimate_cost(self, *, input_tokens, output_tokens, model) -> Decimal:
        ...

    def count_tokens(self, *, system, messages, model) -> int:
        ...

assert isinstance(MyProvider(), LLMProvider)
```

If your provider exposes the framework's instruction-based
structured-output path (most do), reuse
`parse_structured_response(text, schema)` from
`activegraph.llm.parsing` for byte-identical error semantics with
the shipped providers — same `llm.parse_error` and
`llm.schema_violation` reason codes for the same response shapes.

See [CONTRACT v1.0.1 #5](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md)
for the provider-commitment surface: which methods are stable,
which behaviors are provider-dependent (`count_tokens`), and which
capabilities are explicitly v1.1 (tool use for OpenAI, native
structured-output modes).

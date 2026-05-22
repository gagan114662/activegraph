# T4 D-1 Spec Skeptic second pass - provider tool-shape boundary

Reviewed amendment: `frames/t4-amendments/D-1.md`

Reviewed clarification commit: `inner:7ae37da`

Prior challenge: `frames/t4-skeptic/D-1-challenge.md` (`inner:329c2b4`)

Scope: D-1 clarification only.

## Verdict

PASS. The clarification closes both D-1 gaps from the first challenge.

## Cleared findings

### D1-G1 - second-turn OpenAI echo

Cleared by `frames/t4-amendments/D-1.md:76-88` and test hook
`frames/t4-amendments/D-1.md:149-150`.

The amendment now requires the OpenAI fake-client test to inspect the second SDK
call after a tool invocation and assert both:

- the previous assistant message contains OpenAI-native `tool_calls`; and
- the following tool-result message has `role="tool"` and a matching
  `tool_call_id`.

This is the missing assertion path identified against
`activegraph/llm/openai.py:330-343` and
`activegraph/runtime/runtime.py:1110-1116`, `:1176-1181`, `:1487-1492`.

### D1-G2 - malformed direct-provider tool dicts

Cleared by `frames/t4-amendments/D-1.md:90-104` and test hook
`frames/t4-amendments/D-1.md:151-152`.

The amendment now keeps malformed direct-provider calls in scope, defines the
invalid shapes, requires pre-SDK failure, and pins the existing reason
`llm.prompt_assembly_error`. That prevents both uncaught `KeyError` and invalid
OpenAI payload emission from malformed `LLMProvider.complete(..., tools=...)`
input (`activegraph/llm/provider.py:54-66`).

## Residual gaps

None found in D-1 after `inner:7ae37da`.

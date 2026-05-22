# T4 D-1 Spec Skeptic challenge - provider tool-shape boundary

Reviewed amendment: `frames/t4-amendments/D-1.md`

Reviewed commit: `inner:261c3b4`

Scope: D-1 only.

## Verdict

PASS WITH REQUIRED TEST CLARIFICATIONS. The chosen boundary is coherent:
`Tool.to_definition()` remains the internal/Anthropic shape, and OpenAI owns
wire-format translation at request time.

Do not block Code Owner on the boundary choice. Do tighten the tests so the
implementation cannot satisfy D-1 while leaving a provider-turn gap.

## Findings

### D1-G1 - OpenAI tool-result turn is only half-specified

`frames/t4-amendments/D-1.md:66-68` binds `_message_to_openai` to support
assistant messages carrying `LLMMessage.tool_calls` by emitting OpenAI
assistant `tool_calls` entries with canonical JSON arguments. That covers the
assistant tool-call echo.

The paired tool-result echo already exists for OpenAI in
`activegraph/llm/openai.py:330-343`: `role="tool"` maps to
`{"role": "tool", "tool_call_id": ..., "content": ...}`. Runtime depends on
that second turn after every tool call:

- `activegraph/runtime/runtime.py:1110-1116` appends the assistant message with
  `tool_calls`.
- `activegraph/runtime/runtime.py:1176-1181` appends the tool-result message.
- `activegraph/runtime/runtime.py:1487-1492` constructs that tool-result
  `LLMMessage`.

Gap: D-1 test hooks only require the initial SDK `tools=[...]` shape
(`frames/t4-amendments/D-1.md:95-99`). They do not require a second OpenAI SDK
call whose `messages` include both:

1. the previous assistant message with OpenAI `tool_calls`; and
2. the following tool message with matching `tool_call_id`.

Required patch: add a D-1 or D-3 test hook that inspects the second OpenAI SDK
call after one tool invocation and asserts the assistant/tool echo pair is
OpenAI-valid. Otherwise Code Owner can implement only first-request tool shape
translation and still pass D-1 unit tests while the runtime-owned tool loop
breaks on the next provider call.

### D1-G2 - Tool schema fallback is specified, but invalid internal shape handling is not

`frames/t4-amendments/D-1.md:30-38` says OpenAI translation uses
`tool.get("input_schema", {"type": "object", "properties": {}})` as
`function.parameters`.

The source of normal tool definitions is safe:
`activegraph/tools/base.py:49-56` always emits `input_schema`, falling back to
`{"type": "object", "properties": {}}` when no schema exists.

Gap: the provider boundary receives plain `dict[str, Any]` via
`LLMProvider.complete(..., tools=...)` (`activegraph/llm/provider.py:54-66`).
D-1 does not say what OpenAIProvider should do if a custom runtime/provider
caller passes malformed internal tool dicts, e.g. missing `"name"` or
`input_schema=None`.

Required patch: either explicitly out-of-scope malformed direct-provider calls,
or require `_tool_to_openai` to fail loud before the SDK call with an existing
reason taxonomy if required fields are absent/non-string. Without this, the
adapter can raise `KeyError` outside the existing provider exception mapping or
send an invalid OpenAI payload.

## Cleared assumptions

- D-1's provider-owned translation choice matches the current runtime call
  path: runtime builds `tool_defs = [t.to_definition() ...]` once at
  `activegraph/runtime/runtime.py:901` and passes it unchanged to
  `LLMProvider.complete` at `activegraph/runtime/runtime.py:1044-1054`.
- Anthropic passthrough remains the right compatibility anchor:
  `activegraph/llm/anthropic.py:132-135` forwards `tools` unchanged.

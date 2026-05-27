# Provider Tool Parity

Provider tool parity means an `@llm_behavior` can ask for the same
framework `Tool` objects whether the runtime is backed by
`AnthropicProvider` or `OpenAIProvider`. The provider translates the
wire shape; the runtime owns the behavior loop, event sequence, cache
boundary, and failure vocabulary.

## Contract

The stable framework contract is:

- Behavior authors pass framework `Tool` objects through runtime
  policy, not provider-native tool dictionaries.
- `AnthropicProvider` sends Anthropic's
  `{name, description, input_schema}` shape.
- `OpenAIProvider` sends OpenAI's
  `{type: "function", function: {name, description, parameters}}`
  shape.
- Both providers return requested tool calls as
  `LLMResponse.tool_calls`.
- The runtime emits `tool.requested`, dispatches the tool, appends
  the provider-specific tool result message, and continues the same
  LLM behavior loop.

Provider adapters may translate message and tool-call envelopes, but
they do not invent new behavior events or reason codes.

## OpenAI translation

`OpenAIProvider` translates every framework tool definition before the
SDK request. Malformed framework tool dictionaries fail before the SDK
call and surface through the existing LLM behavior error path.

OpenAI assistant responses with `tool_calls` are normalized into the
shared `LLMResponse.tool_calls` model. Tool-result messages are sent
back as OpenAI `role="tool"` messages with the matching
`tool_call_id`.

The normalized event payload stays provider-neutral. Valid
`llm.responded.tool_calls` entries serialize as `id`, `name`, and
`args`. When OpenAI returns malformed tool-call arguments, the provider
keeps the rejection marker internal; the recorded tool-call entry still
uses only `id`, `name`, and `args`. `LLMResponse.to_dict()` also
filters the private provider metadata marker. LLM-cache replay and
recorded fixture hydration keep that boundary: if a fixture or older
event payload carries `invalid_args_error`, hydration ignores it.
Invalid-tool-input LLM turns are skipped for durable replay instead of
being restored from provider metadata.

## Runtime-owned parsing

For providers that declare `runtime_parses_output = True`, the
provider returns final assistant text without applying the structured
output parser. The runtime records `llm.responded` first, then parses
the final text against the behavior output schema. If parsing fails,
the existing `behavior.failed` event is emitted after the LLM response
evidence is in the log.

This preserves replayability: the event log contains the final provider
text that caused the parse failure.

## Failure semantics

T4 does not add reason codes. The existing vocabulary remains the
operator surface:

- Provider/network failures still map to `llm.network_error` or
  provider-specific existing LLM reasons such as `llm.rate_limited`.
- Invalid tool arguments still use `tool.invalid_input`, including
  OpenAI tool calls whose raw `arguments` JSON is malformed or does
  not decode to an object.
- Structured-output parse failures still use the existing LLM parse or
  schema violation path, surfaced through `behavior.failed`.

Recorded fixtures cover OpenAI tool-call replay without live network
access, and parity tests assert that Anthropic and OpenAI runs produce
the same normalized behavior/tool event shape.

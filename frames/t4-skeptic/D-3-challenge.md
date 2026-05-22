# T4 D-3 Spec Skeptic challenge - provider parity fixture strategy

Reviewed amendment: `frames/t4-amendments/D-3.md`

Reviewed commit: `inner:104ab0c`

Scope: D-3 only.

## Verdict

BLOCKING PATCH REQUESTED. The fake-provider-boundary strategy is the right
direction, but D-3 has two ambiguities that can make Theo write parity tests
that are either impossible against the runtime's actual event log or too weak
to catch provider-loop drift.

## Findings

### D3-G1 - "same Graph" is ambiguous and unsafe

`frames/t4-amendments/D-3.md:21-25` says the parity test runs the same
`@llm_behavior`, same `@tool`, same `Graph`, same `Runtime` budget, and same
output schema twice.

The runtime mutates the graph on every run:

- `activegraph/runtime/runtime.py:560-580` emits `goal.created` onto
  `self.graph`.
- `activegraph/runtime/runtime.py:627-661` drains queued graph events and
  invokes matching behaviors.
- `activegraph/runtime/runtime.py:989-1088` emits `llm.requested` and
  `llm.responded`.
- `activegraph/runtime/runtime.py:1358-1372` and
  `activegraph/runtime/runtime.py:1456-1472` emit `tool.requested` and
  `tool.responded`.

If Theo literally reuses the same `Graph` object for Anthropic then OpenAI, the
second run starts with the first provider's event history and objects already
present. That is not provider parity; it is cross-run contamination.

Required patch: replace "same Graph" with "same freshly constructed initial
graph fixture" or "two fresh Graph instances created by the same factory with
the same deterministic clock/id seed." Add a precondition assert that the two
graphs have identical seed state before the provider run.

### D3-G2 - Expected event sequence omits runtime lifecycle events without saying they are filtered

`frames/t4-amendments/D-3.md:38-51` lists this sequence:

```text
goal.created
llm.requested
llm.responded
tool.requested
tool.responded
llm.requested
llm.responded
object.created
```

The runtime actually emits lifecycle events around both normal and LLM
behaviors:

- normal behavior start/complete:
  `activegraph/runtime/runtime.py:781-827`
- LLM behavior start:
  `activegraph/runtime/runtime.py:875-883`
- LLM behavior complete:
  `activegraph/runtime/runtime.py:1254-1266`

If the test compares all `graph.events` types, D-3's listed sequence is false.
If the test filters lifecycle events, D-3 needs to say that explicitly and
define the filter.

Required patch: specify the normalization filter, e.g. include only
`goal.created`, `llm.*`, `tool.*`, and final user-domain `object.created`, or
update the listed expected sequence to include lifecycle events. Without this,
Theo can write a brittle test that disagrees with actual runtime behavior.

### D3-G3 - Second-turn OpenAI message shape must be asserted in the parity fixture

D-3 correctly rejects a runtime-only `ScriptedProvider` because it would bypass
OpenAI wire shape (`frames/t4-amendments/D-3.md:32-34`). But the parity
comparison fields at `frames/t4-amendments/D-3.md:53-74` only inspect emitted
events. They do not require inspecting the fake OpenAI client's received
messages.

Runtime's tool loop specifically relies on the provider adapter reconstructing
provider-native assistant/tool messages on turn two:

- `activegraph/runtime/runtime.py:1110-1116` appends assistant `tool_calls`.
- `activegraph/runtime/runtime.py:1176-1181` appends the tool result.
- `activegraph/llm/openai.py:330-343` currently converts only plain messages
  and tool-result messages; D-1 requires assistant `tool_calls` support at
  `frames/t4-amendments/D-1.md:66-68`.

Required patch: the OpenAI fake parity fixture must record both SDK calls and
assert call 2's `messages` contain an assistant message with `tool_calls` plus a
tool message with the same `tool_call_id`. Event parity alone can pass if the
provider returns canned responses while emitting an invalid second-turn OpenAI
request shape.

### D3-G4 - Failure fixture matrix does not define whether parity compares partial streams or terminal reasons only

The matrix at `frames/t4-amendments/D-3.md:76-85` requires invalid args,
unknown tool, and final parse failure fixtures. The event-field list includes
`behavior.failed.reason` "if any failure path is being tested"
(`frames/t4-amendments/D-3.md:62`).

Runtime failure paths differ in where the terminal event lands:

- invalid tool input emits `tool.requested`, `tool.responded(error=...)`, then
  `behavior.failed` (`activegraph/runtime/runtime.py:1291-1333`);
- unknown tool emits `behavior.failed` before `_invoke_tool`, so there is no
  `tool.requested`/`tool.responded` pair
  (`activegraph/runtime/runtime.py:1140-1162`);
- final parse failure emits `behavior.failed` after the final LLM response
  (`activegraph/runtime/runtime.py:1222-1237`).

Required patch: for failure fixtures, define expected partial event type
sequences per fixture, not only terminal reason parity. Otherwise tests can
assert the same reason while missing provider-specific extra/missing tool events.

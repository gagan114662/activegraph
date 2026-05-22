# T4 D-3 Spec Skeptic second pass - provider parity fixture strategy

Reviewed amendment: `frames/t4-amendments/D-3.md`

Reviewed clarification commit: `inner:2f82f19`

Prior challenge: `frames/t4-skeptic/D-3-challenge.md` (`inner:329c2b4`)

Scope: D-3 clarification only.

## Verdict

PASS. The clarification closes the D-3 blockers from the first challenge.

## Cleared findings

### D3-G1 - fresh graph fixture isolation

Cleared by `frames/t4-amendments/D-3.md:45-55`.

The amendment replaces ambiguous "same Graph" reuse with two fresh `Graph`
instances from the same deterministic fixture factory and requires a pre-run
seed-state equality assertion. That prevents contamination from provider run 1
into provider run 2, which was the runtime mutation risk cited against
`activegraph/runtime/runtime.py:560-580`, `:627-661`, `:989-1088`, and
`:1358-1372`.

### D3-G2 - lifecycle filtering / normalization

Cleared by `frames/t4-amendments/D-3.md:105-119`.

The amendment defines the T4 parity event filter and makes lifecycle events
excluded by default. The happy-path sequence at
`frames/t4-amendments/D-3.md:121-132` is now explicitly a normalized sequence,
not a raw `graph.events` sequence, so it no longer conflicts with runtime
lifecycle emissions at `activegraph/runtime/runtime.py:781-827`,
`:875-883`, and `:1254-1266`.

### D3-G3 - second-turn OpenAI message shape

Cleared by `frames/t4-amendments/D-3.md:57-67`.

The OpenAI fake must record both SDK calls and assert call 2 contains an
assistant `tool_calls` message followed by a `role="tool"` message whose
`tool_call_id` matches. Event parity alone is no longer sufficient.

### D3-G4 - failure fixtures compare partial streams

Cleared by `frames/t4-amendments/D-3.md:69-103`.

The amendment now pins per-fixture partial event type sequences for invalid
args, unknown tool, and final parse failure, plus terminal reasons
`tool.invalid_input`, `tool.unknown_tool`, and `llm.parse_error`. The expected
presence or absence of `tool.requested` / `tool.responded` is now explicit for
the runtime branches cited at `activegraph/runtime/runtime.py:1140-1162`,
`:1222-1237`, and `:1291-1333`.

## Residual gaps

None found in D-3 after `inner:2f82f19`.

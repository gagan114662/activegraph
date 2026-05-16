"""RecordedLLMProvider + RecordingLLMProvider (CONTRACT v0.6 #12 +
decision-3 adjustment).

Recording produces fixtures keyed by prompt hash with `recorded_at`
outside the hashed content. Recorded mode reads them. Missing fixture
raises so tests fail loud rather than silently calling out.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from decimal import Decimal

import pytest
from pydantic import BaseModel

from activegraph.llm import (
    LLMBehaviorError,
    LLMMessage,
    LLMResponse,
    RecordedLLMProvider,
    RecordingLLMProvider,
)


class _Out(BaseModel):
    n: int


class _StubInner:
    def __init__(self):
        self.calls = []

    def complete(self, **kw):
        self.calls.append(kw)
        return LLMResponse(
            raw_text='{"n": 1}',
            parsed=_Out(n=1),
            input_tokens=5,
            output_tokens=2,
            cost_usd=Decimal("0.0001"),
            latency_seconds=0.05,
            model=kw["model"],
            finish_reason="end_turn",
        )

    def estimate_cost(self, **kw):
        return Decimal("0.0001")

    def count_tokens(self, **kw):
        return 5


def _kwargs():
    return dict(
        system="sys",
        messages=[LLMMessage(role="user", content="hi")],
        model="claude-sonnet-4-5",
        max_tokens=64,
        temperature=0.0,
        top_p=1.0,
        output_schema=_Out,
        timeout_seconds=30.0,
    )


def test_recording_writes_fixture_with_recorded_at_outside_hash():
    with tempfile.TemporaryDirectory() as td:
        inner = _StubInner()
        rec = RecordingLLMProvider(inner, td)
        rec.complete(**_kwargs())
        files = os.listdir(td)
        assert len(files) == 1
        path = os.path.join(td, files[0])
        with open(path) as f:
            data = json.load(f)
        # recorded_at present, but it's NOT inside the hashed `prompt` blob
        assert "recorded_at" in data
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", data["recorded_at"]
        )
        assert "recorded_at" not in data["prompt"]
        # The filename matches the hash inside.
        assert files[0] == f"{data['prompt_hash']}.json"


def test_recorded_provider_reads_back_response():
    with tempfile.TemporaryDirectory() as td:
        inner = _StubInner()
        RecordingLLMProvider(inner, td).complete(**_kwargs())
        recorded = RecordedLLMProvider(td)
        response = recorded.complete(**_kwargs())
        assert response.raw_text == '{"n": 1}'
        # Parsed re-validates against schema → Pydantic instance.
        assert isinstance(response.parsed, _Out)
        assert response.parsed.n == 1


def test_recorded_missing_fixture_raises_llm_behavior_error():
    with tempfile.TemporaryDirectory() as td:
        recorded = RecordedLLMProvider(td)
        with pytest.raises(LLMBehaviorError) as exc:
            recorded.complete(**_kwargs())
        assert exc.value.reason == "llm.fixture_missing"
        assert "prompt_hash" in exc.value.payload_extras


def test_recording_provider_delegates_count_tokens_and_estimate_cost():
    with tempfile.TemporaryDirectory() as td:
        inner = _StubInner()
        rec = RecordingLLMProvider(inner, td)
        assert rec.estimate_cost(
            input_tokens=10, output_tokens=2, model="x"
        ) == Decimal("0.0001")
        assert rec.count_tokens(
            system="s", messages=[], model="x"
        ) == 5


def test_fixture_hash_is_stable_across_recordings_of_same_prompt():
    """Same prompt → same hash → same fixture filename (overwrite)."""

    with tempfile.TemporaryDirectory() as td:
        inner = _StubInner()
        rec = RecordingLLMProvider(inner, td)
        rec.complete(**_kwargs())
        rec.complete(**_kwargs())
        # Same key → one file, not two.
        assert len(os.listdir(td)) == 1

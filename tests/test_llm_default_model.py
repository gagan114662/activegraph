"""Provider-aware default model + cross-provider validation. CONTRACT v1.0.2 #1.

Covers:

  * ``@llm_behavior`` with no ``model=`` resolves to the configured
    provider's ``default_model`` at registration time.
  * Both shipped providers declare ``default_model``.
  * Cross-provider mismatches (claude-* on OpenAI, gpt-* on Anthropic)
    raise ``InvalidRuntimeConfiguration`` at registration time, with
    a structured error naming the configured provider and the
    claiming provider.
  * Unknown model names (custom, fine-tuned, internal-deployment)
    pass through silently — the validation is permissive by default.
  * Explicit ``model=`` strings that match the configured provider's
    family pass through unchanged.
  * ``LLMBehavior.build_prompt`` keeps working without a Runtime
    (CONTRACT v0.6 #20), falling back to the v1.0.1 default for
    inspection-time hash stability.
"""

from __future__ import annotations

import pytest

from activegraph import (
    Graph,
    InvalidRuntimeConfiguration,
    Runtime,
    behavior,
    llm_behavior,
)
from activegraph.llm import AnthropicProvider, OpenAIProvider

from tests._llm_helpers import ClaimList, ScriptedProvider


def _scripted(default_model: str = "claude-sonnet-4-5"):
    p = ScriptedProvider(
        respond_fn=lambda messages, schema: ClaimList(claims=[]),
    )
    p.default_model = default_model
    return p


# ---- (a) default_model resolution ------------------------------------------


def test_default_model_resolves_at_registration_when_decorator_omits_it():
    """@llm_behavior with no model= picks up the provider's default."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    # Decorator did not pin a model.
    assert extractor.model is None

    provider = _scripted(default_model="claude-haiku-4-5")
    g = Graph()
    rt = Runtime(g, llm_provider=provider)
    rt._ensure_registry()

    # Registration stamped the provider default onto the behavior.
    assert extractor.model == "claude-haiku-4-5"


def test_anthropic_provider_default_model_is_claude_family():
    """AnthropicProvider declares a claude-family default. v1.0.2 #1 (a)."""
    p = AnthropicProvider()
    assert p.default_model.startswith("claude-")


def test_openai_provider_default_model_is_gpt_family():
    """OpenAIProvider declares a gpt-family default. v1.0.2 #1 (a)."""
    p = OpenAIProvider()
    assert p.default_model.startswith("gpt-")


def test_explicit_model_string_still_works_unchanged():
    """Pre-v1.0.2 call sites with model='...' stay byte-identical."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="claude-sonnet-4-5",
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    assert extractor.model == "claude-sonnet-4-5"

    provider = _scripted(default_model="claude-haiku-4-5")
    g = Graph()
    rt = Runtime(g, llm_provider=provider)
    rt._ensure_registry()

    # Explicit string overrides the provider default.
    assert extractor.model == "claude-sonnet-4-5"


# ---- (b) cross-provider mismatch validation ---------------------------------


def test_claude_model_on_openai_runtime_raises_at_registration():
    """The v1.0.1-user-test finding: claude-sonnet-4-5 + OpenAIProvider
    silently 404s. v1.0.2 surfaces it at registration time instead."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="claude-sonnet-4-5",
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    # Use a fake OpenAI client so the provider doesn't try to load the SDK.
    provider = OpenAIProvider(client=object())
    g = Graph()
    rt = Runtime(g, llm_provider=provider)

    with pytest.raises(InvalidRuntimeConfiguration) as excinfo:
        rt._ensure_registry()

    msg = str(excinfo.value)
    assert "claude-sonnet-4-5" in msg
    assert "OpenAIProvider" in msg
    assert "AnthropicProvider" in msg
    # The error names the way out: swap providers or use the default.
    assert "gpt-4o-mini" in msg or "OpenAIProvider's model families" in msg


def test_gpt_model_on_anthropic_runtime_raises_at_registration():
    """Symmetric: gpt-4o-mini against AnthropicProvider."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="gpt-4o-mini",
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    provider = AnthropicProvider(client=object())
    g = Graph()
    rt = Runtime(g, llm_provider=provider)

    with pytest.raises(InvalidRuntimeConfiguration) as excinfo:
        rt._ensure_registry()

    msg = str(excinfo.value)
    assert "gpt-4o-mini" in msg
    assert "AnthropicProvider" in msg
    assert "OpenAIProvider" in msg


def test_o3_model_on_anthropic_runtime_raises_at_registration():
    """OpenAI's reasoning-model prefixes (o1-/o3-/o4-) also fire."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="o3-mini",
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    provider = AnthropicProvider(client=object())
    g = Graph()
    rt = Runtime(g, llm_provider=provider)

    with pytest.raises(InvalidRuntimeConfiguration) as excinfo:
        rt._ensure_registry()

    assert "o3-mini" in str(excinfo.value)


# ---- (c) permissive default: unknown names pass ----------------------------


def test_unknown_model_name_does_not_raise():
    """Custom, fine-tuned, and internal-deployment names pass validation
    silently — only recognized cross-provider mismatches raise."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="my-custom-model",
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    # Either shipped provider accepts the unrecognized name.
    for provider in (
        AnthropicProvider(client=object()),
        OpenAIProvider(client=object()),
    ):
        g = Graph()
        rt = Runtime(g, llm_provider=provider)
        rt._ensure_registry()  # must not raise
        assert extractor.model == "my-custom-model"


def test_finetuned_openai_model_name_passes_on_openai_runtime():
    """A fine-tune like ft:gpt-4o-mini:org::id starts with 'ft:', not
    'gpt-', so recognizes_model returns False. The runtime passes it
    through because no *other* shipped provider claims it either."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="ft:gpt-4o-mini:my-org::abc123",
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    provider = OpenAIProvider(client=object())
    g = Graph()
    rt = Runtime(g, llm_provider=provider)
    rt._ensure_registry()

    assert extractor.model == "ft:gpt-4o-mini:my-org::abc123"


# ---- (d) recognizes_model unit checks --------------------------------------


def test_anthropic_recognizes_model_claude_family():
    p = AnthropicProvider(client=object())
    assert p.recognizes_model("claude-sonnet-4-5")
    assert p.recognizes_model("claude-opus-4-7")
    assert p.recognizes_model("claude-haiku-4-5-20251001")
    assert not p.recognizes_model("gpt-4o-mini")
    assert not p.recognizes_model("o3-mini")
    assert not p.recognizes_model("my-custom-model")


def test_openai_recognizes_model_gpt_and_reasoning_families():
    p = OpenAIProvider(client=object())
    assert p.recognizes_model("gpt-4o-mini")
    assert p.recognizes_model("gpt-4o")
    assert p.recognizes_model("gpt-4-turbo")
    assert p.recognizes_model("gpt-3.5-turbo")
    assert p.recognizes_model("o1-preview")
    assert p.recognizes_model("o3-mini")
    assert p.recognizes_model("o4-mini")
    assert not p.recognizes_model("claude-sonnet-4-5")
    assert not p.recognizes_model("my-custom-model")
    # Fine-tunes have an ft: prefix; not recognized as base family.
    assert not p.recognizes_model("ft:gpt-4o-mini:org::id")


# ---- (e) build_prompt without Runtime --------------------------------------


def test_build_prompt_without_runtime_uses_inspection_default():
    """CONTRACT v0.6 #20: build_prompt is callable without a Runtime.
    When model is None, falls back to the v1.0.1 default for hash
    stability against pre-v1.0.2 snapshots."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        view={"around": "event.payload.object.id", "depth": 1},
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    g = Graph()
    g.add_object("document", {"title": "T", "body": "B"})
    ev = next(e for e in g.events if e.type == "object.created")
    prompt = extractor.build_prompt(ev, g)

    # No Runtime was constructed, so model is still None on the behavior.
    assert extractor.model is None
    # build_prompt falls back to the v1.0.1 hardcoded default.
    assert prompt.model == "claude-sonnet-4-5"


# ---- (f) end-to-end: the user-test reproducer is now caught early ----------


def test_user_test_reproducer_catches_default_model_mismatch_before_call():
    """The original v1.0.1-user-test bug: a user swaps
    AnthropicProvider() for OpenAIProvider() but their @llm_behavior
    still carries model='claude-...'. v1.0.2 fires at registration
    time instead of producing a silent 404 on first LLM call."""

    @llm_behavior(
        name="extractor",
        on=["object.created"],
        description="extract",
        output_schema=ClaimList,
        model="claude-sonnet-4-5",  # user copied this from an Anthropic example
    )
    def extractor(event, graph, ctx, llm_output):
        pass

    provider = OpenAIProvider(client=object())
    g = Graph()
    rt = Runtime(g, llm_provider=provider)

    # The diagnostic fires BEFORE any LLM call. No HTTP 404, no
    # behavior.failed event with a verbatim provider message — the
    # configuration error names the cross-provider mismatch directly.
    with pytest.raises(InvalidRuntimeConfiguration) as excinfo:
        rt.run_goal("seed")

    assert "claude-sonnet-4-5" in str(excinfo.value)
    assert "OpenAIProvider" in str(excinfo.value)

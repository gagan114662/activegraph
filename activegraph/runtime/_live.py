"""Live-Runtime tracking + single-behavior cross-provider validation.

CONTRACT v1.0.2 #1 (b). The validation fires at *both* binding
moments: ``Runtime(graph, llm_provider=...)`` construction (against
the existing registry) and ``register()`` / ``@llm_behavior``
decoration (against any live Runtime via the WeakSet below).

The WeakSet is module-level so the registration decorators can
look it up without importing ``Runtime`` at module load. Runtimes
self-register inside ``__init__`` after wiring; the WeakSet
auto-cleans GC'd Runtimes — no explicit ``Runtime.close()`` is
required.

The single-behavior validator here is intentionally narrow: it
only does the cross-provider mismatch check (recognized name
belonging to a different shipped provider). It does *not* stamp
provider defaults onto ``model=None`` behaviors — that side
effect lives in ``_resolve_and_validate_llm_models`` in
``runtime.py``, which still runs at first ``_ensure_registry``.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Any

from activegraph.behaviors.base import LLMBehavior

if TYPE_CHECKING:
    from activegraph.runtime.runtime import Runtime


# WeakSet so abandoned Runtimes don't leak validation calls. The
# fork/replay paths construct fresh Runtimes that self-register; the
# parent stays in the set until GC'd.
_LIVE_RUNTIMES: "weakref.WeakSet[Runtime]" = weakref.WeakSet()


def track_runtime(rt: "Runtime") -> None:
    """Register a live Runtime for cross-provider validation. Called
    by ``Runtime.__init__`` after the provider and graph are wired."""
    _LIVE_RUNTIMES.add(rt)


def live_runtimes() -> list["Runtime"]:
    """Snapshot of currently-alive Runtimes (a list of strong refs that
    the caller releases at end-of-call). Used by ``register()`` and the
    decorators to validate a new behavior against each live provider."""
    return list(_LIVE_RUNTIMES)


def validate_behavior_against_live_runtimes(behavior: Any) -> None:
    """Validate a freshly-registered behavior against every live
    Runtime's provider. Raises :class:`InvalidRuntimeConfiguration` on
    the first cross-provider mismatch.

    No-op when ``behavior`` isn't an :class:`LLMBehavior`, when no
    Runtime is live, or when the behavior has no explicit model (model
    resolution against the provider's default happens at Runtime
    construction or first-run, not here).
    """
    if not isinstance(behavior, LLMBehavior):
        return
    if behavior.model is None:
        return
    for rt in live_runtimes():
        provider = getattr(rt, "llm_provider", None)
        if provider is None:
            continue
        _validate_one(behavior, provider)


def _validate_one(behavior: LLMBehavior, provider: Any) -> None:
    """Cross-provider mismatch check for a single behavior against a
    single provider. Pure: no side effects, no model-default stamping.

    Permissive by default per v1.0.2 #1 (b): names no shipped provider
    recognizes pass silently. Only recognized cross-provider mismatches
    raise. The runtime-side ``_resolve_and_validate_llm_models``
    delegates to this for its per-behavior pass so the check lives in
    one place.
    """
    from activegraph.runtime.config_errors import InvalidRuntimeConfiguration

    model = behavior.model
    if model is None:
        return
    recognizes = getattr(provider, "recognizes_model", None)
    if recognizes is None or recognizes(model):
        return
    claimed_by = _which_shipped_provider_claims(model, exclude=type(provider))
    if claimed_by is None:
        return

    provider_class = type(provider).__name__
    provider_default = getattr(provider, "default_model", None) or "claude-sonnet-4-5"
    claimed_by_default = getattr(claimed_by, "default_model", "")
    provider_default_hint = (
        f"or remove the model= argument to use {provider_class}'s "
        f"default ({provider_default!r})"
        if provider_default
        else f"or set a {provider_class}-compatible model name"
    )
    raise InvalidRuntimeConfiguration(
        (
            f"@llm_behavior(name={behavior.name!r}, model={model!r}) "
            f"names a {claimed_by.__name__}-family model, but the "
            f"runtime is configured with {provider_class}"
        ),
        what_failed=(
            f"The behavior {behavior.name!r} pinned model={model!r}. "
            f"That name belongs to {claimed_by.__name__}'s model "
            f"family, but this Runtime was constructed with a "
            f"{provider_class} instance. Sending the name to the "
            f"wrong provider produces an HTTP 404 (or equivalent "
            f"'unknown model' response) at first LLM call, with no "
            f"hint that the mismatch is the cause."
        ),
        why=(
            "v1.0.2 #1 validates explicit model names at both binding "
            "moments (Runtime construction and register()/decoration) "
            "against each shipped provider's recognizes_model() "
            "method. The configured provider doesn't claim this name, "
            "but another shipped provider does — that's a "
            "configuration mismatch worth surfacing before the first "
            "network call rather than after."
        ),
        how_to_fix=(
            f"Either swap the provider — Runtime(graph, "
            f"llm_provider={claimed_by.__name__}()) — "
            f"{provider_default_hint}, or pass an explicit name "
            f"from {provider_class}'s model families."
        ),
        context={
            "behavior": behavior.name,
            "model": model,
            "configured_provider": provider_class,
            "claimed_by_provider": claimed_by.__name__,
            "claimed_by_default_model": claimed_by_default,
        },
    )


def _which_shipped_provider_claims(name: str, *, exclude: type) -> Any:
    """Return the first shipped provider class that recognizes `name`,
    excluding `exclude`. Returns None when no other shipped provider
    claims the name (permissive default per v1.0.2 #1 (b))."""
    from activegraph.llm.anthropic import AnthropicProvider
    from activegraph.llm.openai import OpenAIProvider

    candidates = [AnthropicProvider, OpenAIProvider]
    for cls in candidates:
        if cls is exclude:
            continue
        recognizes = getattr(cls, "recognizes_model", None)
        if recognizes is None:
            continue
        try:
            inst = cls()
        except Exception:
            # Defensive: if a provider's no-arg constructor ever requires
            # real credentials, skip it for the validation lookup.
            continue
        if inst.recognizes_model(name):
            return cls
    return None

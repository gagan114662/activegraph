"""T7 medium 018 coverage for activegraph.errors.ActiveGraphError.doc_url.

`doc_url` is the read-only property that composes the public docs catalog URL
from the module-level ``DOCS_BASE_URL`` and each subclass's ``_doc_slug``
ClassVar. The docs error-catalog and the structured ``__str__`` "More:" line
both depend on it, so its contract (one URL per error category, derived from
the real slug) is worth pinning.

Exercised on REAL error classes — no mocks of the API under test:
  - happy path: every concrete CONTRACT v1.0 category subclass returns the
    base URL joined to ITS OWN slug, and an actually-raised/instantiated error
    surfaces the same URL its ``__str__`` embeds.
  - boundary: the bare ``ActiveGraphError`` base (which should not be raised in
    practice) still yields a valid URL from the fallback base slug, and the
    property is read-only (no setter).
"""

import pytest

from activegraph.errors import (
    DOCS_BASE_URL,
    ActiveGraphError,
    ConfigurationError,
    ExecutionError,
    PackError,
    PatternError,
    RegistrationError,
    ReplayError,
    StorageError,
)


def test_activegraph_errors_ActiveGraphError_doc_url_happy_path_per_category():
    """Each concrete category subclass derives its docs URL from its own slug."""
    expected = {
        ConfigurationError: f"{DOCS_BASE_URL}/errors/configuration-error",
        RegistrationError: f"{DOCS_BASE_URL}/errors/registration-error",
        ExecutionError: f"{DOCS_BASE_URL}/errors/execution-error",
        ReplayError: f"{DOCS_BASE_URL}/errors/replay-error",
        StorageError: f"{DOCS_BASE_URL}/errors/storage-error",
        PatternError: f"{DOCS_BASE_URL}/errors/pattern-error",
        PackError: f"{DOCS_BASE_URL}/errors/pack-error",
    }
    for cls, url in expected.items():
        err = cls(
            "something broke",
            what_failed="a thing failed",
            why="a reason",
            how_to_fix="do the fix",
        )
        assert err.doc_url == url
        # Distinct categories must not collide on the same URL.
    assert len({u for u in expected.values()}) == len(expected)


def test_activegraph_errors_ActiveGraphError_doc_url_embedded_in_structured_str():
    """A real structured error's ``__str__`` "More:" line is exactly doc_url."""
    err = ReplayError(
        "cache hash mismatch",
        what_failed="recorded type stream diverged",
        why="the behavior changed between record and replay",
        how_to_fix="re-record or pin the behavior version",
    )
    rendered = str(err)
    assert err.doc_url == f"{DOCS_BASE_URL}/errors/replay-error"
    assert err.doc_url in rendered
    assert rendered.rstrip().endswith(err.doc_url)


def test_activegraph_errors_ActiveGraphError_doc_url_boundary_base_and_readonly():
    """Bare base class yields the fallback-slug URL; property has no setter."""
    base = ActiveGraphError("bare base — not raised in practice")
    assert base.doc_url == f"{DOCS_BASE_URL}/errors/active-graph-error"

    # doc_url is a read-only property: assigning to it must raise.
    with pytest.raises(AttributeError):
        base.doc_url = "https://example.com/override"  # type: ignore[misc]

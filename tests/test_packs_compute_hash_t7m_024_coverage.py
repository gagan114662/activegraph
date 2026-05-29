"""Coverage for ``activegraph.packs.PackPrompt.compute_hash`` (T7 medium 024).

``compute_hash`` is the prompt **replay contract** (CONTRACT v0.9 #10): the
content hash, not the human-readable version, is what pins replay. These tests
exercise the real static method against real string bodies (no mocks of the API
under test): a known SHA-256 happy path, the ``sha256:<16-hex>`` format
invariant, determinism, and the UTF-8 byte boundary for non-ASCII input. A final
test pins ``from_body`` to the same hash so the contract stays consistent across
the public constructor.
"""

from __future__ import annotations

import hashlib

from activegraph.packs import PackPrompt


def _expected(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def test_compute_hash_happy_path_known_sha256() -> None:
    # Known vector: sha256("hello") starts with 2cf24dba5fb0a30e...
    assert PackPrompt.compute_hash("hello") == "sha256:2cf24dba5fb0a30e"
    assert PackPrompt.compute_hash("hello") == _expected("hello")


def test_compute_hash_format_is_prefixed_16_hex() -> None:
    h = PackPrompt.compute_hash("some prompt body")
    assert h.startswith("sha256:")
    hexpart = h.split(":", 1)[1]
    assert len(hexpart) == 16
    # Every char is a lowercase hex digit (truncated SHA-256 digest).
    assert all(c in "0123456789abcdef" for c in hexpart)


def test_compute_hash_is_deterministic_and_distinguishes_bodies() -> None:
    # Same input -> same hash (replay stability).
    assert PackPrompt.compute_hash("body-A") == PackPrompt.compute_hash("body-A")
    # Different input -> different hash (contract actually discriminates).
    assert PackPrompt.compute_hash("body-A") != PackPrompt.compute_hash("body-B")


def test_compute_hash_empty_and_unicode_boundary() -> None:
    # Empty string is a valid body and hashes to the known empty-SHA-256 prefix.
    assert PackPrompt.compute_hash("") == "sha256:e3b0c44298fc1c14"
    # Non-ASCII hashes over UTF-8 bytes, not codepoints — boundary behavior.
    body = "café ☕"
    assert PackPrompt.compute_hash(body) == _expected(body)
    assert PackPrompt.compute_hash(body) != PackPrompt.compute_hash("cafe")


def test_compute_hash_matches_from_body_constructor() -> None:
    body = "You are a careful reviewer."
    prompt = PackPrompt.from_body(name="reviewer", version="1.0", body=body)
    # The public constructor must populate content_hash via compute_hash.
    assert prompt.content_hash == PackPrompt.compute_hash(body)
    assert prompt.content_hash == _expected(body)

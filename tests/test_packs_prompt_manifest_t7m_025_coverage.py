"""T7 medium run 025 coverage for activegraph.packs.Pack.prompt_manifest.

Exercises the `pack.loaded` prompts-block manifest (CONTRACT v0.9 #10):
the manifest maps each prompt name to {"version", "hash"} where the hash
is the replay-contract content hash, NOT the human-readable version.

Uses real Pack/PackPrompt fixtures (no mocks of the API under test).
"""

from activegraph.packs import Pack, PackPrompt


def test_pack_prompt_manifest_maps_each_prompt_to_version_and_hash():
    """Happy path: a pack with multiple prompts yields one manifest entry
    per prompt, keyed by name, carrying the declared version and the
    content-addressed hash."""
    greet = PackPrompt.from_body("greeting", "1.0.0", "Hello, operator.")
    farewell = PackPrompt.from_body("farewell", "2.3.1", "Goodbye, operator.")
    pack = Pack(name="manifest_pack", version="0.1.0", prompts=(greet, farewell))

    manifest = pack.prompt_manifest()

    assert set(manifest.keys()) == {"greeting", "farewell"}
    assert manifest["greeting"] == {"version": "1.0.0", "hash": greet.content_hash}
    assert manifest["farewell"] == {"version": "2.3.1", "hash": farewell.content_hash}
    # The hash is the SHA-256 replay contract, not the human version.
    assert manifest["greeting"]["hash"].startswith("sha256:")
    assert manifest["greeting"]["hash"] != manifest["greeting"]["version"]


def test_pack_prompt_manifest_is_empty_when_pack_has_no_prompts():
    """Boundary: a pack declaring no prompts produces an empty manifest
    dict (not None, not an error)."""
    pack = Pack(name="empty_prompts_pack", version="9.9.9")

    manifest = pack.prompt_manifest()

    assert manifest == {}
    assert isinstance(manifest, dict)


def test_pack_prompt_manifest_hash_is_content_addressed_not_version_keyed():
    """Contract behavior: two prompts that share a name+version but differ
    in body must produce different manifest hashes — the replay contract
    keys on content, so a body change is visible even when the declared
    version is unchanged."""
    v1 = PackPrompt.from_body("policy", "1.0.0", "Refuse destructive ops.")
    v1_changed_body = PackPrompt.from_body(
        "policy", "1.0.0", "Refuse destructive ops. Require authorization."
    )

    pack_a = Pack(name="hash_pack_a", version="0.1.0", prompts=(v1,))
    pack_b = Pack(name="hash_pack_b", version="0.1.0", prompts=(v1_changed_body,))

    manifest_a = pack_a.prompt_manifest()
    manifest_b = pack_b.prompt_manifest()

    # Same name, same declared version...
    assert manifest_a["policy"]["version"] == manifest_b["policy"]["version"]
    # ...but the content hashes differ because the body changed.
    assert manifest_a["policy"]["hash"] != manifest_b["policy"]["hash"]

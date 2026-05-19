"""License-state gate. CONTRACT v1.0.5.post1 #1.

Anchors on the contract boundary the v1.0.5.post1 #1 amendment names:
"Active Graph is licensed under Apache 2.0 from v1.0.5.post1 forward."
That claim binds five surfaces jointly — LICENSE carries the canonical
Apache text (including the patent-grant section that is the named
reason for the switch), NOTICE carries the project name and copyright
line, pyproject.toml's license field reads SPDX `Apache-2.0`, no
`License ::` classifier remains in pyproject.toml (PEP 639 forbids it
when the SPDX form is used), and README's license section references
Apache 2.0.

The test does not assert byte-equality of LICENSE against the Apache
Foundation's canonical text. The contract claim is the license
identity, not the file's byte-level shape; a future trailing-newline
adjustment should not break the gate, but a license-identity drift
should. Standing Rule §2.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_license_file_carries_apache_2_canonical_text() -> None:
    """LICENSE must carry the Apache 2.0 canonical heading and the
    §3 patent-grant section. The patent grant is the load-bearing
    reason named in the v1.0.5.post1 #1 amendment for switching off
    MIT — a future LICENSE that loses it would silently violate the
    contract claim."""
    license_path = REPO_ROOT / "LICENSE"
    assert license_path.exists(), (
        "LICENSE missing from repo root. CONTRACT v1.0.5.post1 #1 "
        "names LICENSE as one of the four repo-root files carrying "
        "the Apache 2.0 license claim."
    )
    text = _read(license_path)
    assert "Apache License" in text, (
        "LICENSE does not contain the 'Apache License' heading. "
        "CONTRACT v1.0.5.post1 #1 binds the framework to Apache 2.0."
    )
    assert "Version 2.0, January 2004" in text, (
        "LICENSE does not contain the Apache 2.0 version line. "
        "CONTRACT v1.0.5.post1 #1 names the specific version."
    )
    assert "Grant of Patent License" in text, (
        "LICENSE does not contain the §3 'Grant of Patent License' "
        "section. The patent grant is the named reason in CONTRACT "
        "v1.0.5.post1 #1 for switching from MIT to Apache 2.0; "
        "losing it would silently violate the contract claim."
    )


def test_notice_file_carries_attribution() -> None:
    """NOTICE must carry the project name and the copyright line per
    Apache 2.0 §4(d) convention. The NOTICE pair with LICENSE is what
    downstream redistributors must preserve."""
    notice_path = REPO_ROOT / "NOTICE"
    assert notice_path.exists(), (
        "NOTICE missing from repo root. CONTRACT v1.0.5.post1 #1 "
        "names NOTICE as part of the Apache 2.0 §4(d) attribution "
        "surface that v1.0.5.post1 ships."
    )
    text = _read(notice_path)
    assert "Active Graph" in text, "NOTICE does not name the project."
    assert "Copyright 2026 Yohei Nakajima" in text, (
        "NOTICE does not carry the canonical copyright line "
        "named in CONTRACT v1.0.5.post1 #1."
    )


def test_pyproject_license_is_spdx_apache_2_0() -> None:
    """pyproject.toml's [project] table must declare the SPDX
    identifier `Apache-2.0`. The PEP 639 SPDX form is the boundary
    the contract claim names; drift back to `{ text = "MIT" }` or
    to another SPDX identifier breaks this anchor."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    license_field = data["project"]["license"]
    assert license_field == "Apache-2.0", (
        f"pyproject.toml [project].license = {license_field!r} but "
        f"CONTRACT v1.0.5.post1 #1 binds it to the SPDX string "
        f"'Apache-2.0' (PEP 639)."
    )


def test_pyproject_carries_no_license_classifier() -> None:
    """PEP 639 forbids `License ::` classifiers when the SPDX
    `license` field is used. CONTRACT v1.0.5.post1 #1 names the
    removal of the `License :: OSI Approved :: MIT License`
    classifier as part of the switch."""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    classifiers = data["project"].get("classifiers", [])
    offenders = [c for c in classifiers if c.startswith("License ::")]
    assert offenders == [], (
        f"pyproject.toml carries `License ::` classifier(s) "
        f"{offenders!r}. PEP 639 forbids these when `license` is in "
        f"SPDX form; CONTRACT v1.0.5.post1 #1 binds the metadata to "
        f"the SPDX-only shape."
    )


def test_readme_license_section_names_apache_2_0() -> None:
    """README's `## License` section must reference Apache 2.0.
    Catches a documentation drift back to 'MIT' in the public-facing
    surface that a casual reader hits first."""
    readme = _read(REPO_ROOT / "README.md")
    # Extract the `## License` section body (between the header and
    # the next H2). The contract claim binds this section to the
    # Apache 2.0 reference.
    marker = "## License"
    start = readme.find(marker)
    assert start != -1, "README missing `## License` section."
    after = readme[start + len(marker) :]
    next_h2 = after.find("\n## ")
    section = after if next_h2 == -1 else after[:next_h2]
    assert "Apache License 2.0" in section, (
        "README's `## License` section does not name 'Apache License "
        "2.0'. CONTRACT v1.0.5.post1 #1 binds the README to the "
        "Apache 2.0 reference."
    )
    assert "LICENSE" in section, (
        "README's `## License` section does not point at the LICENSE "
        "file. The contract claim binds the README to the LICENSE "
        "pointer so a reader can reach the canonical text."
    )
    assert "MIT" not in section, (
        "README's `## License` section still mentions 'MIT'. "
        "CONTRACT v1.0.5.post1 #1 retired the MIT declaration."
    )


def test_tomllib_available() -> None:
    """Sanity check — tomllib ships in Python >= 3.11. The framework
    declares `requires-python = ">=3.11"` in pyproject.toml, so this
    is structurally true; the check is a fail-fast for any future
    Python-version drift that would break the other assertions in
    this file."""
    assert sys.version_info >= (3, 11), (
        "tomllib requires Python >= 3.11; activegraph's "
        "requires-python matches this floor."
    )

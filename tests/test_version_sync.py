"""Version-sync CI gate. CONTRACT v1.0 PR-C follow-on.

Stale ``__version__`` constants produce confusing GitHub Issues six
months later when a bug reported "in 0.9.0" was actually 0.9.1. This
test asserts the runtime constant and the packaging metadata agree.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import activegraph


_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_runtime_version_matches_pyproject() -> None:
    with _PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    pyproject_version = data["project"]["version"]
    assert activegraph.__version__ == pyproject_version, (
        f"activegraph.__version__ = {activegraph.__version__!r} but "
        f"pyproject.toml version = {pyproject_version!r}. "
        f"Bump one to match the other before merging — every error "
        f"message that embeds the version (see PR-B internal-error "
        f"contexts, PR-C SchemaVersionMismatch) reads activegraph."
        f"__version__, so a drift produces wrong-version error reports."
    )

"""CLI flag drift gate — CONTRACT v1.1 #2.

Compares CLI flags defined in ``activegraph/cli/**/*.py`` against
flag references in the docs corpus (CHANGELOG.md, CONTRACT.md,
README.md, HANDOFF.md, CONTRIBUTING.md, docs/**/*.md). Fails when a
CLI flag is undocumented (definition leak) or a doc flag has no
implementation (runtime leak). Allowlisted entries from
``activegraph/cli_flag_drift_allowlist.toml`` suppress known
in-flight gaps; entries carry a rationale and a hard expiry so the
suppression cannot rot.

Decision provenance:
  D-1 (inner:fd53455) — static regex + ``ast.parse`` fail-closed.
  D-2 (inner:623717f) — TOML allowlist with rationale + expiry.
  D-2 footnote (inner:9469889) — resolution coupling reads
  ``frames/<id>.status`` (mechanism (i)); coupling is named here so
  it does not become hidden magic.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional


_FLAG_LITERAL_RE: re.Pattern[str] = re.compile(r"^--([a-z][a-z0-9](?:[a-z0-9-]*[a-z0-9])?)$")

# Flag-registering call names that the ast walker recognizes. argparse uses
# ``parser.add_argument``; click uses ``click.option`` (often via ``@option``
# imported as ``from click import option``); typer uses ``typer.Option``.
_FLAG_CALL_NAMES: frozenset[str] = frozenset({"add_argument", "option", "Option"})

# Click adds these to every command by default. Treat them as real CLI flags
# so docs mentioning ``--help`` / ``--version`` don't trip the gate.
_CLI_BUILTINS: frozenset[str] = frozenset({"--help", "--version"})

_DOC_FLAG_PATTERN: re.Pattern[str] = re.compile(
    # Two-or-more letter flag, lowercase + digits + internal dashes; the
    # trailing character must be alphanumeric so ``--supports--`` does
    # not capture the trailing dashes.
    r"(?<![A-Za-z0-9_])--([a-z][a-z0-9](?:[a-z0-9-]*[a-z0-9])?)"
)


class GateError(Exception):
    """Base class for fail-closed gate errors."""


class CliParseError(GateError):
    """Raised when a CLI source file fails ``ast.parse`` (D-1 fail-closed)."""

    def __init__(self, path: Path, error: SyntaxError) -> None:
        self.path = path
        self.error = error
        super().__init__(f"CLI parse failed for {path}: {error}")


class AllowlistEntryMalformedError(GateError):
    """Raised when an allowlist entry is missing required fields."""

    def __init__(self, flag: Optional[str], reason: str) -> None:
        self.flag = flag
        self.reason = reason
        super().__init__(f"Allowlist entry malformed (flag={flag!r}): {reason}")


class AllowlistEntryExpiredError(GateError):
    """Raised when an allowlist entry's expiry_date is in the past."""

    def __init__(self, flag: str, expired_on: date) -> None:
        self.flag = flag
        self.expired_on = expired_on
        super().__init__(f"Allowlist entry for {flag} expired on {expired_on}.")


class AllowlistEntryResolvedError(GateError):
    """Raised when the referenced frame has closed and the entry should be removed."""

    def __init__(self, flag: str, resolving_frame: str) -> None:
        self.flag = flag
        self.resolving_frame = resolving_frame
        super().__init__(
            f"Allowlist entry for {flag} is resolved — frame "
            f"{resolving_frame} closed; remove the entry."
        )


@dataclass(frozen=True)
class DriftReport:
    """Outcome of a drift detection pass.

    ``undocumented`` and ``promised_but_missing`` are post-allowlist;
    ``cli_flags`` and ``doc_flags`` are raw extraction outputs.
    """

    cli_flags: frozenset[str]
    doc_flags: frozenset[str]
    undocumented: frozenset[str]
    promised_but_missing: frozenset[str]
    allowlisted: frozenset[str]

    @property
    def is_clean(self) -> bool:
        return not (self.undocumented or self.promised_but_missing)


def _call_func_name(func: ast.expr) -> Optional[str]:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def extract_cli_flags(cli_dir: Path) -> set[str]:
    """Extract CLI flags from every ``*.py`` under ``cli_dir`` via static AST walk.

    Each file is parsed with :func:`ast.parse`; a ``SyntaxError`` triggers
    :class:`CliParseError` so the gate fails closed instead of silently
    emitting an empty set. Calls to ``add_argument``, ``option`` (click), and
    ``Option`` (typer) are walked; every string-literal arg matching
    ``--<name>`` is collected, which correctly handles multi-flag
    decorators like ``@click.option("-o", "--output-dir", ...)``.

    Click's built-in ``--help`` / ``--version`` are included as
    well — every click command registers them implicitly.
    """
    if not cli_dir.exists() or not cli_dir.is_dir():
        raise GateError(f"CLI directory not found: {cli_dir}")
    flags: set[str] = set(_CLI_BUILTINS)
    for py in sorted(cli_dir.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        text = py.read_text()
        try:
            tree = ast.parse(text, filename=str(py))
        except SyntaxError as exc:
            raise CliParseError(py, exc) from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_func_name(node.func) not in _FLAG_CALL_NAMES:
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    candidate = arg.value
                    if _FLAG_LITERAL_RE.match(candidate):
                        flags.add(candidate)
    return flags


def extract_doc_flags(doc_paths: Iterable[Path]) -> set[str]:
    """Extract ``--flag`` references from a set of markdown documents."""
    flags: set[str] = set()
    for doc in doc_paths:
        if not doc.exists():
            continue
        text = doc.read_text()
        for match in _DOC_FLAG_PATTERN.findall(text):
            flags.add(f"--{match}")
    return flags


def compute_drift(
    cli_flags: set[str],
    doc_flags: set[str],
    *,
    allowlisted: Optional[set[str]] = None,
) -> DriftReport:
    """Pure drift comparison given pre-extracted flag sets.

    Exposed so synthetic tests can drive the gate's comparison logic
    without standing up a full source tree.
    """
    allowed = set(allowlisted or ())
    undocumented = (cli_flags - doc_flags) - allowed
    promised_but_missing = (doc_flags - cli_flags) - allowed
    return DriftReport(
        cli_flags=frozenset(cli_flags),
        doc_flags=frozenset(doc_flags),
        undocumented=frozenset(undocumented),
        promised_but_missing=frozenset(promised_but_missing),
        allowlisted=frozenset(allowed),
    )


def _frame_status_closed(repo_root: Path, frame_ref: str) -> Optional[str]:
    """Return the frame id if ``frames/<id>.status`` reads ``closed``, else ``None``.

    Implements mechanism (i) from amendment D-2: read frame-lifecycle
    status from the filesystem. Searches both the current repo root
    and its parent (so the gate works from the inner repo while the
    canonical status file lives in the outer gauntlet repo).
    """
    if not frame_ref.startswith("frame:"):
        return None
    frame_id = frame_ref[len("frame:"):]
    candidates = (
        repo_root / "frames" / f"{frame_id}.status",
        repo_root.parent / "frames" / f"{frame_id}.status",
    )
    for path in candidates:
        if path.exists() and path.read_text().strip() == "closed":
            return frame_id
    return None


def load_allowlist(
    allowlist_path: Path,
    *,
    today: Optional[date] = None,
    repo_root: Optional[Path] = None,
) -> set[str]:
    """Load + validate the allowlist and return the set of allowlisted flags.

    Returns an empty set when ``allowlist_path`` does not exist. A
    missing file means "no suppressions" and is not a gate failure;
    a *malformed* present file is.
    """
    if not allowlist_path.exists():
        return set()
    today = today or date.today()
    repo_root = repo_root or allowlist_path.parent

    with allowlist_path.open("rb") as fh:
        data = tomllib.load(fh)

    if data.get("schema_version") != "1":
        raise AllowlistEntryMalformedError(
            None,
            f"Unknown or missing schema_version (got {data.get('schema_version')!r}).",
        )

    allowlisted: set[str] = set()
    for entry in data.get("entry", []):
        flag = entry.get("flag")
        if not isinstance(flag, str) or not flag.startswith("--"):
            raise AllowlistEntryMalformedError(flag, "Missing or invalid 'flag' field.")
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise AllowlistEntryMalformedError(flag, "Missing or empty 'rationale'.")
        expiry_raw = entry.get("expiry_date")
        if isinstance(expiry_raw, date):
            expiry = expiry_raw
        elif isinstance(expiry_raw, str):
            try:
                expiry = date.fromisoformat(expiry_raw)
            except ValueError as exc:
                raise AllowlistEntryMalformedError(flag, f"Invalid expiry_date: {exc}")
        else:
            raise AllowlistEntryMalformedError(flag, "Missing or invalid 'expiry_date'.")
        if expiry < today:
            raise AllowlistEntryExpiredError(flag, expiry)
        commit_ref = entry.get("expiry_commit_ref")
        if isinstance(commit_ref, str):
            resolved = _frame_status_closed(repo_root, commit_ref)
            if resolved is not None:
                raise AllowlistEntryResolvedError(flag, resolved)
        allowlisted.add(flag)
    return allowlisted


def _default_doc_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for top in ("CHANGELOG.md", "CONTRACT.md", "README.md", "HANDOFF.md", "CONTRIBUTING.md"):
        candidate = repo_root / top
        if candidate.exists():
            paths.append(candidate)
    docs_dir = repo_root / "docs"
    if docs_dir.exists():
        paths.extend(sorted(docs_dir.rglob("*.md")))
    return paths


def detect_drift(
    cli_dir: Path,
    doc_paths: Iterable[Path],
    *,
    allowlist_path: Optional[Path] = None,
    today: Optional[date] = None,
    repo_root: Optional[Path] = None,
) -> DriftReport:
    """Extract CLI + doc flags, apply allowlist, return a :class:`DriftReport`."""
    cli_flags = extract_cli_flags(cli_dir)
    doc_flags = extract_doc_flags(list(doc_paths))
    allowlisted: set[str] = set()
    if allowlist_path is not None:
        allowlisted = load_allowlist(
            allowlist_path, today=today, repo_root=repo_root
        )
    return compute_drift(cli_flags, doc_flags, allowlisted=allowlisted)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for ``python scripts/gate_cli_flag_drift.py``."""
    del argv  # accepted for symmetry; the gate has no flags of its own
    repo_root = _repo_root()
    cli_dir = repo_root / "activegraph" / "cli"
    allowlist_path = repo_root / "cli_flag_drift_allowlist.toml"
    try:
        report = detect_drift(
            cli_dir,
            _default_doc_paths(repo_root),
            allowlist_path=allowlist_path,
            repo_root=repo_root,
        )
    except CliParseError as exc:
        print(f"FAIL (parse): {exc}", file=sys.stderr)
        return 2
    except (
        AllowlistEntryMalformedError,
        AllowlistEntryExpiredError,
        AllowlistEntryResolvedError,
    ) as exc:
        print(f"FAIL (allowlist): {exc}", file=sys.stderr)
        return 2
    if report.is_clean:
        print(
            "OK — cli flag drift gate passes. "
            f"CLI flags: {len(report.cli_flags)}; "
            f"doc flags: {len(report.doc_flags)}; "
            f"allowlisted: {len(report.allowlisted)}."
        )
        return 0
    if report.undocumented:
        print(
            f"FAIL: {len(report.undocumented)} CLI flag(s) missing from docs:",
            file=sys.stderr,
        )
        for flag in sorted(report.undocumented):
            print(f"  - {flag}", file=sys.stderr)
    if report.promised_but_missing:
        print(
            f"FAIL: {len(report.promised_but_missing)} doc flag(s) missing from CLI:",
            file=sys.stderr,
        )
        for flag in sorted(report.promised_but_missing):
            print(f"  - {flag}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

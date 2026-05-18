"""Walk the public surface and produce a mypy --strict pass/fail report.

CONTRACT v1.0 #C5 locks the allowlist source: every module reachable
from ``activegraph.__all__`` plus each pack's top-level ``__all__``.
The tier model from CONTRACT v1.0 #C2 applies (100% target for
re-exports, 80% for second ring).

Output: ``docs/reference/api/TYPE_REPORT.md``. Sibling to
``COVERAGE_REPORT.md`` from the docstring audit; same checklist
shape, consumed by the v1.1 type-completeness follow-on the same
way the docstring report is consumed by the docstring gate.

Per-module classification:

- **clean** — mypy --strict produces zero errors against this module.
  Gets ``strict = true`` in the pyproject override block.
- **dirty** — mypy --strict produces one or more errors against this
  module. Falls back to the lenient default in pyproject; the v1.1
  follow-on closes the gap.

Error categories are surfaced for triage; the largest are usually
mechanical fixes (``no-untyped-def``, ``type-arg``, ``no-any-return``)
while smaller categories (``attr-defined``, ``arg-type``) need
per-case judgment.

Run with::

    python scripts/audit_types.py

Re-runnable; the report regenerates from the current state.
"""

from __future__ import annotations

import inspect
import pkgutil
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import activegraph


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "reference" / "api" / "TYPE_REPORT.md"


# Match `<path>:<line>: error: <message>  [<code>]`
# Note the two spaces before the bracketed code — mypy's standard format.
_ERROR_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+): error: (?P<msg>.+?)  \[(?P<code>[^\]]+)\]$"
)


def collect_allowlist_modules() -> set[str]:
    """Return the set of module paths reachable from public ``__all__``s.

    Each symbol in ``activegraph.__all__`` resolves to an object whose
    ``__module__`` attribute names the module that defined it. That
    module path is the allowlist target. Pack-level ``__all__``s
    contribute the same way.
    """
    modules: set[str] = set()

    for name in activegraph.__all__:
        obj = getattr(activegraph, name, None)
        if obj is None:
            continue
        mod = getattr(obj, "__module__", None)
        if mod and mod.startswith("activegraph"):
            modules.add(mod)

    # Pack-level __all__s.
    if hasattr(activegraph, "packs"):
        for finder, modname, ispkg in pkgutil.iter_modules(
            activegraph.packs.__path__, "activegraph.packs."
        ):
            if not ispkg:
                continue
            try:
                pack_mod = __import__(modname, fromlist=["pack"])
            except Exception:
                continue
            all_list = getattr(pack_mod, "__all__", None)
            if not all_list:
                continue
            for name in all_list:
                obj = getattr(pack_mod, name, None)
                if obj is None:
                    continue
                mod = getattr(obj, "__module__", None)
                if mod and mod.startswith("activegraph"):
                    modules.add(mod)

    return modules


def module_to_path(mod: str) -> Path:
    """``activegraph.runtime.runtime`` -> ``activegraph/runtime/runtime.py``.
    Package modules resolve to ``__init__.py`` instead.
    """
    base = REPO_ROOT / Path(*mod.split("."))
    as_file = base.with_suffix(".py")
    if as_file.exists():
        return as_file
    as_package = base / "__init__.py"
    if as_package.exists():
        return as_package
    return as_file  # fall back to the .py form for error messages


def path_to_module(path: str) -> str:
    """``activegraph/runtime/runtime.py`` -> ``activegraph.runtime.runtime``."""
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(REPO_ROOT)
        except ValueError:
            pass
    parts = list(p.with_suffix("").parts)
    return ".".join(parts)


def _run_mypy_on_set(modules: set[str]) -> str:
    """Run a single mypy --strict invocation against the given set of
    modules. Used both for the converging audit loop and for the final
    pass that produces the dirty-module error breakdown.
    """
    paths: list[str] = []
    for mod in sorted(modules):
        p = module_to_path(mod)
        try:
            rel = str(p.relative_to(REPO_ROOT))
        except ValueError:
            rel = str(p)
        if Path(rel).exists():
            paths.append(rel)
    if not paths:
        return ""
    result = subprocess.run(
        [
            "mypy", "--strict", "--no-color-output", "--no-error-summary",
            "--ignore-missing-imports", "--follow-imports=skip",
            *paths,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.stdout


def converge_clean_set(allowlist: set[str]) -> tuple[set[str], str]:
    """Find the largest stable set of clean modules.

    Mypy's classification depends on which sibling modules are in
    scope. When an allowlist module A is in ``files`` and module B is
    not, A's imports of B become Any (due to ``follow_imports=skip``).
    Conversely, if A and B are both in ``files``, A sees B's real
    types — which can newly trip ``warn_return_any`` if B's return
    type is concrete and A returns an Any from an import outside the
    set.

    The CI gate's pyproject ``files`` list is the canonical scope.
    The audit converges to the same set by:

    1. Start with all allowlist modules.
    2. Run mypy on the set. Remove any module that has errors.
    3. Re-run on the reduced set; removing a dirty module may flip
       previously-clean modules to dirty (their imports now Any).
    4. Repeat until the set stabilises.

    Returns ``(stable_clean_set, final_mypy_output_for_full_allowlist)``.
    The full-allowlist output is the basis for the dirty-module error
    breakdown (we want to surface the actual errors, even on modules
    that fail only because a dependency was removed).
    """
    # Capture the full-allowlist run first so the report's dirty
    # breakdown shows real errors per module.
    full_output = _run_mypy_on_set(allowlist)

    current = set(allowlist)
    while True:
        output = _run_mypy_on_set(current)
        errors_by_file = parse_errors(output)
        dirty_now: set[str] = set()
        for mod in current:
            p = module_to_path(mod)
            try:
                rel = str(p.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(p)
            if errors_by_file.get(rel):
                dirty_now.add(mod)
        if not dirty_now:
            return current, full_output
        current -= dirty_now


def parse_errors(output: str) -> dict[str, list[tuple[int, str, str]]]:
    """Bucket errors by source file path.

    Returns ``{file_path: [(line, code, message), ...]}``.
    """
    by_file: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for line in output.splitlines():
        m = _ERROR_RE.match(line)
        if not m:
            continue
        by_file[m["path"]].append(
            (int(m["line"]), m["code"], m["msg"])
        )
    return by_file


def format_report(
    allowlist: set[str],
    clean_set: set[str],
    errors_by_file: dict[str, list[tuple[int, str, str]]],
) -> str:
    """Render the audit report as Markdown."""
    lines: list[str] = []
    lines.append("# Type coverage report — public surface mypy --strict")
    lines.append("")
    lines.append(
        "Auto-generated by ``scripts/audit_types.py``. The v1.1 "
        "type-completeness follow-on consumes this as a checklist."
    )
    lines.append("")
    lines.append(
        "Allowlist source (CONTRACT v1.0 #C5): every module reachable "
        "from ``activegraph.__all__`` plus each pack's top-level "
        "``__all__``. Tier model (CONTRACT v1.0 #C2): 100% target on "
        "re-exports, 80% on second ring."
    )
    lines.append("")
    lines.append(
        "Classification: **clean** = mypy --strict reports zero errors "
        "against this module; **dirty** = one or more errors. Clean "
        "modules get ``strict = true`` in ``pyproject.toml``; dirty "
        "modules fall back to lenient mypy until the v1.1 follow-on "
        "lands."
    )
    lines.append("")

    # Bucket allowlist modules into clean / dirty. The clean set is
    # the converged result from the audit loop; the dirty list uses
    # the full-allowlist error output so each dirty module's findings
    # show real, fixable errors rather than cascade-from-removal noise.
    clean: list[str] = []
    dirty: list[tuple[str, list[tuple[int, str, str]]]] = []
    for mod in sorted(allowlist):
        mod_path = module_to_path(mod)
        try:
            rel = str(mod_path.relative_to(REPO_ROOT))
        except ValueError:
            rel = str(mod_path)
        if mod in clean_set:
            clean.append(mod)
        else:
            errors = errors_by_file.get(rel, [])
            dirty.append((mod, errors))

    # Top-level summary.
    total = len(clean) + len(dirty)
    pct = (len(clean) / total * 100) if total else 100.0
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- Allowlist modules: **{total}** "
        f"(driven by ``activegraph.__all__`` plus pack-level ``__all__``s)"
    )
    lines.append(
        f"- Clean (mypy --strict passes): **{len(clean)} / {total} ({pct:.1f}%)**"
    )
    lines.append(
        f"- Dirty (one or more findings): **{len(dirty)}** "
        f"(gap to 100% target: {len(dirty)} modules)"
    )
    lines.append("")

    # Error category breakdown across all dirty modules.
    if dirty:
        cat_counts: Counter[str] = Counter()
        for _, errors in dirty:
            for _, code, _ in errors:
                cat_counts[code] += 1
        lines.append("### Error categories (across dirty modules)")
        lines.append("")
        for code, n in cat_counts.most_common():
            lines.append(f"- ``{code}`` — {n} occurrence(s)")
        lines.append("")

    # Clean modules.
    lines.append("## Clean modules (mypy --strict passes)")
    lines.append("")
    if not clean:
        lines.append("(none; the audit will close this gap incrementally)")
    else:
        for mod in clean:
            lines.append(f"- [x] ``{mod}``")
    lines.append("")

    # Dirty modules with their error breakdowns.
    lines.append("## Dirty modules")
    lines.append("")
    if not dirty:
        lines.append("(none)")
    else:
        for mod, errors in dirty:
            lines.append(f"### ``{mod}``")
            lines.append("")
            cat_counts_mod: Counter[str] = Counter()
            for _, code, _ in errors:
                cat_counts_mod[code] += 1
            lines.append(
                f"- [ ] {len(errors)} error(s); categories: "
                + ", ".join(
                    f"``{code}`` ({n})" for code, n in cat_counts_mod.most_common()
                )
            )
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    print("collecting allowlist...")
    allowlist = collect_allowlist_modules()
    print(f"  {len(allowlist)} modules")
    print("converging clean set (iterative mypy --strict; ~10-30s)...")
    clean_set, full_output = converge_clean_set(allowlist)
    print(f"  clean: {len(clean_set)} / {len(allowlist)}")
    errors_by_file = parse_errors(full_output)
    print(f"  errors in {len(errors_by_file)} files (full-allowlist run)")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(format_report(allowlist, clean_set, errors_by_file))
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

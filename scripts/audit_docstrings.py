"""Walk the public surface (`__all__` of `activegraph` and pack-level
`__all__`s) and produce a coverage report against the CONTRACT v1.0
#C2 tier model: 100% on public surface, 80% on the second ring.

Output: ``docs/reference/api/COVERAGE_REPORT.md``. The docstring-gate
(``scripts/gate_docstrings.py``) consumes this informally — the gate
walks the surface independently and compares against the curated
exemption list in ``docstring_gaps.toml``.

Classification per symbol:

- **full** — at least 3 lines of substantive prose, or has obvious
  structured sections (Args:, Returns:, Raises:, Examples:).
- **one-line** — single-line docstring; renders but is thin.
- **missing** — no docstring at all.

Ring:

- **Ring 0** — symbol in `activegraph.__all__` or a pack's top-level
  `__all__`. Target: 100% full or one-line; aim for full.
- **Ring 1** — non-underscore class/function defined in any
  `activegraph.*` submodule but NOT in any `__all__`. Target: 80%
  not-missing (one-line counts).
- **Internal** — symbols beginning with underscore, or in test/CLI-
  entry modules. Not gated.

Re-run after every batch of docstring fixes to confirm the report
shrinks. The gate's exemption list (``docstring_gaps.toml``) is
manually curated from this report — do not auto-regenerate it, or
new gaps would silently exempt themselves.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from collections import defaultdict
from pathlib import Path

import activegraph


REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "reference" / "api" / "COVERAGE_REPORT.md"


def classify(obj) -> str:
    """Classify a symbol's docstring as full / one-line / missing."""
    doc = inspect.getdoc(obj)
    if not doc:
        return "missing"
    nonblank = [line for line in doc.strip().split("\n") if line.strip()]
    if len(nonblank) <= 1:
        return "one-line"
    if any(s in doc for s in ("Args:", "Returns:", "Raises:", "Examples:", "Example:")):
        return "full"
    if len(nonblank) >= 3:
        return "full"
    return "one-line"


def collect_ring0() -> tuple[dict[str, list[tuple[str, str]]], set[tuple[str, str]]]:
    """Return Ring 0 symbols and the (module, name) keys to exclude
    from Ring 1.

    Result tuple:
      - ``surface``: ``{display_module: [(symbol_name, classification)]}``
        for the report's per-module sections.
      - ``ring0_keys``: ``{(__module__, name)}`` to filter Ring 1.
    """
    surface: dict[str, list[tuple[str, str]]] = defaultdict(list)
    ring0_keys: set[tuple[str, str]] = set()
    seen: set[int] = set()

    for name in activegraph.__all__:
        obj = getattr(activegraph, name, None)
        if obj is None:
            surface["activegraph"].append((name, "missing"))
            continue
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        surface["activegraph"].append((name, classify(obj)))
        home = getattr(obj, "__module__", "")
        if home:
            ring0_keys.add((home, name))

    if hasattr(activegraph, "packs"):
        for finder, modname, ispkg in pkgutil.iter_modules(
            activegraph.packs.__path__, "activegraph.packs."
        ):
            if not ispkg:
                continue
            try:
                mod = __import__(modname, fromlist=["pack"])
            except Exception:
                continue
            all_list = getattr(mod, "__all__", None)
            if not all_list:
                continue
            for name in all_list:
                obj = getattr(mod, name, None)
                if obj is None:
                    surface[modname].append((name, "missing"))
                    continue
                if id(obj) in seen:
                    continue
                seen.add(id(obj))
                surface[modname].append((name, classify(obj)))
                home = getattr(obj, "__module__", "")
                if home:
                    ring0_keys.add((home, name))

    return surface, ring0_keys


_RING1_SKIP_PARTS = {"tests", "__main__"}


def collect_ring1(ring0_keys: set[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Return Ring 1 entries as ``[(module, symbol_name, classification)]``.

    Ring 1 = non-underscore class/function defined in any
    ``activegraph.*`` submodule (``obj.__module__ == module_name``)
    that isn't in any Ring 0 ``__all__``.
    """
    entries: list[tuple[str, str, str]] = []
    seen: set[int] = set()
    for finder, modname, ispkg in pkgutil.walk_packages(
        activegraph.__path__, "activegraph."
    ):
        parts = modname.split(".")
        if any(p in _RING1_SKIP_PARTS for p in parts):
            continue
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        for sym_name, obj in inspect.getmembers(mod):
            if sym_name.startswith("_"):
                continue
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != modname:
                continue
            if (modname, sym_name) in ring0_keys:
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            entries.append((modname, sym_name, classify(obj)))
    entries.sort()
    return entries


def format_report(
    surface: dict[str, list[tuple[str, str]]],
    ring1: list[tuple[str, str, str]],
) -> str:
    lines: list[str] = []
    lines.append("# Docstring coverage report — public surface")
    lines.append("")
    lines.append(
        "Auto-generated by ``scripts/audit_docstrings.py``. Read alongside "
        "the gate's curated exemption list at ``docstring_gaps.toml``.\n"
    )
    lines.append(
        "Tier model from CONTRACT v1.0 #C2: 100% on the explicit public surface "
        "(symbols in `__all__`), 80% on the second ring (importable but not "
        "re-exported), no gate on internals.\n"
    )
    lines.append(
        "Classification: ``full`` (≥3 lines OR has Args/Returns/Raises/Examples), "
        "``one-line`` (single line; renders but thin), ``missing`` (no docstring).\n"
    )

    ring0_total = 0
    ring0_full = 0
    ring0_missing: list[tuple[str, str]] = []
    for modname in sorted(surface):
        entries = surface[modname]
        if not entries:
            continue
        lines.append("")
        lines.append(f"## Ring 0 — {modname} (public surface, target 100%)")
        lines.append("")
        for name, status in sorted(entries):
            mark = "x" if status == "full" else " "
            note = "" if status == "full" else f" — **{status}**"
            lines.append(f"- [{mark}] `{name}`{note}")
            ring0_total += 1
            if status == "full":
                ring0_full += 1
            if status == "missing":
                ring0_missing.append((modname, name))

    # Ring 1 grouped by module.
    lines.append("")
    lines.append("## Ring 1 — importable but not in `__all__` (target 80% not-missing)")
    lines.append("")
    by_module: dict[str, list[tuple[str, str]]] = defaultdict(list)
    ring1_full = 0
    ring1_oneline = 0
    ring1_missing_count = 0
    for modname, sym_name, status in ring1:
        by_module[modname].append((sym_name, status))
        if status == "full":
            ring1_full += 1
        elif status == "one-line":
            ring1_oneline += 1
        else:
            ring1_missing_count += 1
    ring1_total = len(ring1)
    ring1_any_doc = ring1_total - ring1_missing_count

    for modname in sorted(by_module):
        lines.append(f"### `{modname}`")
        lines.append("")
        for sym_name, status in sorted(by_module[modname]):
            mark = "x" if status != "missing" else " "
            note = "" if status == "full" else f" — **{status}**"
            lines.append(f"- [{mark}] `{sym_name}`{note}")
        lines.append("")

    # Summary
    ring0_pct_full = (ring0_full / ring0_total * 100) if ring0_total else 100.0
    ring0_pct_any = (
        (ring0_total - len(ring0_missing)) / ring0_total * 100
        if ring0_total else 100.0
    )
    ring1_pct_any = (ring1_any_doc / ring1_total * 100) if ring1_total else 100.0
    ring1_pct_full = (ring1_full / ring1_total * 100) if ring1_total else 100.0

    lines.append("## Summary")
    lines.append("")
    lines.append("### Ring 0 — public surface (target 100%)")
    lines.append("")
    lines.append(
        f"- **{ring0_full}/{ring0_total} fully documented "
        f"({ring0_pct_full:.1f}%)** — gap to 100% full: "
        f"**{ring0_total - ring0_full} symbols**"
    )
    lines.append(
        f"- **{ring0_total - len(ring0_missing)}/{ring0_total} not-missing "
        f"({ring0_pct_any:.1f}%)** — gap to 100% not-missing: "
        f"**{len(ring0_missing)} symbols** (these need `docstring_gaps.toml` "
        f"exemptions for the gate to pass)"
    )
    lines.append("")
    if ring0_missing:
        lines.append("Ring 0 missing-entirely (gate exemptions):")
        lines.append("")
        for modname, name in sorted(ring0_missing):
            lines.append(f"- `{modname}.{name}`")
        lines.append("")

    lines.append("### Ring 1 — importable but not in `__all__` (target 80% not-missing)")
    lines.append("")
    lines.append(
        f"- **{ring1_full}/{ring1_total} fully documented "
        f"({ring1_pct_full:.1f}%)** — v1.1 burndown target is 100% full"
    )
    lines.append(
        f"- **{ring1_any_doc}/{ring1_total} not-missing "
        f"({ring1_pct_any:.1f}%)** — gate threshold is 80% not-missing"
    )
    lines.append("")
    if ring1_pct_any >= 80.0:
        lines.append(
            f"Ring 1 is **above** the 80% gate threshold. The gate enforces "
            f"the threshold; individual missing-Ring-1 symbols are v1.1 "
            f"burndown items, not gate exemptions."
        )
    else:
        lines.append(
            f"Ring 1 is **below** the 80% gate threshold. The gate fails "
            f"until coverage is restored or the threshold is lowered "
            f"deliberately."
        )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    surface, ring0_keys = collect_ring0()
    ring1 = collect_ring1(ring0_keys)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(format_report(surface, ring1))
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

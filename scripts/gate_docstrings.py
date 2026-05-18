"""Docstring coverage CI gate. CONTRACT v1.0 #C2.

Walks the public surface and fails on any gap that isn't either
documented or explicitly exempted in ``docstring_gaps.toml``.

Two gates, mirroring the tier model:

- **Ring 0** (symbols in ``activegraph.__all__`` and pack-level
  ``__all__``s): every symbol must be not-missing (one-line counts)
  OR listed in ``docstring_gaps.toml`` with a reason. A new public
  symbol added without a docstring fails CI; a regression (docstring
  removed from a previously-covered symbol) fails CI.
- **Ring 1** (non-underscore class/function defined in
  ``activegraph.*`` submodules but not in any ``__all__``):
  threshold gate. Coverage (not-missing percentage) must stay at or
  above the floor in ``docstring_gaps.toml``'s ``[ring1]`` block.

Audit vs gate: the audit (``scripts/audit_docstrings.py``) reports
the full classification (full / one-line / missing) — useful for
the v1.1 burndown. The gate is narrower: it just enforces what the
exemption list permits today.

Exit codes:

- 0 — every gate passes.
- 1 — Ring 0 has an unexempted gap, or Ring 1 dropped below the floor.

Run locally with::

    python scripts/gate_docstrings.py

CI invokes the same command. No flags; the source of truth is the
codebase + the exemption file.
"""

from __future__ import annotations

import inspect
import pkgutil
import sys
import tomllib
from pathlib import Path

import activegraph


REPO_ROOT = Path(__file__).resolve().parent.parent
GAPS_PATH = REPO_ROOT / "docstring_gaps.toml"


def load_exemptions() -> tuple[set[str], float]:
    """Return ``({"activegraph.Foo", ...}, ring1_floor_pct)``.

    The set of exempted Ring 0 symbols is dotted-name keyed (matches
    the format the gate's surface walk produces). The Ring 1 floor
    is the percentage threshold below which the gate fails.
    """
    if not GAPS_PATH.exists():
        raise SystemExit(
            f"docstring_gaps.toml not found at {GAPS_PATH}; "
            "the gate requires an explicit exemption file even if it "
            "lists zero exemptions."
        )
    data = tomllib.loads(GAPS_PATH.read_text())
    exemptions: set[str] = set()
    for entry in data.get("exemptions", []):
        sym = entry.get("symbol")
        reason = entry.get("reason", "").strip()
        if not sym:
            raise SystemExit(
                f"docstring_gaps.toml: exemption missing `symbol` field"
            )
        if not reason:
            raise SystemExit(
                f"docstring_gaps.toml: exemption for {sym!r} missing "
                f"`reason` field. Every exemption must be justified."
            )
        exemptions.add(sym)
    ring1_cfg = data.get("ring1", {})
    floor = float(ring1_cfg.get("min_not_missing_pct", 80.0))
    return exemptions, floor


def has_docstring(obj: object) -> bool:
    """A symbol passes the gate if ``inspect.getdoc`` returns
    non-empty text. The audit's full/one-line distinction is finer
    but isn't what the gate enforces — one-line counts as covered
    here.
    """
    return bool(inspect.getdoc(obj))


def collect_ring0_status() -> list[tuple[str, bool]]:
    """Return ``[(dotted_name, has_doc), ...]`` for every Ring 0
    symbol. Dotted name is ``activegraph.<sym>`` for the top-level
    surface and ``activegraph.packs.<pack>.<sym>`` for pack-level
    surfaces.
    """
    status: list[tuple[str, bool]] = []
    seen: set[int] = set()

    for name in activegraph.__all__:
        obj = getattr(activegraph, name, None)
        if obj is None:
            status.append((f"activegraph.{name}", False))
            continue
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        status.append((f"activegraph.{name}", has_docstring(obj)))

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
                dotted = f"{modname}.{name}"
                if obj is None:
                    status.append((dotted, False))
                    continue
                if id(obj) in seen:
                    continue
                seen.add(id(obj))
                status.append((dotted, has_docstring(obj)))

    return status


_RING1_SKIP_PARTS = {"tests", "__main__"}


def collect_ring1_coverage(ring0_dotted: set[str]) -> tuple[int, int]:
    """Walk every ``activegraph.*`` submodule for Ring 1 symbols.

    Returns ``(not_missing, total)``. The ratio is the gate's input.
    Excludes anything already in Ring 0 (by ``activegraph.<name>``
    dotted name; same source as ``collect_ring0_status``).
    """
    seen: set[int] = set()
    total = 0
    not_missing = 0
    for finder, modname, ispkg in pkgutil.walk_packages(
        activegraph.__path__, "activegraph."
    ):
        parts = modname.split(".")
        if any(p in _RING1_SKIP_PARTS for p in parts):
            continue
        try:
            mod = __import__(modname, fromlist=["*"])
        except Exception:
            continue
        for sym_name, obj in inspect.getmembers(mod):
            if sym_name.startswith("_"):
                continue
            if not (inspect.isfunction(obj) or inspect.isclass(obj)):
                continue
            if getattr(obj, "__module__", None) != modname:
                continue
            # Filter out Ring 0 symbols by both possible dotted names
            # (re-exported under activegraph.<name> and packs).
            if f"activegraph.{sym_name}" in ring0_dotted:
                continue
            if f"{modname}.{sym_name}" in ring0_dotted:
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            total += 1
            if has_docstring(obj):
                not_missing += 1
    return not_missing, total


def main() -> int:
    exemptions, floor = load_exemptions()
    ring0 = collect_ring0_status()
    ring0_dotted = {name for name, _ in ring0}

    # Ring 0: each undocumented symbol must be exempted.
    failures: list[str] = []
    stale_exemptions: list[str] = []
    documented_keys = {name for name, doc in ring0 if doc}

    for name, doc in ring0:
        if doc:
            continue
        if name not in exemptions:
            failures.append(name)

    # Stale exemptions: listed but symbol is now documented. Don't
    # fail CI on these, but report so they get removed in v1.1.
    for sym in sorted(exemptions):
        if sym in documented_keys:
            stale_exemptions.append(sym)

    # Ring 1: threshold gate.
    not_missing, total = collect_ring1_coverage(ring0_dotted)
    ring1_pct = (not_missing / total * 100) if total else 100.0
    ring1_pass = ring1_pct >= floor

    # Report.
    print(f"Ring 0: {len(documented_keys)}/{len(ring0)} documented "
          f"({len(documented_keys) / len(ring0) * 100:.1f}%)")
    print(f"Ring 0 exemptions in docstring_gaps.toml: {len(exemptions)}")
    print(f"Ring 1: {not_missing}/{total} not-missing "
          f"({ring1_pct:.1f}%); floor={floor:.1f}%")
    print()

    if failures:
        print("FAIL — Ring 0 symbols without docstrings AND without exemption:")
        for name in failures:
            print(f"  - {name}")
        print()
        print("Fix options:")
        print("  1. Add a docstring (one-line counts for the gate).")
        print("  2. Add the symbol to docstring_gaps.toml with a reason.")
        print()

    if not ring1_pass:
        print(
            f"FAIL — Ring 1 coverage {ring1_pct:.1f}% is below the "
            f"{floor:.1f}% floor in docstring_gaps.toml [ring1] block."
        )
        print()

    if stale_exemptions:
        print(
            f"NOTE — {len(stale_exemptions)} stale exemption(s) "
            f"(symbol now has a docstring); remove from docstring_gaps.toml:"
        )
        for sym in stale_exemptions:
            print(f"  - {sym}")
        print()

    if failures or not ring1_pass:
        return 1
    print("OK — docstring gate passes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

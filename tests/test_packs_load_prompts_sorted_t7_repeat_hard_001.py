"""T7 repeat HARD 001 — docstring↔code drift regression test.

`activegraph.packs.load_prompts_from_dir` documents:

    "Returns a tuple of `PackPrompt` sorted by name."

(see the docstring in activegraph/packs/__init__.py)

The drift: the implementation iterates `sorted(p.glob("*.md"))`, which
sorts by *filename*, then returns the prompts in dict-insertion (i.e.
filename) order. Because a prompt's `name` defaults to the filename stem
but can be OVERRIDDEN by the frontmatter `name` field, filename order and
name order can diverge — and when they do, the returned tuple is NOT
sorted by name, contradicting the documented behavior.

This test asserts the DOCUMENTED behavior (sorted by name). It FAILS
against the pre-fix implementation and PASSES once the function sorts its
output by `PackPrompt.name`.
"""

from activegraph.packs import load_prompts_from_dir


def _write_prompt(path, *, name, version="1.0.0", body="body"):
    fm = f'---\nversion = "{version}"\nname = "{name}"\n---\n{body}\n'
    path.write_text(fm, encoding="utf-8")


def test_load_prompts_from_dir_returns_sorted_by_name(tmp_path):
    # Filenames sort one way; frontmatter `name` values sort the OPPOSITE way.
    # Filename order:  a_outro.md, m_middle.md, z_intro.md
    # Name order:      alpha,      mu,          zeta   (must match THIS)
    _write_prompt(tmp_path / "z_intro.md", name="alpha")
    _write_prompt(tmp_path / "a_outro.md", name="zeta")
    _write_prompt(tmp_path / "m_middle.md", name="mu")

    prompts = load_prompts_from_dir(tmp_path)
    names = [p.name for p in prompts]

    # The docstring promises "sorted by name" — assert exactly that.
    assert names == sorted(names), (
        f"load_prompts_from_dir docstring promises results sorted by name, "
        f"but returned {names!r} (expected {sorted(names)!r})"
    )
    assert names == ["alpha", "mu", "zeta"]

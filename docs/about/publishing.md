# Publishing a release

This page documents the release-publish workflow. It exists so the
maintainer can run a release with confidence and so the next session
(human or agent) picking up release work has a reproducible procedure.

The framework's tag-and-publish flow is **`.github/workflows/publish.yml`**.
It triggers on a git tag push matching `v*` and uploads the built
sdist + wheel to PyPI via trusted publishing. Per
[CONTRACT v1.0 #C8](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md),
PyPI publishing is externally owned — the workflow is the artifact
the framework ships; the maintainer runs the actual publish by
pushing the tag.

## Before the first publish

The workflow uses PyPI **trusted publishing** (OIDC-based, no
long-lived API tokens). Trusted publishing requires one-time setup
on the PyPI side; do this once before tagging the first release.

1. Create the `activegraph` project on PyPI by uploading any test
   release manually (the canonical first-time-publish bootstrap). A
   pre-release tag like `v0.0.0a1` is safe — it doesn't conflict
   with the real version sequence and reserves the project name.
   This step needs a one-time PyPI API token; revoke it after.
2. Configure trusted publishing on the project page. Visit
   [https://pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)
   and add a publisher with:
   - **Owner:** `yoheinakajima`
   - **Repository:** `activegraph`
   - **Workflow:** `publish.yml`
   - **Environment:** `pypi`
3. Confirm the workflow's `publish` job references the same
   environment (`environment: name: pypi`). The repository's
   GitHub Environments → `pypi` settings don't need additional
   protection rules; the OIDC token PyPI accepts is scoped to the
   environment + workflow combination.

After this setup, no PyPI credentials live in repository secrets.
Future maintainers tag-and-push; PyPI accepts the OIDC token
issued by GitHub at workflow runtime.

## Triggering a release

1. Update the version constants. Both must match:
   - `activegraph/__version__` in `activegraph/__init__.py`
   - `version` in `pyproject.toml`
   The version-sync test (`tests/test_version_sync.py`) verifies
   both match before any release work merges to main. The
   forthcoming version-tag-correspondence gate
   ([CONTRACT v1.1 #6](https://github.com/yoheinakajima/activegraph/blob/main/CONTRACT.md))
   will also verify they match the current tag in tagged-release CI.
2. Update the CHANGELOG. Add a section for the new version with
   "Added / Changed / Deprecated / Removed / Fixed / Migration"
   subsections. Follow the existing v1.0-rc2 entry's shape.
3. Merge the version-bump + CHANGELOG PR to `main`.
4. Tag and push from `main`. The tag string uses the human-facing
   form (`v1.0-rc2`, `v1.0`, `v1.0.1`); the `version` strings in
   `__init__.py` and `pyproject.toml` use the PEP 440 normalized
   form (`1.0.0rc2`, `1.0.0`, `1.0.1`).

    ```bash
    git checkout main
    git pull
    git tag -a v1.0-rc2 -m "v1.0-rc2"
    git push origin v1.0-rc2
    ```

5. Watch the publish workflow on GitHub Actions. It builds the
   sdist + wheel, uploads them to PyPI via trusted publishing, and
   exits 0 on success. Total runtime ~2 minutes.

## After the publish

Verify the package is installable from a fresh environment. The
test of record:

```bash
python -m venv /tmp/verify-publish
source /tmp/verify-publish/bin/activate
pip install activegraph==1.0.0rc2
activegraph --version    # should print 1.0.0rc2
activegraph quickstart   # should run end-to-end against fixtures
deactivate
rm -rf /tmp/verify-publish
```

If `pip install` fails, the most likely causes are:

- **PyPI hasn't indexed the package yet** (transient; usually <1
  minute, occasionally up to 5). Retry after a brief wait.
- **The wheel build failed to include a required file.** Check
  `MANIFEST.in` and the `[tool.setuptools.package-data]` section
  of `pyproject.toml` if the import surface is missing data files.
- **Version mismatch.** The PyPI version string is the `pyproject.toml`
  form, not the tag form — `1.0.0rc2`, not `v1.0-rc2`. The tag
  triggers the workflow; the package version is what `pip install`
  asks for.

After verification, update any external references (release notes
on GitHub Releases, social posts, the documentation site's
homepage if relevant). The doc site rebuilds automatically on push
to `main`; no separate publish step is needed there.

## Rolling back

PyPI does not allow re-uploading the same version once published —
this is intentional ([PEP 600](https://peps.python.org/pep-0600/)).
If a release ships broken:

1. Yank the broken version on PyPI (visible to existing installs;
   blocks new ones from resolving to that version unless explicitly
   pinned).
2. Bump the version (`1.0.0rc2` → `1.0.0rc3` or `1.0.0` → `1.0.1`)
   and re-tag.

The yank-and-bump path is documented because the framework's
[invariant-protection voice](https://docs.activegraph.dev/concepts/failure-model/)
extends to release ops: the next maintainer needs to know what to
do, not guess.

## Why trusted publishing

The trade-off vs. API-token publishing:

- **Trusted publishing** uses GitHub's OIDC issuer; PyPI verifies
  the token at workflow runtime against the pre-configured publisher
  (owner + repo + workflow + environment). No long-lived secrets;
  the OIDC token is short-lived and scoped to the workflow run.
- **API-token publishing** stores a long-lived PyPI API token as a
  GitHub Actions secret. Simpler initial setup (one secret, no
  PyPI-side trusted-publisher config), but the token has full
  upload permission for the project as long as it exists, and
  rotation is a manual chore.

For an externally-owned-publish project where the agent loop ships
the workflow but the maintainer runs the tag, trusted publishing is
the right default. The setup cost is once per project; the rotation
cost is zero.

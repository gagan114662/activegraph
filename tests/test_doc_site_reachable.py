"""Deploy-verification gate. CONTRACT v1.1 #9.

Fetches `DOCS_BASE_URL` and a small set of known-good page paths,
asserts HTTP 200, and asserts the response body contains the
mkdocs `site_name` ("Active Graph"). If the doc site is
unreachable (DNS failure, 404, content mismatch), the gate fails
with a message that names the operational step to fix it.

Imports DOCS_BASE_URL from `activegraph.errors` so the test stays
in sync with the cutover constant (CONTRACT v1.0 #C6 v1.0-rc3
amendment).

This gate is the HTTP-reachability complement to
`tests/test_doc_links.py`, which is source-tree-scoped only. The
two together: source presence (always-green) + HTTP reachability
(green once Pages is enabled and DNS resolves).

Marked `slow` so local `pytest` doesn't pay the network cost on
every invocation. CI invokes this test explicitly via
`pytest -m slow tests/test_doc_site_reachable.py`.
"""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request

import pytest

from activegraph.errors import DOCS_BASE_URL


# Known-good pages — one per top-level section from the locked
# CONTRACT v1.0 #5 doc structure. If any of these moves, the test
# updates and the move is visible in the diff.
_KNOWN_PAGES = (
    "",  # the landing page (DOCS_BASE_URL itself)
    "/quickstart/",
    "/reference/errors/",
    "/concepts/graph/",
)

_EXPECTED_BODY_MARKER = "Active Graph"  # mkdocs.yml `site_name`
_REQUEST_TIMEOUT_SECONDS = 10
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (1, 2, 4)


def _fetch(url: str) -> tuple[int, str]:
    """Fetch a URL with retry on connection errors. Returns
    (status_code, body). Does NOT retry on HTTP 4xx/5xx — those
    are real failures, not transient."""
    last_conn_err: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "activegraph-deploy-gate/1.0"}
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # HTTP-level error (4xx/5xx). Read body for the message
            # and return — don't retry.
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return e.code, body
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            last_conn_err = e
            if attempt + 1 < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS[attempt])
    raise AssertionError(
        f"connection to {url} failed after {_RETRY_ATTEMPTS} attempts: "
        f"{last_conn_err}"
    )


@pytest.mark.slow
@pytest.mark.parametrize("page_path", _KNOWN_PAGES)
def test_doc_page_is_reachable(page_path: str) -> None:
    """Each known-good page returns 200 and the body contains the
    framework's site name."""
    url = DOCS_BASE_URL + page_path
    try:
        status, body = _fetch(url)
    except AssertionError as e:
        # Connection-level failure (DNS, timeout, refused).
        pytest.fail(
            f"DNS / connection failure for {url}.\n"
            f"  Underlying error: {e}\n"
            f"  Fix: verify the CNAME record for "
            f"{DOCS_BASE_URL.split('//')[1]} points at "
            f"yoheinakajima.github.io. If DNS is correct, verify the "
            f"docs workflow's most recent deploy job succeeded.",
            pytrace=False,
        )

    if status == 404:
        pytest.fail(
            f"{url} returned HTTP 404.\n"
            f"  Fix: verify GitHub Pages is enabled (Settings → Pages "
            f"→ Source: GitHub Actions) and that the docs workflow's "
            f"most recent deploy job succeeded. If the repo is private, "
            f"GitHub Pages requires a paid plan (Pro/Team/Enterprise).",
            pytrace=False,
        )
    if status != 200:
        pytest.fail(
            f"{url} returned HTTP {status} (expected 200).\n"
            f"  Body (first 500 chars): {body[:500]}",
            pytrace=False,
        )
    if _EXPECTED_BODY_MARKER not in body:
        pytest.fail(
            f"{url} returned 200 but the body does not contain "
            f"'{_EXPECTED_BODY_MARKER}'.\n"
            f"  Fix: verify the deploy artifact is the framework's site, "
            f"not a default Pages landing page or a catchall.\n"
            f"  Body (first 500 chars): {body[:500]}",
            pytrace=False,
        )

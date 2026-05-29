"""T7 HARD repeat run 006 — docstring↔code drift regression test.

`activegraph.store.url.parse_store_url` documents (url.py:88):

    "Parse a store URL, or raise InvalidStoreURL with a helpful message."

and `InvalidStoreURL` (url.py:43) documents it is "Raised when a URL is
missing a scheme, has an unsupported scheme, or is otherwise malformed."

The module docstring further promises operators see a helpful message
"not a confusing parse error". A malformed-IPv6 URL routes through
`urlparse(url)` which raises a bare `ValueError("Invalid IPv6 URL")`,
escaping the contract: the caller gets neither `InvalidStoreURL` nor the
helpful what_failed/why/how_to_fix context. THAT gap is the bug.

This test asserts the DOCUMENTED behavior and FAILS against current code.
"""

import pytest

from activegraph.store.url import InvalidStoreURL, parse_store_url


class TestMalformedURLRaisesInvalidStoreURL:
    @pytest.mark.parametrize(
        "url",
        [
            "http://[::1/db",   # unterminated IPv6 literal
            "sqlite://[v1.x",   # malformed host bracket
        ],
    )
    def test_malformed_url_raises_invalidstoreurl_not_bare_valueerror(self, url):
        # The docstring promises InvalidStoreURL on a malformed URL.
        # A bare ValueError("Invalid IPv6 URL") from urlparse violates it.
        with pytest.raises(InvalidStoreURL):
            parse_store_url(url)

    def test_malformed_url_message_is_helpful(self):
        # Module + class docstrings promise a helpful message, not a
        # confusing parse error.
        with pytest.raises(InvalidStoreURL) as exc:
            parse_store_url("http://[::1/db")
        msg = str(exc.value)
        assert "Invalid IPv6 URL" not in msg

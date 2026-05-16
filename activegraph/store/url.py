"""Connection URL parsing for stores. CONTRACT v0.8 #2.

The framework addresses stores by URL everywhere (runtime, CLI, library).
URLs follow SQLAlchemy conventions:

- sqlite:///absolute/path/to/run.db         (three slashes!)
- sqlite:///./relative/path.db
- postgres://user:pass@host:port/dbname
- postgresql://user:pass@host:port/dbname    (same scheme)

A path with no scheme is rejected with a message pointing operators at
the right form. We do not silently guess. The operator who types
`activegraph inspect run.db` should see "use sqlite:///run.db", not a
confusing parse error from psycopg.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse


SQLITE_SCHEMES = ("sqlite",)
POSTGRES_SCHEMES = ("postgres", "postgresql")


@dataclass(frozen=True)
class StoreURL:
    scheme: str
    """Normalised: "sqlite" or "postgres"."""

    raw: str
    """The original URL as the user typed it."""

    sqlite_path: Optional[str] = None
    """Filesystem path; populated for SQLite URLs only."""


class InvalidStoreURL(ValueError):
    """Raised when a URL is missing a scheme, has an unsupported scheme,
    or is otherwise malformed.

    The message always points the user at a concrete fix.
    """


def parse_store_url(url: str) -> StoreURL:
    """Parse a store URL, or raise InvalidStoreURL with a helpful message."""
    if not url or not isinstance(url, str):
        raise InvalidStoreURL(
            "store URL is empty. Use sqlite:///path/to/run.db or "
            "postgres://host/dbname."
        )
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if not scheme:
        # Bare path — the most common operator mistake.
        raise InvalidStoreURL(
            f"store URL {url!r} has no scheme. Use sqlite:///{url} for a "
            f"SQLite file, or a postgres://... URL for Postgres. See "
            f"docs/operating.md#connection-urls."
        )
    if scheme in SQLITE_SCHEMES:
        # SQLAlchemy convention (the de-facto standard the framework
        # follows):
        #   sqlite:///path           — relative path
        #   sqlite:////abs/path      — absolute path (the leading / of
        #                              the absolute path adds a 4th slash)
        # urlparse splits these as path="/path" and path="//abs/path"
        # respectively. Strip one leading slash to recover the actual
        # filesystem path.
        path = parsed.path
        if parsed.netloc:
            # "sqlite://host/path" — non-standard; treat host as part of
            # the path component for forgiveness in tests.
            path = f"//{parsed.netloc}{path}"
        if not path:
            raise InvalidStoreURL(
                f"sqlite URL {url!r} has no path. Use sqlite:///relative/path "
                f"or sqlite:////absolute/path."
            )
        if path.startswith("/"):
            path = path[1:]
        if not path:
            raise InvalidStoreURL(
                f"sqlite URL {url!r} has no path. Use sqlite:///relative/path "
                f"or sqlite:////absolute/path."
            )
        return StoreURL(scheme="sqlite", raw=url, sqlite_path=path)
    if scheme in POSTGRES_SCHEMES:
        if not (parsed.hostname or parsed.path.lstrip("/")):
            raise InvalidStoreURL(
                f"postgres URL {url!r} has no host or database. Use "
                f"postgres://host/dbname."
            )
        return StoreURL(scheme="postgres", raw=url)
    raise InvalidStoreURL(
        f"unsupported store URL scheme {scheme!r} in {url!r}. Supported: "
        f"sqlite:///..., postgres://..., postgresql://...."
    )


def open_store(url: str, run_id: str) -> Any:
    """Open a store for `run_id` at `url`. Returns an EventStore.

    This is the single entry point the runtime and CLI use to open a
    store from a URL. Drivers are imported lazily so the Postgres
    dependency stays optional.
    """
    parsed = parse_store_url(url)
    if parsed.scheme == "sqlite":
        from activegraph.store.sqlite import SQLiteEventStore

        assert parsed.sqlite_path is not None
        return SQLiteEventStore(parsed.sqlite_path, run_id=run_id)
    if parsed.scheme == "postgres":
        from activegraph.store.postgres import PostgresEventStore

        return PostgresEventStore(parsed.raw, run_id=run_id)
    raise InvalidStoreURL(f"unhandled scheme {parsed.scheme!r}")

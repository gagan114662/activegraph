from pathlib import Path

import pytest

from activegraph.store.sqlite import SQLiteEventStore
from activegraph.store.url import InvalidStoreURL, open_store


pytestmark = getattr(pytest.mark, "activegraph.store.url.open_store")


def test_activegraph_store_url_open_store_returns_sqlite_event_store_for_relative_sqlite_url(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "t7m_024_relative.db"

    store = open_store(f"sqlite:///{db_path}", run_id="run-t7m-024-relative")

    assert isinstance(store, SQLiteEventStore)
    assert db_path.exists()


def test_activegraph_store_url_open_store_rejects_bare_path_with_invalid_store_url(
    tmp_path: Path,
) -> None:
    bare_path = str(tmp_path / "t7m_024_bare.db")

    with pytest.raises(InvalidStoreURL) as excinfo:
        open_store(bare_path, run_id="run-t7m-024-bare")

    assert "no scheme" in str(excinfo.value)
    assert not (tmp_path / "t7m_024_bare.db").exists()


def test_activegraph_store_url_open_store_rejects_unsupported_scheme_with_invalid_store_url() -> None:
    with pytest.raises(InvalidStoreURL) as excinfo:
        open_store("mysql://localhost/db", run_id="run-t7m-024-mysql")

    assert "mysql" in str(excinfo.value)

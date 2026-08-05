"""A+ path resolution: wenjv primary + legacy inquisitive fallback (empty-dir safe)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.core.paths import (
    dir_has_kb_data,
    resolve_base_dir,
    resolve_sqlite_db_path,
)


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    real_expand = os.path.expanduser

    def _expand(p: str) -> str:
        if p in ("~", "~/"):
            return str(home)
        if isinstance(p, str) and p.startswith("~/"):
            return str(home / p[2:])
        return real_expand(p)

    monkeypatch.setattr(os.path, "expanduser", _expand)
    return home


def _cfg(home: Path, name: str) -> Path:
    d = home / ".config" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_dir_has_kb_data_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    assert dir_has_kb_data(d) is False


def test_dir_has_kb_data_empty_shell_with_empty_subdirs(tmp_path):
    d = tmp_path / "shell"
    (d / "uploads").mkdir(parents=True)
    (d / "logs").mkdir(parents=True)
    (d / "lance_db").mkdir(parents=True)
    assert dir_has_kb_data(d) is False


def test_dir_has_kb_data_backend_env(tmp_path):
    d = tmp_path / "env"
    d.mkdir()
    (d / "backend.env").write_text("# hi\n", encoding="utf-8")
    assert dir_has_kb_data(d) is True


def test_dir_has_kb_data_nonempty_db(tmp_path):
    d = tmp_path / "db"
    d.mkdir()
    (d / "inquisitive.db").write_bytes(b"SQLite-format-placeholder")
    assert dir_has_kb_data(d) is True


def test_dir_has_kb_data_zero_byte_db_ignored(tmp_path):
    d = tmp_path / "z"
    d.mkdir()
    (d / "wenjv.db").write_bytes(b"")
    assert dir_has_kb_data(d) is False


def test_resolve_fresh_install_prefers_wenjv(tmp_home):
    assert resolve_base_dir().endswith(os.path.join(".config", "wenjv"))
    assert "inquisitive" not in Path(resolve_base_dir()).name


def test_resolve_legacy_only(tmp_home):
    legacy = _cfg(tmp_home, "inquisitive")
    (legacy / "inquisitive.db").write_bytes(b"data-legacy")
    assert Path(resolve_base_dir()) == legacy


def test_resolve_empty_wenjv_does_not_steal_legacy(tmp_home):
    """The critical A+ case: empty mkdir shell must not beat real legacy data."""
    primary = _cfg(tmp_home, "wenjv")
    assert primary.is_dir()
    legacy = _cfg(tmp_home, "inquisitive")
    (legacy / "backend.env").write_text("SECRET_KEY=x\n", encoding="utf-8")
    (legacy / "inquisitive.db").write_bytes(b"legacy-db")
    assert Path(resolve_base_dir()) == legacy


def test_resolve_wenjv_with_data_wins(tmp_home):
    primary = _cfg(tmp_home, "wenjv")
    (primary / "wenjv.db").write_bytes(b"new-db")
    legacy = _cfg(tmp_home, "inquisitive")
    (legacy / "inquisitive.db").write_bytes(b"old-db")
    assert Path(resolve_base_dir()) == primary


def test_resolve_wenjv_with_lance_wins_over_legacy(tmp_home):
    primary = _cfg(tmp_home, "wenjv")
    lance = primary / "lance_db"
    lance.mkdir()
    (lance / "chunk.lance").write_text("x", encoding="utf-8")
    legacy = _cfg(tmp_home, "inquisitive")
    (legacy / "inquisitive.db").write_bytes(b"old")
    assert Path(resolve_base_dir()) == primary


def test_sqlite_prefers_nonempty_wenjv(tmp_path):
    base = tmp_path / "b"
    base.mkdir()
    (base / "wenjv.db").write_bytes(b"new")
    (base / "inquisitive.db").write_bytes(b"old")
    assert resolve_sqlite_db_path(base).endswith("wenjv.db")


def test_sqlite_falls_back_to_legacy_when_wenjv_missing(tmp_path):
    base = tmp_path / "b"
    base.mkdir()
    (base / "inquisitive.db").write_bytes(b"old")
    assert resolve_sqlite_db_path(base).endswith("inquisitive.db")


def test_sqlite_empty_wenjv_loses_to_nonempty_legacy(tmp_path):
    base = tmp_path / "b"
    base.mkdir()
    (base / "wenjv.db").write_bytes(b"")
    (base / "inquisitive.db").write_bytes(b"old-data")
    assert resolve_sqlite_db_path(base).endswith("inquisitive.db")


def test_sqlite_fresh_default_name(tmp_path):
    base = tmp_path / "b"
    base.mkdir()
    p = resolve_sqlite_db_path(base)
    assert p.endswith("wenjv.db")
    assert not Path(p).exists()


def test_config_reexports(tmp_home):
    """backend.config must expose the same resolve helpers."""
    from backend.config import resolve_base_dir as r1
    from backend.config import resolve_sqlite_db_path as r2
    from backend.core.paths import resolve_base_dir as r3

    legacy = _cfg(tmp_home, "inquisitive")
    (legacy / "inquisitive.db").write_bytes(b"x")
    assert r1() == r3()
    assert r2(legacy).endswith("inquisitive.db")


def test_kb_launcher_get_config_dir_matches(tmp_home):
    from start.kb_launcher import get_config_dir

    legacy = _cfg(tmp_home, "inquisitive")
    (legacy / "backend.env").write_text("A=1\n", encoding="utf-8")
    # empty primary shell
    _cfg(tmp_home, "wenjv")
    assert get_config_dir() == legacy

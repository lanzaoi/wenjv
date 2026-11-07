"""Product data-dir resolution for wenjv with legacy inquisitive fallback.

Stdlib-only so start/wenjv_launcher can import the same logic as backend.config.

Rules (A+):
- Prefer ~/.config/wenjv when it has real KB markers (db / env / lance / uploads…).
- Else fall back to ~/.config/inquisitive when *that* has markers (even if empty
  wenjv dir exists — empty shell must not steal the install).
- Fresh install (neither has markers) → wenjv path (caller may mkdir).
- DB filename: non-empty wenjv.db > non-empty/any inquisitive.db > default wenjv.db.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

PathLike = Union[str, Path]

PRODUCT_CONFIG_NAME = "wenjv"
LEGACY_CONFIG_NAME = "inquisitive"
PRODUCT_DB_NAME = "wenjv.db"
LEGACY_DB_NAME = "inquisitive.db"

# Files/dirs that mean "this is a real install, not an empty mkdir shell"
_DATA_FILES = (
    PRODUCT_DB_NAME,
    LEGACY_DB_NAME,
    "backend.env",
    "frontend.env",
    "cache.db",
    "knowledge_base.db",
)
_DATA_DIRS = (
    "lance_db",
    "chroma_db",
    "uploads",
    "logs",
)


def dir_has_wenjv_data(dir_path: PathLike) -> bool:
    """True if path is a directory with at least one real KB / wenjv marker."""
    p = Path(dir_path)
    if not p.is_dir():
        return False

    for name in _DATA_FILES:
        fp = p / name
        if not fp.is_file():
            continue
        try:
            if fp.stat().st_size > 0:
                return True
        except OSError:
            continue
        # zero-byte placeholder files do not count

    for name in _DATA_DIRS:
        dp = p / name
        if not dp.is_dir():
            continue
        try:
            next(dp.iterdir())
            return True
        except StopIteration:
            continue
        except OSError:
            continue

    return False


# Backward compatibility alias
dir_has_kb_data = dir_has_wenjv_data


def resolve_base_dir(home: Optional[str] = None) -> str:
    """Pick config/data root: wenjv if populated, else legacy, else wenjv (fresh)."""
    home_dir = home if home is not None else os.path.expanduser("~")
    primary = os.path.join(home_dir, ".config", PRODUCT_CONFIG_NAME)
    fallback = os.path.join(home_dir, ".config", LEGACY_CONFIG_NAME)

    if dir_has_wenjv_data(primary):
        return primary
    if dir_has_wenjv_data(fallback):
        return fallback
    return primary


def resolve_sqlite_db_path(base_dir: PathLike) -> str:
    """Pick sqlite file under base_dir with non-empty preference."""
    base = Path(base_dir)
    primary = base / PRODUCT_DB_NAME
    fallback = base / LEGACY_DB_NAME

    def _nonempty(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    if _nonempty(primary):
        return str(primary)
    if _nonempty(fallback):
        return str(fallback)
    # empty primary file alone → still prefer name for new installs that touched it
    if primary.is_file() and not fallback.is_file():
        return str(primary)
    if fallback.is_file() and not primary.is_file():
        return str(fallback)
    return str(primary)

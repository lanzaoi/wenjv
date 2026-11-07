import asyncio
import os
import time
from pathlib import Path

from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger()

# Default TTL: 24 hours for temporary session images
SESSION_ASSET_TTL_SECONDS = getattr(settings, "SESSION_ASSET_TTL_SECONDS", 24 * 3600)


def cleanup_expired_session_assets(max_age_seconds: int = SESSION_ASSET_TTL_SECONDS) -> int:
    """
    Scan UPLOAD_DIR/mm_assets/sessions/ and remove images older than max_age_seconds.
    Also removes empty directories.
    Returns number of removed files.
    """
    sessions_root = Path(settings.UPLOAD_DIR) / "mm_assets" / "sessions"
    if not sessions_root.exists() or not sessions_root.is_dir():
        return 0

    now = time.time()
    removed_count = 0

    try:
        for file_path in sessions_root.rglob("*"):
            if file_path.is_file():
                try:
                    mtime = file_path.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        file_path.unlink(missing_ok=True)
                        removed_count += 1
                except Exception as err:
                    logger.debug(f"GC: failed to check/remove {file_path}: {err}")

        # Clean empty subdirectories
        for dir_path in sorted(sessions_root.glob("**/*"), key=lambda p: len(p.parts), reverse=True):
            if dir_path.is_dir() and not any(dir_path.iterdir()):
                try:
                    dir_path.rmdir()
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Error during session asset cleanup: {e}")

    if removed_count > 0:
        logger.info(f"Session asset GC cleaned {removed_count} expired files.")
    return removed_count


async def periodic_asset_gc_worker(interval_seconds: int = 3600):
    """Background task running periodic garbage collection."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await asyncio.to_thread(cleanup_expired_session_assets)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Periodic asset GC encountered error: {e}")

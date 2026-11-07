import io
import time
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.dependencies import current_active_user
from backend.api.models import User
from backend.core.asset_gc import cleanup_expired_session_assets


def test_attachment_upload_oversize_rejected(tmp_path, monkeypatch):
    """Verify that uploading attachment over MAX_UPLOAD_BYTES returns 413 (H4)."""
    monkeypatch.setattr("backend.config.settings.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("backend.config.settings.MAX_UPLOAD_BYTES", 1000)

    dummy_user = User(
        id=101,
        email="test_oversize@wenjv.internal",
        hashed_password="pw",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    app.dependency_overrides[current_active_user] = lambda: dummy_user
    client = TestClient(app)

    # 2KB payload
    big_bytes = b"X" * 2000
    res = client.post(
        "/chat/attachments",
        files={"file": ("big.jpg", big_bytes, "image/jpeg")},
    )
    assert res.status_code == 413
    app.dependency_overrides.clear()


def test_asset_cross_user_isolation(tmp_path, monkeypatch):
    """Verify User B cannot access User A's session attachments (H1)."""
    monkeypatch.setattr("backend.config.settings.UPLOAD_DIR", str(tmp_path))

    user_a = User(id=1001, email="user_a@wenjv.internal", hashed_password="pw", is_active=True)
    user_b = User(id=1002, email="user_b@wenjv.internal", hashed_password="pw", is_active=True)

    from backend.api.dependencies import current_active_user, current_optional_user

    # 1. User A uploads an attachment
    app.dependency_overrides[current_active_user] = lambda: user_a
    app.dependency_overrides[current_optional_user] = lambda: user_a
    client = TestClient(app)

    test_img = Image.new("RGB", (50, 50), color=(10, 20, 30))
    buf = io.BytesIO()
    test_img.save(buf, format="JPEG")

    res = client.post(
        "/chat/attachments",
        files={"file": ("secret.jpg", buf.getvalue(), "image/jpeg")},
        data={"session_id": "sess_a"},
    )
    assert res.status_code == 200
    media_url = res.json()["media_url"]
    assert "mm_assets/sessions/1001/sess_a" in media_url

    # User A accesses it -> 200
    res_a = client.get(media_url)
    assert res_a.status_code == 200

    # 2. User B tries to access User A's image -> 403 Forbidden!
    app.dependency_overrides[current_active_user] = lambda: user_b
    app.dependency_overrides[current_optional_user] = lambda: user_b
    res_b = client.get(media_url)
    assert res_b.status_code == 403
    assert "Access denied" in res_b.json()["detail"]

    app.dependency_overrides.clear()


def test_session_asset_gc_cleanup(tmp_path, monkeypatch):
    """Verify expired session assets are cleaned up by GC (H5)."""
    monkeypatch.setattr("backend.config.settings.UPLOAD_DIR", str(tmp_path))

    sess_dir = tmp_path / "mm_assets" / "sessions" / "999" / "sess_old"
    sess_dir.mkdir(parents=True, exist_ok=True)
    old_file = sess_dir / "old_image.jpg"
    old_file.write_bytes(b"dummy_data")

    # Set mtime to 2 days ago
    two_days_ago = time.time() - (48 * 3600)
    import os
    os.utime(old_file, (two_days_ago, two_days_ago))

    # Run cleanup with 24h TTL
    cleaned = cleanup_expired_session_assets(max_age_seconds=24 * 3600)
    assert cleaned == 1
    assert not old_file.exists()
    assert not sess_dir.exists()  # Directory removed when empty

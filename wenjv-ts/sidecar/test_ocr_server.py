import io
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import ocr_server

client = TestClient(ocr_server.app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "engines" in data


def test_ocr_image_real_handwritten_physics_note() -> None:
    note_path = Path(
        "/home/lanzao/antigravity/jolly-hawking/wenjv-ts/.data/uploads/"
        "波动光学_01_光的相干性与光程_手抄笔记-004-622f45b5.png"
    )
    if not note_path.exists():
        return

    with note_path.open("rb") as f:
        resp_auto = client.post(
            "/ocr/image",
            files={"file": ("note.png", f, "image/png")},
            data={"mode": "auto"},
        )
    assert resp_auto.status_code == 200
    data = resp_auto.json()
    assert data["engine"] == "ppocrv5-mobile+pix2text"
    print("REAL IMAGE OUTPUT:\n", data["text"])
    assert "相位差" in data["text"]
    assert "相消" in data["text"]
    assert "121" in data["text"]


def test_ocr_pdf_scanned_page() -> None:
    img = Image.new("RGB", (600, 180), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((24, 60), "Optical Path Difference 30 um", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PDF")

    resp = client.post(
        "/ocr/pdf",
        files={"file": ("scan.pdf", buf.getvalue(), "application/pdf")},
        data={"mode": "general", "max_pages": "3"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pages"] == 1
    assert "Optical" in data["text"] or "30" in data["text"]

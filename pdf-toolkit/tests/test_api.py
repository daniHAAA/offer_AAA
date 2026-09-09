"""HTTP-Schnittstelle -- inklusive der Frage, was ein Client NICHT darf."""

import io
import json
from pathlib import Path

import pytest

from conftest import build_form, build_pdf, build_image
from pdftoolkit.app import create_app
from pdftoolkit.config import Config


@pytest.fixture
def client(tmp_path):
    class TestConfig(Config):
        WORKSPACE_ROOT = tmp_path / "workspaces"
        SECRET_KEY = "test"
        TESTING = True

    app = create_app(TestConfig)
    with app.test_client() as test_client:
        yield test_client


def upload(client, path: Path, name: str | None = None) -> str:
    """Lädt eine Datei hoch und gibt ihre ID zurück."""
    data = {"files": (io.BytesIO(path.read_bytes()), name or path.name)}
    response = client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200, response.get_json()
    return response.get_json()["files"][0]["id"]


def post(client, url: str, body: dict):
    return client.post(url, data=json.dumps(body), content_type="application/json")


# ------------------------------------------------------------ Grundfunktionen

def test_index_and_health(client):
    assert client.get("/").status_code == 200
    health = client.get("/api/health").get_json()
    assert health["ok"] is True
    assert "version" in health


def test_upload_list_and_delete(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 2))

    files = client.get("/api/files").get_json()["files"]
    assert len(files) == 1
    assert files[0]["name"] == "a.pdf"
    assert files[0]["is_pdf"] is True

    assert client.delete(f"/api/files/{file_id}").status_code == 200
    assert client.get("/api/files").get_json()["files"] == []


def test_upload_rejects_foreign_type(client, tmp_path):
    script = tmp_path / "boese.exe"
    script.write_bytes(b"MZ")
    response = client.post(
        "/api/upload",
        data={"files": (io.BytesIO(script.read_bytes()), "boese.exe")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert "PDF" in response.get_json()["error"]


def test_info_and_preview(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 3))

    info = client.get(f"/api/files/{file_id}/info").get_json()["info"]
    assert info["page_count"] == 3
    assert len(info["pages"]) == 3

    preview = client.get(f"/api/files/{file_id}/page/2.png?width=120")
    assert preview.status_code == 200
    assert preview.mimetype == "image/png"


def test_preview_rejects_missing_page(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    assert client.get(f"/api/files/{file_id}/page/9.png").status_code == 400


def test_unknown_file_id_is_rejected(client):
    assert client.get("/api/files/deadbeef/info").status_code == 400
    assert post(client, "/api/organize", {"file": "deadbeef", "layout": [{"page": 1}]}).status_code == 400


def test_workspaces_are_separated(client, tmp_path):
    """Was eine Sitzung hochlädt, darf eine andere nicht sehen."""
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    client.delete_cookie("session")
    assert client.get("/api/files").get_json()["files"] == []
    assert client.get(f"/api/files/{file_id}/download").status_code == 400


# ------------------------------------------------------------ Werkzeuge

def test_merge_endpoint(client, tmp_path):
    first = upload(client, build_pdf(tmp_path / "a.pdf", 2, "A"))
    second = upload(client, build_pdf(tmp_path / "b.pdf", 3, "B"))

    response = post(client, "/api/merge", {"files": [{"id": first}, {"id": second}]})
    result = response.get_json()
    assert response.status_code == 200
    assert result["file"]["kind"] == "result"

    info = client.get(f"/api/files/{result['file']['id']}/info").get_json()["info"]
    assert info["page_count"] == 5


def test_merge_needs_two_files(client, tmp_path):
    only = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    assert post(client, "/api/merge", {"files": [{"id": only}]}).status_code == 400


def test_split_returns_zip_for_multiple_parts(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 4))
    result = post(client, "/api/split",
                  {"file": file_id, "mode": "ranges", "ranges": ["1-2", "3-4"]}).get_json()
    assert result["file"]["name"].endswith(".zip")


def test_split_single_range_returns_pdf(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 4))
    result = post(client, "/api/split",
                  {"file": file_id, "mode": "ranges", "ranges": ["2-3"]}).get_json()
    assert result["file"]["name"].endswith(".pdf")


def test_organize_endpoint(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 3))
    result = post(client, "/api/organize",
                  {"file": file_id, "layout": [{"page": 3, "rotate": 90}, {"page": 1}]}).get_json()

    info = client.get(f"/api/files/{result['file']['id']}/info").get_json()["info"]
    assert info["page_count"] == 2
    assert info["pages"][0]["rotation"] == 90


def test_edit_endpoint(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    response = post(client, "/api/edit", {
        "file": file_id,
        "annotations": [{"type": "text", "page": 1, "x": .1, "y": .5, "w": .6, "h": .1,
                         "text": "Hallo Welt"}],
    })
    assert response.status_code == 200


def test_edit_image_must_come_from_workspace(client, tmp_path):
    """Ein freier Pfad im Feld image_path darf nicht durchschlagen."""
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    response = post(client, "/api/edit", {
        "file": file_id,
        "annotations": [{"type": "image", "page": 1, "x": .1, "y": .1, "w": .2, "h": .2,
                         "image_path": "/etc/passwd"}],
    })
    assert response.status_code == 400
    assert "Bilddatei" in response.get_json()["error"]


def test_edit_with_workspace_image(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    image_id = upload(client, build_image(tmp_path / "bild.png"))
    response = post(client, "/api/edit", {
        "file": file_id,
        "annotations": [{"type": "image", "page": 1, "x": .1, "y": .1, "w": .2, "h": .2,
                         "image_id": image_id}],
    })
    assert response.status_code == 200


def test_watermark_and_page_numbers(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 2))
    assert post(client, "/api/watermark", {"file": file_id, "text": "ENTWURF"}).status_code == 200
    assert post(client, "/api/page-numbers", {"file": file_id}).status_code == 200


def test_forms_read_and_fill(client, tmp_path):
    file_id = upload(client, build_form(tmp_path / "form.pdf"))

    fields = client.get(f"/api/forms/{file_id}").get_json()["fields"]
    assert {field["name"] for field in fields} == {"name", "agb", "stufe"}

    response = post(client, f"/api/forms/{file_id}/fill",
                    {"values": {"name": "Daniel", "agb": True}, "flatten": True})
    assert response.status_code == 200

    result_id = response.get_json()["file"]["id"]
    assert client.get(f"/api/forms/{result_id}").get_json()["fields"] == []


def test_form_fill_reports_unknown_field(client, tmp_path):
    file_id = upload(client, build_form(tmp_path / "form.pdf"))
    response = post(client, f"/api/forms/{file_id}/fill", {"values": {"quatsch": "1"}})
    assert response.status_code == 400
    assert "Unbekannte Felder" in response.get_json()["error"]


def test_convert_text_endpoint(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 2, "Inhalt"))
    result = post(client, "/api/convert/text", {"file": file_id}).get_json()
    assert "Inhalt Seite 1" in result["preview"]


def test_convert_images_endpoint(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 2))
    result = post(client, "/api/convert/images", {"file": file_id, "dpi": 72}).get_json()
    assert result["file"]["name"].endswith(".zip")


def test_images_to_pdf_endpoint(client, tmp_path):
    image_id = upload(client, build_image(tmp_path / "bild.png"))
    result = post(client, "/api/convert/images-to-pdf", {"files": [image_id]}).get_json()
    assert result["file"]["name"].endswith(".pdf")


def test_encrypt_then_locked_response(client, tmp_path):
    """Ein geschütztes PDF muss mit 423 antworten, damit die Oberfläche fragen kann."""
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 1))
    encrypted = post(client, "/api/security/encrypt",
                     {"file": file_id, "user_password": "geheim"}).get_json()["file"]["id"]

    locked = client.get(f"/api/files/{encrypted}/info")
    assert locked.status_code == 423
    assert locked.get_json()["needs_password"] is True

    opened = client.get(f"/api/files/{encrypted}/info?password=geheim")
    assert opened.status_code == 200

    removed = post(client, "/api/security/decrypt", {"file": encrypted, "password": "geheim"})
    assert removed.status_code == 200


def test_compress_returns_statistics(client, tmp_path):
    file_id = upload(client, build_pdf(tmp_path / "a.pdf", 3))
    result = post(client, "/api/compress", {"file": file_id}).get_json()
    assert result["stats"]["before"] >= result["stats"]["after"]


def test_results_can_be_chained(client, tmp_path):
    """Das Ergebnis eines Schrittes muss Eingabe des nächsten sein können."""
    first = upload(client, build_pdf(tmp_path / "a.pdf", 2))
    second = upload(client, build_pdf(tmp_path / "b.pdf", 2))

    merged = post(client, "/api/merge", {"files": [{"id": first}, {"id": second}]})
    merged_id = merged.get_json()["file"]["id"]

    numbered = post(client, "/api/page-numbers", {"file": merged_id})
    assert numbered.status_code == 200

    info = client.get(f"/api/files/{numbered.get_json()['file']['id']}/info").get_json()["info"]
    assert info["page_count"] == 4


def test_clear_workspace(client, tmp_path):
    upload(client, build_pdf(tmp_path / "a.pdf", 1))
    assert client.post("/api/files/clear").status_code == 200
    assert client.get("/api/files").get_json()["files"] == []

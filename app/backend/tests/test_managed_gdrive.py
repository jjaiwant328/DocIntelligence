"""Offline tests for the managed-MCP Google Drive adapter (no network)."""
import base64

from indexer.managed_gdrive import (
    ManagedDriveSource,
    is_text_readable,
    map_search_item,
)


def test_map_search_item_file():
    raw = {
        "id": "F1", "name": "INV-2001.txt", "mimeType": "text/plain",
        "webViewLink": "https://drive.google.com/file/d/F1/view",
        "modifiedTime": "2026-02-20T00:00:00Z",
        "owners": [{"emailAddress": "u@databricks.com"}],
    }
    m = map_search_item(raw)
    assert m["item_id"] == "F1"
    assert m["is_folder"] is False
    assert m["web_url"] == "https://drive.google.com/file/d/F1/view"
    assert m["etag"] == "2026-02-20T00:00:00Z"      # modifiedTime is the change token
    assert m["owner"] == "u@databricks.com"


def test_map_search_item_folder():
    m = map_search_item({"id": "D1", "name": "sub", "mimeType": "application/vnd.google-apps.folder"})
    assert m["is_folder"] is True


def test_is_text_readable():
    assert is_text_readable("text/plain")
    assert is_text_readable("application/vnd.google-apps.document")
    assert not is_text_readable("application/pdf")


def test_list_children_queries_parent_and_maps():
    calls = []

    def fake(tool, args):
        calls.append((tool, args))
        return {"items": [
            {"id": "F1", "name": "a.txt", "mimeType": "text/plain"},
            {"id": "D1", "name": "sub", "mimeType": "application/vnd.google-apps.folder"},
        ]}

    src = ManagedDriveSource(fake, root_folder_id="ROOT")
    out = src.list_children()            # empty -> uses root
    assert calls[0][0] == "google_drive_search"
    assert "'ROOT' in parents" in calls[0][1]["query"]
    assert [o["item_id"] for o in out] == ["F1", "D1"]
    assert out[1]["is_folder"] is True


def test_fetch_document_b64_and_filename():
    def fake(tool, args):
        assert tool == "google_file_download"
        assert args["file_id"] == "F1"
        return {"name": "INV-2001.txt", "mime_type": "text/plain", "content": "hello drive"}

    src = ManagedDriveSource(fake, root_folder_id="ROOT")
    r = src.fetch_document("F1")
    assert r["filename"] == "INV-2001.txt"
    assert base64.b64decode(r["content_b64"]).decode() == "hello drive"


def test_fetch_document_raises_on_unsupported():
    def fake(tool, args):
        return {"error_code": "UNSUPPORTED_FILE_FORMAT", "message": "pdf not supported"}

    src = ManagedDriveSource(fake, root_folder_id="ROOT")
    try:
        src.fetch_document("P1")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "UNSUPPORTED_FILE_FORMAT" in str(e)

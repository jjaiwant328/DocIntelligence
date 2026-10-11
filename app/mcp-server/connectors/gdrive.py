"""Google Drive connector. Uses the real Drive v3 REST API when OAuth is
configured AND connected; otherwise transparently serves the synthetic dataset,
so the demo always works and real Drive is a drop-in once secrets are set."""
from __future__ import annotations

import base64
import time

import requests

from .base import Connector
from .synthetic import SyntheticDriveConnector

_FILES = "https://www.googleapis.com/drive/v3/files"

# Fields requested for every item fetch; covers all keys in the metadata dict.
# owners(emailAddress) is nested — Drive API accepts this dotted form.
_ITEM_FIELDS = (
    "id,name,mimeType,size,webViewLink,modifiedTime,"
    "owners(emailAddress),version,md5Checksum,parents"
)


def _file_to_meta(f: dict) -> dict:
    """Convert a Drive v3 file resource to the standard crawler metadata dict."""
    is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
    owners = f.get("owners") or [{}]
    owner_email = owners[0].get("emailAddress", "")
    # Prefer version (opaque string Drive uses for change detection), then
    # md5Checksum (not set for native docs), then fall back to modifiedTime.
    etag = f.get("version") or f.get("md5Checksum") or f.get("modifiedTime", "")
    # Building a full path requires parent-name traversal (extra API calls).
    # Use the file name as a simple relative path; callers that need a full
    # tree path should traverse parents with list_children().
    return {
        "item_id": f["id"],
        "name": f.get("name", f["id"]),
        "path": f.get("name", f["id"]),
        "mime_type": f.get("mimeType", ""),
        "size": int(f.get("size", 0) or 0),
        "web_url": f.get("webViewLink", ""),
        "etag": str(etag),
        "modified_at": f.get("modifiedTime", ""),
        "owner": owner_email,
        "is_folder": is_folder,
    }
# Google-native docs must be exported; pick a sensible binary export per type.
_EXPORT = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "application/pdf",
}


class GoogleDriveConnector(Connector):
    id = "gdrive"
    name = "Google Drive"

    def __init__(self, oauth) -> None:
        self.oauth = oauth
        self._synthetic = SyntheticDriveConnector()

    def describe(self) -> dict:
        if not self.oauth.configured:
            return self._synthetic.describe()
        return {"id": self.id, "name": self.name, "mode": "real",
                "connected": self.oauth.connected,
                "auth_path": "/oauth/google/start" if not self.oauth.connected else None}

    def _live(self) -> bool:
        return self.oauth.configured and self.oauth.connected

    def list_documents(self, folder_id: str = "", query: str = "") -> dict:
        if not self._live():
            return self._synthetic.list_documents(folder_id, query)
        token = self.oauth.access_token()
        q_parts = ["trashed = false"]
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if query:
            q_parts.append(f"name contains '{query}'")
        params = {"q": " and ".join(q_parts), "pageSize": 100,
                  "fields": "files(id,name,mimeType,size,modifiedTime,parents)"}
        r = requests.get(_FILES, params=params,
                         headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        items = []
        for f in r.json().get("files", []):
            items.append({
                "doc_ref": f["id"], "name": f.get("name", f["id"]),
                "mime_type": f.get("mimeType", ""), "size": int(f.get("size", 0) or 0),
                "modified": f.get("modifiedTime", ""),
                "folder": (f.get("parents") or [""])[0], "doc_type_hint": "",
            })
        return {"items": items}

    def fetch_document(self, doc_ref: str) -> dict:
        if not self._live():
            return self._synthetic.fetch_document(doc_ref)
        token = self.oauth.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        meta = requests.get(f"{_FILES}/{doc_ref}", params={"fields": "name,mimeType"},
                            headers=headers, timeout=30)
        meta.raise_for_status()
        name = meta.json().get("name", doc_ref)
        mime = meta.json().get("mimeType", "")
        if mime in _EXPORT:
            export_mime = _EXPORT[mime]
            r = requests.get(f"{_FILES}/{doc_ref}/export", params={"mimeType": export_mime},
                             headers=headers, timeout=60)
            ext = {"application/pdf": ".pdf", "text/csv": ".csv"}.get(export_mime, "")
            filename, out_mime = f"{name}{ext}", export_mime
        else:
            r = requests.get(f"{_FILES}/{doc_ref}", params={"alt": "media"},
                             headers=headers, timeout=60)
            filename, out_mime = name, mime
        r.raise_for_status()
        return {"doc_ref": doc_ref, "name": name, "filename": filename,
                "mime_type": out_mime, "content_b64": base64.b64encode(r.content).decode("ascii")}

    # ── metadata / crawl ─────────────────────────────────────────────────────

    def list_children(self, folder_id: str = "") -> dict:
        if not self._live():
            return self._synthetic.list_children(folder_id)
        token = self.oauth.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        # Drive uses 'root' to mean the user's My Drive root folder.
        parent = folder_id if folder_id else "root"
        params = {
            "q": f"'{parent}' in parents and trashed = false",
            "pageSize": 100,
            "fields": f"files({_ITEM_FIELDS}),nextPageToken",
        }
        items = []
        while True:
            r = requests.get(_FILES, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            for f in data.get("files", []):
                items.append(_file_to_meta(f))
            next_page = data.get("nextPageToken")
            if next_page:
                params["pageToken"] = next_page
            else:
                break
        return {"items": items}

    def get_file_metadata(self, item_id: str) -> dict:
        if not self._live():
            return self._synthetic.get_file_metadata(item_id)
        token = self.oauth.access_token()
        r = requests.get(
            f"{_FILES}/{item_id}",
            params={"fields": _ITEM_FIELDS},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        return _file_to_meta(r.json())

    def get_changes(self, since_token: str = "") -> dict:
        """Full-list fallback — returns every non-trashed Drive item as 'changed'.
        NOTE: Does not use the Drive incremental Changes API; since_token is
        accepted but ignored. Use list_children / get_file_metadata for targeted
        crawls instead. A timestamp-based opaque token is returned as next_token."""
        if not self._live():
            return self._synthetic.get_changes(since_token)
        token = self.oauth.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "q": "trashed = false",
            "pageSize": 100,
            "fields": f"files({_ITEM_FIELDS}),nextPageToken",
        }
        items = []
        while True:
            r = requests.get(_FILES, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            for f in data.get("files", []):
                items.append(_file_to_meta(f))
            next_page = data.get("nextPageToken")
            if next_page:
                params["pageToken"] = next_page
            else:
                break
        return {"items": items, "next_token": str(int(time.time()))}

    def check_access(self, item_id: str) -> dict:
        if not self._live():
            return self._synthetic.check_access(item_id)
        try:
            token = self.oauth.access_token()
            r = requests.get(
                f"{_FILES}/{item_id}",
                params={"fields": "id"},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if r.status_code == 200:
                return {"accessible": True, "reason": ""}
            return {"accessible": False, "reason": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"accessible": False, "reason": str(e)}

    def get_source_url(self, item_id: str) -> str:
        if not self._live():
            return self._synthetic.get_source_url(item_id)
        token = self.oauth.access_token()
        r = requests.get(
            f"{_FILES}/{item_id}",
            params={"fields": "webViewLink"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("webViewLink", "")

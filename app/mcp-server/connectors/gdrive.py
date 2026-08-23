"""Google Drive connector. Uses the real Drive v3 REST API when OAuth is
configured AND connected; otherwise transparently serves the synthetic dataset,
so the demo always works and real Drive is a drop-in once secrets are set."""
from __future__ import annotations

import base64

import requests

from .base import Connector
from .synthetic import SyntheticDriveConnector

_FILES = "https://www.googleapis.com/drive/v3/files"
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

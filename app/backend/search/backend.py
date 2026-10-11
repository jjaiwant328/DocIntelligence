"""SearchBackend protocol — anything implementing .search() can be used."""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class SearchBackend(Protocol):
    """Protocol for hybrid search backends.

    Implementors embed the query and run a fused vector+FTS search,
    returning a list of result dicts with at minimum chunk_id, snippet,
    and score keys.
    """

    def search(
        self,
        domain_id: str,
        project_id: str,
        query: str,
        k: int = 10,
        folder: str = "",
        types: Optional[list[str]] = None,
    ) -> list[dict]:
        """Run a hybrid search and return up to *k* ranked results."""
        ...

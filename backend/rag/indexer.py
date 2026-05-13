"""Indexer stub — keyword-based retrieval needs no pre-indexing.

ChromaDB vector indexing is available but requires embedding API.
Use index_metadata_with_embeddings() if you have an embedding provider.
"""


def index_metadata(force: bool = False) -> int:
    """No-op: keyword retrieval reads metadata directly, no pre-indexing needed."""
    return 0

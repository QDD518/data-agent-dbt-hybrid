"""ChromaDB indexer — embeds dbt metadata into a persistent vector store."""

import chromadb
from chromadb.api import Collection

from backend.config import settings
from backend.metadata.parser import load_metadata
from backend.llm.client import get_embeddings

COLLECTION_NAME = "dbt_metadata"


def _get_collection() -> Collection:
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return client.get_or_create_collection(name=COLLECTION_NAME)


def index_metadata(force: bool = False) -> int:
    """Index dbt metadata into ChromaDB. Returns number of documents indexed.
    Skips if collection already has data, unless force=True."""
    collection = _get_collection()

    if not force and collection.count() > 0:
        return collection.count()

    store = load_metadata()
    docs = store.to_rag_documents()

    # Clear stale data
    try:
        collection.delete(ids=[str(i) for i in range(collection.count())])
    except Exception:
        pass

    if not docs:
        return 0

    embeddings = get_embeddings(docs)
    collection.add(
        ids=[str(i) for i in range(len(docs))],
        embeddings=embeddings,
        documents=docs,
    )
    return len(docs)

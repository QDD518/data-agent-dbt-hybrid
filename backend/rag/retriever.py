"""ChromaDB retriever — semantic search over dbt metadata."""

from backend.rag.indexer import _get_collection, index_metadata
from backend.llm.client import get_embeddings


def retrieve_context(query: str, top_k: int = 5) -> list[str]:
    """Retrieve the most relevant dbt metadata documents for a query.
    Auto-indexes if the collection is empty."""
    index_metadata()
    collection = _get_collection()

    query_embedding = get_embeddings([query])
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, collection.count()),
    )

    documents = results.get("documents", [[]])
    return documents[0] if documents else []

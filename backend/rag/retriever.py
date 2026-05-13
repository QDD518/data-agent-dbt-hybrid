"""Metadata retriever — keyword-based search over dbt metadata documents.

Uses simple keyword overlap scoring (no embedding API dependency).
For 22 documents this is fast enough, avoids external embedding costs.
"""

import re

from backend.metadata.parser import load_metadata


def retrieve_context(query: str, top_k: int = 5) -> list[str]:
    """Retrieve the most relevant dbt metadata documents by keyword overlap."""
    store = load_metadata()
    docs = store.to_rag_documents()

    if not docs:
        return []

    # Tokenize query
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return docs[:top_k]

    # Score each doc by overlap
    scored: list[tuple[int, str]] = []
    for doc in docs:
        doc_tokens = set(_tokenize(doc))
        score = len(query_tokens & doc_tokens)
        scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Return docs with score > 0, capped at top_k
    results = [doc for score, doc in scored if score > 0][:top_k]
    if not results:
        results = [scored[0][1]]  # at least return the best match
    return results


def _tokenize(text: str) -> list[str]:
    """Tokenize: bigrams for CJK, words for Latin."""
    tokens: list[str] = []

    # Latin words
    tokens.extend(re.findall(r"[a-zA-Z0-9_]+", text.lower()))

    # CJK: character bigrams for better matching
    cjk = re.findall(r"[一-鿿㐀-䶿]", text)
    for i in range(len(cjk)):
        tokens.append(cjk[i])                    # unigram
        if i < len(cjk) - 1:
            tokens.append(cjk[i] + cjk[i + 1])   # bigram

    return tokens

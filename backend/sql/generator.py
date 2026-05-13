"""Path B — LLM Text-to-SQL generator for exploratory queries."""

from backend.llm.client import chat
from backend.rag.retriever import retrieve_context

_SQL_GENERATOR_PROMPT = """You are a PostgreSQL SQL expert for a Chat BI system. Generate a read-only SELECT query for the user's question.

## Database Context (from dbt documentation):
{context}

## Rules:
1. Output ONLY the SQL query. No markdown, no explanation, no ``` fences.
2. Only SELECT / WITH queries — never INSERT, UPDATE, DELETE, DROP.
3. Use the table and column names exactly as shown in the context above.
4. Always include reasonable LIMIT (max 1000).
5. Use proper PostgreSQL date functions: CURRENT_DATE, date_trunc(), interval.
6. If you can't answer, output: UNABLE_TO_GENERATE
"""


def generate_sql(user_question: str) -> str:
    """Generate exploratory SQL using LLM + RAG context."""
    context_docs = retrieve_context(user_question, top_k=8)
    context = "\n".join(f"- {doc}" for doc in context_docs)

    if not context.strip():
        context = "No relevant table metadata found. Use information_schema conventions."

    prompt = _SQL_GENERATOR_PROMPT.format(context=context)

    response = chat([
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_question},
    ])

    sql = response.strip()
    if sql.startswith("```"):
        lines = sql.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        sql = "\n".join(lines)

    return sql.strip()

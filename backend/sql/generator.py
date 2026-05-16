"""Path B — LLM Text-to-SQL generator for exploratory queries."""

from backend.llm.client import chat
from backend.rag.retriever import retrieve_context

_SQL_GENERATOR_PROMPT = """You are a PostgreSQL SQL expert for a Chat BI system. Generate a read-only SELECT query for the user's question.

## Database Tables and Columns (from dbt documentation):
{context}

## Ontology Object Graph (valid relationships between business objects):
{ontology_context}

## Rules:
1. Output ONLY the SQL query. No markdown, no explanation, no ``` fences.
2. Only SELECT / WITH queries — never INSERT, UPDATE, DELETE, DROP.
3. Use the table and column names exactly as shown in the context above.
4. When joining tables, prefer the relationships described in the Ontology Object Graph above.
5. Object types that share the same home table do not need JOINs — their properties are already available as columns on that table.
6. Always include reasonable LIMIT (max 1000).
7. Use proper PostgreSQL date functions: CURRENT_DATE, date_trunc(), interval.
8. If you can't answer, output: UNABLE_TO_GENERATE
"""


def generate_sql(user_question: str) -> str:
    """Generate exploratory SQL using LLM + RAG context."""
    context_docs = retrieve_context(user_question, top_k=8)
    context = "\n".join(f"- {doc}" for doc in context_docs)

    if not context.strip():
        context = "No relevant table metadata found. Use information_schema conventions."

    # Build ontology context for join-path guidance
    ontology_context = "No ontology available."
    try:
        from backend.ontology.parser import load_ontology
        onto = load_ontology()
        onto_lines = []
        for obj in onto.object_by_name.values():
            links = onto.outbound_links.get(obj.name, [])
            link_str = ", ".join(
                f"{l.name} -> {l.target} (JOIN {l.source_column} = {l.target_column})"
                for l in links
            ) if links else "none"
            onto_lines.append(
                f"- {obj.name} ({obj.display_name}) → table: {obj.table}, "
                f"primary key: {obj.primary_key}. Links: {link_str}"
            )
        ontology_context = "\n".join(onto_lines)
    except Exception:
        pass

    prompt = _SQL_GENERATOR_PROMPT.format(context=context, ontology_context=ontology_context)

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

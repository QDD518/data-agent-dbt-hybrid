"""Chat Orchestrator — routes user questions through Path A/B/C/D, streams SSE events."""

import asyncio
import json
from typing import AsyncGenerator

from backend.agent.router import classify_intent
from backend.semantic.query_builder import MetricQueryBuilder, SemanticQuery, CrossModelQueryError
from backend.sql.generator import generate_sql
from backend.sql.executor import execute_sql
from backend.sql.security import SQLSecurityError
from backend.rag.retriever import retrieve_context
from backend.llm.client import chat
from backend.ontology.parser import load_ontology
from backend.ontology.traversal import (
    GraphTraverser,
    TraversalRequest,
    TraversalStep,
    FilterClause,
)


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


async def process_message(message: str) -> AsyncGenerator[str, None]:
    """Main pipeline: route → execute → interpret. Yields SSE events."""

    # ── Phase 1: Intent Classification ──
    yield _sse("status", {"stage": "classifying", "message": "Analyzing your question..."})

    loop = asyncio.get_running_loop()
    intent = await loop.run_in_executor(None, classify_intent, message)
    path = intent.get("path", "exploratory")
    yield _sse("status", {"stage": "classified", "path": path, "intent": intent})

    # ── Phase 2: Execute by path ──
    if path == "metric_query":
        async for event in _handle_path_a(intent):
            yield event

    elif path == "ontology_query":
        async for event in _handle_path_d(intent, message):
            yield event

    elif path == "exploratory":
        async for event in _handle_path_b(message):
            yield event

    elif path == "metadata":
        async for event in _handle_path_c(message):
            yield event

    else:
        yield _sse("error", {"message": f"Unknown path: {path}"})


async def _handle_path_a(intent: dict) -> AsyncGenerator[str, None]:
    """Path A: MetricFlow-style deterministic SQL from semantic metadata."""
    yield _sse("status", {"stage": "building_sql", "message": "Building metric query..."})

    loop = asyncio.get_running_loop()

    query = SemanticQuery(
        metric_names=intent.get("metric_names", []),
        dimensions=intent.get("dimensions", []),
        time_range=intent.get("time_range"),
    )

    if not query.metric_names:
        yield _sse("error", {"message": "No metrics identified. Please rephrase."})
        return

    try:
        builder = MetricQueryBuilder()
        sql = await loop.run_in_executor(None, builder.build_sql, query)
    except CrossModelQueryError as e:
        # Fallback: try ontology traversal for cross-model queries
        yield _sse("status", {"stage": "cross_model_fallback", "message": "Cross-model query detected, routing through ontology..."})
        async for event in _handle_path_a_ontology_fallback(intent, e):
            yield event
        return
    except ValueError as e:
        yield _sse("error", {"message": str(e)})
        return

    yield _sse("sql", {"sql": sql})

    # Execute
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, sql)
    except SQLSecurityError as e:
        yield _sse("error", {"message": f"SQL rejected: {e}"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Query failed: {e}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })

    # Interpret
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    interpretation = await _interpret_results(message="", result=result)
    yield _sse("done", {"summary": interpretation})


async def _handle_path_b(message: str) -> AsyncGenerator[str, None]:
    """Path B: LLM Text-to-SQL for exploratory queries."""
    yield _sse("status", {"stage": "retrieving_context", "message": "Searching relevant data models..."})

    loop = asyncio.get_running_loop()

    # Retrieve relevant context
    context_docs = await loop.run_in_executor(None, retrieve_context, message, 5)
    yield _sse("context", {"documents": context_docs[:3]})

    # Generate SQL
    yield _sse("status", {"stage": "generating_sql", "message": "Generating SQL with LLM..."})
    sql = await loop.run_in_executor(None, generate_sql, message)

    if sql == "UNABLE_TO_GENERATE" or not sql:
        yield _sse("error", {"message": "Unable to generate SQL for this question. Try rephrasing."})
        return

    yield _sse("sql", {"sql": sql})

    # Execute
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, sql)
    except SQLSecurityError as e:
        yield _sse("error", {"message": f"SQL rejected by security: {e}"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Query failed: {e}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })

    # Interpret
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    interpretation = await _interpret_results(message=message, result=result)
    yield _sse("done", {"summary": interpretation})


async def _handle_path_c(message: str) -> AsyncGenerator[str, None]:
    """Path C: RAG-based metadata Q&A — direct answer, no SQL."""
    yield _sse("status", {"stage": "retrieving_docs", "message": "Searching documentation..."})

    loop = asyncio.get_running_loop()
    context_docs = await loop.run_in_executor(None, retrieve_context, message, 5)
    context = "\n".join(f"- {doc}" for doc in context_docs)

    yield _sse("status", {"stage": "answering", "message": "Generating answer..."})

    response = await loop.run_in_executor(
        None,
        chat,
        [
            {
                "role": "system",
                "content": (
                    "You are a data documentation assistant. Answer the user's question "
                    "based on the following dbt metadata context. Be concise and accurate. "
                    "If the context doesn't contain the answer, say so.\n\n"
                    f"## Context:\n{context}"
                ),
            },
            {"role": "user", "content": message},
        ],
    )

    yield _sse("done", {"answer": response, "sources": context_docs[:3]})


# ── Path D: Ontology traversal ──


async def _handle_path_d(intent: dict, message: str) -> AsyncGenerator[str, None]:
    """Path D: Ontology graph traversal for multi-object queries."""
    yield _sse("status", {"stage": "traversing", "message": "Analyzing object relationships..."})

    loop = asyncio.get_running_loop()
    store = load_ontology()
    traverser = GraphTraverser(store)

    start_object = intent.get("start_object", "")
    if not start_object or start_object not in store.object_by_name:
        yield _sse("error", {"message": f"Unknown start object: {start_object}. Available: {list(store.object_by_name.keys())}"})
        return

    # Build TraversalRequest from router intent
    try:
        request = await loop.run_in_executor(
            None, _build_ontology_request, intent, store
        )
        sql = await loop.run_in_executor(None, traverser.build_sql, request)
    except ValueError as e:
        yield _sse("error", {"message": str(e)})
        return

    yield _sse("sql", {"sql": sql})

    # Execute
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, sql)
    except SQLSecurityError as e:
        yield _sse("error", {"message": f"SQL rejected: {e}"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Query failed: {e}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })

    # Interpret
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    interpretation = await _interpret_results(message=message, result=result)
    yield _sse("done", {"summary": interpretation})


async def _handle_path_a_ontology_fallback(intent: dict, error: CrossModelQueryError) -> AsyncGenerator[str, None]:
    """Path A fallback: cross-model metric query resolved via ontology traversal."""
    loop = asyncio.get_running_loop()
    store = load_ontology()
    traverser = GraphTraverser(store)

    # Determine start object from the first metric's model
    metric_names = intent.get("metric_names", [])
    dimensions = intent.get("dimensions", [])
    time_range = intent.get("time_range")

    # Find which semantic model each metric is on
    builder = MetricQueryBuilder()
    metric_models = {}
    for m_name in metric_names:
        md = builder._metric_index.get(m_name)
        if md:
            model_name = builder._metric_model.get(m_name)
            metric_models[model_name] = md

    if not metric_models:
        yield _sse("error", {"message": "Unable to resolve metrics to ontology objects."})
        return

    # Use the first metric's model as the start object
    # Map semantic model names to object type names
    model_to_object = {
        "orders": "Order",
        "customers": "Customer",
        "inventory": "InventoryRecord",
        "marketing": "CampaignResult",
        "customers_rfm": "RFMCustomer",
    }

    first_model = list(metric_models.keys())[0]
    start_object = model_to_object.get(first_model, first_model)

    # Build request with aggregates from metrics
    aggregates = []
    for md in metric_models.values():
        aggregates.append(AggregateDef(md.agg.upper(), md.expr, md.name))

    request = TraversalRequest(
        start_object=start_object,
        properties=dimensions if dimensions else [],
        aggregates=aggregates,
        time_range=time_range,
    )

    try:
        sql = await loop.run_in_executor(None, traverser.build_sql, request)
    except ValueError as e:
        yield _sse("error", {"message": str(e)})
        return

    yield _sse("sql", {"sql": sql})

    # Execute
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, sql)
    except SQLSecurityError as e:
        yield _sse("error", {"message": f"SQL rejected: {e}"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Query failed: {e}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })

    # Interpret
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    interpretation = await _interpret_results(message="", result=result)
    yield _sse("done", {"summary": interpretation})


def _build_ontology_request(intent: dict, store) -> TraversalRequest:
    """Convert router intent dict into a TraversalRequest."""
    start_object = intent.get("start_object", "")
    time_range = intent.get("time_range")
    properties = intent.get("properties", [])
    filters_raw = intent.get("filters", [])

    # Parse filters
    filters = []
    for f in filters_raw:
        if isinstance(f, dict):
            filters.append(FilterClause(
                property_name=f.get("property", ""),
                operator=f.get("op", "eq"),
                value=f.get("value"),
            ))

    # If start_object has foreign entities, traverse to get enriched properties
    # For now, use the start object directly (single-object query from ontology)
    request = TraversalRequest(
        start_object=start_object,
        properties=properties,
        filters=filters,
        time_range=time_range,
    )

    return request


_INTERPRET_PROMPT = """You are a data analyst. Summarize the query results for the user.

User question: {question}

Query results:
Columns: {columns}
Rows ({row_count} rows{truncated}):
{rows_preview}

Provide:
1. A concise natural language summary (2-4 sentences)
2. A recommended chart type: one of "bar", "line", "pie", "table"
3. Key insight (1 sentence)

Output as JSON:
{{"summary": "...", "chart_type": "bar", "insight": "..."}}
"""


async def _interpret_results(message: str, result) -> dict:
    """Generate NL summary + chart recommendation from query results."""
    if result.row_count == 0:
        return {"summary": "查询未返回任何结果。", "chart_type": "table", "insight": ""}

    loop = asyncio.get_running_loop()

    # Preview first 10 rows max
    rows_preview = "\n".join(
        str(row) for row in result.rows[:10]
    )

    prompt = _INTERPRET_PROMPT.format(
        question=message or "data query",
        columns=", ".join(result.columns),
        row_count=result.row_count,
        truncated=", truncated" if result.truncated else "",
        rows_preview=rows_preview,
    )

    response = await loop.run_in_executor(
        None,
        chat,
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Generate the JSON summary."},
        ],
    )

    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text, "chart_type": "table", "insight": ""}

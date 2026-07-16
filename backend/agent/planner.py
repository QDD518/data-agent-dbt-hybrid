"""Query-plan resolution: deterministic legacy translation plus LLM JSON fallback."""

from __future__ import annotations

import json

from backend.llm.client import chat
from backend.semantic.query_plan import (
    EntityQueryPlan,
    MetadataQueryPlan,
    MetricQueryPlan,
    PlanValidationError,
    parse_query_plan,
    plan_from_legacy_intent,
    validate_query_plan,
)
from backend.semantic.registry import SemanticRegistry, load_registry


_PLANNER_PROMPT = """You are a query planner for a Chat BI system. Return only JSON.
You never write SQL. Select exactly one supported plan shape:

Metric plan:
{"mode":"metric_analysis","metrics":["metric_name"],"dimensions":["dimension"],"filters":[{"field":"dimension","operator":"eq","value":"..."}],"time_range":"last_month"}

Entity plan:
{"mode":"entity_analysis","root_entity":"InventoryRecord","selections":[{"entity":"InventoryRecord","property":"quantity_on_hand"}],"relationships":[{"relationship":"tracks","from_entity":"InventoryRecord","to_entity":"Product"}],"filters":[{"field":"needs_reorder","operator":"eq","value":true}],"time_range":null}

Metadata plan:
{"mode":"metadata_qa","question":"..."}

Use only names listed in the semantic registry. If the registry cannot answer,
return the metadata plan rather than inventing fields or SQL.

{context}
"""


def resolve_query_plan(
    message: str,
    intent: dict,
    registry: SemanticRegistry | None = None,
) -> MetricQueryPlan | EntityQueryPlan | MetadataQueryPlan:
    registry = registry or load_registry()
    if intent.get("path") != "exploratory":
        return plan_from_legacy_intent(intent, registry, message)

    prompt = _PLANNER_PROMPT.replace("{context}", registry.planning_context())
    response = chat([
        {"role": "system", "content": prompt},
        {"role": "user", "content": message},
    ])
    payload = _parse_json(response)
    plan = parse_query_plan(payload)
    validate_query_plan(plan, registry)
    return plan


def _parse_json(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanValidationError("The planner did not return valid JSON.") from exc
    if not isinstance(payload, dict):
        raise PlanValidationError("The planner response must be a JSON object.")
    return payload

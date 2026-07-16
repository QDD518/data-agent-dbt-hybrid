"""Intent Router — LLM-driven four-way classifier for Path A/B/C/D routing."""

import json

from backend.llm.client import chat
from backend.semantic.query_builder import MetricQueryBuilder
from backend.ontology.parser import load_ontology


_ROUTER_PROMPT = """You are an intent classifier for a Chat BI system. Analyze the user's question and output a JSON classification.

## Available Metrics (Path A — guaranteed accurate SQL):
{metrics_desc}

## Available Dimensions:
{dimensions_desc}

## Available Object Types (Path D — ontology traversal for multi-object queries):
{objects_desc}

## Classification Rules:
1. **metric_query** (Path A): The user asks about a specific metric from the list above. Simple single-metric aggregation.
   - Extract: metric_names (list), dimensions (list, optional), time_range (str, optional)
   - time_range can be: "last_month", "this_month", "last_week", "this_week", "last_quarter", "this_quarter", "last_year", "this_year", or null
   - Example: "上月营收多少？" → metric_query with total_revenue, time_range=last_month
   - Example: "每个品类的销售额" → metric_query with total_revenue, dimensions=[product_category]

2. **ontology_query** (Path D): The user asks about multiple business objects connected through relationships. Use this for cross-entity questions involving filters on related objects.
   - Extract: start_object (str — one of the Object Type names), target_objects (list[str], optional), properties (list[str] — properties to display), filters (list of {{"property": "...", "op": "eq/gt/lt/in/like/...", "value": ...}} objects), time_range (str, optional)
   - Example: "华北仓库中有哪些商品低于补货阈值？" → ontology_query, start_object=InventoryRecord, properties=["product_name","quantity_on_hand","warehouse_name"], filters=[{{"property":"warehouse_region","op":"eq","value":"North China"}},{{"property":"needs_reorder","op":"eq","value":true}}]
   - Example: "北京仓库库存不足的商品有哪些？" → ontology_query, start_object=InventoryRecord, filters=[{{"property":"warehouse_city","op":"eq","value":"Beijing"}}]

3. **exploratory** (Path B): The user asks a complex data question better handled by flexible Text-to-SQL.
   - Example: "购买超过3次的客户还买了什么？", "比较各地区不同品类利润率"

4. **metadata** (Path C): The user asks about data definitions, column meanings, or how something is calculated.
   - Example: "revenue 指标是怎么计算的？", "订单表有哪些字段？"

Output ONLY a JSON object. No markdown, no explanation:
{{"path": "metric_query"|"ontology_query"|"exploratory"|"metadata", "metric_names": [...], "dimensions": [...], "start_object": "..."|null, "target_objects": [...], "properties": [...], "filters": [...], "time_range": "..."|null}}
"""


def classify_intent(user_message: str) -> dict:
    """Classify user intent and extract parameters. Returns a routing dict."""
    builder = MetricQueryBuilder()
    metrics = builder.list_metrics()
    dims = builder.list_dimensions()

    metrics_desc = "\n".join(
        f"- {m['name']}: {m['description']}" for m in metrics
    )
    dimensions_desc = "\n".join(
        f"- {d['name']} ({d['type']})" for d in dims
    )

    # Ontology objects for Path D classification
    try:
        onto = load_ontology()
        objects_desc = "\n".join(
            f"- {obj.name} ({obj.display_name}): {obj.description}. "
            f"Table: {obj.table}. Properties: {', '.join(obj.properties.keys())}"
            for obj in onto.object_by_name.values()
        )
    except Exception:
        objects_desc = "No ontology available."

    prompt = _ROUTER_PROMPT.format(
        metrics_desc=metrics_desc,
        dimensions_desc=dimensions_desc,
        objects_desc=objects_desc,
    )

    response = chat([
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_message},
    ])

    # Parse JSON — strip any accidental markdown fences
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: treat as exploratory
        return {"path": "exploratory", "metric_names": [], "dimensions": [], "time_range": None}

    return result

"""Intent Router — LLM-driven three-way classifier for Path A/B/C routing."""

import json

from backend.llm.client import chat
from backend.semantic.query_builder import MetricQueryBuilder


_ROUTER_PROMPT = """You are an intent classifier for a Chat BI system. Analyze the user's question and output a JSON classification.

## Available Metrics (Path A — guaranteed accurate SQL):
{metrics_desc}

## Available Dimensions:
{dimensions_desc}

## Classification Rules:
1. **metric_query** (Path A): The user asks about a specific metric from the list above.
   - Extract: metric_names (list), dimensions (list, optional), time_range (str, optional)
   - time_range can be: "last_month", "this_month", "last_week", "this_week", "last_quarter", "this_quarter", "last_year", "this_year", or null
   - Example: "上月营收多少？" → metric_query with total_revenue, time_range=last_month
   - Example: "每个品类的销售额" → metric_query with total_revenue, dimensions=[product_category]

2. **exploratory** (Path B): The user asks a data question that doesn't match any predefined metric.
   - This is for ad-hoc queries that need flexible Text-to-SQL.
   - Example: "购买超过3次的客户还买了什么？"

3. **metadata** (Path C): The user asks about data definitions, column meanings, or how something is calculated.
   - Example: "revenue 指标是怎么计算的？", "订单表有哪些字段？"

Output ONLY a JSON object. No markdown, no explanation:
{{"path": "metric_query"|"exploratory"|"metadata", "metric_names": [...], "dimensions": [...], "time_range": "..."|null}}
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

    prompt = _ROUTER_PROMPT.format(
        metrics_desc=metrics_desc,
        dimensions_desc=dimensions_desc,
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

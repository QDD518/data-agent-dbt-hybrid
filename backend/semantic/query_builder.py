"""Backward-compatible metric facade over the canonical semantic compiler.

Historically this module assembled SQL independently from ontology traversal.
It now translates the old ``SemanticQuery`` input into a validated QueryPlan so
metrics and entity queries share the same registry and compiler invariants.
"""

from __future__ import annotations

from backend.semantic.compiler import compile_metric_query
from backend.semantic.query_plan import FilterPlan, MetricQueryPlan, validate_query_plan
from backend.semantic.registry import MetricDefinition as MetricDef
from backend.semantic.registry import SemanticRegistry, load_registry


class CrossModelQueryError(ValueError):
    """Raised when a legacy metric request spans semantic models."""

    def __init__(
        self,
        metric_name: str,
        expected_table: str,
        actual_table: str,
        model_name: str | None = None,
        intent: dict | None = None,
    ):
        self.metric_name = metric_name
        self.expected_table = expected_table
        self.actual_table = actual_table
        self.model_name = model_name
        self.intent = intent or {}
        super().__init__(
            f"Cross-model query: '{metric_name}' is on '{actual_table}', expected '{expected_table}'."
        )


class SemanticQuery:
    """Legacy API accepted by existing callers and tests."""

    def __init__(
        self,
        metric_names: list[str],
        dimensions: list[str] | None = None,
        time_range: str | None = None,
        filters: dict[str, object] | None = None,
    ):
        self.metric_names = metric_names
        self.dimensions = dimensions or []
        self.time_range = time_range
        self.filters = filters or {}


class MetricQueryBuilder:
    """Compatibility facade that delegates to ``compile_metric_query``."""

    def __init__(self, registry: SemanticRegistry | None = None):
        self.registry = registry or load_registry()
        self._metric_index = self.registry.metrics
        self._metric_model = {
            name: metric.semantic_model for name, metric in self.registry.metrics.items()
        }

    def list_metrics(self) -> list[dict]:
        return [
            {
                "name": metric.name,
                "description": metric.description,
                "label": metric.label,
                "time_granularity": metric.time_granularity,
            }
            for metric in self.registry.metrics.values()
        ]

    def list_dimensions(self) -> list[dict]:
        seen: set[str] = set()
        dimensions: list[dict] = []
        for model_dimensions in self.registry.dimensions_by_model.values():
            for dimension in model_dimensions.values():
                if dimension.name not in seen:
                    seen.add(dimension.name)
                    dimensions.append({"name": dimension.name, "type": dimension.dim_type})
        return dimensions

    def build_sql(self, query: SemanticQuery) -> str:
        if not query.metric_names:
            raise ValueError("At least one metric is required.")
        plan = MetricQueryPlan(
            metrics=query.metric_names,
            dimensions=query.dimensions,
            filters=[FilterPlan(field=name, value=value) for name, value in query.filters.items()],
            time_range=query.time_range,
        )
        validate_query_plan(plan, self.registry)
        return compile_metric_query(plan, self.registry)


def _agg_sql(agg: str, expr: str) -> str:
    aggregation = agg.upper()
    if aggregation == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {expr})"
    if aggregation == "AVERAGE":
        aggregation = "AVG"
    return f"{aggregation}({expr})"


def _resolve_time_filter(time_range: str | None, time_column: str = "order_date") -> str | None:
    if not time_range:
        return None
    ranges = {
        "last_month": f"{time_column} >= date_trunc('month', CURRENT_DATE) - interval '1 month' AND {time_column} < date_trunc('month', CURRENT_DATE)",
        "this_month": f"{time_column} >= date_trunc('month', CURRENT_DATE)",
        "last_week": f"{time_column} >= date_trunc('week', CURRENT_DATE) - interval '1 week' AND {time_column} < date_trunc('week', CURRENT_DATE)",
        "this_week": f"{time_column} >= date_trunc('week', CURRENT_DATE)",
        "last_quarter": f"{time_column} >= date_trunc('quarter', CURRENT_DATE) - interval '3 months' AND {time_column} < date_trunc('quarter', CURRENT_DATE)",
        "this_quarter": f"{time_column} >= date_trunc('quarter', CURRENT_DATE)",
        "last_year": f"{time_column} >= date_trunc('year', CURRENT_DATE) - interval '1 year' AND {time_column} < date_trunc('year', CURRENT_DATE)",
        "this_year": f"{time_column} >= date_trunc('year', CURRENT_DATE)",
    }
    return ranges.get(time_range.lower().strip())

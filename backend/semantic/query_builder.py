"""
Path A — Last-mile SQL aggregator.

Principle (per architecture decision):
  dbt models already handle complex joins → wide OBT (fact_orders).
  This layer only does SELECT agg(expr) ... GROUP BY dim ... WHERE filter.
  No joins. No graph traversal. 100% deterministic from YAML metadata.
"""

from functools import lru_cache

from backend.metadata.parser import load_metadata


class SemanticQuery:
    """Input: what the Intent Router extracted from the user question."""

    def __init__(
        self,
        metric_names: list[str],
        dimensions: list[str] | None = None,
        time_range: str | None = None,
        filters: dict[str, str] | None = None,
    ):
        self.metric_names = metric_names
        self.dimensions = dimensions or []
        self.time_range = time_range       # "last_month", "2025-Q1", etc.
        self.filters = filters or {}       # {"product_category": "Smartphones"}


class MetricDef:
    """Resolved metric: combines the metric config + underlying measure."""

    def __init__(self, name: str, description: str, label: str,
                 agg: str, expr: str, table: str,
                 filter_sql: str | None, time_granularity: str | None):
        self.name = name
        self.description = description
        self.label = label
        self.agg = agg
        self.expr = expr
        self.table = table
        self.filter_sql = filter_sql
        self.time_granularity = time_granularity


class DimensionDef:
    """Resolved dimension."""

    def __init__(self, name: str, expr: str, dim_type: str, time_granularity: str | None):
        self.name = name
        self.expr = expr              # column or SQL expression
        self.dim_type = dim_type      # "time" or "categorical"
        self.time_granularity = time_granularity


def _agg_sql(agg: str, expr: str) -> str:
    """Map MetricFlow agg name → SQL aggregate expression."""
    agg_upper = agg.upper()
    if agg_upper == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {expr})"
    if agg_upper == "AVERAGE":
        return f"AVG({expr})"
    return f"{agg_upper}({expr})"


class MetricQueryBuilder:
    """Builds last-mile aggregation SQL from semantic metadata."""

    def __init__(self):
        store = load_metadata()

        # Index: metric_name → MetricDef
        self._metric_index: dict[str, MetricDef] = {}

        # Index: (model_name, dim_name) → DimensionDef (scoped per model)
        self._dimensions_by_model: dict[str, dict[str, DimensionDef]] = {}

        # Map: semantic_model_name → relation_name (qualified table)
        self._model_table: dict[str, str] = {}

        # Map: measure_name → (semantic_model_name, table)
        self._measure_to_table: dict[str, tuple[str, str]] = {}

        # Map: metric_name → semantic_model_name (for dimension scoping)
        self._metric_model: dict[str, str] = {}

        # ── Build indices ──
        for sm in store.semantic_models:
            sm_name = sm["name"]
            nr = sm.get("node_relation", {})
            # Use alias.schema as a clean identifier
            schema = nr.get("schema_name", "analytics")
            alias = nr.get("alias", sm_name)
            table = f"{schema}.{alias}"
            self._model_table[sm_name] = table

            for measure in sm.get("measures", []):
                m_name = measure["name"]
                self._measure_to_table[m_name] = (sm_name, table)

            dims_by_name: dict[str, DimensionDef] = {}
            for dim in sm.get("dimensions", []):
                d = DimensionDef(
                    name=dim["name"],
                    expr=dim.get("expr") or dim["name"],
                    dim_type=dim.get("type", "categorical"),
                    time_granularity=dim.get("type_params", {}).get("time_granularity") if dim.get("type_params") else None,
                )
                dims_by_name[d.name] = d
            self._dimensions_by_model[sm_name] = dims_by_name

        # ── Resolve metrics ──
        for metric in store.metrics:
            tp = metric.get("type_params", {})
            measure_ref = tp.get("measure", {}) or {}
            input_measures = tp.get("input_measures", [])
            measure_name = measure_ref.get("name", "")

            # Find which semantic model contains this measure
            sm_name, table = self._measure_to_table.get(measure_name, ("unknown", "unknown"))

            # Find the actual measure definition
            measure_def = None
            for sm in store.semantic_models:
                for m in sm.get("measures", []):
                    if m["name"] == measure_name:
                        measure_def = m
                        break
                if measure_def:
                    break

            if measure_def is None:
                continue

            # Extract filter SQL
            filter_sql = None
            filter_config = metric.get("filter", {})
            where_filters = filter_config.get("where_filters", []) if filter_config else []
            if where_filters:
                filter_sql = " AND ".join(
                    wf.get("where_sql_template", "").strip()
                    for wf in where_filters
                    if wf.get("where_sql_template", "").strip()
                )

            md = MetricDef(
                name=metric["name"],
                description=metric.get("description", ""),
                label=metric.get("label", metric["name"]),
                agg=measure_def.get("agg", "sum"),
                expr=measure_def.get("expr", "*"),
                table=table,
                filter_sql=filter_sql or None,
                time_granularity=metric.get("time_granularity"),
            )
            self._metric_index[md.name] = md
            self._metric_model[md.name] = sm_name

    # ── Public API ──

    def list_metrics(self) -> list[dict]:
        """Return all known metrics for the Intent Router / RAG."""
        return [
            {
                "name": m.name,
                "description": m.description,
                "label": m.label,
                "time_granularity": m.time_granularity,
            }
            for m in self._metric_index.values()
        ]

    def list_dimensions(self) -> list[dict]:
        """Return all known dimensions across all models."""
        seen: set[str] = set()
        result: list[dict] = []
        for model_dims in self._dimensions_by_model.values():
            for d in model_dims.values():
                if d.name not in seen:
                    seen.add(d.name)
                    result.append({"name": d.name, "type": d.dim_type})
        return result

    def build_sql(self, query: SemanticQuery) -> str:
        """Build a last-mile aggregation SQL from the given query intent."""
        select_parts: list[str] = []
        group_by_parts: list[str] = []
        filter_set: set[str] = set()  # deduplicate filters
        table: str | None = None
        model_name: str | None = None
        time_dim: str | None = None

        # ── SELECT: resolve metrics to agg expressions ──
        for metric_name in query.metric_names:
            md = self._metric_index.get(metric_name)
            if md is None:
                raise ValueError(f"Unknown metric: {metric_name}")

            if table is None:
                table = md.table
                model_name = self._metric_model.get(metric_name)
            elif table != md.table:
                raise ValueError(
                    f"Cross-model queries not supported in last-mile mode. "
                    f"Metric '{metric_name}' is on '{md.table}', expected '{table}'."
                )

            agg_expr = _agg_sql(md.agg, md.expr)
            select_parts.append(f"{agg_expr} AS {metric_name}")

            if md.filter_sql:
                filter_set.add(md.filter_sql)

            if md.time_granularity:
                time_dim = md.time_granularity

        # ── GROUP BY: resolve dimensions (scoped to the model) ──
        model_dims = self._dimensions_by_model.get(model_name or "", {})
        for dim_name in query.dimensions:
            dd = model_dims.get(dim_name)
            if dd is None:
                raise ValueError(f"Unknown dimension '{dim_name}' for model '{model_name}'")

            dim_expr = dd.expr
            if dd.dim_type == "time" and time_dim:
                dim_expr = f"DATE_TRUNC('{time_dim}', {dd.expr})"

            select_parts.append(f"{dim_expr} AS {dim_name}")
            group_by_parts.append(dim_expr)

        # ── Additional filters ──
        for col, val in query.filters.items():
            if isinstance(val, str):
                filter_set.add(f"{col} = '{val}'")
            else:
                filter_set.add(f"{col} = {val}")

        # ── Time range filter ──
        time_filter = _resolve_time_filter(query.time_range, time_dim or "day")
        if time_filter:
            filter_set.add(time_filter)

        # ── Assemble SQL ──
        select_str = ",\n  ".join(select_parts)
        sql = f"SELECT\n  {select_str}\nFROM {table}"

        if filter_set:
            sql += "\nWHERE " + "\n  AND ".join(sorted(filter_set))

        if group_by_parts:
            sql += "\nGROUP BY " + ", ".join(group_by_parts)

        # Default ordering by first metric desc
        sql += f"\nORDER BY 1 DESC"

        return sql


def _resolve_time_filter(time_range: str | None, granularity: str) -> str | None:
    """Convert a time-range label into a SQL where clause."""
    if not time_range:
        return None

    time_range_lower = time_range.lower().strip()

    # Map common relative ranges
    relative_ranges = {
        "last_month": "date_trunc('month', CURRENT_DATE) - interval '1 month'",
        "this_month": "date_trunc('month', CURRENT_DATE)",
        "last_week": "date_trunc('week', CURRENT_DATE) - interval '1 week'",
        "this_week": "date_trunc('week', CURRENT_DATE)",
        "last_quarter": "date_trunc('quarter', CURRENT_DATE) - interval '3 months'",
        "this_quarter": "date_trunc('quarter', CURRENT_DATE)",
        "last_year": "date_trunc('year', CURRENT_DATE) - interval '1 year'",
        "this_year": "date_trunc('year', CURRENT_DATE)",
    }

    if time_range_lower in relative_ranges:
        start_expr = relative_ranges[time_range_lower]
        # We need the time dimension column — use a parameterized approach
        return f"order_date >= {start_expr}"

    return None

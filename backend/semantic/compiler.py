"""Deterministic SQL compiler for validated semantic query plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.semantic.query_plan import (
    EntityQueryPlan,
    FilterPlan,
    MetadataQueryPlan,
    MetricQueryPlan,
    PropertySelection,
    validate_query_plan,
)
from backend.semantic.registry import EntityDefinition, MetricDefinition, SemanticRegistry


class QueryCompilationError(ValueError):
    """The validated plan cannot be represented safely in PostgreSQL SQL."""


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    mode: str


def compile_query(
    plan: MetricQueryPlan | EntityQueryPlan | MetadataQueryPlan,
    registry: SemanticRegistry,
) -> CompiledQuery:
    validate_query_plan(plan, registry)
    if isinstance(plan, MetricQueryPlan):
        return CompiledQuery(sql=compile_metric_query(plan, registry), mode=plan.mode)
    if isinstance(plan, EntityQueryPlan):
        return CompiledQuery(sql=compile_entity_query(plan, registry), mode=plan.mode)
    raise QueryCompilationError("Metadata plans do not compile to SQL.")


def compile_metric_query(plan: MetricQueryPlan, registry: SemanticRegistry) -> str:
    metrics = [registry.metric(name) for name in plan.metrics]
    model_name = metrics[0].semantic_model
    table = metrics[0].table
    if any(metric.semantic_model != model_name for metric in metrics):
        return _compile_cross_model_scalar_metrics(plan, metrics, registry)

    select_parts = [_metric_expression(metric) for metric in metrics]
    group_by_parts: list[str] = []
    for dimension_name in plan.dimensions:
        dimension = registry.dimension(model_name, dimension_name)
        expression = dimension.expression
        metric_granularity = next(
            (metric.time_granularity for metric in metrics if metric.time_granularity),
            None,
        )
        if dimension.dim_type == "time" and metric_granularity:
            expression = f"DATE_TRUNC('{metric_granularity}', {expression})"
        select_parts.append(f"{expression} AS {dimension.name}")
        group_by_parts.append(expression)

    where_parts = [
        _metric_filter_expression(filter_plan, model_name, registry)
        for filter_plan in plan.filters
    ]
    if plan.time_range:
        time_dimension = metrics[0].default_time_dimension
        if not time_dimension:
            raise QueryCompilationError(
                f"Metric '{metrics[0].name}' has no default time dimension for '{plan.time_range}'."
            )
        time_expression = registry.dimension(model_name, time_dimension).expression
        where_parts.append(_time_range_expression(time_expression, plan.time_range))

    sql = "SELECT\n  " + ",\n  ".join(select_parts) + f"\nFROM {table}"
    if where_parts:
        sql += "\nWHERE " + "\n  AND ".join(where_parts)
    if group_by_parts:
        sql += "\nGROUP BY " + ", ".join(group_by_parts)
    sql += "\nORDER BY 1 DESC"
    sql += f"\nLIMIT {plan.limit}"
    return sql


def _compile_cross_model_scalar_metrics(
    plan: MetricQueryPlan,
    metrics: list[MetricDefinition],
    registry: SemanticRegistry,
) -> str:
    """Compile independent scalar metrics without unsafe fan-out joins.

    The former fallback attempted to aggregate all expressions from the first
    table, which either failed or returned wrong numbers. Independent CTEs keep
    each metric at its native grain and are cross-joined only after aggregation.
    Dimensional cross-model analysis remains an explicit entity-plan problem.
    """
    if plan.dimensions or plan.filters:
        raise QueryCompilationError(
            "Cross-model scalar compilation does not accept dimensions or filters."
        )
    ctes: list[str] = []
    select_parts: list[str] = []
    for index, metric in enumerate(metrics):
        alias = f"m{index}"
        where_parts: list[str] = []
        if plan.time_range:
            if not metric.default_time_dimension:
                raise QueryCompilationError(
                    f"Metric '{metric.name}' has no default time dimension for '{plan.time_range}'."
                )
            time_expression = registry.dimension(
                metric.semantic_model, metric.default_time_dimension
            ).expression
            where_parts.append(_time_range_expression(time_expression, plan.time_range))
        cte = f"{alias} AS (SELECT {_metric_expression(metric)} FROM {metric.table}"
        if where_parts:
            cte += " WHERE " + " AND ".join(where_parts)
        cte += ")"
        ctes.append(cte)
        select_parts.append(f"{alias}.{metric.name}")
    return "WITH\n  " + ",\n  ".join(ctes) + "\nSELECT\n  " + ",\n  ".join(select_parts) + "\nFROM " + "\nCROSS JOIN ".join(f"m{index}" for index in range(len(metrics))) + "\nLIMIT 1"


def compile_entity_query(plan: EntityQueryPlan, registry: SemanticRegistry) -> str:
    root = registry.entity(plan.root_entity)
    aliases: dict[str, str] = {root.name: "t0"}
    from_clause = f"FROM {root.table} AS t0"
    joins: list[str] = []

    for index, step in enumerate(plan.relationships, start=1):
        relationship = registry.relationships[step.relationship]
        if step.from_entity not in aliases:
            raise QueryCompilationError(
                f"Relationship '{relationship.name}' starts from an entity absent from the compiled path."
            )
        if step.to_entity in aliases:
            raise QueryCompilationError(
                f"Relationship '{relationship.name}' would create a cycle through '{step.to_entity}'."
            )
        current_alias = aliases[step.from_entity]
        next_entity = registry.entity(step.to_entity)
        if relationship.denormalized:
            aliases[next_entity.name] = current_alias
        else:
            next_alias = f"t{index}"
            aliases[next_entity.name] = next_alias
            if relationship.source == step.from_entity and relationship.target == next_entity.name:
                condition = (
                    f"{current_alias}.{relationship.source_column} = "
                    f"{next_alias}.{relationship.target_column}"
                )
            elif relationship.target == step.from_entity and relationship.source == next_entity.name:
                condition = (
                    f"{next_alias}.{relationship.source_column} = "
                    f"{current_alias}.{relationship.target_column}"
                )
            else:
                raise QueryCompilationError(
                    f"Relationship '{relationship.name}' does not connect the requested entities."
                )
            joins.append(f"JOIN {next_entity.table} AS {next_alias} ON {condition}")

    selections = plan.selections or [PropertySelection(entity=root.name, property=root.primary_key)]
    select_parts = [_selection_expression(selection, aliases, registry) for selection in selections]
    where_parts = [_entity_filter_expression(filter_plan, root, aliases, registry) for filter_plan in plan.filters]
    if plan.time_range:
        if not root.time_dimension:
            raise QueryCompilationError(
                f"Entity '{root.name}' has no time dimension for '{plan.time_range}'."
            )
        where_parts.append(
            _time_range_expression(
                f"{aliases[root.name]}.{root.properties[root.time_dimension]}", plan.time_range
            )
        )

    sql = "SELECT\n  " + ",\n  ".join(select_parts) + "\n" + from_clause
    if joins:
        sql += "\n" + "\n".join(joins)
    if where_parts:
        sql += "\nWHERE " + "\n  AND ".join(where_parts)
    sql += f"\nLIMIT {plan.limit}"
    return sql


def _metric_expression(metric: MetricDefinition) -> str:
    if metric.numerator_measure and metric.denominator_measure:
        numerator = _measure_aggregate(metric.numerator_measure, metric.filter_sql)
        denominator = _measure_aggregate(metric.denominator_measure, metric.filter_sql)
        return f"({numerator}) / NULLIF({denominator}, 0) AS {metric.name}"
    return f"{_measure_aggregate(metric.measure, metric.filter_sql)} AS {metric.name}"


def _measure_aggregate(measure, condition: str | None) -> str:
    aggregation = measure.aggregation.upper()
    expression = measure.expression
    if aggregation == "COUNT_DISTINCT":
        inner = f"CASE WHEN {condition} THEN {expression} END" if condition else expression
        aggregate = f"COUNT(DISTINCT {inner})"
    else:
        inner = f"CASE WHEN {condition} THEN {expression} END" if condition else expression
        if aggregation == "AVERAGE":
            aggregation = "AVG"
        aggregate = f"{aggregation}({inner})"
    return aggregate


def _selection_expression(
    selection: PropertySelection,
    aliases: dict[str, str],
    registry: SemanticRegistry,
) -> str:
    entity = registry.entity(selection.entity)
    alias = aliases.get(entity.name)
    if alias is None:
        raise QueryCompilationError(f"Entity '{entity.name}' is absent from the compiled path.")
    column = entity.properties[selection.property]
    output_name = selection.alias or selection.property
    return f"{alias}.{column} AS {output_name}"


def _metric_filter_expression(filter_plan: FilterPlan, model_name: str, registry: SemanticRegistry) -> str:
    dimension = registry.dimension(model_name, filter_plan.field)
    return _filter_expression(dimension.expression, filter_plan)


def _entity_filter_expression(
    filter_plan: FilterPlan,
    root: EntityDefinition,
    aliases: dict[str, str],
    registry: SemanticRegistry,
) -> str:
    entity = registry.entity(filter_plan.entity or root.name)
    alias = aliases.get(entity.name)
    if alias is None:
        raise QueryCompilationError(f"Entity '{entity.name}' is absent from the compiled path.")
    return _filter_expression(f"{alias}.{entity.properties[filter_plan.field]}", filter_plan)


def _filter_expression(column: str, filter_plan: FilterPlan) -> str:
    operator = filter_plan.operator
    if operator == "is_null":
        return f"{column} IS NULL"
    if operator == "is_not_null":
        return f"{column} IS NOT NULL"
    if operator == "between":
        low, high = filter_plan.value
        return f"{column} BETWEEN {_literal(low)} AND {_literal(high)}"
    if operator == "in":
        return f"{column} IN ({_literal_list(filter_plan.value)})"
    if operator == "not_in":
        return f"{column} NOT IN ({_literal_list(filter_plan.value)})"
    operator_sql = {
        "eq": "=",
        "neq": "!=",
        "gt": ">",
        "gte": ">=",
        "lt": "<",
        "lte": "<=",
        "like": "LIKE",
    }.get(operator)
    if operator_sql is None:
        raise QueryCompilationError(f"Unsupported filter operator: {operator}")
    return f"{column} {operator_sql} {_literal(filter_plan.value)}"


def _literal_list(value: Any) -> str:
    if not isinstance(value, (list, tuple)) or not value:
        raise QueryCompilationError("in/not_in filters require a non-empty list.")
    return ", ".join(_literal(item) for item in value)


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _time_range_expression(column: str, time_range: str) -> str:
    ranges = {
        "today": f"{column} >= CURRENT_DATE",
        "yesterday": f"{column} >= CURRENT_DATE - interval '1 day' AND {column} < CURRENT_DATE",
        "this_week": f"{column} >= date_trunc('week', CURRENT_DATE)",
        "last_week": f"{column} >= date_trunc('week', CURRENT_DATE) - interval '1 week' AND {column} < date_trunc('week', CURRENT_DATE)",
        "this_month": f"{column} >= date_trunc('month', CURRENT_DATE)",
        "last_month": f"{column} >= date_trunc('month', CURRENT_DATE) - interval '1 month' AND {column} < date_trunc('month', CURRENT_DATE)",
        "this_quarter": f"{column} >= date_trunc('quarter', CURRENT_DATE)",
        "last_quarter": f"{column} >= date_trunc('quarter', CURRENT_DATE) - interval '3 months' AND {column} < date_trunc('quarter', CURRENT_DATE)",
        "this_year": f"{column} >= date_trunc('year', CURRENT_DATE)",
        "last_year": f"{column} >= date_trunc('year', CURRENT_DATE) - interval '1 year' AND {column} < date_trunc('year', CURRENT_DATE)",
    }
    try:
        return ranges[time_range]
    except KeyError as exc:
        raise QueryCompilationError(f"Unsupported time range: {time_range}") from exc

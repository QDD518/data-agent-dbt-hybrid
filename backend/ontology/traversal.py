"""Graph traversal engine — builds CTE-based multi-hop SQL from the ontology graph."""

from collections import deque
from dataclasses import dataclass, field

from backend.ontology.parser import OntologyStore, LinkType


# ── Data structures ──


@dataclass
class FilterClause:
    property_name: str
    operator: str  # eq, neq, gt, gte, lt, lte, in, between, like, is_null, is_not_null
    value: str | int | float | list | tuple | None


@dataclass
class AggregateDef:
    function: str  # SUM, COUNT, AVG, MIN, MAX, COUNT_DISTINCT
    property_name: str
    alias: str


@dataclass
class TraversalStep:
    from_object: str
    to_object: str
    link: LinkType
    filters: list[FilterClause] = field(default_factory=list)
    select_properties: list[str] = field(default_factory=list)
    aggregates: list[AggregateDef] = field(default_factory=list)


@dataclass
class TraversalRequest:
    start_object: str
    path: list[TraversalStep] = field(default_factory=list)
    properties: list[str] = field(default_factory=list)  # property names on the final object
    filters: list[FilterClause] = field(default_factory=list)
    aggregates: list[AggregateDef] = field(default_factory=list)
    time_range: str | None = None
    limit: int = 1000


# ── SQL operators ──

_OPERATOR_SQL: dict[str, str] = {
    "eq":           "{col} = {val}",
    "neq":          "{col} != {val}",
    "gt":           "{col} > {val}",
    "gte":          "{col} >= {val}",
    "lt":           "{col} < {val}",
    "lte":          "{col} <= {val}",
    "in":           "{col} IN ({val})",
    "not_in":       "{col} NOT IN ({val})",
    "between":      "{col} BETWEEN {val_low} AND {val_high}",
    "like":         "{col} LIKE {val}",
    "is_null":      "{col} IS NULL",
    "is_not_null":  "{col} IS NOT NULL",
}

_TIME_RANGE_SQL: dict[str, str] = {
    "today":        "{col} >= CURRENT_DATE",
    "yesterday":    "{col} >= CURRENT_DATE - interval '1 day' AND {col} < CURRENT_DATE",
    "this_week":    "{col} >= date_trunc('week', CURRENT_DATE)",
    "last_week":    "{col} >= date_trunc('week', CURRENT_DATE) - interval '1 week' AND {col} < date_trunc('week', CURRENT_DATE)",
    "this_month":   "{col} >= date_trunc('month', CURRENT_DATE)",
    "last_month":   "{col} >= date_trunc('month', CURRENT_DATE) - interval '1 month' AND {col} < date_trunc('month', CURRENT_DATE)",
    "this_quarter": "{col} >= date_trunc('quarter', CURRENT_DATE)",
    "last_quarter": "{col} >= date_trunc('quarter', CURRENT_DATE) - interval '3 months' AND {col} < date_trunc('quarter', CURRENT_DATE)",
    "this_year":    "{col} >= date_trunc('year', CURRENT_DATE)",
    "last_year":    "{col} >= date_trunc('year', CURRENT_DATE) - interval '1 year' AND {col} < date_trunc('year', CURRENT_DATE)",
}


def _format_value(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_value(v) for v in value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _filter_to_sql(f: FilterClause, alias: str = "") -> str:
    col = f"{alias}.{f.property_name}" if alias else f.property_name
    template = _OPERATOR_SQL.get(f.operator)
    if template is None:
        raise ValueError(f"Unknown operator: {f.operator}")
    if f.operator in ("is_null", "is_not_null"):
        return template.format(col=col)
    if f.operator == "between":
        low, high = (f.value[0], f.value[1]) if isinstance(f.value, (list, tuple)) else (f.value, f.value)
        return template.format(col=col, val_low=_format_value(low), val_high=_format_value(high))
    return template.format(col=col, val=_format_value(f.value))


def _resolve_time_filter(time_range: str, time_column: str) -> str | None:
    template = _TIME_RANGE_SQL.get(time_range)
    if template is None:
        return None
    return template.format(col=time_column)


def _agg_sql(func: str, expr: str) -> str:
    f = func.upper()
    if f == "COUNT_DISTINCT":
        return f"COUNT(DISTINCT {expr})"
    return f"{f}({expr})"


# ── Graph Traverser ──


class GraphTraverser:
    """Builds multi-hop SQL by traversing the ontology graph."""

    def __init__(self, store: OntologyStore):
        self.store = store

    # ── Path finding (BFS) ──

    def find_paths(self, start: str, end: str, max_hops: int = 3) -> list[list[LinkType]]:
        """BFS to find all paths between two object types."""
        if start not in self.store.object_by_name or end not in self.store.object_by_name:
            return []

        queue = deque([(start, [])])
        seen = set()
        results = []

        while queue:
            current, path = queue.popleft()
            if len(path) >= max_hops:
                continue

            for neighbor, link in self.store.adjacency.get(current, []):
                state = tuple(l.name for l in path) + (link.name,)
                if state in seen:
                    continue
                seen.add(state)
                new_path = path + [link]

                # Determine direction: if current is link.source, we're going outbound
                # If current is link.target, we're traversing inbound (reverse)
                if neighbor == end:
                    results.append(new_path)
                else:
                    queue.append((neighbor, new_path))

        results.sort(key=len)
        return results

    # ── SQL generation ──

    def build_sql(self, request: TraversalRequest) -> str:
        self._validate(request)

        if not request.path:
            return self._single_object_sql(request)
        return self._multi_hop_sql(request)

    def _validate(self, request: TraversalRequest):
        if request.start_object not in self.store.object_by_name:
            raise ValueError(f"Unknown start object: {request.start_object}")
        for step in request.path:
            if step.link.name not in self.store.link_by_name:
                raise ValueError(f"Unknown link: {step.link.name}")

    # ── Single-object SQL ──

    def _single_object_sql(self, request: TraversalRequest) -> str:
        obj = self.store.object_by_name[request.start_object]

        # SELECT
        if request.aggregates:
            select_parts = [
                _agg_sql(a.function, a.property_name) + f" AS {a.alias}"
                for a in request.aggregates
            ]
        elif request.properties:
            select_parts = list(request.properties)
        else:
            select_parts = ["*"]

        select_str = ",\n  ".join(select_parts)
        sql = f"SELECT\n  {select_str}\nFROM {obj.table}"

        # WHERE
        where_parts = []
        for f in request.filters:
            where_parts.append(_filter_to_sql(f))
        if request.time_range and obj.time_dimension:
            time_sql = _resolve_time_filter(request.time_range, obj.time_dimension)
            if time_sql:
                where_parts.append(time_sql)

        if where_parts:
            sql += "\nWHERE " + "\n  AND ".join(where_parts)

        sql += f"\nLIMIT {request.limit}"
        return sql

    # ── Multi-hop SQL (CTE chain) ──

    def _multi_hop_sql(self, request: TraversalRequest) -> str:
        """
        Strategy:
        - Every non-denormalized object traversed gets its own CTE with just the columns we need.
        - Denormalized objects share the same CTE as their source — no extra hop.
        - Final SELECT joins all CTEs through their primary/foreign key chains.

        Example for Product -> InventoryRecord (tracks link):
        WITH
          _product AS (SELECT product_id, product_name FROM dim_products),
          _inventory AS (SELECT product_id, quantity_on_hand, warehouse_region FROM fact_inventory WHERE ...)
        SELECT p.product_name, i.quantity_on_hand
        FROM _product p JOIN _inventory i ON p.product_id = i.product_id
        """
        start_obj = self.store.object_by_name[request.start_object]

        # Determine which objects need their own CTE (non-denormalized)
        # and which are merged into their source (denormalized)
        cte_defs: list[dict] = []  # [{name, object, alias, select_cols, filters}]
        join_chain: list[dict] = []  # [{left_alias, left_col, right_alias, right_col}]

        current_object = request.start_object
        current_alias = "c0"

        # Build CTE for the start object
        col_names = start_obj.column_names()
        cte_defs.append({
            "name": current_alias,
            "object": start_obj,
            "alias": current_alias,
            "select_cols": [start_obj.primary_key] + [
                p for p in request.properties or col_names
                if p in col_names
            ],
            "filters": [],
        })

        cte_idx = 1
        prev_object = current_object
        prev_alias = current_alias

        for step in request.path:
            link = step.link
            target_obj = self.store.object_by_name[link.target]

            if link.denormalized:
                # Target shares table with source — merge its columns into the source CTE
                source_cte = cte_defs[-1]
                target_cols = target_obj.column_names()
                for p in step.select_properties or target_cols:
                    if p in target_cols and p not in source_cte["select_cols"]:
                        source_cte["select_cols"].append(p)
                source_cte["filters"].extend(step.filters)
                # No join needed — columns are on the same table
                continue

            # Non-denormalized: create a new CTE
            alias = f"c{cte_idx}"
            cte_idx += 1

            target_cols = target_obj.column_names()
            select_cols = [target_obj.primary_key]
            for p in step.select_properties:
                if p in target_cols and p not in select_cols:
                    select_cols.append(p)

            cte_defs.append({
                "name": alias,
                "object": target_obj,
                "alias": alias,
                "select_cols": select_cols,
                "filters": list(step.filters),
            })

            # Add join link
            join_chain.append({
                "left_alias": prev_alias,
                "left_col": link.source_column,
                "right_alias": alias,
                "right_col": link.target_column,
            })

            prev_alias = alias
            prev_object = link.target

        # Apply time_range to the last CTE if applicable
        last_obj = cte_defs[-1]["object"]
        if request.time_range and last_obj.time_dimension:
            time_sql = _resolve_time_filter(request.time_range, last_obj.time_dimension)
            if time_sql:
                cte_defs[-1]["filters"].append(
                    FilterClause(last_obj.time_dimension, "eq", None)
                )

        # Build SQL
        sql_parts = []

        if len(cte_defs) > 1:
            cte_lines = []
            for cte in cte_defs:
                cols = ", ".join(cte["select_cols"])
                cte_sql = f"  {cte['name']} AS (\n    SELECT {cols}\n    FROM {cte['object'].table}"
                if cte["filters"]:
                    where_parts = []
                    for f in cte["filters"]:
                        if f.operator == "eq" and f.value is None:
                            continue  # time_range placeholder, handled below
                        where_parts.append(_filter_to_sql(f))
                    if where_parts:
                        cte_sql += "\n    WHERE " + "\n      AND ".join(where_parts)
                cte_sql += "\n  )"
                cte_lines.append(cte_sql)

            sql_parts.append("WITH")
            sql_parts.append(",\n".join(cte_lines))

        # Collect all output properties (from request + denormalized steps)
        output_props = set(request.properties)
        for step in request.path:
            if step.link.denormalized:
                output_props.update(step.select_properties)

        # Final SELECT
        final_cols = []
        for p in output_props:
            # Find which CTE has this property
            for cte in cte_defs:
                if p in cte["select_cols"]:
                    final_cols.append(f"{cte['alias']}.{p}")
                    break
            else:
                final_cols.append(p)

        if request.aggregates:
            final_cols = [
                _agg_sql(a.function, a.property_name) + f" AS {a.alias}"
                for a in request.aggregates
            ]

        select_str = ",\n  ".join(final_cols) if final_cols else "*"
        sql_parts.append(f"SELECT\n  {select_str}")

        # FROM: first CTE
        first_alias = cte_defs[0]["alias"]
        sql_parts.append(f"FROM {cte_defs[0]['object'].table} AS {first_alias}")

        # JOINs
        for j in join_chain:
            sql_parts.append(
                f"JOIN {j['right_alias']} "
                f"ON {j['left_alias']}.{j['left_col']} = {j['right_alias']}.{j['right_col']}"
            )

        # WHERE on final query (time_range)
        if request.time_range and last_obj.time_dimension:
            time_sql = _resolve_time_filter(request.time_range, last_obj.time_dimension)
            if time_sql:
                qualified = time_sql.replace(
                    last_obj.time_dimension,
                    f"{prev_alias}.{last_obj.time_dimension}"
                )
                sql_parts.append(f"WHERE {qualified}")

        # Apply request-level filters
        if request.filters:
            prefix = "WHERE" if "WHERE" not in "\n".join(sql_parts[-2:]) else "AND"
            filter_strs = [_filter_to_sql(f) for f in request.filters]
            sql_parts.append(f"{prefix} " + "\n  AND ".join(filter_strs))

        sql_parts.append(f"LIMIT {request.limit}")
        return "\n".join(sql_parts)

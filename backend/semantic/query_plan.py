"""Validated intermediate representation between natural language and SQL.

No component outside the compiler may construct executable SQL.  The router and
LLM fallback produce one of these plans; registry-backed validation resolves all
business identifiers before compilation.
"""

from __future__ import annotations

from typing import Any, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.semantic.registry import SemanticRegistry, SemanticRegistryError


VALID_OPERATORS = {
    "eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "between",
    "like", "is_null", "is_not_null",
}
VALID_TIME_RANGES = {
    "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
    "this_quarter", "last_quarter", "this_year", "last_year",
}


class PlanValidationError(ValueError):
    """The requested business query cannot be safely resolved."""


class FilterPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    operator: str = "eq"
    value: Any = None
    entity: str | None = None

    @model_validator(mode="after")
    def validate_operator(self) -> "FilterPlan":
        if self.operator not in VALID_OPERATORS:
            raise ValueError(f"Unsupported filter operator: {self.operator}")
        if self.operator == "between":
            if not isinstance(self.value, (list, tuple)) or len(self.value) != 2:
                raise ValueError("between filters require exactly two values")
        if self.operator in {"is_null", "is_not_null"} and self.value is not None:
            raise ValueError(f"{self.operator} filters cannot have a value")
        return self


class PropertySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity: str
    property: str
    alias: str | None = None


class RelationshipStepPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship: str
    from_entity: str
    to_entity: str


class MetricQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["metric_analysis"] = "metric_analysis"
    metrics: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[FilterPlan] = Field(default_factory=list)
    time_range: str | None = None
    limit: int = Field(default=1000, ge=1, le=1000)


class EntityQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["entity_analysis"] = "entity_analysis"
    root_entity: str
    selections: list[PropertySelection] = Field(default_factory=list)
    relationships: list[RelationshipStepPlan] = Field(default_factory=list)
    filters: list[FilterPlan] = Field(default_factory=list)
    time_range: str | None = None
    limit: int = Field(default=1000, ge=1, le=1000)


class MetadataQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["metadata_qa"] = "metadata_qa"
    question: str = Field(min_length=1)


QueryPlan = Annotated[
    MetricQueryPlan | EntityQueryPlan | MetadataQueryPlan,
    Field(discriminator="mode"),
]
_QUERY_PLAN_ADAPTER = TypeAdapter(QueryPlan)


def parse_query_plan(payload: dict[str, Any]) -> MetricQueryPlan | EntityQueryPlan | MetadataQueryPlan:
    try:
        return _QUERY_PLAN_ADAPTER.validate_python(payload)
    except Exception as exc:  # Pydantic's detailed error is preserved for the API caller.
        raise PlanValidationError(f"Invalid query plan: {exc}") from exc


def validate_query_plan(
    plan: MetricQueryPlan | EntityQueryPlan | MetadataQueryPlan,
    registry: SemanticRegistry,
) -> None:
    """Validate all identifiers and graph steps against the canonical registry."""
    if isinstance(plan, MetadataQueryPlan):
        return
    if plan.time_range and plan.time_range not in VALID_TIME_RANGES:
        raise PlanValidationError(f"Unsupported time range: {plan.time_range}")

    if isinstance(plan, MetricQueryPlan):
        definitions = [registry.metric(metric) for metric in plan.metrics]
        models = {definition.semantic_model for definition in definitions}
        if len(models) != 1:
            if plan.dimensions or plan.filters:
                raise PlanValidationError(
                    "Cross-model metric plans currently support only scalar metrics; "
                    "use an explicit entity analysis plan for dimensions or filters."
                )
            return
        model_name = definitions[0].semantic_model
        for dimension in plan.dimensions:
            registry.dimension(model_name, dimension)
        for filter_plan in plan.filters:
            if filter_plan.entity is not None:
                raise PlanValidationError("Metric filters cannot target a separate entity.")
            registry.dimension(model_name, filter_plan.field)
        return

    root = registry.entity(plan.root_entity)
    entity_names = {root.name}
    for step in plan.relationships:
        relationship = registry.relationships.get(step.relationship)
        if relationship is None:
            raise PlanValidationError(f"Unknown relationship: {step.relationship}")
        if step.from_entity not in entity_names or step.to_entity not in registry.entities:
            raise PlanValidationError(
                f"Relationship step '{step.relationship}' must start from an entity already in the plan."
            )
        valid_direction = (
            (relationship.source == step.from_entity and relationship.target == step.to_entity)
            or (relationship.target == step.from_entity and relationship.source == step.to_entity)
        )
        if not valid_direction:
            raise PlanValidationError(
                f"Relationship '{step.relationship}' does not connect "
                f"{step.from_entity} to {step.to_entity}."
            )
        if step.to_entity in entity_names:
            raise PlanValidationError(
                f"Relationship step '{step.relationship}' introduces a cycle through '{step.to_entity}'."
            )
        entity_names.add(step.to_entity)

    for selection in plan.selections:
        entity = registry.entity(selection.entity)
        if entity.name not in entity_names:
            raise PlanValidationError(
                f"Selection '{selection.property}' requires entity '{selection.entity}', "
                "which is not present in the relationship path."
            )
        if selection.property not in entity.properties:
            raise PlanValidationError(
                f"Unknown property '{selection.property}' for entity '{selection.entity}'."
            )
    for filter_plan in plan.filters:
        entity_name = filter_plan.entity or root.name
        entity = registry.entity(entity_name)
        if entity_name not in entity_names:
            raise PlanValidationError(
                f"Filter entity '{entity_name}' is not present in the relationship path."
            )
        if filter_plan.field not in entity.properties:
            raise PlanValidationError(
                f"Unknown property '{filter_plan.field}' for entity '{entity_name}'."
            )


def plan_from_legacy_intent(intent: dict[str, Any], registry: SemanticRegistry, message: str = "") -> QueryPlan:
    """Translate the existing router contract while the frontend migrates to QueryPlan."""
    path = intent.get("path")
    if path == "metric_query":
        plan = parse_query_plan({
            "mode": "metric_analysis",
            "metrics": intent.get("metric_names") or [],
            "dimensions": intent.get("dimensions") or [],
            "filters": [
                {"field": item.get("property", ""), "operator": item.get("op", "eq"), "value": item.get("value")}
                for item in intent.get("filters", [])
                if isinstance(item, dict)
            ],
            "time_range": intent.get("time_range"),
        })
    elif path == "ontology_query":
        root = intent.get("start_object") or ""
        if not root:
            raise PlanValidationError("Ontology query did not include a start object.")
        target_objects = list(intent.get("target_objects") or [])
        filters = []
        for item in intent.get("filters", []):
            if not isinstance(item, dict):
                continue
            entity = item.get("entity") or _resolve_property_owner(
                root, item.get("property", ""), registry
            )
            if entity != root and entity not in target_objects:
                target_objects.append(entity)
            filters.append({
                "field": item.get("property", ""),
                "operator": item.get("op", "eq"),
                "value": item.get("value"),
                "entity": entity,
            })
        selections, steps = _resolve_entity_selections(
            root,
            intent.get("properties") or [],
            target_objects,
            registry,
        )
        plan = parse_query_plan({
            "mode": "entity_analysis",
            "root_entity": root,
            "selections": [selection.model_dump() for selection in selections],
            "relationships": [step.model_dump() for step in steps],
            "filters": filters,
            "time_range": intent.get("time_range"),
        })
    elif path == "metadata":
        plan = MetadataQueryPlan(question=message or intent.get("question") or "metadata question")
    else:
        raise PlanValidationError(f"Unknown path: {path}")
    validate_query_plan(plan, registry)
    return plan


def _resolve_entity_selections(
    root: str,
    properties: list[str],
    target_objects: list[str],
    registry: SemanticRegistry,
) -> tuple[list[PropertySelection], list[RelationshipStepPlan]]:
    """Resolve legacy unqualified property names into an explicit graph plan."""
    registry.entity(root)
    requested_entities = list(target_objects)
    resolved: list[PropertySelection] = []

    for property_name in properties:
        owner = _resolve_property_owner(root, property_name, registry)
        if owner not in requested_entities and owner != root:
            requested_entities.append(owner)
        resolved.append(PropertySelection(entity=owner, property=property_name))

    steps: list[RelationshipStepPlan] = []
    seen_steps: set[tuple[str, str, str]] = set()
    for target in requested_entities:
        if target == root:
            continue
        path = registry.find_path(root, target)
        current = root
        for relationship in path:
            if relationship.source == current:
                next_entity = relationship.target
            else:
                next_entity = relationship.source
            step_key = (relationship.name, current, next_entity)
            if step_key not in seen_steps:
                steps.append(
                    RelationshipStepPlan(
                        relationship=relationship.name,
                        from_entity=current,
                        to_entity=next_entity,
                    )
                )
                seen_steps.add(step_key)
            current = next_entity
    return resolved, steps


def _resolve_property_owner(root: str, property_name: str, registry: SemanticRegistry) -> str:
    owners = registry.property_owners(property_name)
    if root in owners:
        return root
    if len(owners) == 1:
        return owners[0]
    reachable = []
    for candidate in owners:
        try:
            registry.find_path(root, candidate)
            reachable.append(candidate)
        except SemanticRegistryError:
            continue
    if len(reachable) != 1:
        raise PlanValidationError(
            f"Property '{property_name}' is ambiguous; specify its target object."
        )
    return reachable[0]

"""Canonical semantic registry assembled from dbt artifacts and the ontology overlay.

The registry is the only runtime source used by planning and SQL compilation.
dbt remains responsible for physical models, metrics, dimensions and tests;
``ontology.yml`` contributes business objects, relationships and display names.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.metadata.parser import MetadataStore, load_metadata
from backend.ontology.parser import OntologyStore, load_ontology


class SemanticRegistryError(ValueError):
    """Raised when dbt metadata and the ontology overlay are inconsistent."""


@dataclass(frozen=True)
class DimensionDefinition:
    name: str
    expression: str
    dim_type: str
    time_granularity: str | None = None


@dataclass(frozen=True)
class MeasureDefinition:
    name: str
    aggregation: str
    expression: str
    semantic_model: str


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    description: str
    label: str
    semantic_model: str
    table: str
    measure: MeasureDefinition
    default_time_dimension: str | None
    filter_sql: str | None = None
    time_granularity: str | None = None
    numerator_measure: MeasureDefinition | None = None
    denominator_measure: MeasureDefinition | None = None


@dataclass(frozen=True)
class EntityDefinition:
    name: str
    table: str
    model_name: str
    primary_key: str
    time_dimension: str | None
    properties: dict[str, str]
    description: str = ""


@dataclass(frozen=True)
class RelationshipDefinition:
    name: str
    source: str
    target: str
    source_column: str
    target_column: str
    cardinality: str
    denormalized: bool
    description: str = ""


def _table_name(relation: dict[str, Any], fallback: str) -> str:
    """Return the stable unquoted ``schema.alias`` relation identifier."""
    schema = relation.get("schema_name") or "analytics"
    alias = relation.get("alias") or fallback
    return f"{schema}.{alias}"


def _filter_sql(metric: dict[str, Any]) -> str | None:
    config = metric.get("filter") or {}
    clauses = [
        item.get("where_sql_template", "").strip()
        for item in config.get("where_filters", [])
        if item.get("where_sql_template", "").strip()
    ]
    return " AND ".join(clauses) or None


class SemanticRegistry:
    """Typed, validated view of dbt semantic metadata and ontology objects."""

    def __init__(self):
        self.metrics: dict[str, MetricDefinition] = {}
        self.dimensions_by_model: dict[str, dict[str, DimensionDefinition]] = {}
        self.entities: dict[str, EntityDefinition] = {}
        self.relationships: dict[str, RelationshipDefinition] = {}
        self.models_by_table: dict[str, str] = {}
        self.model_columns: dict[str, set[str]] = {}
        self._adjacency: dict[str, list[tuple[str, RelationshipDefinition]]] = {}

    def metric(self, name: str) -> MetricDefinition:
        try:
            return self.metrics[name]
        except KeyError as exc:
            raise SemanticRegistryError(f"Unknown metric: {name}") from exc

    def entity(self, name: str) -> EntityDefinition:
        try:
            return self.entities[name]
        except KeyError as exc:
            raise SemanticRegistryError(f"Unknown entity: {name}") from exc

    def dimension(self, model_name: str, name: str) -> DimensionDefinition:
        try:
            return self.dimensions_by_model[model_name][name]
        except KeyError as exc:
            raise SemanticRegistryError(
                f"Unknown dimension '{name}' for semantic model '{model_name}'"
            ) from exc

    def find_path(self, start: str, target: str, max_hops: int = 4) -> list[RelationshipDefinition]:
        """Return the shortest relationship path, including reverse traversal."""
        if start not in self.entities or target not in self.entities:
            raise SemanticRegistryError(f"Unknown entity in path: {start} -> {target}")
        if start == target:
            return []

        queue: list[tuple[str, list[RelationshipDefinition]]] = [(start, [])]
        seen = {start}
        while queue:
            current, path = queue.pop(0)
            if len(path) >= max_hops:
                continue
            for neighbour, relationship in self._adjacency.get(current, []):
                if neighbour in seen:
                    continue
                next_path = [*path, relationship]
                if neighbour == target:
                    return next_path
                seen.add(neighbour)
                queue.append((neighbour, next_path))
        raise SemanticRegistryError(f"No relationship path from '{start}' to '{target}'")

    def property_owners(self, property_name: str) -> list[str]:
        return [
            entity.name
            for entity in self.entities.values()
            if property_name in entity.properties
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "metrics": {name: asdict(metric) for name, metric in self.metrics.items()},
            "dimensions": {
                model: {name: asdict(dim) for name, dim in dimensions.items()}
                for model, dimensions in self.dimensions_by_model.items()
            },
            "entities": {name: asdict(entity) for name, entity in self.entities.items()},
            "relationships": {
                name: asdict(relationship)
                for name, relationship in self.relationships.items()
            },
        }

    def planning_context(self) -> str:
        """Small, deterministic context for the LLM fallback planner."""
        metric_lines = [
            f"- {metric.name}: {metric.description} (model={metric.semantic_model})"
            for metric in self.metrics.values()
        ]
        entity_lines = [
            f"- {entity.name}: properties={', '.join(entity.properties)}"
            for entity in self.entities.values()
        ]
        relationship_lines = [
            f"- {relationship.name}: {relationship.source} -> {relationship.target} "
            f"({relationship.cardinality})"
            for relationship in self.relationships.values()
        ]
        return "\n".join([
            "## Metrics", *metric_lines,
            "## Entities", *entity_lines,
            "## Relationships", *relationship_lines,
        ])


def build_registry(
    metadata: MetadataStore | None = None,
    ontology: OntologyStore | None = None,
) -> SemanticRegistry:
    """Build and validate the registry from the current dbt artifacts."""
    metadata = metadata or load_metadata()
    ontology = ontology or load_ontology()
    if not metadata.models:
        raise SemanticRegistryError("dbt manifest.json contains no models; run 'dbt parse' first.")
    if not metadata.semantic_models:
        raise SemanticRegistryError(
            "dbt semantic_manifest.json contains no semantic models; run 'dbt parse' first."
        )

    registry = SemanticRegistry()
    for model in metadata.models:
        name = model["name"]
        table = f"{model.get('schema') or 'analytics'}.{name}"
        registry.models_by_table[table] = name
        registry.model_columns[name] = {
            column["name"] for column in metadata.columns_by_model.get(name, [])
        }

    measures: dict[str, MeasureDefinition] = {}
    model_tables: dict[str, str] = {}
    model_time_dimensions: dict[str, str | None] = {}
    for semantic_model in metadata.semantic_models:
        model_name = semantic_model["name"]
        table = _table_name(semantic_model.get("node_relation", {}), model_name)
        if table not in registry.models_by_table:
            raise SemanticRegistryError(
                f"Semantic model '{model_name}' points to unknown dbt relation '{table}'."
            )
        model_tables[model_name] = table
        model_time_dimensions[model_name] = (
            (semantic_model.get("defaults") or {}).get("agg_time_dimension")
        )

        dimensions: dict[str, DimensionDefinition] = {}
        for dimension in semantic_model.get("dimensions", []):
            type_params = dimension.get("type_params") or {}
            dimensions[dimension["name"]] = DimensionDefinition(
                name=dimension["name"],
                expression=dimension.get("expr") or dimension["name"],
                dim_type=dimension.get("type", "categorical"),
                time_granularity=type_params.get("time_granularity"),
            )
        registry.dimensions_by_model[model_name] = dimensions

        for measure in semantic_model.get("measures", []):
            measure_name = measure["name"]
            if measure_name in measures:
                raise SemanticRegistryError(f"Duplicate measure name: '{measure_name}'.")
            measures[measure_name] = MeasureDefinition(
                name=measure_name,
                aggregation=measure.get("agg", "sum"),
                expression=measure.get("expr", "*"),
                semantic_model=model_name,
            )

    for metric in metadata.metrics:
        type_params = metric.get("type_params") or {}
        measure_ref = type_params.get("measure") or {}
        measure_name = measure_ref.get("name") if isinstance(measure_ref, dict) else measure_ref
        if not measure_name or measure_name not in measures:
            # Unsupported dbt metric types are deliberately not silently compiled.
            continue
        measure = measures[measure_name]
        model_name = measure.semantic_model
        formula = (((metric.get("config") or {}).get("meta") or {}).get("data_agent") or {}).get("formula") or {}
        numerator_measure = denominator_measure = None
        if formula:
            if formula.get("kind") != "ratio":
                raise SemanticRegistryError(
                    f"Metric '{metric['name']}' has unsupported data_agent formula '{formula.get('kind')}'."
                )
            numerator_name = formula.get("numerator_measure")
            denominator_name = formula.get("denominator_measure")
            numerator_measure = measures.get(numerator_name)
            denominator_measure = measures.get(denominator_name)
            if numerator_measure is None or denominator_measure is None:
                raise SemanticRegistryError(
                    f"Metric '{metric['name']}' ratio formula references an unknown measure."
                )
            if {numerator_measure.semantic_model, denominator_measure.semantic_model} != {model_name}:
                raise SemanticRegistryError(
                    f"Metric '{metric['name']}' ratio formula must use measures from '{model_name}'."
                )
        registry.metrics[metric["name"]] = MetricDefinition(
            name=metric["name"],
            description=metric.get("description", ""),
            label=metric.get("label") or metric["name"],
            semantic_model=model_name,
            table=model_tables[model_name],
            measure=measure,
            default_time_dimension=model_time_dimensions[model_name],
            filter_sql=_filter_sql(metric),
            time_granularity=metric.get("time_granularity"),
            numerator_measure=numerator_measure,
            denominator_measure=denominator_measure,
        )

    if not registry.metrics:
        raise SemanticRegistryError("No supported simple metrics were found in semantic_manifest.json.")

    _add_entities(registry, ontology)
    _add_relationships(registry, ontology)
    return registry


def _add_entities(registry: SemanticRegistry, ontology: OntologyStore) -> None:
    for obj in ontology.object_by_name.values():
        model_name = registry.models_by_table.get(obj.table)
        if model_name is None:
            raise SemanticRegistryError(
                f"Ontology object '{obj.name}' points to unknown dbt relation '{obj.table}'."
            )
        known_columns = registry.model_columns[model_name]
        properties = {name: prop.column_name for name, prop in obj.properties.items()}
        missing_columns = sorted(set(properties.values()) - known_columns)
        if missing_columns:
            raise SemanticRegistryError(
                f"Ontology object '{obj.name}' has properties missing from dbt model "
                f"'{model_name}': {', '.join(missing_columns)}"
            )
        if obj.primary_key not in known_columns:
            raise SemanticRegistryError(
                f"Ontology object '{obj.name}' primary key '{obj.primary_key}' is not in dbt model '{model_name}'."
            )
        if obj.time_dimension and obj.column_for(obj.time_dimension) not in known_columns:
            raise SemanticRegistryError(
                f"Ontology object '{obj.name}' time dimension '{obj.time_dimension}' is not in dbt model '{model_name}'."
            )
        registry.entities[obj.name] = EntityDefinition(
            name=obj.name,
            table=obj.table,
            model_name=model_name,
            primary_key=obj.primary_key,
            time_dimension=obj.time_dimension,
            properties=properties,
            description=obj.description,
        )


def _add_relationships(registry: SemanticRegistry, ontology: OntologyStore) -> None:
    for link in ontology.link_by_name.values():
        if link.source not in registry.entities or link.target not in registry.entities:
            raise SemanticRegistryError(f"Relationship '{link.name}' references an unknown entity.")
        source = registry.entity(link.source)
        target = registry.entity(link.target)
        source_columns = registry.model_columns[source.model_name]
        target_columns = registry.model_columns[target.model_name]
        if link.source_column not in source_columns or link.target_column not in target_columns:
            raise SemanticRegistryError(
                f"Relationship '{link.name}' has an invalid join key: "
                f"{link.source}.{link.source_column} -> {link.target}.{link.target_column}."
            )
        if link.denormalized and source.table != target.table:
            raise SemanticRegistryError(
                f"Relationship '{link.name}' is marked denormalized but uses different tables."
            )
        relationship = RelationshipDefinition(
            name=link.name,
            source=link.source,
            target=link.target,
            source_column=link.source_column,
            target_column=link.target_column,
            cardinality=link.cardinality,
            denormalized=link.denormalized,
            description=link.description,
        )
        registry.relationships[relationship.name] = relationship
        registry._adjacency.setdefault(relationship.source, []).append((relationship.target, relationship))
        registry._adjacency.setdefault(relationship.target, []).append((relationship.source, relationship))


@lru_cache(maxsize=1)
def load_registry() -> SemanticRegistry:
    return build_registry()


def clear_registry_cache() -> None:
    load_registry.cache_clear()


def write_registry(path: Path | None = None) -> Path:
    """Persist a build artifact for inspection and deployment pipelines."""
    destination = path or Path(settings.dbt_project_dir) / "target" / "semantic_registry.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(load_registry().to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination

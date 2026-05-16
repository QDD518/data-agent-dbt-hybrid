"""Ontology metadata parser — reads ontology.yml and builds fast-lookup indices."""

import yaml
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from backend.config import settings


# ── Data classes ──


@dataclass
class PropertyDef:
    name: str
    prop_type: str  # "String" | "Numeric" | "Date" | "Boolean"
    description: str


@dataclass
class ObjectType:
    name: str
    description: str
    display_name: str
    icon: str | None
    color: str | None
    primary_key: str
    table: str
    time_dimension: str | None
    properties: dict[str, PropertyDef] = field(default_factory=dict)

    def column_names(self) -> list[str]:
        return [p.name for p in self.properties.values()]


@dataclass
class LinkType:
    name: str
    description: str
    source: str  # ObjectType name
    target: str  # ObjectType name
    source_column: str
    target_column: str
    cardinality: str  # "many_to_one" | "one_to_many" | "one_to_one"
    denormalized: bool  # True if source and target share the same table


# ── Ontology Store ──


class OntologyStore:
    """In-memory indices built from ontology.yml. Fast lookup for graph traversal."""

    def __init__(self):
        self.object_by_name: dict[str, ObjectType] = {}
        self.link_by_name: dict[str, LinkType] = {}
        self.outbound_links: dict[str, list[LinkType]] = {}   # source → links
        self.inbound_links: dict[str, list[LinkType]] = {}    # target → links
        self.adjacency: dict[str, list[tuple[str, LinkType]]] = {}  # object → [(neighbor, link), ...]

    def to_rag_documents(self) -> list[str]:
        """Produce text chunks for Path B/C keyword retrieval."""
        docs: list[str] = []

        for obj in self.object_by_name.values():
            props = ", ".join(
                f"{p.name} ({p.prop_type})" for p in obj.properties.values()
            )
            links = self.outbound_links.get(obj.name, [])
            link_str = ", ".join(f"{l.name} -> {l.target}" for l in links) if links else "none"
            docs.append(
                f"Object Type {obj.name} ({obj.display_name}): {obj.description}. "
                f"Home table: {obj.table}. "
                f"Primary key: {obj.primary_key}. "
                f"Properties: {props}. "
                f"Outbound links: {link_str}."
            )

        for link in self.link_by_name.values():
            dn = " [denormalized — no JOIN needed]" if link.denormalized else ""
            docs.append(
                f"Link Type {link.name}: {link.source} -> {link.target} "
                f"via {link.source_column} = {link.target_column} "
                f"({link.cardinality}){dn}. {link.description}"
            )

        return docs

    def to_graph_dict(self) -> dict:
        """Return nodes + edges structure for frontend visualization."""
        nodes = []
        for obj in self.object_by_name.values():
            nodes.append({
                "id": obj.name,
                "label": obj.display_name,
                "description": obj.description,
                "icon": obj.icon,
                "color": obj.color,
                "table": obj.table,
                "primary_key": obj.primary_key,
                "properties": [
                    {"name": p.name, "type": p.prop_type, "description": p.description}
                    for p in obj.properties.values()
                ],
            })

        edges = []
        for link in self.link_by_name.values():
            edges.append({
                "id": link.name,
                "source": link.source,
                "target": link.target,
                "label": link.name,
                "description": link.description,
                "cardinality": link.cardinality,
                "source_column": link.source_column,
                "target_column": link.target_column,
                "denormalized": link.denormalized,
            })

        return {"nodes": nodes, "edges": edges}


# ── Public API ──


@lru_cache(maxsize=1)
def load_ontology() -> OntologyStore:
    """Parse ontology.yml and build in-memory indices. Cached in-process."""
    project_dir = Path(settings.dbt_project_dir)
    onto_path = project_dir / "models" / "marts" / "ontology.yml"

    if not onto_path.exists():
        raise FileNotFoundError(f"Ontology file not found: {onto_path}")

    with open(onto_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    store = OntologyStore()

    # Build object types
    for obj_data in data.get("object_types", []):
        props = {}
        for p in obj_data.get("properties", []):
            props[p["name"]] = PropertyDef(
                name=p["name"],
                prop_type=p.get("type", "String"),
                description=p.get("description", ""),
            )

        ot = ObjectType(
            name=obj_data["name"],
            description=obj_data.get("description", ""),
            display_name=obj_data.get("display_name", obj_data["name"]),
            icon=obj_data.get("icon"),
            color=obj_data.get("color"),
            primary_key=obj_data["primary_key"],
            table=obj_data["table"],
            time_dimension=obj_data.get("time_dimension"),
        )
        ot.properties = props
        store.object_by_name[ot.name] = ot

    # Build link types and adjacency
    for link_data in data.get("link_types", []):
        link = LinkType(
            name=link_data["name"],
            description=link_data.get("description", ""),
            source=link_data["source"],
            target=link_data["target"],
            source_column=link_data["join_key"]["source_column"],
            target_column=link_data["join_key"]["target_column"],
            cardinality=link_data.get("cardinality", "many_to_one"),
            denormalized=link_data.get("denormalized", False),
        )
        store.link_by_name[link.name] = link

        # outbound
        store.outbound_links.setdefault(link.source, []).append(link)
        # inbound
        store.inbound_links.setdefault(link.target, []).append(link)
        # adjacency (both directions)
        store.adjacency.setdefault(link.source, []).append((link.target, link))
        store.adjacency.setdefault(link.target, []).append((link.source, link))

    return store

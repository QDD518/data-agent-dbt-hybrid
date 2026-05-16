# Data Agent — dbt Hybrid

**A four-path hybrid Chat BI architecture powered by dbt Semantic Layer and Palantir-inspired Ontology.**

This project routes natural language questions through an intent router, converting them into deterministic or constrained SQL. It addresses two core engineering pain points: the low accuracy of pure Text-to-SQL, and the inability of pure semantic layers to handle cross-object queries.

Ask questions in natural language. The system routes intelligently:

- **Metric questions** → dbt metric layer → deterministic SQL → execute (never hallucinates)
- **Cross-object questions** → Ontology graph traversal → CTE chain SQL → execute (multi-hop)
- **Exploratory questions** → LLM + dbt Schema + Ontology relationships → Text-to-SQL → execute (flexible & constrained)
- **Metadata questions** → search dbt Docs → direct answer (no query needed)

Built on dbt + PostgreSQL + Ontology + DeepSeek (or any OpenAI-compatible LLM).

> [中文版本 →](README.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![dbt 1.11+](https://img.shields.io/badge/dbt-1.11+-orange.svg)](https://docs.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-latest-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Architecture: dbt Semantic Layer + Ontology Graph Model

Pure Text-to-SQL suffers from table schema hallucinations and uncontrollable JOINs. A pure dbt semantic layer (e.g., MetricFlow) is typically limited to single-table aggregation with poor extensibility.

DataAgent-ChatBI introduces an **ontology graph model** on top of dbt's semantic layer, forming a four-path hybrid architecture:

```
┌──────────────────────────────────────────────────────┐
│              Ontology (Business Graph)                │
│       8 Object Types · 6 Link Types · Graph Traversal │
│       "InventoryRecord —tracks→ Product               │
│        —stored_in→ Warehouse"                         │
└────────────────────────┬─────────────────────────────┘
                         │ maps to
┌────────────────────────▼─────────────────────────────┐
│           dbt Semantic Layer (Physical Schema)         │
│      5 Semantic Models · 28 Metrics · MetricQueryBuilder│
└────────────────────────┬─────────────────────────────┘
                         │ queries
┌────────────────────────▼─────────────────────────────┐
│              PostgreSQL (chatbi_demo)                  │
│       17 dbt Models (OBT wide tables) · 8 Seeds        │
└──────────────────────────────────────────────────────┘

User Question (NL)
    │
    ▼
┌──────────────────────────┐
│  Intent Router (LLM)      │  classify: metric / ontology / exploratory / metadata
└──┬─────────┬─────────┬───┘
   │         │         │        │
   ▼         ▼         ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│Path A│ │Path B│ │Path C│ │Path D│
│Metric│ │Ontol-│ │Text- │ │Meta- │
│Query │ │ogy   │ │to-SQL│ │data  │
│      │ │Traver│ │      │ │Q&A   │
└──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
   │        │        │        │
   ▼        ▼        ▼        ▼
 Semantic  Graph    LLM+    RAG+LLM
 metadata  Traversal RAG+    direct
 determin- CTE chain Ontology answer
 istic SQL SQL      generates
 single-            SQL
 table
   │        │        │        │
   └────────┼────────┼────────┘
            ▼
   ┌──────────────┐
   │  SQL Security │  Keyword blocklist · SELECT-only · Row limit
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │  SQL Executor │  Read-only tx · Timeout · Auto-serialization
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │ NL Interpreter│  LLM summary + Chart recommendation + Insights
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │  SSE Stream   │  Real-time events: classify → SQL → execute → done
   └──────────────┘
```

## Core Execution Paths

### Path A — Metric Query (Deterministic)

When the router identifies a standard metric (e.g., "last month's revenue"), the system extracts parameters and parses `semantic_manifest.json`, directly generating single-table aggregation SQL. This path does NOT pass through an LLM during SQL construction, achieving 100% determinism at the logic layer.

Complex JOIN logic is already handled by the underlying dbt OBT wide tables.

### Path B — Ontology Graph Traversal (Deterministic Cross-Table)

For questions spanning multiple business objects, the router identifies target entities. `GraphTraverser` reads `ontology.yml`, computes the shortest link path between objects via BFS, and automatically generates standard CTE chain SQL.

> Note: The current pathfinding logic assumes shortest-path routing. If the business domain contains multiple complex graph edges, intervention via link cardinality tuning or table restructuring may be required.

**Denormalized Link Optimization**: When adjacent objects physically reside in the same wide table (configured as `denormalized: true`), the system automatically skips JOINs during SQL generation and performs direct column merging.

### Path C — Exploratory Query (Constrained Text-to-SQL)

For non-standard metric questions, the LLM receives dbt Schema and Ontology relationships retrieved via RAG as system prompts. Ontology constraints narrow the LLM's divergence space, significantly reducing hallucinations from illegal JOINs.

### Path D — Metadata RAG Q&A

For questions about data definitions and calculation logic, the system retrieves from dbt `manifest.json` and its description fields, with the LLM synthesizing answers. No database access is involved.

### Intent Router

A lightweight LLM prompt classifies every question into one of four paths and extracts structured parameters. The router prompt includes 28 available metrics, all dimensions, and 8 Ontology object types to ensure accurate classification.

---

## Ontology Design & Implementation

dbt's semantic layer defines measures and dimensions, but lacks abstraction for object relationships. This project implements business graph mapping via custom `ontology.yml`:

```yaml
# Excerpt from dbt_project/models/marts/ontology.yml
object_types:
  - name: Order
    primary_key: order_id
    table: "analytics_analytics.fact_orders"
    time_dimension: order_date
    # ...

  - name: Warehouse
    primary_key: warehouse_id
    table: "analytics_analytics.fact_inventory"

link_types:
  - name: stored_in          # InventoryRecord → Warehouse
    source: InventoryRecord
    target: Warehouse
    join_key:
      source_column: warehouse_id
      target_column: warehouse_id
    denormalized: true       # Target object shares physical table — blocks self-JOIN
```

**Key Design Points**:
- **Lightweight graph computation**: No graph database dependency. Uses native Python dict for adjacency storage. At current scale (8 nodes / 6 edges), BFS time complexity is negligible ($O(V+E)$).
- **Explicit JOIN keys**: Clearly defined cross-table association rules, replacing implicit LLM inference.
- **`denormalized: true` flag**: Prevents redundant self-JOINs when objects share a wide table.
- **Typed properties**: String / Numeric / Date / Boolean — helps the router understand filter semantics.

---

## Why dbt Semantic Layer Instead of MetricFlow?

Compared to dbt's official MetricFlow, this project provides a viable open-source alternative with enhanced graph capabilities:

| Feature | MetricFlow | DataAgent-ChatBI |
|---------|-----------|------------------|
| Dependency compatibility | Strict (requires `click<8.3`, conflicts with dbt-core 1.11) | Compatible with dbt-core 1.11+ ecosystem |
| Execution environment | Query engine requires dbt Cloud (commercial) | Local custom SQL Builder, fully open-source |
| Cross-object computation | Limited, relies on underlying views | Explicit graph traversal via `ontology.yml` |
| Object relationship modeling | None | 8 Object Types + 6 Link Types, BFS graph traversal |

---

## Features

| Feature | Detail |
|---------|--------|
| **4-path hybrid router** | Metric query / Ontology traversal / Text-to-SQL / Metadata Q&A |
| **Ontology graph traversal** | 8 Object Types, 6 Link Types, BFS path finding + CTE chain SQL |
| **Denormalized link optimization** | Shared-table objects skip JOINs, auto-merge columns |
| **SSE streaming** | Real-time progress: classifying → traversing → building SQL → executing → interpreting |
| **Deterministic metric SQL** | Path A zero hallucination (parses `semantic_manifest.json`) |
| **LLM Text-to-SQL + RAG** | Exploratory queries grounded in dbt Schema + Ontology relationship context |
| **SQL security layer** | Keyword blocklist, SELECT-only, multi-statement prevention, row limit |
| **12 filter operators** | eq/neq/gt/gte/lt/lte/in/between/like/is_null/is_not_null |
| **Auto-serialization** | Decimal → float, datetime → ISO string for JSON-safe output |
| **CJK-aware RAG** | Chinese character bigram + Latin tokenizer keyword retrieval (36 documents, no embedding API needed) |
| **Frontend ontology browser** | Sidebar renders Object Type cards with properties and link visualization |
| **Vendor-agnostic LLM** | Compatible with DeepSeek, OpenAI, or any OpenAI-compatible API |

---

## Project Structure

```
├── dbt_project/                 # dbt project (multi-fact models + semantic layer + ontology)
│   ├── models/
│   │   ├── staging/             # 9 staging views
│   │   └── marts/               # 5 mart models + ontology definitions
│   │       ├── fact_orders.sql   # OBT wide table (43 cols)
│   │       ├── fact_inventory.sql # Inventory fact (w/ warehouse/supplier dimensions)
│   │       ├── fact_marketing.sql # Marketing campaign fact (w/ campaign dims + derived KPIs)
│   │       ├── dim_customers_rfm.sql # RFM segmented customer table
│   │       ├── cohort_monthly.sql   # Monthly cohort retention table
│   │       ├── semantic_models.yml  # 5 semantic models (orders, customers, inventory, marketing, customers_rfm)
│   │       ├── metrics.yml          # 28 metrics (revenue/orders/customers/inventory/marketing/RFM/cohort)
│   │       └── ontology.yml         # 8 Object Types + 6 Link Types
│   ├── seeds/                   # 8 seeds (orders 95 rows, inventory 48, marketing 47...)
│   └── target/
│       ├── manifest.json
│       └── semantic_manifest.json  # generated by dbt parse
│
├── backend/                     # FastAPI (Python 3.12)
│   ├── agent/
│   │   ├── router.py            # 4-path intent classifier (LLM + Ontology object list)
│   │   └── orchestrator.py      # 4-path dispatcher + CrossModelQueryError fallback + SSE emitter
│   ├── semantic/
│   │   └── query_builder.py     # Path A: deterministic single-table SQL from semantic_manifest
│   ├── ontology/
│   │   ├── parser.py            # OntologyStore: parse ontology.yml, build lookup indices
│   │   └── traversal.py         # GraphTraverser: BFS path finding + CTE chain SQL generation
│   ├── sql/
│   │   ├── security.py          # SQL validator (keyword blocklist, SELECT-only)
│   │   ├── generator.py         # Path C: LLM Text-to-SQL (w/ Ontology relationship context)
│   │   └── executor.py          # SQLAlchemy read-only executor + serialization
│   ├── rag/
│   │   └── retriever.py         # Keyword retriever (36 docs: 22 dbt + 14 Ontology)
│   ├── api/
│   │   ├── chat.py              # POST /api/chat (SSE streaming)
│   │   ├── health.py            # GET /api/health
│   │   └── ontology.py          # GET /api/ontology (nodes + edges JSON)
│   ├── metadata/
│   │   └── parser.py            # dbt manifest + semantic_manifest parser + RAG doc generation
│   └── llm/
│       └── client.py            # OpenAI-compatible API wrapper
│
├── frontend/                    # Streamlit
│   ├── app.py                   # Entry: chat UI + Ontology browser + SSE consumer
│   ├── components/
│   │   ├── chat.py              # Rich assistant message renderer (SQL/result/chart/summary)
│   │   ├── chart.py             # pyecharts bar/line/pie → HTML embed
│   │   └── ontology_graph.py   # Ontology graph visualizer (expandable object cards)
│   └── utils/
│       └── api.py               # httpx SSE client + fetch_ontology()
│
├── tests/                       # 145 tests (81 core + 64 Ontology)
│   ├── test_ontology_parser.py  # 15: parsing, indices, RAG docs, graph JSON
│   ├── test_ontology_traversal.py # 49: filter operators, BFS, single/multi-hop/denormalized SQL
│   ├── test_security.py
│   ├── test_query_builder.py
│   ├── test_retriever.py
│   ├── test_router.py
│   ├── test_generator.py
│   ├── test_executor.py
│   └── test_integration.py
│
└── docs/
    └── architecture.md          # Full architecture doc (dbt + Ontology dual-layer design)
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ (or use the included `docker-compose.yml`)
- dbt-core 1.11+
- LLM API Key (DeepSeek, OpenAI, or compatible)

### 1. Clone

```bash
git clone https://github.com/QDD518/data-agent-dbt-hybrid.git
cd data-agent-dbt-hybrid
python -m venv venv
source venv/Scripts/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API key and PostgreSQL connection
```

Required `.env` variables:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | LLM API key |
| `OPENAI_BASE_URL` | API base URL (DeepSeek: `https://api.deepseek.com`) |
| `LLM_MODEL` | Chat model name |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PG connection |
| `POSTGRES_SCHEMA` | Default schema (default: `analytics`) |

### 3. Seed Data & Build dbt Models

```bash
cd dbt_project
dbt deps
dbt seed
dbt run
dbt parse          # generates manifest.json + semantic_manifest.json
cd ..
```

Or use Docker PostgreSQL:
```bash
docker-compose up -d        # starts PG16, creates schema
cd dbt_project && dbt seed && dbt run && dbt parse
```

### 4. Start

**Terminal 1 — Backend:**
```bash
source venv/Scripts/activate
python -m backend.main
# → http://localhost:8000
# Startup log: Metadata loaded (17 models). Ontology loaded (8 objects, 6 links).
```

**Terminal 2 — Frontend:**
```bash
source venv/Scripts/activate
streamlit run frontend/app.py
# → http://localhost:8501
```

### 5. Ask Questions

Try these in the Streamlit UI (the sidebar also displays the Ontology object browser):

| Question | Path | What Happens |
|----------|------|--------------|
| What was last month's revenue? | A | Deterministic SQL from semantic metadata (metric → measure → table → column) |
| Which products in North warehouse need reorder? | B | Ontology traversal → CTE SQL (InventoryRecord → Product + Warehouse) |
| Which city has the highest average order value? | C | LLM generates ad-hoc SQL with dbt Schema + Ontology JOIN constraints |
| Total inventory value by category | A | Metric + dimension group-by (total_inventory_value by product_category) |
| How is revenue calculated? | D | RAG retrieves metric definition, LLM answers directly |

---

## How the Semantic Layer Works

### Define metrics in dbt YAML

```yaml
# dbt_project/models/marts/metrics.yml
metrics:
  - name: total_revenue
    label: "Total Revenue"
    type: simple
    type_params:
      measure: revenue          # references measure in semantic_models.yml
    filter: "{{ dim('status') }} = 'Completed'"
```

### Define semantic models (measures + dimensions + entities)

```yaml
# dbt_project/models/marts/semantic_models.yml
semantic_models:
  - name: orders
    model: ref('fact_orders')
    entities:
      - name: order
        type: primary
        expr: order_id
      - name: customer
        type: foreign
        expr: customer_id
    dimensions:
      - name: order_date
        type: time
        type_params:
          time_granularity: day
      - name: product_category
        type: categorical
    measures:
      - name: revenue
        agg: sum
        expr: net_amount
```

### dbt parse → semantic_manifest.json → Deterministic SQL

```bash
dbt parse  # validates & outputs manifest files
# Path A generates: SELECT SUM(net_amount) FROM analytics_analytics.fact_orders WHERE status = 'Completed'
# Path B uses the object-link graph in ontology.yml for cross-object traversal
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Data transformation | dbt-core 1.11 (9 staging views → 6 mart tables) |
| Semantic layer | dbt Semantic Models + Metrics (5 models, 28 metrics) |
| Ontology | Custom YAML graph model (8 Object Types, 6 Link Types) |
| Query gen (Path A) | Custom Python MetricQueryBuilder (parses semantic_manifest.json) |
| Query gen (Path B) | Custom Python GraphTraverser (BFS + CTE chain SQL) |
| Query gen (Path C) | LLM Text-to-SQL (w/ dbt Schema + Ontology relationships as RAG context) |
| Database | PostgreSQL 16 (SQLAlchemy + psycopg2) |
| Backend | FastAPI + SSE streaming + 4-path orchestrator |
| Frontend | Streamlit + pyecharts + Ontology object browser |
| LLM | DeepSeek V4 / OpenAI / compatible API |
| RAG | Keyword overlap retrieval (CJK bigram + Latin tokenizer, 36 documents) |
| Security | SQL keyword blocklist, SELECT-only, row limit, timeout |
| Testing | 145 tests (pytest), 4 PG-dependent skipped |

---

## License

MIT — see [LICENSE](LICENSE) file.

---

## Author

**QDD518** — [github.com/QDD518](https://github.com/QDD518)

*Built as an open-source Chat BI reference architecture. Contributions and feedback welcome.*

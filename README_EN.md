# Data Agent — dbt Hybrid

**One agent. Three paths. Never hallucinates. — An open-source Chat BI powered by dbt Semantic Layer.**

Ask questions in natural language. The system routes intelligently:

- **Metric questions** → dbt Metrics → deterministic SQL → execute (never hallucinates)
- **Exploratory questions** → LLM + dbt Schema → Text-to-SQL → execute (flexible)
- **Metadata questions** → dbt Docs → direct answer (no query needed)

Built on dbt + PostgreSQL + DeepSeek (or any OpenAI-compatible LLM).

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![dbt 1.11+](https://img.shields.io/badge/dbt-1.11+-orange.svg)](https://docs.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-latest-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Architecture: Why a Hybrid Router?

Pure Text-to-SQL is **fragile**. LLMs hallucinate column names, fabricate aggregation logic, and fail silently on structured business metrics. A pure semantic layer (MetricFlow) is **rigid** — it can't handle ad-hoc exploratory questions.

DataAgent-ChatBI uses a **three-path hybrid architecture** that gets the best of both worlds:

```
User Question
    │
    ▼
┌──────────────────┐
│  Intent Router    │  LLM classifier → metric_query / exploratory / metadata
└──────┬───────┬───┘
       │       │
       ▼       ▼       ▼
   ┌──────┐ ┌──────┐ ┌──────┐
   │Path A│ │Path B│ │Path C│
   │Metric│ │Text- │ │ Meta │
   │Query │ │to-SQL│ │ Q&A  │
   └──┬───┘ └──┬───┘ └──┬───┘
      │        │        │
      ▼        ▼        ▼
 Deterministic  LLM + RAG   RAG + LLM
 SQL from      generates    direct
 semantic      ad-hoc SQL   answer
 metadata
      │        │        │
      └────────┼────────┘
               ▼
      ┌──────────────┐
      │  SQL Executor │  Read-only, row-limited, timeout-protected
      └──────┬───────┘
             ▼
      ┌──────────────┐
      │ NL Interpreter│  LLM summary + chart recommendation
      └──────┬───────┘
             ▼
      ┌──────────────┐
      │  SSE Stream   │  Real-time progress events to frontend
      └──────────────┘
```

### Path A — Metric Query (Deterministic SQL)

When the user asks "上月营收是多少？" or "按城市分组的订单量", the Intent Router extracts metric names and dimensions. The system parses `semantic_manifest.json` (dbt Semantic Layer metadata) and **deterministically generates SQL** — no LLM involved in SQL generation.

**Key insight — Last-Mile Aggregation**: dbt models handle all the complex joins (our `fact_orders` is a 43-column OBT wide table). The semantic layer only does:

```sql
SELECT SUM(net_amount) AS total_revenue, DATE_TRUNC('month', order_date) AS month
FROM analytics.fact_orders
WHERE status = 'Completed'
GROUP BY month
ORDER BY 1 DESC
```

This guarantees **zero hallucination** for metric queries. Same logic as MetricFlow, but implemented in pure Python from the dbt-generated metadata.

### Path B — Exploratory Text-to-SQL

For ad-hoc questions that don't match predefined metrics ("哪个城市的客户平均客单价最高？"), the LLM generates SQL with RAG context from dbt metadata. The keyword-based retriever finds the most relevant tables and columns, providing ground-truth schema context to the LLM.

### Path C — Metadata Q&A

"revenue 是怎么计算的？" → RAG retrieves the relevant dbt docs (model descriptions, column tests, metric definitions) and the LLM answers directly — no SQL execution needed.

### Intent Router

A lightweight LLM prompt classifies each question into one of the three paths и extracts structured parameters (metric names, dimensions, time ranges). This means the system **adapts its strategy** per question rather than using one-size-fits-all Text-to-SQL.

---

## Why dbt Semantic Layer, Not MetricFlow?

dbt's Semantic Layer (`.yml` definitions + `semantic_manifest.json`) gives us structured metric metadata that the Path A engine parses to build deterministic SQL. This is the same principle as MetricFlow, but:

- **No pip dependency conflicts** — MetricFlow's package is dead (requires `click<8.3`, dbt-core 1.11 requires `click>=8.3`)
- **No dbt Cloud required** — dbt OSS only defines/validates semantic models; the query engine is a Cloud paid feature. Our custom SQL builder fills this gap
- **Simpler architecture** — last-mile aggregation means semantic SQL has no joins, just `SELECT agg FROM table GROUP BY dim WHERE filter`

The dbt project generates `semantic_manifest.json` via `dbt parse`, and our `MetricQueryBuilder` parses it at runtime.

---

## Features

| Feature | Detail |
|---------|--------|
| **3-path hybrid router** | Metric query / Text-to-SQL / Metadata QA |
| **SSE streaming** | Real-time progress: classifying → building SQL → executing → interpreting |
| **Deterministic metric SQL** | Zero hallucination for metric queries (parses `semantic_manifest.json`) |
| **LLM Text-to-SQL + RAG** | Ad-hoc queries grounded in dbt metadata schema context |
| **SQL security** | Keyword blocklist, SELECT-only, multi-statement prevention, row limits |
| **Auto-serialization** | Decimal → float, datetime → ISO string for JSON-safe output |
| **CJK-aware RAG** | Chinese character bigram tokenizer for keyword retrieval (no embedding API needed) |
| **LLM result interpretation** | NL summary + chart type recommendation (bar/line/pie/table) |
| **Vendor-agnostic LLM** | Works with DeepSeek, OpenAI, or any OpenAI-compatible API |

---

## Project Structure

```
├── dbt_project/              # dbt project (star schema + semantic layer)
│   ├── models/
│   │   ├── staging/          # stg_orders, stg_customers, stg_products, dates
│   │   └── marts/            # fact_orders (OBT, 43 cols), dim_customers, dim_products
│   ├── seeds/                # raw_orders.csv (95 rows), raw_customers.csv, raw_products.csv
│   └── semantic manifest →   # 2 semantic models, 12 metrics, 15+ dimensions
│       semantic_manifest.json
│
├── backend/                  # FastAPI (Python 3.12)
│   ├── agent/
│   │   ├── router.py         # Intent classifier (LLM)
│   │   └── orchestrator.py   # 3-path dispatcher + SSE emitter + result interpreter
│   ├── semantic/
│   │   └── query_builder.py  # Path A: deterministic SQL from semantic_manifest.json
│   ├── sql/
│   │   ├── security.py       # SQL validator (SELECT-only, keyword blocklist)
│   │   ├── generator.py      # Path B: LLM Text-to-SQL
│   │   └── executor.py       # SQLAlchemy read-only executor + serialization
│   ├── rag/
│   │   └── retriever.py      # Keyword retriever (CJK bigram + Latin tokenizer)
│   ├── metadata/
│   │   └── parser.py         # dbt manifest.json + semantic_manifest.json parser
│   └── llm/
│       └── client.py         # OpenAI-compatible API wrapper
│
├── frontend/                 # Streamlit
│   ├── app.py                # Entry: chat UI, SSE consumer, session state
│   ├── components/
│   │   ├── chat.py           # Rich assistant message renderer
│   │   └── chart.py          # pyecharts bar/line/pie → HTML embed
│   └── utils/
│       └── api.py            # httpx SSE client
│
├── scripts/
│   └── init_db.sql           # PostgreSQL schema initialization
│
└── requirements.txt
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ (or use the included `docker-compose.yml`)
- dbt-core 1.11+
- An LLM API key (DeepSeek, OpenAI, or compatible)

### 1. Clone

```bash
git clone https://github.com/QDD518/data-agent-dbt-hybrid.git
cd data-agent-dbt-hybrid
python -m venv venv
source venv/Scripts/activate  # or: venv\Scripts\activate
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
```

**Terminal 2 — Frontend:**
```bash
source venv/Scripts/activate
streamlit run frontend/app.py
# → http://localhost:8501
```

### 5. Ask Questions

Try these in the Streamlit UI:

| Question | Path | What Happens |
|----------|------|--------------|
| 上月营收是多少？ | A | Deterministic SQL from semantic metadata |
| 按城市分组的订单量 | A | Metric + dimension, grouped |
| 哪个城市的客户平均客单价最高？ | B | LLM generates ad-hoc SQL with RAG context |
| 本月每天的收入趋势 | A | Metric + time dimension + daily granularity |
| revenue 是怎么计算的？ | C | RAG retrieves metric definition, LLM answers |

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

### Define semantic models (measures + dimensions)

```yaml
# dbt_project/models/marts/semantic_models.yml
semantic_models:
  - name: orders
    model: ref('fact_orders')
    entities:
      - name: order
        type: primary
        expr: order_id
    dimensions:
      - name: order_date
        type: time
        type_params:
          time_granularity: day
    measures:
      - name: revenue
        agg: sum
        expr: net_amount
```

### dbt parse → semantic_manifest.json → Deterministic SQL

```bash
dbt parse  # validates & outputs manifests
# backend reads semantic_manifest.json at startup
# Path A generates: SELECT SUM(net_amount) FROM analytics.fact_orders WHERE status = 'Completed'
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Data transformation | dbt-core 1.11 (staging views → mart tables) |
| Semantic layer | dbt Semantic Models + Metrics (YAML → `semantic_manifest.json`) |
| Query generation | Custom Python SQL builder (Path A) + LLM (Path B) |
| Database | PostgreSQL 16 (SQLAlchemy + psycopg2) |
| Backend | FastAPI + SSE streaming |
| Frontend | Streamlit + pyecharts |
| LLM | DeepSeek V4 / OpenAI / compatible API |
| RAG | Keyword overlap (CJK bigram + Latin tokenizer) |
| Security | SQL keyword blocklist, SELECT-only, row limit, timeout |

---

## License

MIT — see [LICENSE](LICENSE) file.

---

## Author

**QDD518** — [github.com/QDD518](https://github.com/QDD518)

*Built as an open-source Chat BI reference architecture. Contributions and feedback welcome.*

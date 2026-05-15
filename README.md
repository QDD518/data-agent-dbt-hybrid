# Data Agent — dbt Hybrid

**基于 dbt Semantic Layer + LLM Text-to-SQL + RAG 的开源 Chat BI 智能体。三路径混合架构（指标查询 / Text-to-SQL / 元数据问答），确定性 + 灵活性兼得。**

用自然语言提问 — 系统将每个问题路由到三条专用路径之一，返回 SQL、数据表格、图表和自然语言摘要。基于 dbt + PostgreSQL + DeepSeek（或任何 OpenAI 兼容的 LLM）。

> [English Version →](README_EN.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![dbt 1.11+](https://img.shields.io/badge/dbt-1.11+-orange.svg)](https://docs.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-latest-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 架构：为什么需要混合路由？

纯 Text-to-SQL **很脆弱**：LLM 会幻觉列名、凭空捏造聚合逻辑、在结构化业务指标上静默失败。纯语义层（MetricFlow）又**太死板**：无法处理灵活探索性问题。

DataAgent-ChatBI 采用 **三路径混合架构**，取两者之长：

```
用户自然语言提问
    │
    ▼
┌──────────────────┐
│  意图路由器       │  LLM 分类 → metric_query / exploratory / metadata
└──────┬───────┬───┘
       │       │
       ▼       ▼       ▼
   ┌──────┐ ┌──────┐ ┌──────┐
   │路径 A│ │路径 B│ │路径 C│
   │指标  │ │Text- │ │元数据│
   │查询  │ │to-SQL│ │问答  │
   └──┬───┘ └──┬───┘ └──┬───┘
      │        │        │
      ▼        ▼        ▼
 从语义元数据   LLM + RAG   RAG + LLM
 确定性生成     生成灵活     直接回答
 SQL           ad-hoc SQL
      │        │        │
      └────────┼────────┘
               ▼
      ┌──────────────┐
      │  SQL 执行器   │  只读、行数限制、超时保护
      └──────┬───────┘
             ▼
      ┌──────────────┐
      │  NL 解释器    │  LLM 摘要 + 图表推荐
      └──────┬───────┘
             ▼
      ┌──────────────┐
      │  SSE 流式推送 │  实时进度事件推送到前端
      └──────────────┘
```

### 路径 A — 指标查询（确定性 SQL）

当用户问"上月营收是多少？"或"按城市分组的订单量"时，意图路由器提取指标名和维度。系统解析 `semantic_manifest.json`（dbt 语义层元数据）并**确定性地生成 SQL** — 此路径不涉及 LLM，零幻觉。

**核心设计 — 最后一公里聚合**：dbt 模型负责所有复杂 JOIN（我们的 `fact_orders` 是一张 43 列的 OBT 宽表）。语义层只做最简单的事：

```sql
SELECT SUM(net_amount) AS total_revenue, DATE_TRUNC('month', order_date) AS month
FROM analytics.fact_orders
WHERE status = 'Completed'
GROUP BY month
ORDER BY 1 DESC
```

与 MetricFlow 同等逻辑，但从 dbt 生成的元数据中以纯 Python 实现，无需 MetricFlow 包依赖。

### 路径 B — 探索性 Text-to-SQL

对于不匹配预定义指标的灵活提问（"哪个城市的客户平均客单价最高？"），LLM 结合 dbt 元数据的 RAG 上下文生成 SQL。基于关键词的检索器找到最相关的表和列，为 LLM 提供真实的 Schema 上下文。

### 路径 C — 元数据问答

"revenue 是怎么计算的？"→ RAG 检索相关 dbt 文档（模型描述、列测试、指标定义），LLM 直接回答 — 无需执行 SQL。

### 意图路由器

一个轻量级 LLM prompt，将每个问题分类到三条路径之一，并提取结构化参数（指标名、维度、时间范围）。系统**针对每个问题自适应选择策略**，而非一刀切地使用 Text-to-SQL。

---

## 为什么用 dbt Semantic Layer 而不是 MetricFlow？

dbt 语义层（`.yml` 定义 + `semantic_manifest.json`）提供了结构化的指标元数据，路径 A 引擎解析元数据构建确定性 SQL。这与 MetricFlow 原理相同，但：

- **无 pip 依赖冲突** — MetricFlow 的 PyPI 包已死（要求 `click<8.3`，而 dbt-core 1.11 要求 `click>=8.3`）
- **无需 dbt Cloud** — dbt 开源版只能定义/校验语义模型；查询引擎是 Cloud 付费功能。我们的自定义 SQL Builder 填补了这个开源空白
- **架构更简单** — 最后一公里聚合意味着语义 SQL 无需 JOIN，只是 `SELECT agg FROM table GROUP BY dim WHERE filter`

dbt 项目通过 `dbt parse` 生成 `semantic_manifest.json`，`MetricQueryBuilder` 在运行时解析它。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **三路径混合路由** | 指标查询 / Text-to-SQL / 元数据问答 |
| **SSE 流式推送** | 实时进度：分类中 → 构建 SQL → 执行中 → 解释中 |
| **确定性指标 SQL** | 指标查询零幻觉（解析 `semantic_manifest.json` 生成） |
| **LLM Text-to-SQL + RAG** | 探索性查询基于 dbt 元数据 Schema 上下文 |
| **SQL 安全层** | 关键词黑名单、仅允许 SELECT、防多语句、行数限制 |
| **自动序列化** | Decimal → float、datetime → ISO 字符串，确保 JSON 兼容 |
| **中文分词 RAG** | CJK 字符二元分词 + 拉丁词分词的关键词检索（无需 Embedding API） |
| **LLM 结果解释** | 自然语言摘要 + 图表类型推荐（柱状图/折线图/饼图/表格） |
| **LLM 厂商无关** | 兼容 DeepSeek、OpenAI 或任何 OpenAI 兼容 API |

---

## 项目结构

```
├── dbt_project/              # dbt 项目（星型模型 + 语义层）
│   ├── models/
│   │   ├── staging/          # stg_orders, stg_customers, stg_products, dates
│   │   └── marts/            # fact_orders (OBT宽表, 43列), dim_customers, dim_products
│   ├── seeds/                # raw_orders.csv (95行), raw_customers.csv, raw_products.csv
│   └── 语义层 →              # 2 个语义模型, 12 个指标, 15+ 个维度
│       semantic_manifest.json
│
├── backend/                  # FastAPI 后端 (Python 3.12)
│   ├── agent/
│   │   ├── router.py         # 意图分类器 (LLM)
│   │   └── orchestrator.py   # 三路径调度 + SSE 事件推送 + 结果解释
│   ├── semantic/
│   │   └── query_builder.py  # 路径 A: 从 semantic_manifest.json 确定性生成 SQL
│   ├── sql/
│   │   ├── security.py       # SQL 校验器 (仅允许 SELECT, 关键词黑名单)
│   │   ├── generator.py      # 路径 B: LLM Text-to-SQL
│   │   └── executor.py       # SQLAlchemy 只读执行器 + 序列化
│   ├── rag/
│   │   └── retriever.py      # 关键词检索器 (CJK 二元分词 + 拉丁词分词)
│   ├── metadata/
│   │   └── parser.py         # dbt manifest.json + semantic_manifest.json 解析器
│   └── llm/
│       └── client.py         # OpenAI 兼容 API 封装
│
├── frontend/                 # Streamlit 前端
│   ├── app.py                # 入口：聊天 UI, SSE 消费, 会话状态
│   ├── components/
│   │   ├── chat.py           # 富文本助手消息渲染
│   │   └── chart.py          # pyecharts 柱状图/折线图/饼图 → HTML 嵌入
│   └── utils/
│       └── api.py            # httpx SSE 客户端
│
├── scripts/
│   └── init_db.sql           # PostgreSQL Schema 初始化
│
└── requirements.txt
```

---

## 快速开始

### 环境要求

- Python 3.12+
- PostgreSQL 16+（或使用项目自带的 `docker-compose.yml`）
- dbt-core 1.11+
- LLM API Key（DeepSeek、OpenAI 或兼容 API）

### 1. 克隆项目

```bash
git clone https://github.com/QDD518/data-agent-dbt-hybrid.git
cd data-agent-dbt-hybrid
python -m venv venv
source venv/Scripts/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key 和 PostgreSQL 连接信息
```

必要的 `.env` 变量：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API 密钥 |
| `OPENAI_BASE_URL` | API 基础 URL（DeepSeek: `https://api.deepseek.com`） |
| `LLM_MODEL` | 对话模型名 |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PG 连接信息 |
| `POSTGRES_SCHEMA` | 默认 Schema（默认: `analytics`） |

### 3. 导入种子数据 & 构建 dbt 模型

```bash
cd dbt_project
dbt deps
dbt seed
dbt run
dbt parse          # 生成 manifest.json + semantic_manifest.json
cd ..
```

或使用 Docker PostgreSQL：
```bash
docker-compose up -d        # 启动 PG16, 创建 Schema
cd dbt_project && dbt seed && dbt run && dbt parse
```

### 4. 启动服务

**终端 1 — 后端：**
```bash
source venv/Scripts/activate
python -m backend.main
# → http://localhost:8000
```

**终端 2 — 前端：**
```bash
source venv/Scripts/activate
streamlit run frontend/app.py
# → http://localhost:8501
```

### 5. 开始提问

在 Streamlit 界面中尝试：

| 问题 | 路径 | 执行逻辑 |
|------|------|----------|
| 上月营收是多少？ | A | 从语义元数据确定性生成 SQL |
| 按城市分组的订单量 | A | 指标 + 维度，分组聚合 |
| 哪个城市的客户平均客单价最高？ | B | LLM 结合 RAG 上下文生成 ad-hoc SQL |
| 本月每天的收入趋势 | A | 指标 + 时间维度 + 日粒度 |
| revenue 是怎么计算的？ | C | RAG 检索指标定义，LLM 直接回答 |

---

## 语义层工作原理

### 在 dbt YAML 中定义指标

```yaml
# dbt_project/models/marts/metrics.yml
metrics:
  - name: total_revenue
    label: "Total Revenue"
    type: simple
    type_params:
      measure: revenue          # 引用 semantic_models.yml 中的 measure
    filter: "{{ dim('status') }} = 'Completed'"
```

### 定义语义模型（度量 + 维度）

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

### dbt parse → semantic_manifest.json → 确定性 SQL

```bash
dbt parse  # 校验并输出 manifest 文件
# 后端在启动时读取 semantic_manifest.json
# 路径 A 生成: SELECT SUM(net_amount) FROM analytics.fact_orders WHERE status = 'Completed'
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 数据转换 | dbt-core 1.11（staging 视图 → mart 表） |
| 语义层 | dbt Semantic Models + Metrics（YAML → `semantic_manifest.json`） |
| 查询生成 | 自定义 Python SQL Builder（路径 A）+ LLM（路径 B） |
| 数据库 | PostgreSQL 16（SQLAlchemy + psycopg2） |
| 后端 | FastAPI + SSE 流式传输 |
| 前端 | Streamlit + pyecharts |
| 大模型 | DeepSeek V4 / OpenAI / 兼容 API |
| RAG | 关键词重叠度检索（CJK 二元分词 + 拉丁词分词） |
| 安全 | SQL 关键词黑名单、仅允许 SELECT、行数限制、超时控制 |

---

## License

MIT — 详见 [LICENSE](LICENSE) 文件。

---

## 作者

**QDD518** — [github.com/QDD518](https://github.com/QDD518)

*作为开源 Chat BI 参考架构构建。欢迎贡献和反馈。*
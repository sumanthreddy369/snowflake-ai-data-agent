# Snowflake AI Data Agent

Project 1 of a two-part portfolio series (Snowflake + Databricks) proving that messy
raw data can be made **accurate and understandable to an AI agent** — not just piped
through a warehouse.

Domain used throughout this scaffold: **bank card transactions** — customers,
merchants, and transactions, with a fraud flag. Chosen over retail/healthcare for
current + future job-market demand: finance/banking is one of the largest DE/DA
hiring verticals, and it gives the Governance step (RBAC + masking of email/SSN) a
real regulatory reason to exist (PCI/GLBA-style controls) instead of feeling
decorative. The companion Databricks project (separate repo) covers healthcare —
unstructured clinical notes and streaming vitals — to show range across both
lakehouse styles and both top regulated industries.

## Pipeline

| Step | What happens | Tool | Where |
|---|---|---|---|
| 1. Ingest | Raw data lands automatically | Snowpipe | [`sql/01_ingest/snowpipe_setup.sql`](sql/01_ingest/snowpipe_setup.sql) |
| 2. Bronze | Raw data lands untouched | Snowflake raw tables | [`sql/02_bronze/bronze_tables.sql`](sql/02_bronze/bronze_tables.sql) |
| 3. Silver | Clean, dedupe, standardize | Streams + Tasks | [`sql/03_silver/streams_and_tasks.sql`](sql/03_silver/streams_and_tasks.sql) |
| 4. Gold | Business-ready star schema | dbt | [`dbt/models/marts`](dbt/models/marts) |
| 5. Semantic Layer | Define "spend", "fraud rate", "active customer" | Cortex Analyst YAML | [`semantic_layer/semantic_model.yaml`](semantic_layer/semantic_model.yaml) |
| 6. Agent | Ask questions in plain English | Cortex Analyst | Snowsight → Cortex Analyst, pointed at the semantic model |
| 7. Governance | Control who/what can access data | RBAC + Data Masking | [`sql/07_governance/rbac_and_masking.sql`](sql/07_governance/rbac_and_masking.sql) |
| 8. Validate | Check the agent's answers are correct | Manual SQL comparison | [`sql/08_validation/validation_queries.sql`](sql/08_validation/validation_queries.sql) |

## Layout

```
snowflake-ai-data-agent/
├── sql/
│   ├── 01_ingest/snowpipe_setup.sql        # stage + pipe definitions
│   ├── 02_bronze/bronze_tables.sql         # raw landing tables, untouched
│   ├── 03_silver/streams_and_tasks.sql     # dedupe/standardize via Streams+Tasks
│   ├── 07_governance/rbac_and_masking.sql  # roles, grants, masking policies
│   └── 08_validation/validation_queries.sql
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml.example
│   └── models/
│       ├── staging/     # 1:1 views over Silver (transactions, customers, merchants)
│       └── marts/       # Gold star schema (dim_customers, dim_merchants, dim_date, fct_transactions)
└── semantic_layer/
    └── semantic_model.yaml                 # Cortex Analyst semantic model
```

## Setup order

1. Run `sql/01_ingest` then `sql/02_bronze` to stand up the stage, pipe, and raw
   tables. Point the external stage at your actual bucket/container and a real or
   synthetic transactions dataset (e.g. Kaggle "Credit Card Fraud Detection",
   "Bank Marketing", or a Sparkov-style synthetic transaction generator).
2. Run `sql/03_silver` to create the Silver schema, the Stream on Bronze, and the
   Task that merges changes in on a schedule.
3. `cd dbt && dbt run` to build the Gold star schema from Silver (edit
   `profiles.yml.example` → `~/.dbt/profiles.yml` with your account first).
4. Upload `semantic_layer/semantic_model.yaml` in Snowsight (AI & ML → Cortex
   Analyst) pointed at the Gold tables, or reference it from a Streamlit/API app.
5. Run `sql/07_governance` to mask email/SSN and restrict roles before opening the
   agent up to real users — the ANALYST_AGENT role should never see raw PII.
6. Ask the agent a question, then run the matching query in
   `sql/08_validation/validation_queries.sql` and diff the numbers by hand.

## Status

Scaffold only — SQL and dbt models are structurally complete and runnable against a
real Snowflake account once you point the stage/sources at actual data. Swap in a
real transactions dataset before treating any numbers as meaningful.

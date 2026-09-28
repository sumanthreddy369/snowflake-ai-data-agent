# Restructure proposal

Suggestions only — nothing here has been applied. Each item is something
noticed while documenting the repo, not something silently fixed, per the
documentation task's ground rules.

## 1. Stale dbt project name

`dbt/dbt_project.yml`'s `name:` and `dbt/profiles.yml.example`'s profile key
are both `retail_agent_gold`. This is a leftover from the very first version
of this project (a generic retail-orders domain), which was later pivoted to
bank-card-transactions and then to the current real-time market-data domain.
The database name (`MARKET_AGENT`) was updated at each pivot; the dbt project
name was not.

**Suggestion**: rename to `market_agent_gold` in both files, and note in the
README's setup instructions that anyone with an existing `~/.dbt/profiles.yml`
needs to update their profile key to match. This is a one-line change in each
file but touches something every dbt user's local machine also has a copy
of, so it's flagged here rather than done automatically.

## 2. Two same-named `schemas.py` modules, loaded via `sys.path` hacks

`streaming/schemas.py` and `agent/schemas.py` are different modules with
different contents (ingestion-time records vs. query-time request/response
shapes). `ui/streamlit_app.py` and `api/main.py` both add `agent/` to
`sys.path` (`sys.path.insert(0, "../agent")`) to import from
`agent/cortex_agent_client.py` and `agent/cortex_client.py`. This works today
because nothing also adds `streaming/` to `sys.path` in the same process —
but if that ever happens (e.g. a future script that needs both a
`streaming.schemas.TradeRecord` and an `agent.schemas.CortexAnalystResponse`),
`import schemas` becomes ambiguous: Python resolves it to whichever directory
was inserted into `sys.path` first, silently.

**Suggestion**: either (a) rename the two files to be unambiguous
(`streaming_schemas.py`, `agent_schemas.py`), or (b) turn `streaming/` and
`agent/` into proper Python packages (add `__init__.py` to each, and to a
repo-root package or adjust `PYTHONPATH`) so imports become
`from agent.schemas import ...` / `from streaming.schemas import ...`
regardless of working directory, removing the `sys.path.insert` calls
entirely. (b) is the more durable fix but touches more files (every import
in `agent/`, `ui/`, `api/`).

## 3. `sql/` numbering has gaps and one out-of-order entry

Folders exist for `01_ingest`, `02_bronze`, `03_silver`, `04_documents`,
`07_governance`, `08_validation`, `09_guardrails`, `10_agent` — there is no
`05_` or `06_`. The README's pipeline table calls the Cortex Agent "step 6b,"
but its SQL lives in `sql/10_agent`, not `sql/06_agent`. The native Semantic
View (conceptually "step 5") lives outside `sql/` entirely, in
`semantic_layer/semantic_view.sql`.

**Suggestion, pick one**:
- Renumber `sql/10_agent` → `sql/06_agent` and add a `sql/05_semantic/`
  folder containing (or referencing) `semantic_layer/semantic_view.sql`, so
  the numbering is genuinely sequential; or
- Keep `semantic_layer/` and `agent/`-adjacent SQL as deliberately
  outside the numbered `sql/` sequence (they're not "batch pipeline steps"
  in the same sense as ingest/bronze/silver), and just close the `05`/`06`
  gap by renumbering `10_agent` down, with a comment at the top of `sql/`
  (or in the README) explaining that the numbering covers the batch/streaming
  pipeline only, not the query-time layer.

Either is defensible; the current state (numbering that looks sequential but
isn't) is the one option that's actually confusing.

## 4. `mcp_server.py` docstring claims a tool that doesn't exist

The module docstring says *"ask_market_data and search_market_news go
through the Cortex Agent / Cortex Search..."* — but the file defines three
tools: `ask_market_data`, `ask_market_data_direct`, and
`get_flagged_anomalies`. There is no `search_market_news` function. Search
happens only indirectly, as one of two tools the Cortex Agent may invoke
inside `ask_market_data`.

**Suggestion**: either add a real `search_market_news` tool that calls
Cortex Search directly (bypassing the agent's routing decision, mirroring
how `ask_market_data_direct` bypasses it for the analyst tool), or fix the
docstring to describe the three tools that actually exist. Not fixed here
since it's ambiguous which one the user actually wants.

## 5. Trained model artifacts have nowhere dedicated to live

`snowpark/train_anomaly_model.py` writes `anomaly_model.onnx` into the same
folder as the script (gitignored, so it doesn't get committed, but there's no
subfolder convention either). Fine for one model; if this grows to
per-symbol models or versioned exports, a flat folder will get hard to
navigate.

**Suggestion**: a `snowpark/models/` output directory once there's more than
one artifact — not urgent with a single model.

## 6. One flat `requirements.txt` for five independent surfaces

`requirements.txt` covers `streaming/`, `agent/`, `ui/`, `api/`, and
`snowpark/` in one file (grouped by comments). This means deploying, say,
just the Streamlit UI pulls in `scikit-learn`/`onnx`/`skl2onnx`, which it
never imports.

**Suggestion**: split into per-surface requirement files
(`requirements-streaming.txt`, `requirements-agent.txt`, etc.) once any of
these is actually deployed independently — premature before that, since it
adds bookkeeping (keeping shared deps like `pydantic` in sync) for no benefit
while everything still runs from one `pip install -r requirements.txt`.

## 7. `sys.path.insert(0, "../agent")` is resolved against CWD, not the file's location

`ui/streamlit_app.py` and `api/main.py` both insert `"../agent"` into
`sys.path` to import `cortex_agent_client`/`cortex_client`. This string is a
relative path resolved against the process's working directory at import
time — **not** relative to where `streamlit_app.py`/`main.py` themselves live
on disk. Verified directly: running `python ui/streamlit_app.py` from the
repo root raises `ModuleNotFoundError: No module named 'cortex_agent_client'`;
the same import only succeeds when the working directory is `ui/` itself
(same for `api/`). The README documents the correct invocation (`cd ui/` or
`cd api/` first), but the scripts themselves give no error-message hint about
*why* it fails if you get the CWD wrong — it just looks like a missing
dependency.

**Suggestion**: replace the relative `sys.path.insert` with something that
resolves relative to the script's own file location —
`sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))`
— so the script works regardless of the caller's working directory. This is
a small, low-risk change since it only affects import resolution, not
behavior, but it touches two files so it's listed here rather than applied.

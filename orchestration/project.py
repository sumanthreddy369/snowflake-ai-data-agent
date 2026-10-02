"""Paths and the dbt project handle shared by every orchestration module."""

import os
from pathlib import Path

from dagster_dbt import DbtProject

# Resolved from this file's location, not the caller's working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

dbt_project = DbtProject(
    project_dir=REPO_ROOT / "dbt",
    # dbt's own convention: DBT_PROFILES_DIR if set, else ~/.dbt (profiles.yml
    # holds credentials and is gitignored, so it never lives in dbt/).
    profiles_dir=os.getenv("DBT_PROFILES_DIR", str(Path.home() / ".dbt")),
    target=os.getenv("DBT_TARGET", "dev"),
)
# Under `dagster dev`, re-parse the dbt project on load so the asset graph
# tracks model edits without a manual `dbt parse`. Elsewhere (CI, deploy) the
# manifest must already exist -- CI runs `dbt parse` before loading.
dbt_project.prepare_if_dev()

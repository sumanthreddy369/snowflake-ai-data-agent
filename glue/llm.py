"""
Model client for the glue agents: Claude on Google Vertex AI (Model Garden).

Why Vertex AI: the pipeline already runs on GCP (bucket, Pub/Sub), so calling
Claude through the same project keeps billing, quotas, IAM and audit logs in
one cloud -- how companies typically consume models, instead of a separate
vendor account. Snowflake Cortex stays the model for analysts' questions,
because those models run inside Snowflake and the data never leaves it.

Off by default. Model calls cost money per token, so nothing here sends a
request unless GLUE_LLM_ENABLED=1. Every call the glue agents make must go
through the guardrail gateway (docs/glue-and-guardrails.md), which adds
budgets, approvals and the audit log -- this module only builds the client.

Setup (once, by a human):
  1. `terraform apply` in infra/terraform (enables the Vertex AI API and
     creates the market-agent-glue service account).
  2. In the GCP console, Vertex AI -> Model Garden -> Claude: enable the model
     (this includes accepting Anthropic's terms).
  3. Authenticate: `gcloud auth application-default login`, or set
     GOOGLE_APPLICATION_CREDENTIALS to the glue service account's key.

Env vars: GCP_PROJECT (required), GLUE_VERTEX_REGION (default "global"),
GLUE_MODEL (default "claude-opus-5-5"), GLUE_LLM_ENABLED ("1" to allow calls).

`python -m glue.llm --check` prints the configuration and builds the client
without sending any request (no cost).
"""

import argparse
import logging
import os

from anthropic import AnthropicVertex

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("glue.llm")

DEFAULT_MODEL = "claude-opus-5-5"
# "global" lets Vertex route to available capacity; set a region instead if
# data-residency rules require one.
DEFAULT_REGION = "global"


class LlmDisabledError(RuntimeError):
    """Raised when code asks for a client while model calls are switched off."""


def settings() -> dict:
    return {
        "project_id": os.getenv("GCP_PROJECT"),
        "region": os.getenv("GLUE_VERTEX_REGION", DEFAULT_REGION),
        "model": os.getenv("GLUE_MODEL", DEFAULT_MODEL),
        "enabled": os.getenv("GLUE_LLM_ENABLED") == "1",
    }


def get_client(require_enabled: bool = True) -> AnthropicVertex:
    """Build the Vertex AI client. Refuses unless calls are explicitly enabled,
    so a stray import can't start spending."""
    cfg = settings()
    if require_enabled and not cfg["enabled"]:
        raise LlmDisabledError("Model calls are off. Set GLUE_LLM_ENABLED=1 once Vertex AI is set up and budgeted.")
    if not cfg["project_id"]:
        raise ValueError("Set GCP_PROJECT to the project where Claude is enabled in Model Garden.")
    return AnthropicVertex(project_id=cfg["project_id"], region=cfg["region"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Print config and build the client; sends nothing.")
    args = parser.parse_args()
    if not args.check:
        parser.error("only --check is available; model calls happen through the guardrail gateway")
    cfg = settings()
    logger.info("project=%s region=%s model=%s calls_enabled=%s",
                cfg["project_id"], cfg["region"], cfg["model"], cfg["enabled"])
    if cfg["project_id"]:
        get_client(require_enabled=False)
        logger.info("Vertex AI client built (no request sent).")
    else:
        logger.info("GCP_PROJECT not set; client not built.")


if __name__ == "__main__":
    main()

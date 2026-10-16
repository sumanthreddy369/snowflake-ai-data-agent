"""
One-time setup for the Snowflake CI/CD pipelines. Run it yourself, once:

    python cicd/bootstrap_ci.py

It does the three things that need an admin's hands:
  1. Creates role CI_RUNNER and service user CI_DEPLOY in Snowflake
     (sql/12_cicd/ci_deploy_user.sql, with the CI public key filled in),
     using your own [market_agent] connection, and checks the key fingerprint.
  2. Stores two GitHub secrets: SNOWFLAKE_ACCOUNT, and SNOWFLAKE_CI_PRIVATE_KEY
     piped straight from the key file to `gh` (never printed).
  3. Creates the GitHub environment "production" with you as required reviewer,
     so every production deploy waits for your approval.
Then it logs in as CI_DEPLOY to prove the key works.
"""

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import snowflake.connector

REPO_ROOT = Path(__file__).resolve().parent.parent
KEY_DIR = Path.home() / ".snowflake" / "keys"
PRIVATE_KEY = KEY_DIR / "ci_deploy_rsa_key.p8"
PUBLIC_KEY = KEY_DIR / "ci_deploy_rsa_key.pub"


def gh(*args, stdin=None) -> str:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True).stdout


def main():
    pub_body = "".join(l for l in PUBLIC_KEY.read_text().splitlines() if "-----" not in l)
    expected_fp = "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(pub_body)).digest()).decode()

    print("1. Snowflake: role CI_RUNNER + user CI_DEPLOY")
    sql = (REPO_ROOT / "sql/12_cicd/ci_deploy_user.sql").read_text().replace("<public-key-body>", pub_body)
    with snowflake.connector.connect(connection_name="market_agent", role="ACCOUNTADMIN") as conn:
        conn.execute_string(sql)
        account = conn.cursor().execute("SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME()").fetchone()[0]
        desc = {r[0]: r[1] for r in conn.cursor().execute("DESC USER CI_DEPLOY")}
    if desc.get("RSA_PUBLIC_KEY_FP") != expected_fp:
        sys.exit(f"   key fingerprint mismatch: {desc.get('RSA_PUBLIC_KEY_FP')} != {expected_fp}")
    print(f"   ok, key fingerprint {expected_fp}")

    print("2. GitHub secrets")
    gh("secret", "set", "SNOWFLAKE_ACCOUNT", "--body", account)
    gh("secret", "set", "SNOWFLAKE_CI_PRIVATE_KEY", stdin=PRIVATE_KEY.read_text())
    print("   ok:", ", ".join(gh("secret", "list", "--json", "name", "-q", ".[].name").split()))

    print("3. GitHub environment 'production' with a required reviewer")
    me = json.loads(gh("api", "user"))["id"]
    gh("api", "-X", "PUT", "repos/{owner}/{repo}/environments/production", "--input", "-",
       stdin=json.dumps({"reviewers": [{"type": "User", "id": me}]}))
    print("   ok")

    print("4. Test login as CI_DEPLOY")
    with snowflake.connector.connect(account=account, user="CI_DEPLOY", authenticator="SNOWFLAKE_JWT",
                                     private_key_file=str(PRIVATE_KEY), role="CI_RUNNER",
                                     warehouse="COMPUTE_WH") as conn:
        user, role = conn.cursor().execute("SELECT CURRENT_USER(), CURRENT_ROLE()").fetchone()
    print(f"   ok, connected as {user} / {role}")
    print("\nDone. CI/CD is ready.")


if __name__ == "__main__":
    main()

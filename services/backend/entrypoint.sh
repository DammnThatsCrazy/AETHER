#!/bin/sh
# Entrypoint for the aether-backend container.
#
# When running on ECS with RDS manage_master_user_password, the task definition
# injects DATABASE_URL_SECRET as an AWS-managed JSON blob containing the database
# credentials. AWS-managed RDS secrets do not include the cluster endpoint or
# database name, so ECS also injects DATABASE_HOST, DATABASE_PORT, and
# DATABASE_NAME from the canonical Terraform database outputs.
#
# The application reads DATABASE_URL as a postgresql:// connection string.
# This shim bridges the two: if DATABASE_URL_SECRET is present and DATABASE_URL
# is not already set, it constructs and exports DATABASE_URL then execs the CMD.
#
# When DATABASE_URL is already set (local Docker Compose, CI, etc.) this script
# is a transparent no-op.
set -e

if [ -n "$DATABASE_URL_SECRET" ] && [ -z "$DATABASE_URL" ]; then
  export DATABASE_URL
  DATABASE_URL=$(python3 - <<'PYEOF'
import json, os, urllib.parse
d = json.loads(os.environ["DATABASE_URL_SECRET"])
pw = urllib.parse.quote_plus(d["password"])
host = d.get("host") or os.environ.get("DATABASE_HOST")
if not host:
    raise SystemExit("DATABASE_URL_SECRET does not contain host and DATABASE_HOST is unset")
port = d.get("port") or os.environ.get("DATABASE_PORT", "5432")
user = d["username"]
dbname = d.get("dbname") or d.get("dbName") or os.environ.get("DATABASE_NAME", "aether")
print(f"postgresql://{user}:{pw}@{host}:{port}/{dbname}")
PYEOF
  )
fi

# Opt-in migration step: /v1/ready requires alembic current == head, but
# nothing else in the deploy path applies migrations. Set RUN_MIGRATIONS=1 in
# the task environment to upgrade before the app starts. Failures abort the
# container (set -e) rather than booting an unready service.
if [ "$RUN_MIGRATIONS" = "1" ]; then
  echo "RUN_MIGRATIONS=1 — applying alembic migrations to head..."
  alembic upgrade head
fi

exec "$@"

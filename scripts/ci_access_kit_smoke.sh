#!/usr/bin/env bash
# Access Kit container smoke (moved from access-kit-container.yml; run by CI V2 check `access-kit-container`).
set -euo pipefail
docker run --detach --name access-kit-container-check \
  --publish 127.0.0.1:18080:8080 \
  --env AETHER_API_URL=https://api.aether.io \
  --env AETHER_MCP_ALLOWED_HOSTS=localhost \
  aether-access-kit:ci
cleanup() {
  docker logs access-kit-container-check || true
  docker rm --force access-kit-container-check >/dev/null 2>&1 || true
}
trap cleanup EXIT

ready=false
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error \
    --header 'Host: localhost' \
    http://127.0.0.1:18080/readyz >/tmp/access-kit-ready.json; then
    ready=true
    break
  fi
  sleep 2
done
test "$ready" = true || {
  echo 'Access Kit container did not become ready.' >&2
  exit 1
}
jq -e '.status == "ready" and .path == "/v1/access/mcp"' \
  /tmp/access-kit-ready.json >/dev/null
curl --fail --silent --show-error \
  --header 'Host: localhost' \
  http://127.0.0.1:18080/healthz \
  | jq -e '.status == "ok"' >/dev/null
docker run --rm --entrypoint node aether-access-kit:ci \
  ./bin/aether.js --help >/dev/null

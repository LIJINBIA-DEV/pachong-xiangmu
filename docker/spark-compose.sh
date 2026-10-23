#!/bin/sh
# Keep the optional private Jev socket enabled during future app updates.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
if grep -q '^TYPESAFE_RELAY_TOKEN=.' .env.spark; then
    exec docker compose --env-file .env.spark -f compose.spark.yaml -f compose.spark-jev-relay.yaml "$@"
fi
exec docker compose --env-file .env.spark -f compose.spark.yaml "$@"

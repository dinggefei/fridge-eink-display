#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

if [[ ! -f .env ]]; then
  echo "Missing $script_dir/.env" >&2
  echo "Copy production.env.example to .env and fill every value." >&2
  exit 1
fi

docker compose build --pull backend
docker compose up -d
docker compose ps

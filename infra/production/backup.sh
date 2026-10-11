#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backup_dir="$script_dir/backups"
compose_file="$script_dir/compose.yml"

if [[ ! -f "$script_dir/.env" ]]; then
  echo "Missing $script_dir/.env" >&2
  exit 1
fi

set -a
source "$script_dir/.env"
set +a

mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
umask 077

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$backup_dir/rfm-$timestamp.dump"

docker compose \
  --env-file "$script_dir/.env" \
  -f "$compose_file" \
  exec -T postgres \
  pg_dump --format=custom --no-owner \
  --username "$POSTGRES_USER" "$POSTGRES_DB" > "$output"

find "$backup_dir" -type f -name 'rfm-*.dump' -mtime +14 -delete
echo "Backup written to $output"

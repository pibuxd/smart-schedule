#!/bin/sh
# Deploys the newest code from GitHub on the VPS: backup, pull, rebuild, restart.
# Migrations run when the api container starts. Run as root: /opt/grafikomat/deploy/update.sh
set -eu

cd "$(dirname "$0")/.."
./deploy/backup.sh
git pull --ff-only
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
docker compose ps

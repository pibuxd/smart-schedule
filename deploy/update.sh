#!/bin/sh
# Deploys the newest code from GitHub on the VPS: backup, pull, rebuild, restart.
# Migrations run when the api container starts. Run as root: /opt/grafikomat/deploy/update.sh
set -eu

# Inside main() so the whole file is read before it runs: `git pull` may replace this script mid-run.
main() {
cd "$(dirname "$0")/.."
./deploy/backup.sh
git pull --ff-only
docker compose up -d --build --remove-orphans

# The update counts only when the API answers again.
tries=0
until docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -gt 36 ]; then
    echo "The API did not come back after the update. Check: docker compose logs api" >&2
    exit 1
  fi
  sleep 5
done

docker image prune -f >/dev/null
# Remember what is running, for deploy/auto-update.sh.
git rev-parse HEAD > .deployed-commit
docker compose ps
}

main "$@"

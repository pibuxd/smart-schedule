#!/bin/sh
# Run from cron every few minutes on the VPS: when GitHub has a newer commit on the deployed branch,
# run deploy/update.sh. Installed by deploy/setup-server.sh (/etc/cron.d/grafikomat-auto-update);
# output goes to /var/log/grafikomat-update.log. To switch it off, remove that cron file.
set -eu

cd "$(dirname "$0")/.."

# One update at a time; a run that starts while another is still building just leaves.
exec 9> /var/lock/grafikomat-update.lock
flock -n 9 || exit 0

branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$branch"
latest="$(git rev-parse "origin/$branch")"

deployed="$(cat .deployed-commit 2>/dev/null || git rev-parse HEAD)"
[ "$latest" = "$deployed" ] && exit 0
# A version that failed to deploy is not retried; the next commit (the fix) is.
[ "$latest" = "$(cat .deploy-failed-commit 2>/dev/null || true)" ] && exit 0

echo "$(date -Iseconds) new version $latest (running: $deployed), updating"
if ./deploy/update.sh; then
  rm -f .deploy-failed-commit
  echo "$(date -Iseconds) updated to $latest"
else
  echo "$latest" > .deploy-failed-commit
  echo "$(date -Iseconds) UPDATE FAILED for $latest; the service keeps running the previous containers if they still work" >&2
  exit 1
fi

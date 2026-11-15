#!/bin/sh
# Run from cron every few minutes on the VPS: when GitHub has a newer commit on the deployed branch,
# run deploy/update.sh. Installed by deploy/setup-server.sh (/etc/cron.d/grafikomat-auto-update);
# output goes to /var/log/grafikomat-update.log. To switch it off, remove that cron file.
set -eu

# Inside main() so the whole file is read before it runs: `git pull` may replace this script mid-run.
main() {
cd "$(dirname "$0")/.."

# One update at a time; a run that starts while another is still building just leaves.
exec 9> /var/lock/grafikomat-update.lock
flock -n 9 || exit 0

branch="$(git rev-parse --abbrev-ref HEAD)"
git fetch --quiet origin "$branch"
latest="$(git rev-parse "origin/$branch")"

# What is running now. Without the marker (server set up by an older script) it is the checked-out commit.
[ -f .deployed-commit ] || git rev-parse HEAD > .deployed-commit
deployed="$(cat .deployed-commit)"
[ "$latest" = "$deployed" ] && exit 0

# A version that failed is tried once more (the cause may have been the network, not the code).
# After the second failure it is left alone until a newer commit (the fix) arrives.
failed_commit=""
failed_times=0
if [ -f .deploy-failed-commit ]; then
  read -r failed_commit failed_times < .deploy-failed-commit || true
fi
if [ "$latest" = "$failed_commit" ]; then
  [ "${failed_times:-1}" -ge 2 ] && exit 0
else
  failed_times=0
fi

# Optional: DEPLOY_ALERT_URL in .env gets a short text message (HTTP POST) when an update fails for good.
alert() {
  url="$(sed -n 's/^DEPLOY_ALERT_URL=//p' .env | head -n 1)"
  [ -n "$url" ] || return 0
  curl -fsS --max-time 15 -H "Title: Grafikomat" -d "$1" "$url" >/dev/null 2>&1 || echo "The alert could not be sent." >&2
}

echo "$(date -Iseconds) new version $latest (running: $deployed), updating"
if ./deploy/update.sh; then
  rm -f .deploy-failed-commit
  echo "$(date -Iseconds) updated to $latest"
else
  failed_times=$((failed_times + 1))
  echo "$latest $failed_times" > .deploy-failed-commit
  echo "$(date -Iseconds) UPDATE FAILED for $latest (attempt $failed_times of 2)" >&2
  if [ "$failed_times" -ge 2 ]; then
    alert "Wdrożenie nowej wersji nie udało się dwa razy (${latest%"${latest#???????}"}). Sprawdź serwer: tail -n 50 /var/log/grafikomat-update.log"
  fi
  exit 1
fi
}

main "$@"

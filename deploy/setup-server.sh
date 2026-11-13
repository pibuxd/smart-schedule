#!/bin/sh
# First-time setup of Grafikomat on a fresh Debian or Ubuntu VPS. Run as root on the server:
#
#   curl -fsSL https://raw.githubusercontent.com/pibuxd/smart-schedule/main/deploy/setup-server.sh | sh
#   curl -fsSL .../deploy/setup-server.sh | sh -s -- grafikomat.pl      # with your own domain
#
# Set GRAFIKOMAT_AUTO_UPDATE=0 to skip automatic updates.
# Safe to run again: it keeps an existing .env (and so the secrets and the database) and only
# rebuilds and restarts the containers. Without a domain it uses <ip>.sslip.io, a free name that
# points at the server's address, so HTTPS and logging in work from the first minute.
# Details: docs/deploy.md
set -eu

# Everything is inside main() so the whole script is read before anything runs (it is piped from curl).
main() {
DOMAIN="${1:-}"
REPO_URL="${GRAFIKOMAT_REPO:-https://github.com/pibuxd/smart-schedule.git}"
BRANCH="${GRAFIKOMAT_BRANCH:-main}"
APP_DIR="${GRAFIKOMAT_DIR:-/opt/grafikomat}"

say() { printf '\n==> %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run this script as root." >&2; exit 1; }

say "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git openssl cron util-linux >/dev/null

if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null

# Building the frontend and running the solver need headroom on a small server.
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ] && [ ! -e /swapfile ]; then
  say "Adding 2 GB of swap"
  if fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile; then
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  else
    rm -f /swapfile
    echo "Swap could not be added; continuing without it."
  fi
fi

say "Fetching the code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" merge --quiet --ff-only "origin/$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ -f .env ]; then
  say "Keeping the existing .env"
  if [ -n "$DOMAIN" ]; then
    echo "To change the domain edit SITE_ADDRESS, DJANGO_ALLOWED_HOSTS and DJANGO_CSRF_TRUSTED_ORIGINS in $APP_DIR/.env"
  fi
else
  if [ -z "$DOMAIN" ]; then
    ip_address="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n 1)"
    case "$ip_address" in
      ''|10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*)
        ip_address="$(curl -fsS4 --max-time 10 https://api.ipify.org)" ;;
    esac
    DOMAIN="$(echo "$ip_address" | tr . -).sslip.io"
  fi
  say "Writing .env for $DOMAIN (new secrets are generated here and stay on this server)"
  umask 077
  sed -e "s|^SITE_ADDRESS=.*|SITE_ADDRESS=$DOMAIN|" \
      -e "s|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=$DOMAIN,localhost|" \
      -e "s|^DJANGO_CSRF_TRUSTED_ORIGINS=.*|DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN|" \
      -e "s|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=$(openssl rand -hex 32)|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" \
      .env.production.example > .env
  umask 022
fi
if grep -q '^[A-Z_]*=.*CHANGE-ME' .env; then
  echo "$APP_DIR/.env still contains CHANGE-ME values. Fill them in and run this script again." >&2
  exit 1
fi
site="$(sed -n 's/^SITE_ADDRESS=//p' .env)"

say "Building and starting the containers (the first time takes a few minutes)"
docker compose up -d --build --remove-orphans

say "Waiting for the application"
tries=0
until docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1; do
  tries=$((tries + 1))
  if [ "$tries" -gt 60 ]; then
    echo "The API did not start. Check: cd $APP_DIR && docker compose logs api" >&2
    exit 1
  fi
  sleep 5
done

say "Scheduling the daily database backup (03:15, kept 14 days in /var/backups/grafikomat)"
cat > /etc/cron.d/grafikomat-backup <<CRON
15 3 * * * root $APP_DIR/deploy/backup.sh >> /var/log/grafikomat-backup.log 2>&1
CRON
chmod 644 /etc/cron.d/grafikomat-backup
git rev-parse HEAD > .deployed-commit

if [ "${GRAFIKOMAT_AUTO_UPDATE:-1}" = "1" ]; then
  say "Switching on automatic updates (every 5 minutes the server checks GitHub for a new version)"
  cat > /etc/cron.d/grafikomat-auto-update <<CRON
*/5 * * * * root $APP_DIR/deploy/auto-update.sh >> /var/log/grafikomat-update.log 2>&1
CRON
  chmod 644 /etc/cron.d/grafikomat-auto-update
fi

cat <<DONE

Grafikomat is running: https://$site
(the HTTPS certificate can take a minute after the first start)

Next steps, all from $APP_DIR:
  docker compose exec api python manage.py createsuperuser      # admin panel: https://$site/api/admin/
  docker compose exec api python manage.py seed_demo            # optional demo data
  docker compose logs api --since 5m | grep "SMS to"            # read a login code (no SMS gateway yet)
  New versions merged to the main branch are deployed automatically within about 10 minutes
  (log: /var/log/grafikomat-update.log; by hand: ./deploy/update.sh).
DONE
}

main "$@" </dev/null

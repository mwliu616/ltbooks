#!/usr/bin/env bash
# ============================================================================
# LtBooks Ver 1.0 clean installer
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
#
# Automatic mode installs the operating-system services and configures HTTPS.
# Manual mode installs application files, dependencies and an empty database,
# leaving the Web/SSL/service configuration to an existing hosting panel.
# No existing business database is overwritten.
# ============================================================================
set -euo pipefail

MODE="auto"
if [[ "${1:-}" == "--manual" ]]; then MODE="manual"; shift; fi
if [[ "${1:-}" == "--auto" ]]; then MODE="auto"; shift; fi
[[ $# -eq 0 ]] || { printf 'Unknown arguments: %s\n' "$*" >&2; exit 2; }

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${LTBOOKS_APP_DIR:-/opt/ltbooks}"
WEB_ROOT="${LTBOOKS_WEB_ROOT:-/var/www/ltbooks}"
UPLOAD_DIR="${LTBOOKS_UPLOAD_DIR:-/var/lib/ltbooks/uploads}"
BACKUP_DIR="${LTBOOKS_BACKUP_DIR:-/var/backups/ltbooks}"
DB_HOST="${LTBOOKS_DB_HOST:-127.0.0.1}"
DB_PORT="${LTBOOKS_DB_PORT:-3306}"
DB_NAME="${LTBOOKS_DB_NAME:-ltbooks}"
DB_USER="${LTBOOKS_DB_USER:-ltbooks_app}"
DOMAIN="${LTBOOKS_DOMAIN:-finance.example.com}"
SSL_EMAIL="${LTBOOKS_SSL_EMAIL:-}"
SSL_MODE="${LTBOOKS_SSL_MODE:-auto}" # auto / letsencrypt / selfsigned / off
RUN_USER="ltbooks"
RUN_GROUP="ltbooks"
WEB_USER="${LTBOOKS_WEB_USER:-}"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

is_ipv4() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }

# Automatic mode needs two interactive inputs: the domain or server IP, and an
# optional certificate email. When they are not provided through LTBOOKS_DOMAIN /
# LTBOOKS_SSL_EMAIL, ask on a terminal; without a terminal fail or use self-signed.
if [[ "$MODE" == "auto" && -z "${LTBOOKS_DOMAIN:-}" ]]; then
  if [[ -t 0 ]]; then
    printf '\nDomain name or server IP (for example finance.example.com or 203.0.113.10):\n> '
    read -r DOMAIN_INPUT
    [[ -n "${DOMAIN_INPUT:-}" ]] || die "The domain name or IP address cannot be empty"
    DOMAIN="$DOMAIN_INPUT"
  else
    die "Automatic installation needs a domain or IP: set LTBOOKS_DOMAIN or run in an interactive terminal"
  fi
fi

# A public certificate cannot be issued for a bare IP, so use self-signed HTTPS.
if is_ipv4 "$DOMAIN" && [[ -z "${LTBOOKS_SSL_MODE:-}" ]]; then
  SSL_MODE="selfsigned"
fi

# For domain deployments ask once more for the certificate email: Let's Encrypt
# needs it for expiry notices. A blank value keeps the self-signed certificate;
# an explicit letsencrypt mode requires an address.
if [[ "$MODE" == "auto" && "$SSL_MODE" != "off" && "$SSL_MODE" != "selfsigned" ]] \
   && ! is_ipv4 "$DOMAIN" && [[ "$DOMAIN" != *"example.com" && "$DOMAIN" != "_" ]] \
   && [[ -z "$SSL_EMAIL" ]]; then
  if [[ -t 0 ]]; then
    printf '\nEmail address for Let'"'"'s Encrypt certificate notices (leave blank for a self-signed certificate):\n> '
    read -r SSL_EMAIL_INPUT
    SSL_EMAIL="${SSL_EMAIL_INPUT:-}"
  fi
  if [[ "$SSL_MODE" == "letsencrypt" && -z "$SSL_EMAIL" ]]; then
    die "LTBOOKS_SSL_MODE=letsencrypt requires an email: set LTBOOKS_SSL_EMAIL or run interactively"
  fi
fi
[[ -z "$SSL_EMAIL" || "$SSL_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] \
  || die "Invalid SSL email: $SSL_EMAIL"

for path in "$APP_DIR" "$WEB_ROOT" "$UPLOAD_DIR" "$BACKUP_DIR"; do
  [[ "$path" =~ ^/[A-Za-z0-9_./-]+$ ]] || die "Paths must be absolute and contain no spaces: $path"
done
[[ "$DB_NAME" =~ ^[A-Za-z0-9_]+$ ]] || die "Invalid database name"
[[ "$DB_USER" =~ ^[A-Za-z0-9_]+$ ]] || die "Invalid database user"
[[ "$DB_PORT" =~ ^[0-9]+$ ]] || die "Invalid database port"
[[ "$DOMAIN" =~ ^[A-Za-z0-9._-]+$ || "$DOMAIN" == "_" ]] || die "Invalid domain"
[[ "$SSL_MODE" =~ ^(auto|letsencrypt|selfsigned|off)$ ]] || die "Invalid LTBOOKS_SSL_MODE"
for required in backend/api.py frontend/index.php sql/01-schema.sql sql/02-master-data.sql; do
  [[ -f "$PACKAGE_ROOT/$required" ]] || die "Incomplete package: missing $required"
done

if [[ "$MODE" == "auto" ]]; then
  [[ "$(id -u)" == "0" ]] || die "Automatic installation must run as root"
  command -v apt-get >/dev/null 2>&1 || die "Automatic mode supports Debian/Ubuntu (apt); use install-manual.sh on other systems"
  say "1/9 Installing Web, SSL, PHP, Python, database, OCR and PDF dependencies"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
    nginx mariadb-server mariadb-client php-fpm php-cli php-mysql php-curl \
    php-mbstring php-xml php-gd php-zip python3 python3-venv python3-pip \
    rsync openssl ca-certificates curl nodejs poppler-utils tesseract-ocr \
    tesseract-ocr-chi-sim tesseract-ocr-eng fonts-noto-cjk libpango-1.0-0 \
    libpangoft2-1.0-0 libcairo2 libffi-dev certbot python3-certbot-nginx cron
  systemctl enable --now mariadb cron nginx
else
  say "1/9 Checking the existing hosting environment (no system packages changed)"
fi

node_supported() {
  command -v node >/dev/null 2>&1 && \
    node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' >/dev/null 2>&1
}
if [[ "$MODE" == "auto" ]] && ! node_supported; then
  say "Installing a supported Node.js 20 runtime"
  NODE_SETUP="$(mktemp)"
  curl --fail --silent --show-error --location https://deb.nodesource.com/setup_20.x -o "$NODE_SETUP"
  bash "$NODE_SETUP"
  rm -f "$NODE_SETUP"
  apt-get install -y --no-install-recommends nodejs
fi

for command_name in php python3 mysql mysqldump rsync openssl node; do
  command -v "$command_name" >/dev/null 2>&1 || die "Missing command: $command_name"
done
if [[ "$MODE" == "auto" ]]; then
  for command_name in nginx certbot; do command -v "$command_name" >/dev/null 2>&1 || die "Missing command: $command_name"; done
fi
php -r 'exit(version_compare(PHP_VERSION,"8.1","<")?1:0);' || die "PHP 8.1 or newer is required"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' || die "Python 3.10 or newer is required"
node_supported || die "Node.js 18 or newer is required"
php -r '$m=["curl","mbstring","xml"];foreach($m as $x){if(!extension_loaded($x)){fwrite(STDERR,"Missing PHP extension: $x\n");exit(1);}}'

if [[ "$MODE" == "auto" ]]; then
  if ! getent group ltbooks >/dev/null; then groupadd --system ltbooks; fi
  if ! id ltbooks >/dev/null 2>&1; then
    useradd --system --gid ltbooks --home-dir "$APP_DIR" --shell /usr/sbin/nologin ltbooks
  fi
  if [[ -z "$WEB_USER" ]]; then
    for candidate in www-data nginx apache www; do
      if id "$candidate" >/dev/null 2>&1; then WEB_USER="$candidate"; break; fi
    done
  fi
  WEB_USER="${WEB_USER:-$(id -un)}"
  POOL_GROUP="$RUN_GROUP"
  usermod -a -G ltbooks "$WEB_USER"
else
  RUN_USER="$(id -un)"
  RUN_GROUP="$(id -gn)"
  # A root-run panel installation must use an existing Web account for PHP-FPM;
  # non-root installations default to the current account and never create users.
  if [[ -z "$WEB_USER" && "$(id -u)" == "0" ]]; then
    for candidate in www-data nginx apache www; do
      if id "$candidate" >/dev/null 2>&1; then WEB_USER="$candidate"; break; fi
    done
  fi
  WEB_USER="${WEB_USER:-$RUN_USER}"
  POOL_GROUP="$(id -gn "$WEB_USER")"
fi

MYSQL_ROOT=(mysql --protocol=socket -uroot)
if [[ -n "${LTBOOKS_DB_ROOT_PASSWORD:-}" ]]; then
  MYSQL_ROOT=(mysql -h"$DB_HOST" -P"$DB_PORT" -uroot)
  export MYSQL_PWD="$LTBOOKS_DB_ROOT_PASSWORD"
fi
mysql_root() { "${MYSQL_ROOT[@]}" "$@"; }

say "2/9 Protecting existing data and preparing database credentials"
existing_tables="$(mysql_root -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME'" 2>/dev/null || printf '0')"
if [[ "$existing_tables" != "0" && ! -f "$APP_DIR/.ltbooks-owned" ]]; then
  die "Database $DB_NAME already contains tables. Choose a new LTBOOKS_DB_NAME; no data was changed"
fi
mkdir -p "$APP_DIR" "$WEB_ROOT" "$UPLOAD_DIR" "$BACKUP_DIR"
if [[ ! -f "$APP_DIR/.ltbooks-owned" ]]; then
  printf 'LtBooks clean installation\nDatabase: %s\nCreated: %s\n' "$DB_NAME" "$(date -u +%FT%TZ)" > "$APP_DIR/.ltbooks-owned"
fi

read_env() {
  local wanted="$1" key value
  while IFS='=' read -r key value; do
    if [[ "$key" == "$wanted" ]]; then printf '%s' "$value"; return 0; fi
  done < "$APP_DIR/.env"
  return 1
}

if [[ ! -f "$APP_DIR/.env" ]]; then
  DB_PASSWORD="${LTBOOKS_DB_PASSWORD:-$(openssl rand -hex 24)}"
  API_TOKEN="$(openssl rand -hex 32)"
  NODE_BIN="$(command -v node)"
  cat > "$APP_DIR/.env" <<EOF
# LtBooks Ver 1.0 runtime configuration; keep this file private.
LEDU_DB_HOST=$DB_HOST
LEDU_DB_PORT=$DB_PORT
LEDU_DB_NAME=$DB_NAME
LEDU_DB_USER=$DB_USER
LEDU_DB_PASSWORD=$DB_PASSWORD
LEDU_API_HOST=127.0.0.1
LEDU_API_PORT=8099
LEDU_API_TOKEN=$API_TOKEN
LEDU_WEB_ROOT=$WEB_ROOT
LEDU_WEB_ASSETS_DIR=$WEB_ROOT/assets
LEDU_STORAGE_DIR=$APP_DIR/storage
LEDU_UPLOAD_DIR=$UPLOAD_DIR
LEDU_UPLOAD_DIRS=$UPLOAD_DIR:$APP_DIR/storage/uploads
LEDU_BACKUP_DIR=$BACKUP_DIR
LEDU_BACKUP_KEEP=180
LEDU_BACKUP_LOCK=$APP_DIR/storage/backup.lock
LEDU_AGENT_PRESET=$APP_DIR/agent
LEDU_NODE_BIN=$NODE_BIN
LEDU_LLM_BASE=${LEDU_LLM_BASE:-https://api.deepseek.com}
LEDU_LLM_MODEL=${LEDU_LLM_MODEL:-deepseek-chat}
LEDU_LLM_API_KEY=${LEDU_LLM_API_KEY:-}
LEDU_VISION_API_KEY=${LEDU_VISION_API_KEY:-}
LEDU_SMTP_HOST=
LEDU_SMTP_PORT=465
LEDU_SMTP_SECURE=ssl
LEDU_SMTP_USER=
LEDU_SMTP_PASSWORD=
LEDU_SMTP_FROM_NAME=LtBooks
EOF
else
  [[ "$(read_env LEDU_DB_NAME)" == "$DB_NAME" ]] || die "Existing .env uses another database; refusing to continue"
fi
chmod 600 "$APP_DIR/.env"

mysql_root <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL
if [[ "$existing_tables" == "0" ]]; then
  DB_PASSWORD="$(read_env LEDU_DB_PASSWORD)"
  mysql_root <<SQL
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES,TRIGGER,
CREATE ROUTINE,ALTER ROUTINE,EXECUTE,LOCK TABLES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
fi

say "3/9 Creating the empty schema and accounting master data"
if [[ "$existing_tables" == "0" ]]; then
  mysql_root "$DB_NAME" < "$PACKAGE_ROOT/sql/01-schema.sql"
  mysql_root "$DB_NAME" < "$PACKAGE_ROOT/sql/02-master-data.sql"
else
  printf 'Existing LtBooks schema detected; preserving all database rows.\n'
fi

say "4/9 Installing the current LtBooks backend and bundled validator"
rsync -a --exclude '.git' --exclude '.env' --exclude 'venv' --exclude 'storage' \
  --exclude '__pycache__' --exclude '*.pyc' "$PACKAGE_ROOT/backend/" "$APP_DIR/"
mkdir -p "$APP_DIR/storage/uploads" "$APP_DIR/storage/home" "$APP_DIR/setup" "$UPLOAD_DIR/tmp"
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then python3 -m venv "$APP_DIR/venv"; fi
"$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check --quiet --upgrade pip
"$APP_DIR/venv/bin/python" -m pip install --disable-pip-version-check --quiet -r "$APP_DIR/requirements.txt"

say "5/9 Creating the first administrator without using a fixed password"
LTBOOKS_CREDENTIALS_FILE="$APP_DIR/storage/initial-credentials.txt" \
  "$APP_DIR/venv/bin/python" "$APP_DIR/tools/create_admin.py"
chmod 600 "$APP_DIR/storage/initial-credentials.txt"

say "6/9 Installing the PHP frontend"
rsync -a --exclude '.git' --exclude '.user.ini' --exclude 'files' --exclude 'storage' \
  --exclude 'tests' "$PACKAGE_ROOT/frontend/" "$WEB_ROOT/"
PHP_VERSION="$(php -r 'echo PHP_MAJOR_VERSION,".",PHP_MINOR_VERSION;')"
API_TOKEN="$(read_env LEDU_API_TOKEN)"
POOL_FILE="/etc/php/$PHP_VERSION/fpm/pool.d/ltbooks.conf"
PHP_SERVICE="php$PHP_VERSION-fpm"
if [[ "$MODE" == "manual" ]]; then
  POOL_FILE="$APP_DIR/setup/php-fpm-ltbooks.conf.example"
  PHP_SERVICE="php-fpm"
fi
mkdir -p "$(dirname "$POOL_FILE")"
cat > "$POOL_FILE" <<EOF
; LtBooks dedicated PHP-FPM pool. Configure the panel to use ltbooks.sock.
[ltbooks]
user = $WEB_USER
group = $POOL_GROUP
listen = /run/php/ltbooks.sock
listen.owner = $WEB_USER
listen.group = $POOL_GROUP
listen.mode = 0660
pm = dynamic
pm.max_children = 10
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
chdir = $WEB_ROOT
catch_workers_output = yes
env[LEDU_API_BASE] = http://127.0.0.1:8099
env[LEDU_API_TOKEN] = $API_TOKEN
env[LEDU_UPLOAD_DIR] = $UPLOAD_DIR
php_admin_value[upload_tmp_dir] = $UPLOAD_DIR/tmp
php_admin_value[upload_max_filesize] = 25M
php_admin_value[post_max_size] = 27M
EOF
chmod 600 "$POOL_FILE"

NGINX_TARGET="$APP_DIR/setup/nginx-ltbooks.conf.example"
if [[ "$MODE" == "auto" ]]; then
  if [[ -d /etc/nginx/sites-available ]]; then NGINX_TARGET="/etc/nginx/sites-available/ltbooks.conf"; else NGINX_TARGET="/etc/nginx/conf.d/ltbooks.conf"; fi
fi
CERT_DIR="/etc/ssl/ltbooks"
if [[ "$MODE" == "manual" ]]; then CERT_DIR="$APP_DIR/setup/ssl"; fi
mkdir -p "$CERT_DIR"
if [[ "$SSL_MODE" != "off" && ! -f "$CERT_DIR/privkey.pem" ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$CERT_DIR/privkey.pem" -out "$CERT_DIR/fullchain.pem" \
    -subj "/CN=$DOMAIN" >/dev/null 2>&1
  chmod 600 "$CERT_DIR/privkey.pem"
fi

cat > "$NGINX_TARGET" <<EOF
# LtBooks Ver 1.0 Web and HTTPS virtual host.
server {
    listen 80;
    server_name $DOMAIN;
$(if [[ "$SSL_MODE" == "off" ]]; then printf '    root %s;\n    index index.php;\n' "$WEB_ROOT"; else printf '    return 301 https://$host$request_uri;\n'; fi)
}
$(if [[ "$SSL_MODE" != "off" ]]; then cat <<SSL
server {
    listen 443 ssl http2;
    server_name $DOMAIN;
    root $WEB_ROOT;
    index index.php;
    ssl_certificate $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
SSL
fi)
$(if [[ "$SSL_MODE" == "off" ]]; then printf 'server { listen 80; server_name _; return 444; }\n'; fi)
EOF
# The location block is shared by HTTP-only and HTTPS modes.
if [[ "$SSL_MODE" == "off" ]]; then
  cat >> "$NGINX_TARGET" <<EOF
# Merge these locations into the HTTP server above when SSL is disabled.
EOF
else
  sed -i '$d' "$NGINX_TARGET"
  cat >> "$NGINX_TARGET" <<'EOF'
    client_max_body_size 25m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    location ^~ /files/ { deny all; }
    location / { try_files $uri $uri/ /index.php?$query_string; }
    location ~ \.php$ {
        try_files $uri =404;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_pass unix:/run/php/ltbooks.sock;
        fastcgi_read_timeout 300s;
    }
    location ~ /\.(?!well-known) { deny all; }
}
EOF
fi

if [[ "$SSL_MODE" == "off" ]]; then
  # Replace the generated skeleton with a complete HTTP-only virtual host.
  cat > "$NGINX_TARGET" <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    root $WEB_ROOT;
    index index.php;
    client_max_body_size 25m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    location ^~ /files/ { deny all; }
    location / { try_files \$uri \$uri/ /index.php?\$query_string; }
    location ~ \.php$ {
        try_files \$uri =404;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;
        fastcgi_pass unix:/run/php/ltbooks.sock;
        fastcgi_read_timeout 300s;
    }
    location ~ /\.(?!well-known) { deny all; }
}
EOF
fi

SERVICE_FILE="$APP_DIR/setup/ltbooks-api.service.example"
if [[ "$MODE" == "auto" ]]; then SERVICE_FILE="/etc/systemd/system/ltbooks-api.service"; fi
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=LtBooks Ver 1.0 API
After=network.target mariadb.service

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$APP_DIR
Environment=LEDU_ENV_FILE=$APP_DIR/.env
Environment=LEDU_APP_DIR=$APP_DIR
Environment=HOME=$APP_DIR/storage/home
Environment=TZ=Asia/Hong_Kong
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/api.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

BACKUP_SERVICE="$APP_DIR/setup/ltbooks-backup.service.example"
BACKUP_TIMER="$APP_DIR/setup/ltbooks-backup.timer.example"
if [[ "$MODE" == "auto" ]]; then
  BACKUP_SERVICE="/etc/systemd/system/ltbooks-backup.service"
  BACKUP_TIMER="/etc/systemd/system/ltbooks-backup.timer"
fi
cat > "$BACKUP_SERVICE" <<EOF
[Unit]
Description=LtBooks database and attachment backup
[Service]
Type=oneshot
User=$RUN_USER
Environment=LEDU_ENV_FILE=$APP_DIR/.env
Environment=LEDU_APP_DIR=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/tools/auto_backup.py tick
EOF
cat > "$BACKUP_TIMER" <<'EOF'
[Unit]
Description=LtBooks automatic backup scheduler
[Timer]
# Checked every minute; the interface settings decide the actual run time (Hong Kong time).
OnCalendar=*-*-* *:*:00
AccuracySec=30s
Persistent=true
Unit=ltbooks-backup.service
[Install]
WantedBy=timers.target
EOF

say "7/9 Applying file ownership and directory permissions"
if [[ "$MODE" == "auto" ]]; then
  chown -R root:ltbooks "$APP_DIR"
  chown -R "$RUN_USER":ltbooks "$APP_DIR/storage" "$BACKUP_DIR"
  chmod 700 "$APP_DIR/storage"
  chown root:ltbooks "$APP_DIR/.env"
  chmod 640 "$APP_DIR/.env"
  chmod 600 "$APP_DIR/storage/initial-credentials.txt"
  chown root:root "$APP_DIR/storage/initial-credentials.txt"
  chown -R root:ltbooks "$WEB_ROOT"
  chown -R "$RUN_USER":ltbooks "$WEB_ROOT/assets"
  chmod -R g+rwX "$WEB_ROOT/assets"
  chown -R "$WEB_USER":ltbooks "$UPLOAD_DIR"
  chmod 2770 "$UPLOAD_DIR" "$UPLOAD_DIR/tmp"
  chmod 700 "$BACKUP_DIR"
else
  chmod 700 "$APP_DIR/storage" "$BACKUP_DIR" "$UPLOAD_DIR"
  if [[ "$WEB_USER" != "$RUN_USER" ]]; then
    [[ "$(id -u)" == "0" ]] || die "Choose the current account as LTBOOKS_WEB_USER or ask root to grant upload access"
    chown -R "$WEB_USER":"$POOL_GROUP" "$UPLOAD_DIR"
  fi
fi

if [[ "$MODE" == "auto" ]]; then
  say "8/9 Starting the backend, PHP-FPM, HTTPS and scheduled backups"
  if [[ -d /etc/nginx/sites-enabled ]]; then ln -sfn "$NGINX_TARGET" /etc/nginx/sites-enabled/ltbooks.conf; fi
  systemctl daemon-reload
  systemctl enable --now ltbooks-api ltbooks-backup.timer
  systemctl restart "$PHP_SERVICE"
  nginx -t
  systemctl reload nginx
  for attempt in {1..20}; do
    if curl --fail --silent http://127.0.0.1:8099/health >/dev/null; then break; fi
    if [[ "$attempt" == "20" ]]; then systemctl status ltbooks-api --no-pager >&2 || true; die "Backend health check failed"; fi
    sleep 1
  done
  (cd "$APP_DIR" && "$APP_DIR/venv/bin/python" -c 'from core.agent import _run; import json; print(json.dumps(_run("finance_journal_entry_check", {"entry":{"lines":[]}}), ensure_ascii=False))') >/dev/null

  request_certificate=0
  if [[ "$SSL_MODE" == "letsencrypt" ]] && ! is_ipv4 "$DOMAIN"; then request_certificate=1; fi
  if [[ "$SSL_MODE" == "auto" && -n "$SSL_EMAIL" && "$DOMAIN" != *"example.com" && "$DOMAIN" != "_" ]] && ! is_ipv4 "$DOMAIN"; then request_certificate=1; fi
  if [[ "$request_certificate" == "1" ]]; then
    [[ -n "$SSL_EMAIL" ]] || die "LTBOOKS_SSL_EMAIL is required for a public certificate"
    if certbot --nginx --non-interactive --agree-tos --redirect -m "$SSL_EMAIL" -d "$DOMAIN"; then
      say "Public SSL certificate installed"
    elif [[ "$SSL_MODE" == "letsencrypt" ]]; then
      die "Public certificate issuance failed; the self-signed fallback remains active"
    else
      warn "Public certificate issuance failed; the self-signed fallback remains active"
    fi
  elif [[ "$SSL_MODE" != "off" ]]; then
    if is_ipv4 "$DOMAIN"; then
      warn "IP deployment uses a self-signed HTTPS certificate; trust it manually in the browser on first visit. Bind a domain and rerun with LTBOOKS_SSL_EMAIL to request a public certificate"
    else
      warn "Using a self-signed HTTPS certificate. Set LTBOOKS_DOMAIN and LTBOOKS_SSL_EMAIL to request a public certificate"
    fi
  fi
else
  say "8/9 Leaving Web, SSL and process activation to the hosting panel"
fi

say "9/9 Verifying the installation"
"$APP_DIR/venv/bin/python" -m py_compile "$APP_DIR/api.py" "$APP_DIR/config.py" "$APP_DIR/tools/create_admin.py"
"$APP_DIR/venv/bin/python" "$APP_DIR/tools/verify_audit_chain.py" >/dev/null
printf '\nLtBooks Ver 1.0 installation completed.\n'
printf 'Backend: %s\nWeb root: %s\n' "$APP_DIR" "$WEB_ROOT"
printf 'Initial credentials: %s (change the password after login, then delete this file)\n' "$APP_DIR/storage/initial-credentials.txt"
if [[ "$MODE" == "auto" ]]; then
  if [[ "$SSL_MODE" == "off" ]]; then printf 'URL: http://%s\n' "$DOMAIN"; else printf 'URL: https://%s\n' "$DOMAIN"; fi
else
  printf 'Panel configuration examples: %s\n' "$APP_DIR/setup"
  printf 'Backend start command: %s/venv/bin/python %s/api.py\n' "$APP_DIR" "$APP_DIR"
  warn "Configure HTTPS before logging in; secure session cookies are intentionally required"
fi

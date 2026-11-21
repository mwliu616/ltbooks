# LtBooks 1.0 Clean Deployment Package

Copyright (c) 2026 LEDU TECH CO., LIMITED. Released under the MIT license.

This package contains the PHP front end, Python backend, accounting check agent, database
schema and general accounting master data. It does not contain customers, vendors,
documents, entries, bank transactions, exchange rate caches, user accounts, receipt
files, backups, exports, real passwords or API keys.

Two packages are available. Use the one that matches the server.

| Package | File | Use when |
| --- | --- | --- |
| Automatic | `LtBooks-Ver1.0-auto-clean-*.tar.gz` | New Debian 12 or Ubuntu 22.04+ server with internet access. Enter a domain or IP and an optional certificate email; the rest is automatic |
| Manual | `LtBooks-Ver1.0-manual-clean-*.zip` | Existing hosting panel, internal network, offline server, or when you manage every system package yourself |

---

## 1. Automatic package (recommended)

You need a clean Linux server and root access. The installer asks for a domain name or
server IP. When a domain is used, it also asks for a certificate email address, which may
be left blank.

```bash
tar -xzf LtBooks-Ver1.0-auto-clean-*.tar.gz
cd LtBooks-Ver1.0-auto-clean-*
sudo ./install.sh
```

Prompts:

```text
Domain name or server IP (for example finance.example.com or 203.0.113.10):
> finance.example.com

Email address for Let's Encrypt certificate notices (leave blank for a self-signed certificate):
> admin@example.com
```

The email is used for certificate expiry notices. Leave it blank to keep the self-signed
certificate. A pure IP address is never asked for an email address.

Skip the prompts with environment variables:

```bash
sudo LTBOOKS_DOMAIN=finance.example.com LTBOOKS_SSL_EMAIL=admin@example.com ./install.sh
```

The installer runs these steps:

1. Checks the system version, architecture, disk space and root access.
2. Installs Nginx, MariaDB, PHP-FPM, Python, Node.js 20, OCR, PDF fonts and Certbot.
3. Creates the `ltbooks` service account and directories, and generates a random
   database password and internal API token.
4. Creates the database, imports the empty schema, 108 accounts and 12 tax rates, and
   creates the administrator.
5. Installs the backend virtual environment and the front end.
6. Writes the PHP-FPM pool, Nginx site, `ltbooks-api.service` and
   `ltbooks-backup.timer`.
7. Configures HTTPS, runs a self-check and prints the URL and credential path.

Environment variables:

| Variable | Default |
| --- | --- |
| `LTBOOKS_DOMAIN` | Prompt. Required when not interactive |
| `LTBOOKS_SSL_EMAIL` | Prompt (may be blank) |
| `LTBOOKS_SSL_MODE` | `auto` (`auto`, `letsencrypt`, `selfsigned`, `off`) |
| `LTBOOKS_APP_DIR` | `/opt/ltbooks` |
| `LTBOOKS_WEB_ROOT` | `/var/www/ltbooks` |
| `LTBOOKS_UPLOAD_DIR` | `/var/lib/ltbooks/uploads` |
| `LTBOOKS_BACKUP_DIR` | `/var/backups/ltbooks` |
| `LTBOOKS_DB_NAME` | `ltbooks` |
| `LTBOOKS_DB_USER` | `ltbooks_app` |

The installer stops if the target database already contains LtBooks tables. It does not
overwrite an existing ledger.

---

## 2. Manual package

Use this when you already manage the host, when the server is on an internal network, or
when you want to control package versions yourself. You prepare the system environment;
the script deploys the application and initialises the database.

### 2.1 Prepare the environment

Example for Debian or Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y nginx php8.2-fpm php8.2-cli php8.2-mysql \
  php8.2-curl php8.2-mbstring php8.2-xml php8.2-gd php8.2-zip \
  python3 python3-venv python3-pip rsync openssl curl nodejs
sudo apt-get install -y mariadb-server mariadb-client
sudo systemctl enable --now mariadb nginx php8.2-fpm
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-sim \
  tesseract-ocr-eng fonts-noto-cjk libpango-1.0-0 libpangoft2-1.0-0 libcairo2
```

| Component | Minimum | Recommended |
| --- | --- | --- |
| PHP | 8.1 | 8.2 or 8.3 |
| Python | 3.10 | 3.12 |
| Node.js | 18 | 20 |
| MariaDB | 10.6 | 10.11 |

Required PHP extensions: `curl`, `mbstring`, `xml`, `pdo_mysql`. `gd` is optional.

```bash
php -v && python3 -V && node -v && mysql --version
php -r '$m=["curl","mbstring","xml","pdo_mysql"];foreach($m as $x){echo $x,": ",extension_loaded($x)?"ok":"MISSING","\n";}'
```

### 2.2 Deploy the application

```bash
unzip LtBooks-Ver1.0-manual-clean-*.zip
cd LtBooks-Ver1.0-manual-clean-*
./install-manual.sh
```

The script creates directories, initialises the database, installs the front end and
backend, and writes sample configuration. It does not install system packages, create a
system account or start services.

Custom locations:

```bash
LTBOOKS_APP_DIR=/srv/ltbooks \
LTBOOKS_WEB_ROOT=/var/www/ltbooks \
LTBOOKS_UPLOAD_DIR=/srv/ltbooks/uploads \
LTBOOKS_BACKUP_DIR=/srv/ltbooks/backups \
./install-manual.sh
```

### 2.3 Web server and HTTPS

The `setup/` directory contains samples for Nginx, PHP-FPM, systemd and the backup timer.
Adjust the paths and connect them to your panel or copy them into place:

```bash
sudo cp setup/nginx-ltbooks.conf.example /etc/nginx/sites-available/ltbooks.conf
sudo ln -s /etc/nginx/sites-available/ltbooks.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Start the backend yourself:

```bash
<app dir>/venv/bin/python <app dir>/api.py
```

HTTPS is required. Session cookies use the `Secure` flag, so a plain HTTP browser does
not send them back. Configure a certificate with your panel or Certbot.

### 2.4 Manual database import (optional)

If you do not use `install-manual.sh`, follow `docs/HOWTO.md` and run:

```bash
mysql -uroot -p -e "CREATE DATABASE ltbooks CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -uroot -p ltbooks < sql/01-schema.sql
mysql -uroot -p ltbooks < sql/02-master-data.sql
```

---

## 3. First login

The administrator name is `admin`. The random first password is in:

```text
<app dir>/storage/initial-credentials.txt
```

The file has mode 600. Change the password at the first login and delete the file.
Company details, bank accounts, real exchange rates, SMTP and model settings are entered
after login.

## 4. After installation

```bash
systemctl is-active nginx php*-fpm ltbooks-api
curl -fsS http://127.0.0.1:8099/health
<app dir>/venv/bin/python <app dir>/tools/auto_backup.py create --full
systemctl list-timers ltbooks-backup.timer
```

- Automatic backups use one rolling file: a full archive first, then each run replaces
  it with the latest complete snapshot.
- PHP-FPM concurrency: raise `pm.max_children` to about 20 for busier servers, then
  reload the service.
- Log rotation: add a rule under `/etc/logrotate.d/` for the backend log (daily, keep 14
  files).

## 5. Integrity

Each archive has a matching `.sha256` file. `MANIFEST.txt` lists a SHA-256 hash for every
file in the package.

```bash
sha256sum -c LtBooks-Ver1.0-auto-clean-*.tar.gz.sha256
```

## 6. Documentation

| File | Content |
| --- | --- |
| `README.md` | This file |
| `README.zh-CN.md` | Simplified Chinese edition |
| `docs/HOWTO.md` | Installation and daily use |
| `docs/DEPLOYMENT.md` | Deployment parameters and troubleshooting |
| `docs/DEPLOYMENT.zh-CN.md` | Simplified Chinese deployment guide |
| `docs/DEPLOYMENT.zh-HK.md` | Traditional Chinese deployment guide |
| `docs/DEVELOPMENT.md` | Source layout and development |
| `docs/RELEASE.md` | Release and acceptance notes |

## 7. License

MIT. Copyright (c) 2026 LEDU TECH CO., LIMITED. The full text is in `LICENSE`.

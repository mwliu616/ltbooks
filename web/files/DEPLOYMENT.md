# Lt-AI-Books 1.1 Deployment Guide

This applies to both release packages: the automatic package and the manual package.
Both share the same source and installer; they differ in how much system setup they do.

Section 12 describes a single-server production baseline (service names, paths and
parameters). Use it when troubleshooting that layout.

- Copyright (c) 2026 LEDU TECH CO., LIMITED
- License: MIT

## 1. Requirements

| Component | Minimum | Notes |
| --- | --- | --- |
| Operating system | Debian 12 / Ubuntu 22.04+ | The automatic mode uses apt. Use the manual package on RHEL-based systems |
| Nginx | 1.18+ | HTTPS and PHP forwarding |
| PHP | 8.1+ (8.3 recommended) | Needs `curl`, `mbstring` and `xml`. `gd` is optional |
| PHP-FPM | Same version as PHP | Use a dedicated pool and socket |
| Python | 3.10+ (3.12 recommended) | Backend and installer |
| Node.js | 18+ (20 recommended) | Accounting check agent shipped with the package. The automatic mode can install 20 |
| MariaDB | 10.6+ (10.11 recommended) | `utf8mb4` |
| Other | openssl, rsync, curl | Certificates, sync, downloads |

Suggested server size: 2 cores, 4 GB RAM, 20 GB disk. Leave extra disk space for fonts
and WeasyPrint dependencies if OCR and PDF export are used.

## 2. Package layout

Both packages have the same layout. Only the entry script differs.

```
Lt-AI-Books-Ver1.1-<variant>-<date>/
├── install.sh                 Automatic installer (auto package)
├── install-manual.sh          Manual installer (manual package)
├── backend/                   Python backend and bundled agent
├── frontend/                  PHP front end
├── sql/01-schema.sql          50 tables, triggers and routines (no business data)
├── sql/02-master-data.sql     Company record, 108 accounts, 12 tax rates
├── LICENSE / README.md / MANIFEST.txt / PACKAGE.json
└── docs/                      This guide, HOWTO, development notes, release notes
```

The installer writes a SHA-256 hash for every file into `MANIFEST.txt`. Each archive has
a separate `.sha256` next to it.

## 3. Automatic mode

For a new Debian 12 or Ubuntu 22.04+ server with internet access. Run as root.

```bash
sudo ./install.sh
```

Prompts:

```text
Domain name or server IP (for example finance.example.com or 203.0.113.10):
> finance.example.com

Email address for Let's Encrypt certificate notices (leave blank for a self-signed certificate):
> admin@example.com
```

The email address is optional. Leave it blank to keep the self-signed certificate. A pure
IP address is never asked for an email address.

Non-interactive example:

```bash
sudo LTBOOKS_DOMAIN=books.example.com LTBOOKS_SSL_EMAIL=admin@example.com ./install.sh
```

The installer stops if the target database already contains Lt-AI-Books tables. It does not
overwrite an existing ledger.

Environment variables:

| Variable | Default |
| --- | --- |
| `LTBOOKS_DOMAIN` | Prompt. Required when not interactive |
| `LTBOOKS_SSL_MODE` | `auto` (`auto`, `letsencrypt`, `selfsigned`, `off`) |
| `LTBOOKS_SSL_EMAIL` | Prompt (may be blank) |
| `LTBOOKS_APP_DIR` | `/opt/ltbooks` |
| `LTBOOKS_WEB_ROOT` | `/var/www/ltbooks` |
| `LTBOOKS_UPLOAD_DIR` | `/var/lib/ltbooks/uploads` |
| `LTBOOKS_BACKUP_DIR` | `/var/backups/ltbooks` |
| `LTBOOKS_DB_HOST` / `PORT` | `127.0.0.1` / `3306` |
| `LTBOOKS_DB_NAME` / `USER` | `ltbooks` / `ltbooks_app` |
| `LTBOOKS_DB_PASSWORD` | Random 48-character hex string |

### 3.1 Domain and IP

| Input | HTTPS | Notes |
| --- | --- | --- |
| Resolved domain + email | Let's Encrypt certificate | Trusted by browsers |
| Domain + blank email | Self-signed certificate | The browser warns once. You can add `LTBOOKS_SSL_EMAIL` later |
| Pure IP | Self-signed certificate | Let's Encrypt does not issue certificates for IP addresses |

The interactive installer asks for the certificate email after the domain name. It does
not ask for an email address for a pure IP, or in `selfsigned` or `off` mode.

## 4. Manual mode

For servers managed by a hosting panel, internal networks, or environments where system
packages are controlled by someone else. You install the system environment; the script
only deploys the application.

### 4.1 Environment

See section 1.2 of HOWTO for the full Debian/Ubuntu command. Minimum versions:

| Component | Minimum |
| --- | --- |
| PHP | 8.1 (extensions curl, mbstring, xml, pdo_mysql) |
| Python | 3.10 |
| Node.js | 18 |
| MariaDB | 10.6 |

### 4.2 Deploy the application

```bash
unzip Lt-AI-Books-Ver1.1-manual-clean-<date>.zip
cd Lt-AI-Books-Ver1.1-manual-clean-<date>
./install-manual.sh
```

The script creates directories, creates the database and tables, creates the
administrator, installs the front end and backend, and writes sample configuration. It
does not install system packages, create a system account, start services or change the
panel configuration.

After installation, `<app dir>/setup/` contains:

- `nginx-ltbooks.conf.example`
- `php-fpm-ltbooks.conf.example`
- `ltbooks-api.service.example`
- `ltbooks-backup.service.example` and `.timer.example`
- `ssl/fullchain.pem`, `ssl/privkey.pem` (self-signed fallback)

When connecting it to a panel:

1. The PHP-FPM pool `user` and `group` must match the web account that reads the upload
   directory.
2. The site root points to the front end directory. `/files/` must be blocked.
3. The upload directory must be outside the web root.
4. When the installer runs as root and `LTBOOKS_WEB_USER` is not set, it uses an existing
   web account. When it runs as a normal user, it uses the current account.

Start the backend:

```bash
<app dir>/venv/bin/python <app dir>/api.py
```

You can also register `setup/ltbooks-api.service.example` as a service.

## 5. HTTPS

- `LTBOOKS_SSL_MODE=auto`: uses Certbot when a domain and email are available; otherwise
  a self-signed certificate. The interactive installer asks for the email after the
  domain and accepts a blank value.
- `certbot`: always requests a public certificate. Fails if no certificate can be
  issued. The email address is required.
- `selfsigned`: local certificate only, suitable for internal acceptance tests.
- `off`: HTTP only. Not recommended. Session cookies use `Secure`, so login does not work.

Certificate locations: `/etc/ssl/ltbooks/` in automatic mode;
`<app dir>/setup/ssl/` in manual mode.

## 6. Directories and permissions (automatic mode)

| Path | Owner | Mode |
| --- | --- | --- |
| Application directory | `root:ltbooks` | 755 |
| `.env` | `root:ltbooks` | 640 |
| `storage/` | `ltbooks:ltbooks` | 700 |
| `storage/initial-credentials.txt` | `root:root` | 600 |
| Web root | `root:ltbooks` | 755 |
| Web `assets/` | `ltbooks:ltbooks` | 775 (logo upload) |
| Upload directory | `www-data:ltbooks` | 2770 |
| Backup directory | `ltbooks:ltbooks` | 700 |

## 7. Runtime configuration (.env)

The installer writes `.env` with mode 600 or 640. Main keys:

| Key | Purpose |
| --- | --- |
| `LEDU_DB_*` | Database connection |
| `LEDU_API_HOST` / `PORT` | Backend listener. Default `127.0.0.1:8099` |
| `LEDU_API_TOKEN` | Internal token from the front end to the backend. At least 32 random characters |
| `LEDU_WEB_ROOT` | Front end directory, used for PDF and logo files |
| `LEDU_STORAGE_DIR` | Certificates and temporary application files |
| `LEDU_UPLOAD_DIR` / `LEDU_UPLOAD_DIRS` | Receipt and attachment directories (one or more) |
| `LEDU_BACKUP_DIR` / `KEEP` / `LOCK` | Backup directory, retention and lock file |
| `LEDU_AGENT_PRESET` | Directory of the bundled accounting check agent |
| `LEDU_NODE_BIN` | Node executable |
| `LEDU_LLM_*` | Model endpoint. Settings in the interface take precedence |
| `LEDU_VISION_API_KEY` | Vision or OCR endpoint key |
| `LEDU_SMTP_*` | Email. Settings in the interface take precedence |

Restart the backend after changing `.env`: `systemctl restart ltbooks-api`.

## 8. Post-deployment checks

```bash
curl -fsS http://127.0.0.1:8099/health
curl -kfsS https://<domain>/login | head
systemctl is-active ltbooks-api
```

Database check. Only the company record, accounts, tax rates and administrator should
exist:

```sql
SELECT COUNT(*) FROM information_schema.tables
 WHERE table_schema='ltbooks' AND table_type='BASE TABLE';   -- 50
SELECT COUNT(*) FROM accounts;    -- 108
SELECT COUNT(*) FROM tax_rates;   -- 12
SELECT COUNT(*) FROM customers;   -- 0
SELECT COUNT(*) FROM journal_entries; -- 0
```

After login, check that the dashboard has no errors, report periods switch correctly,
financial statements export to PDF, and Settings, Backup can create and download a
backup.

## 9. Moving from an existing environment

1. Create and download a backup in the old environment.
2. Install the same version on the new server.
3. Upload and restore the backup in the new environment.
4. Copy the model, SMTP and token settings from the old `.env`, or enter them again in
   the interface.
5. Compare the customer and vendor counts and the latest report with the old environment.

## 10. Uninstall

```bash
systemctl disable --now ltbooks-api ltbooks-backup.timer
rm -f /etc/systemd/system/ltbooks-api.service /etc/systemd/system/ltbooks-backup.*
rm -f /etc/nginx/sites-enabled/ltbooks.conf /etc/nginx/sites-available/ltbooks.conf
rm -f /etc/php/*/fpm/pool.d/ltbooks.conf
systemctl reload nginx && systemctl restart 'php*-fpm'
```

Delete the data directories (`/opt/ltbooks`, `/var/lib/ltbooks`, `/var/backups/ltbooks`)
only after confirming the backup. Remove the database with `DROP DATABASE ltbooks;`.

## 11. Troubleshooting

| Symptom | Action |
| --- | --- |
| `Missing PHP extension` | Install the extension and retry. Only `curl`, `mbstring` and `xml` are required |
| `Node.js 18 or newer is required` | The automatic mode installs Node 20. In manual mode, upgrade Node first |
| Nginx fails to start | Run `nginx -t`. Confirm the socket path matches the PHP-FPM pool |
| 502 | Backend is down or on another port. Run `systemctl status ltbooks-api` |
| Login loop | HTTPS is not enabled |
| Upload returns 413 | Raise Nginx `client_max_body_size` and PHP `upload_max_filesize` |
| Certificate is not trusted | Expected with a self-signed certificate. Configure a real certificate in production |

## 12. Single-server baseline (example)

This baseline comes from a working single-server deployment. Domain names and database
names are replaced with examples. It shows the shape when every component runs on one
machine and shares one directory tree.

### 12.1 Paths and services

| Item | Example value |
| --- | --- |
| Application root | `/opt/ltbooks` (`app/`, `web/`, `storage/`, `uploads/`, `backups/`, `archive/`) |
| Front end site | `/opt/ltbooks/web`, reachable through a `/var/www/ltbooks` symlink |
| Domain | `finance.example.com` |
| Backend service | `ledu-api.service` on `127.0.0.1:8099` |
| Backend log | `/var/log/ledu-api.log` |
| Web server | Nginx. Site file `/www/server/panel/vhost/nginx/finance.example.com.conf` |
| PHP | 8.3, FPM pool `www` (`/etc/php/8.3/fpm/pool.d/www.conf`) |
| Database | MariaDB `ltbooks`, user `ltbooks`, `127.0.0.1:3306` |
| Certificate | Let's Encrypt, valid until 2027-02-17, renewed by acme.sh |

### 12.2 Key parameters

```ini
; /etc/php/8.3/fpm/pool.d/www.conf
pm = dynamic
pm.max_children = 20
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 10
```

The previous values were `5 / 2 / 1 / 3`. They were raised on 2026-11-21 after
`server reached pm.max_children` warnings. Run `systemctl reload php8.3-fpm` after the
change.

```ini
; /etc/logrotate.d/ledu-api
/var/log/ledu-api.log {
    su root root
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    create 0640 root root
}
```

`su root root` is needed because `/var/log` is `root:syslog 775`. `copytruncate` avoids
restarting the backend.

### 12.3 Automatic backup

Production uses a system crontab with `flock` and runs `tick` every minute:

```cron
* * * * * /usr/bin/flock -n /var/run/ltbooks-auto-backup-tick.lock \
  /usr/bin/env -u LD_LIBRARY_PATH \
  /opt/ltbooks/app/venv/bin/python /opt/ltbooks/app/tools/auto_backup.py tick \
  >> /opt/ltbooks/backups/auto-backup.log 2>&1
```

The schedule is stored in the `settings` table under `backup.schedule`. The default is
09:00 and 17:00 Hong Kong time. 180 backups are kept (`LEDU_BACKUP_KEEP`). Create the
first full base archive explicitly:

```bash
cd /opt/ltbooks/app && ./venv/bin/python tools/auto_backup.py create --full
```

### 12.4 Verification

```bash
systemctl is-active nginx php8.3-fpm ledu-api cron
curl -fsS http://127.0.0.1:8099/health
curl -fsS -o /dev/null -w '%{http_code}\n' https://finance.example.com/
crontab -l | grep auto_backup
ls -lh /opt/ltbooks/backups/
```

```bash
# Backend regression
cd /opt/ltbooks/app && PYTHONPATH=. ./venv/bin/python -m unittest discover -s tests -p 'test_*.py'
# Front end syntax
find /opt/ltbooks/web -name '*.php' -print0 | xargs -0 -n1 env -u LD_LIBRARY_PATH php -l
```

Expected: services `active`, `/health` returns 200, the home page returns 200, the
crontab has one matching entry, the backup directory contains at least one `tar.gz`,
131 backend tests pass and PHP reports no syntax errors.

The local commands need the `env -u LD_LIBRARY_PATH` prefix. Without it, some binaries
fail with `GLIBCXX_3.4.32 not found`.

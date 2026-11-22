# LtBooks 1.0

LtBooks is an accounting and financial reporting system for small and medium businesses
in Hong Kong. The browser interface is server-rendered PHP 8.3, the ledger and API run
on Python 3.12, and data is stored in MariaDB 10.11.

Amounts, tax figures and report totals are calculated by deterministic code. The AI
features only extract document data, suggest account classifications and write
commentary. They do not produce numbers on their own.

- Copyright (c) 2026 LEDU TECH CO., LIMITED
- License: MIT (see `LICENSE`)
- Version: 1.0.0 (maintenance update, 2026-11-21)

## What it covers

| Area | Functions |
| --- | --- |
| AI workspace | Create documents, post entries, query figures, reconcile and export through natural language. Uploaded or photographed receipts are parsed and classified first; nothing is written until a person confirms the result. |
| Sales | Customers, quotes, sales orders, invoices, receipts, credit notes, recurring invoices. Documents can be emailed and foreign currency amounts show both original and functional currency. |
| Purchases | Vendors, purchase orders, bills, expenses, payments, recurring bills. Same email and foreign currency support. |
| Banking | Bank accounts, bank rules, statement import (the imported list keeps the original file for download), transactions, reconciliation, transfers between accounts. |
| Accounting | Chart of accounts, opening balances, manual journals, journal list, exchange rates, review queue, period close and lock, period-end revaluation. |
| Reports | Trial balance, statement of profit or loss and OCI, statement of financial position, cash flows, aging, bank balances, exchange gain or loss, profits tax, financial ratios, customer and vendor balances, general ledger, day book, sales and purchase details, financial statement set. |
| Financial analysis | Company analysis for this month, a chosen month, calendar year, fiscal year, since inception or a custom period. Deterministic figures and charts plus written commentary, exportable as PDF or Word in three languages. |
| Settings | Company profile, user account, model settings, themes (8 presets), email, backup and restore, agent management, audit explorer, user guide. |

Foreign currency: documents and reports show `original amount × rate = functional
currency amount`. The functional currency comes from the company profile. Documents
switch between Simplified Chinese, Traditional Chinese and English as a whole, based on
the current interface language.

## Deployment packages

Packages are published in `files/releases/` and attached to the GitHub release at
https://github.com/mwliu616/ltbooks/releases/tag/v1.0.0. Both are clean installers with
no business data. They contain:

- an empty schema for 50 tables, including triggers and routines;
- one editable company record (`My Company`, HKD, fiscal year end 12-31);
- 108 accounts and 12 tax rates;
- source code, dependency list, license and installation scripts.

They do not contain customers, vendors, documents, journal entries, bank transactions,
accounts, exchange rate caches, user passwords, receipt files, backups or API keys.

| Package | File | When to use it |
| --- | --- | --- |
| Automatic | `LtBooks-Ver1.0-auto-clean-20261122.tar.gz` | New Debian or Ubuntu server. Run `./install.sh` as root. It asks for a domain name or server IP, then for an optional certificate email when a domain is used. It installs Nginx, MariaDB, PHP, Python, Node and the OCR/PDF dependencies, then configures HTTPS. |
| Manual | `LtBooks-Ver1.0-manual-clean-20261122.zip` | Existing hosting panel, internal network, or a server where you manage system packages yourself. Prepare the environment first, then run `./install-manual.sh`, which only creates directories, the database and the configuration. |

Use one package per server, not both. The old AI deployment package has been removed.

A pure IP address, or an empty certificate email, results in a self-signed certificate.
A public Let's Encrypt certificate is requested only when a resolved domain and an email
address are both provided.

Each package has a matching `.sha256` file. Inside the package, `MANIFEST.txt` lists a
hash for every file and `PACKAGE.json` records the variant, build date and file count.

```bash
sha256sum -c LtBooks-Ver1.0-auto-clean-20261122.tar.gz.sha256
```

Installation steps are in [HOWTO.md](HOWTO.md). Deployment parameters, directories and
troubleshooting are in [DEPLOYMENT.md](DEPLOYMENT.md), with Simplified Chinese and
Traditional Chinese editions in [DEPLOYMENT.zh-CN.md](DEPLOYMENT.zh-CN.md) and
[DEPLOYMENT.zh-HK.md](DEPLOYMENT.zh-HK.md). Source layout and data flow are in
[DEVELOPMENT.md](DEVELOPMENT.md). Release and acceptance notes are in
[RELEASE.md](RELEASE.md).

## Architecture

```
Browser
  |  HTTPS
  v
Nginx -> PHP-FPM (index.php, server-side rendering and sessions)
             |  internal HTTP with X-Ledu-Token
             v
       Python API (127.0.0.1:8099, Flask)
             |  parameterised SQL, writes inside transactions
             v
       MariaDB (ltbooks)
             |
             +- receipts and attachments (/opt/ltbooks/uploads)
             +- automatic backups (/opt/ltbooks/backups, default 09:00 and 17:00)
```

- The browser never talks to the Python API directly. The front end uses an internal
  token stored in `.env`.
- Session cookies are `Secure`, `HttpOnly` and `SameSite=Lax`, so HTTPS is required.
- Automatic backups use a single rolling file: the first run writes a full archive and
  later runs atomically replace it. Manual backups are always full archives and become
  the base for later automatic updates. Restoring a rolling archive needs no chain of
  earlier files.

## Directories

| Path | Installer default | Example production layout |
| --- | --- | --- |
| Backend and virtual environment | `/opt/ltbooks` | `/opt/ltbooks/app` |
| PHP front end | `/var/www/ltbooks` | `/opt/ltbooks/web` (symlinked from `/www/wwwroot/finance.example.com`) |
| Receipts and attachments | `/var/lib/ltbooks/uploads` | `/opt/ltbooks/uploads` |
| Automatic and manual backups | `/var/backups/ltbooks` | `/opt/ltbooks/backups` |
| Backend service | `ltbooks-api.service` | `ledu-api.service` (log at `/var/log/ledu-api.log`) |
| Backup schedule | `ltbooks-backup.timer` | system crontab running `auto_backup.py tick` every minute |

The manual installer does not write system directories. Locations are controlled by
`LTBOOKS_APP_DIR`, `LTBOOKS_WEB_ROOT` and related variables.

## First login

After installation, the initial administrator account and a random password are stored
in `<app directory>/storage/initial-credentials.txt` with mode 600. Change the password
at the first login and delete the file. Existing accounts are never reset, so running
the installer again is safe.

## License

LtBooks is released under the MIT license. The full text is in `LICENSE` (in the
deployment package) and in the repository root. Runtime dependencies (Flask, PyMySQL,
WeasyPrint, python-docx, openpyxl and others) keep their own licenses; the list is in
`backend/requirements.txt`. The documentation and code do not depend on a particular
cloud provider, mail provider or hosting panel.

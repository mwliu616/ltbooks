# Lt-AI-Books 1.1: Installation and User Guide

Copyright (c) 2026 LEDU TECH CO., LIMITED. Released under the MIT license.

## 1. Installation

### 1.1 Automatic package (recommended)

Use this on a new Debian 12 or Ubuntu 22.04+ server with internet access. Run it as root.
The installer asks for a domain name or server IP. When a domain is used, it also asks
for an optional certificate email address. Everything else is automatic.

```bash
# Keep the archive and its .sha256 file in the same directory.
sha256sum -c Lt-AI-Books-Ver1.1-auto-clean-20261123.tar.gz.sha256
tar -xzf Lt-AI-Books-Ver1.1-auto-clean-20261123.tar.gz
cd Lt-AI-Books-Ver1.1-auto-clean-20261123
sudo ./install.sh
```

Prompts:

```text
Domain name or server IP (for example finance.example.com or 203.0.113.10):
> finance.example.com

Email address for Let's Encrypt certificate notices (leave blank for a self-signed certificate):
> admin@example.com
```

The email address is used for certificate expiry notices. If you leave it blank, the
installer keeps the self-signed certificate. A pure IP address is never asked for an
email address. You can skip both prompts with environment variables:

```bash
sudo LTBOOKS_DOMAIN=finance.example.com LTBOOKS_SSL_EMAIL=admin@example.com ./install.sh
```

The installer performs these steps:

1. Checks root access and that `apt-get` is available. Installs any missing Nginx,
   MariaDB, PHP-FPM, Python, Node.js, OCR/PDF packages and Certbot.
2. Creates the `ltbooks` service account and directories, and generates a random
   database password and internal API token.
3. Creates the database and imports the empty schema, 108 accounts and 12 tax rates,
   then creates the initial administrator.
4. Installs the backend virtual environment and the front end.
5. Writes the PHP-FPM pool, Nginx site, `ltbooks-api.service` and
   `ltbooks-backup.timer`.
6. Configures HTTPS, runs a self-check and prints the access URL and credential path.

Certificate behaviour:

| Input | HTTPS | Notes |
| --- | --- | --- |
| Resolved domain + email | Let's Encrypt certificate | Trusted by browsers |
| Domain + blank email | Self-signed certificate | The browser warns once. You can add `LTBOOKS_SSL_EMAIL` later and rerun |
| Pure IP | Self-signed certificate | Let's Encrypt does not issue certificates for IP addresses |

Common environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LTBOOKS_DOMAIN` | Prompt | Domain or IP. Required when not interactive |
| `LTBOOKS_SSL_EMAIL` | Prompt (may be blank) | Enables a Let's Encrypt certificate |
| `LTBOOKS_SSL_MODE` | `auto` | `auto`, `letsencrypt`, `selfsigned` or `off` |
| `LTBOOKS_APP_DIR` | `/opt/ltbooks` | Backend directory |
| `LTBOOKS_WEB_ROOT` | `/var/www/ltbooks` | Front end directory |
| `LTBOOKS_UPLOAD_DIR` | `/var/lib/ltbooks/uploads` | Receipts and attachments |
| `LTBOOKS_BACKUP_DIR` | `/var/backups/ltbooks` | Backups |
| `LTBOOKS_DB_NAME` | `ltbooks` | Database name |
| `LTBOOKS_DB_USER` | `ltbooks_app` | Database user |

The installer stops if the target database already contains Lt-AI-Books tables. It does not
overwrite an existing ledger.

### 1.2 Manual package

Use this on a server managed by a hosting panel, on an internal network, or where system
packages are managed by someone else. The script deploys the application, initialises the
database and writes configuration. It does not install system packages, create a system
account or start services.

Example environment setup on Debian or Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y nginx php8.2-fpm php8.2-cli php8.2-mysql \
  php8.2-curl php8.2-mbstring php8.2-xml php8.2-gd php8.2-zip \
  python3 python3-venv python3-pip rsync openssl curl nodejs \
  mariadb-server mariadb-client poppler-utils tesseract-ocr \
  tesseract-ocr-chi-sim tesseract-ocr-eng fonts-noto-cjk \
  libpango-1.0-0 libpangoft2-1.0-0 libcairo2
sudo systemctl enable --now mariadb nginx php8.2-fpm
```

| Component | Minimum | Recommended |
| --- | --- | --- |
| PHP | 8.1 | 8.2 or 8.3 |
| Python | 3.10 | 3.12 |
| Node.js | 18 | 20 |
| MariaDB | 10.6 | 10.11 |

Required PHP extensions: `curl`, `mbstring`, `xml`, `pdo_mysql`.

```bash
php -v && python3 -V && node -v && mysql --version
php -r '$m=["curl","mbstring","xml","pdo_mysql"];foreach($m as $x){echo $x,": ",extension_loaded($x)?"ok":"MISSING","\n";}'
```

Deploy:

```bash
unzip Lt-AI-Books-Ver1.1-manual-clean-20261123.zip
cd Lt-AI-Books-Ver1.1-manual-clean-20261123
./install-manual.sh
```

Locations can be changed with `LTBOOKS_APP_DIR`, `LTBOOKS_WEB_ROOT`,
`LTBOOKS_UPLOAD_DIR` and `LTBOOKS_BACKUP_DIR`.

Connect the Nginx and PHP-FPM samples under `setup/` to your panel, then start the
backend yourself:

```bash
<app dir>/venv/bin/python <app dir>/api.py
```

HTTPS is required. Session cookies use the `Secure` flag, so a plain HTTP browser does
not send them back and the login page reloads.

### 1.3 First login and setup

1. Open `https://<domain>/`.
2. Sign in as `admin`. The password is in `<app dir>/storage/initial-credentials.txt`.
3. Change the password under Settings, Account. Delete the file afterwards.
4. Under Settings, Company, set the company name, address, contact details, functional
   currency and fiscal year end.
5. Under Accounting, Chart of Accounts, review the account list. Add any exchange rates
   you need under Accounting, Exchange Rates.
6. For email, fill in SMTP under Settings, Email. For AI features, add a model endpoint
   under Settings, Model.

## 2. Daily use

### 2.1 AI workspace

The AI workspace is in the left navigation. Document creation, posting, queries,
reconciliation and exports happen on the same page.

- Text commands, for example "record a bill for August rent, 12,000 HKD". The system
  returns a result card with the document, accounts, amounts and voucher number. Nothing
  is written until you confirm.
- Receipt extraction. Upload or photograph invoices, receipts and bank slips. The system
  reads the content, suggests the business nature and accounts, then shows a confirmation
  card.
- Missing fields. The system asks only when the document really lacks a value, such as
  a missing amount, date or counterparty.
- Mobile. The same page accepts a photo or file from a phone browser and returns the
  same confirmation card.

### 2.2 Documents and email

Quote, sales order, invoice, bill, purchase order and credit note detail pages have a
Send email button. The message body and attached PDF use the same template as printing:
foreign currency documents show the original amount, rate and functional amount; the
document uses the current interface language only; the sender name comes from
Settings, Email.

### 2.3 Receipt and payment progress

Invoice and bill lists show a received or paid progress column with the settled ratio and
remaining amount. Click it to open the settlement workspace.

### 2.4 Bank statement import

Bank, Import statement opens with the list of imported statements, newest first.

| Column | Meaning |
| --- | --- |
| Imported at | When the batch was written |
| File name | Original upload name |
| Bank account | Account the statement belongs to |
| Period | First and last date in the file |
| Lines | Number of transaction lines |
| Actions | View opens the account transactions; Download returns the original file when kept |

Import steps:

1. Select + Import statement. The list is replaced by a dedicated upload screen.
2. Choose the bank account and a CSV, XLSX, XLS or PDF file (20 MB maximum). Select
   Upload and parse.
3. Review the parsed rows below. The arithmetic check requires opening + credits - debits
   to equal the closing balance.
4. Select Import and validate and confirm in the dialog. Balances and the period are
   taken from the parsed data.
5. Select Back to list. The new batch appears at the top.

Files are de-duplicated by SHA-256. Parsing never writes to the database. Original files
are stored under `<app dir>/storage/bank-statements/<entity>/`, named by SHA-256. Records
imported before this feature have no original file, so they show no Download button.

### 2.5 Reports

The Reports navigation has three entries: Report centre, Financial statements and Profits
tax. Detail reports open from the report centre. Report pages share a period bar with
presets, custom dates and comparison. Amounts come from posted entries.

### 2.6 Financial analysis

The analysis can be generated for this month, a chosen month, a calendar year, the fiscal
year, since inception or a custom period. A report contains key figures and charts,
financial statements, and written commentary. All numbers come from deterministic report
functions. The AI writes narrative text without inventing figures; when no model is
available, the text falls back to deterministic wording. Exports are PDF and DOCX in
Simplified Chinese, Traditional Chinese or English.

### 2.7 Themes

Settings, Appearance offers eight themes. Themes change colour variables only; layout,
data and reports are unchanged. The choice is stored in the current browser.

### 2.8 Period close and review

Accounting, Review handles entries waiting for confirmation. Accounting, Period close
checks unposted documents, unsettled items and period issues before locking a period. A
locked period rejects new writes. Unlock it under Period locks before making adjustments.

### 2.9 Journal and entry detail

In Accounting, Journal, the Details, Attachments and Edit buttons open a dedicated entry
page (`?p=journal-view&id=...`). The list itself has no inline action panel. The Voucher
button opens a PDF in the current language in a new tab. The list can be searched by
entry number, description or source, and shows counts for this page, all entries and
drafts. Rows are grouped by period, with the line count and debit/credit subtotal for
that period on this page.

The entry page provides:

- Entry information and lines. Reversed and reversing entries show links to each other.
- Drafts: edit or delete. Deletion returns to the list and keeps an audit record.
- Posted entries: enter a reversal reason and select Reverse. A reversing entry is
  created after confirmation; the original entry stays.
- Attachments: upload (multiple files), view and delete. The limit is 20 MB per file and
  the SHA-256 hash is recorded on upload.

Auditors can view entries and attachments but cannot edit, delete, reverse or change
attachments.

## 3. Language and PDF export

The interface supports Simplified Chinese, Traditional Chinese and English. Switch in the
top right corner or with `?lang=zh_cn`, `?lang=zh_hk` or `?lang=en`. The `<html lang>`
attribute follows the choice.

Company legal names, customer and vendor names, manual descriptions, document numbers,
currency codes and HKFRS/HKAS names are kept as entered and are not translated.

New interface strings must be added to all three dictionaries:

- Simplified Chinese: the source text;
- Traditional Chinese: `lib/lang/zh_hk.php`, with the character fallback in
  `lib/zh_hk_chars.php`;
- English: `lib/lang/en.php`. Values must not contain Chinese characters.

Documents, 17 report types, the financial statement set, tax reports, vouchers, financial
analysis and the annual report package support all three languages. The annual package
`MANIFEST.txt` also follows the selected language.

Check the text layer of a PDF with:

```bash
pdftotext -layout <file>.pdf - | head -50
```

## 4. Backup and restore

### 4.1 Automatic backup

In the automatic package, a systemd timer calls `tools/auto_backup.py tick` every minute.
The script runs at the times configured in the interface, Hong Kong time. The default is
09:00 and 17:00. Up to four times can be set under Settings, Backup, Automatic backup
settings. An empty value disables the schedule. The last 180 backups are kept.

- Automatic backups use a single rolling file. The first run writes a full archive; later
  runs atomically replace it with a new full archive. The directory keeps one automatic
  backup and restore reads that file directly.
- If there is no usable base file, the next run creates a full backup again.
- Manual backups are always full backups. They are kept and become the base for later
  automatic updates.
- Manual and automatic backups are listed separately and can be downloaded or deleted
  independently.

Because the rolling update rewrites the whole archive, each run reads and writes roughly
the size of the backup (about 62 MB at the time of writing). In return the directory holds
one file and restore is simple.

Check status:

```bash
# Automatic package
systemctl list-timers ltbooks-backup.timer
systemctl status ltbooks-backup.service
journalctl -u ltbooks-backup.service -n 50
```

```bash
# Production layout with a system crontab
crontab -l | grep auto_backup
tail -n 50 /opt/ltbooks/backups/auto-backup.log
ls -lh /opt/ltbooks/backups/
```

The manual package does not register a timer. Call the same command from the panel
scheduler every minute. To force a full backup:

```bash
<app dir>/venv/bin/python <app dir>/tools/auto_backup.py tick
<app dir>/venv/bin/python <app dir>/tools/auto_backup.py create
<app dir>/venv/bin/python <app dir>/tools/auto_backup.py create --full
```

### 4.2 Backup and restore in the interface

Settings, Backup can create a full backup, download a backup, inspect its type and file
list, delete one backup and restore one. Automatic backups are marked as rolling and show
how many updates they contain. A restore:

1. creates a full safety backup first;
2. verifies the manifest and the SHA-256 of every file;
3. restores the database and attachments from the selected file;
4. reports any failure and keeps the safety backup;
5. clears the rolling state so the next automatic backup starts from a full archive.

### 4.3 Backup contents

Rolling and full backups contain all business tables, uploaded receipts and attachments,
and the manifest. They include a `rolling` marker and the update count. They do not
contain `.env`, model or SMTP keys, or sessions. When moving to another server, copy
`.env` separately or enter the settings again.

## 5. Security

- Every write requires a signed-in session. Administrative endpoints also require the
  admin role.
- The front end calls the backend with an internal token that browsers never see. The
  backend refuses to start if the token is missing or too short.
- Attachment downloads resolve the real path and reject anything outside the upload
  directory.
- Login, AI uploads and attachment uploads have size and type limits. The upload
  directory is outside the web root.
- Production must use HTTPS. Self-signed certificates are for internal networks and
  acceptance tests only.

## 6. Troubleshooting

| Symptom | Check |
| --- | --- |
| Login returns to the login page | HTTPS is off, so the Secure cookie is not returned. Check the certificate and `X-Forwarded-Proto` |
| 502 Bad Gateway | The backend is down or on another port. Run `systemctl status ltbooks-api` and check `LEDU_API_PORT` in `.env` |
| Internal token error | `LEDU_API_TOKEN` in `.env` does not match the backend. Restart the backend after fixing it |
| Email fails | Check host, port, encryption and account under Settings, Email. Use SSL on 465 and STARTTLS on 587 |
| Receipt extraction unavailable | No model or vision endpoint is configured. Add one under Settings, Model |
| Report figures are empty | No posted entries in the period. Check the period and the journal |
| Backup task does not run | Check the timer in the automatic package, or `crontab -l` for `auto_backup.py tick` and `/opt/ltbooks/backups/auto-backup.log` |
| Backup directory is empty | No base file yet. Run `auto_backup.py create --full` and confirm `LEDU_BACKUP_DIR` is writable |
| Occasional timeout or 502 | PHP-FPM workers are exhausted. Check `pm.max_children` in `/etc/php/8.3/fpm/pool.d/www.conf` (20 in production) and reload the service |
| Backend restarts repeatedly | Check `/var/log/ledu-api.log` for a traceback, usually a token or database setting in `.env` |
| Logs fill the disk | `/etc/logrotate.d/ledu-api` rotates daily and keeps 14 files. Confirm `logrotate.timer` is active |
| Installer reports a missing PHP extension | `curl`, `mbstring` and `xml` are required. `gd` is optional |

Log locations:

```bash
journalctl -u ltbooks-api -n 100      # automatic package
tail -n 100 /var/log/ledu-api.log     # production layout
tail -n 100 /var/log/nginx/error.log  # web server
```

## 7. Upgrade and rollback

1. Create a backup under Backup before upgrading, and note the current version.
2. Unpack the new package and run the installer with the same `LTBOOKS_*` values. The
   existing database is kept.
3. To roll back, restore the backup taken before the upgrade and replace the application
   directory with the previous source.
4. Restart the backend service after a rollback.

## 8. License

Copyright (c) 2026 LEDU TECH CO., LIMITED. Released under the MIT license. See `LICENSE`.

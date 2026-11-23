# LtBooks 1.0 Release Notes

Release date: 2026-11-19
Version: 1.0.0
Copyright (c) 2026 LEDU TECH CO., LIMITED
License: MIT

## 0. Maintenance update, 2026-11-21

This update does not change the data model and needs no migration. Packages keep the
1.0.0 version number.

### 0.1 Language fixes

| Issue | Fix |
| --- | --- |
| Real P&L PDFs kept Chinese labels for this period, prior year and change | Labels follow the requested language, including the Traditional Chinese wording |
| Journal PDF showed `manual` and `posted` | Now `Manual entry` and `Posted` |
| PDF errors mixed an English prefix with a Chinese detail | Error detail follows the requested language. Unknown report types keep the supplied name |
| Annual report `MANIFEST.txt` was English only | Title, generation info, report notes, document units and failure flags are translated |
| Missing English strings in the front end | English dictionary grew from 3310 to 3349 entries, plus dynamic SMTP rules |

Business text (legal names, customer and vendor names, manual descriptions, document
numbers, currencies, HKFRS/HKAS terms) is kept as entered.

### 0.2 Release readiness

| Item | Change |
| --- | --- |
| Automatic backup | Restored the per-minute `tick` crontab. First full backup completed and verified (50 tables, 305 attachments) |
| PHP-FPM concurrency | `pm.max_children` raised from 5 to 20 |
| Log rotation | Added `/etc/logrotate.d/ledu-api`, 14 daily files |
| Version control | Release baselines committed |
| Regression | 131 backend tests pass, all PHP files pass `php -l`, 69 real PDFs and 18 error cases checked, annual package text layer checked in three languages |

### 0.3 Interface and interaction

| Area | Change |
| --- | --- |
| Bank statement import | The page opens on the imported list. + Import statement opens a dedicated upload screen with no list. Parsed rows appear below and are written only after confirmation. Original files are kept by SHA-256 and can be downloaded |
| Journal | Each row manages attachments (upload, view, delete). Details, edit, delete and reverse open a dedicated entry page. Rows are grouped by period with line count and debit/credit subtotals. Search and counts sit in a toolbar |
| Chart of accounts | Each category heading appears once and shows the account count. Add account uses a full-width panel. Action column is right aligned and the table header is sticky |
| Email | SMTP connection test card matches the SMTP settings card. Recipient field spans the full width |
| Inputs | text, number, date, time, email, search, password, select and textarea share one style. List toolbar searches use 34 px; form fields use 36 px |
| Languages | Added strings and page titles for bank import, journal, entry detail and email. English and Traditional Chinese have no leftover fixed Chinese text |

### 0.4 Deployment scripts

The automatic installer asks for a Let's Encrypt certificate email after the domain:

- A valid email requests a public certificate. A blank value keeps the self-signed
  certificate.
- A pure IP, `selfsigned` or `off` mode does not ask for an email.
- `LTBOOKS_SSL_EMAIL` skips the prompt. `LTBOOKS_SSL_MODE=letsencrypt` requires an email
  and validates the format before continuing.

### 0.5 User administration and sign-out (2026-11-23)

| Item | Change |
| --- | --- |
| User management | The account page can edit a user (display name, role, status) and delete users. The built-in `admin` account cannot be demoted, disabled or deleted; the signed-in account and the last active administrator are also protected |
| Sign out | The sign-out button posts to `?p=logout`, deletes the server session, clears the session cookie and returns to the sign-in page |
| Letterhead PDF | Generation no longer fails silently when the API storage directory is not writable; the upstream error message is returned as-is |
| Currencies | The FX rate form can add a currency that is not listed yet by choosing **Other currency** and entering its three-letter code. Once a rate exists the currency appears in every currency selector |
| Bank accounts | **New bank account** lets you pick an existing 112x bank account; when none is picked the system reuses a free one for the currency or creates it. The list shows each account's GL account, and the first account becomes primary receiving |

## 1. Artifacts

| Artifact | Path |
| --- | --- |
| Automatic package | `releases/LtBooks-Ver1.0-auto-clean-20261123.tar.gz` |
| Manual package | `releases/LtBooks-Ver1.0-manual-clean-20261123.zip` |
| Checksums | Matching `.sha256` file next to each archive |
| Manifests | `MANIFEST.txt` (per-file SHA-256) and `PACKAGE.json` (variant and counts) |
| Documentation | `README.md`, `docs/HOWTO.md`, `docs/DEPLOYMENT.md`, `docs/DEPLOYMENT.zh-CN.md`, `docs/DEPLOYMENT.zh-HK.md`, `docs/DEVELOPMENT.md`, `docs/RELEASE.md` |

Both packages are clean installers: 50 empty tables, one company record, 108 accounts and
12 tax rates. They contain no customers, vendors, documents, entries, bank transactions,
user passwords, receipts, backups or keys. The automatic package asks for a domain or IP
and an optional certificate email. The manual package leaves the system environment to
the operator.

## 2. Changes in 1.0

### 2.1 Interface, brand and backup

- Product name is LtBooks throughout: browser title, document footer, report footer,
  PDF and DOCX footers.
- The brand area shows the logo, product name and company or period information on
  separate lines.
- Settings, Appearance uses visual theme cards with eight presets.
- Settings, Backup supports consistent backup of the database and uploaded files, with
  download, delete, verify and restore. Automatic backups default to 09:00 and 17:00
  Hong Kong time, can be changed in the interface and use a single rolling file. Manual
  backups are always full backups. The last 180 backups are kept.

### 2.2 AI workspace

- Document creation, posting, queries, reconciliation and exports happen in one page.
- Receipts are read for content and business nature before the system suggests accounts
  and documents. It asks only when the receipt really lacks an amount, date or
  counterparty.
- Rules cover common expenses, services, rent, payroll, bank fees and related parties,
  and record learning results.
- Mobile browsers can take a photo or choose a file and use the same confirmation flow.

### 2.3 Documents, email and currencies

- Settings, Email was rebuilt with grouped cards, a connection test and separate sender
  information.
- Quotes, sales orders, invoices, bills, purchase orders and credit notes can be emailed.
  The template matches the printed document.
- Invoice drafts can be edited again. The number stays, validation runs again and the
  review state resets. Posted invoices must be reversed first.
- Customer notes and terms stay internal and are not printed on invoice PDFs.
- Company footer on invoice, bill, credit note, quote and order PDFs sits 10 mm above the
  bottom edge and repeats on every page.
- Navigation follows the accounting flow: Sales, Purchases, Banking, Accounting,
  Reports, Settings.
- Foreign currency documents show the original amount, rate and functional amount. Each
  document uses one language only.

### 2.4 Lists and menus

- Invoice and bill lists show received or paid progress with settled ratio and remaining
  amount.
- Reports has three entries: Report centre, Financial statements and Profits tax.
- AI assistant, agent and AI dashboard pages are grouped under AI workspace. The agent
  configuration page is named Agent management.

### 2.5 Dashboard and financial analysis

- Company financial analysis can be generated for this month, a chosen month, calendar
  year, fiscal year, since inception or a custom period.
- Reports contain key figures, charts, financial statements and written commentary.
  Numbers come from deterministic report functions. When no model is available, the text
  falls back to deterministic wording and states the data source and period.
- PDF and DOCX export in three languages. The dashboard does not embed the report.

### 2.6 Code and documentation

- Source files carry a consistent copyright and SPDX header.
- Removed old brand names, abbreviations and references to specific cloud, mail or panel
  providers.
- Removed old refactoring plans, construction reports, test reports and prompts from
  `files`. Rewrote README, HOWTO, deployment guide, developer guide and release notes.
- Removed the old backend `docs/` and `docs-legacy/` directories.

### 2.7 Deployment packages

- Automatic package: asks for a domain or IP, plus an optional certificate email for a
  domain. Installs Nginx, MariaDB, PHP-FPM, Python, Node.js, OCR and PDF dependencies and
  Certbot. Writes a dedicated PHP-FPM pool, site, systemd services and a backup timer.
  Uses a public certificate when domain and email are available, otherwise self-signed.
- Manual package: the operator prepares the system. The script creates directories,
  database, account and sample configuration only. It does not install packages, create a
  system account or start services.
- The old AI deployment package is removed. AI features remain inside the application.

## 3. Acceptance record

### 3.1 Automated tests

Backend unit and API tests cover AI command boundaries, backup create, verify and
restore, backup API permissions, foreign currency documents, period resolution and report
checks, AI fallback, and PDF/DOCX export. The 2026-11-21 update runs 9 files with 131
test cases, all passing.

### 3.2 Source checks

- PHP: 104 files pass `php -l`.
- Python: 51 files compile.
- Node: 9 files pass `node --check`.
- Shell: build and install scripts pass `bash -n`.

### 3.3 Package checks

- Archive paths are safe: no absolute paths, `..` or symlinks.
- `MANIFEST.txt` hashes match the archive contents.
- `.env`, runtime directories, virtual environments, backups, exports, keys and
  production baselines are rejected.
- Seed SQL inserts only into `entities`, `accounts` and `tax_rates`.
- Common API key and private key patterns are not found.

### 3.4 Isolated install on an empty database

A manual install was run in a temporary directory with an empty database:

- 50 tables created. Foreign key checks are disabled during creation so the account
  table can be imported before the company table.
- One company row, 108 account rows, 12 tax rate rows and one administrator. All
  business tables are empty.
- `/health` returns 200 and the administrator can sign in.
- Trial balance, P&L, balance sheet, cash flow and summary endpoints return 200.
- Financial analysis produces a PDF starting with `%PDF-` and a valid DOCX zip.
- Running the installer again does not change row counts, password hashes, `.env` or the
  credentials file.
- Generated Nginx, PHP-FPM and systemd files pass syntax checks.
- Credentials file mode is 600. The upload directory is writable only by the service
  account and the web account.

### 3.5 Installer inputs and certificate paths

Three entry paths were checked: domain only, domain then certificate email, and pure IP.
Domain plus email uses the public certificate path. A pure IP or a blank email switches
to the self-signed certificate without calling Certbot. `LTBOOKS_SSL_MODE=letsencrypt`
requires an email; a missing or malformed address stops the installer. A non-interactive
run without `LTBOOKS_DOMAIN` exits with an error instead of using a placeholder domain.

## 4. Known points

1. One real ledger entry records 20,000 of interest under short-term borrowings, which is
   a non-cash item. It is shown separately as `cash_unclassified` in reports. The system
   does not rewrite entries to force a balance.
2. The automatic package performs a full system install on Debian or Ubuntu only.
3. Self-signed certificates are for internal use and acceptance. Production must use a
   real certificate.

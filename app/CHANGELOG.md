# Changelog

## Maintenance update, 2026-11-21 (version stays 1.0.0)

This is an online maintenance update. It does not change the data model and needs no
migration. Packages keep the 1.0.0 name.

### Languages (Simplified Chinese, Traditional Chinese, English)

- Added missing English and Traditional Chinese interface strings (3310 to 3349
  entries), covering banking, search, empty states, vouchers and expenses, attachment
  hints, recurring documents and the eight theme names.
- Added dynamic SMTP sentence rules (outgoing server, SSL, STARTTLS, authentication).
- Fixed Chinese headers left in real P&L PDFs: this period, prior year, change and the
  comparison subtitle now follow the requested language. The Traditional Chinese term
  for change was corrected.
- Fixed untranslated journal PDF status values (`manual` to `Manual entry`, `posted` to
  `Posted`).
- PDF error details now follow the requested language instead of mixing an English
  prefix with a Chinese detail. Unknown report types keep the supplied type name.
- The annual report package `MANIFEST.txt` is translated: title, generation
  information, report notes, sales and purchase units, and failure flags. File names
  stay English for cross-platform use.

### Banking and interface

- Bank statement import now starts with a list: imported statements show time, file
  name, account, period and line count, with links to the account transactions and the
  original file. + Import statement opens a dedicated upload screen with no list. Parsed
  rows appear below and are written only after a confirmation dialog.
- The upload area keeps only bank account and file. The old import form fields (file
  name, opening and closing balance, debit and credit totals, period, CSV detail) were
  removed. Balances and period come from the parsed data; the period is the minimum and
  maximum row date.
- Parsing keeps the original statement under `storage/bank-statements/<entity>/`, named
  by SHA-256 with mode 600. New list and download endpoints serve it through
  `download.php?statement=<batch>`.
- Removed the duplicate New invoice entry from the Sales menu. The invoice list keeps
  its + New invoice button.
- Chart of accounts was reorganised: each category heading appears once and shows the
  account count. Add account uses a full-width panel with a six-column grid (two columns
  on narrow screens). The action column is right aligned and wider. The table is limited
  to 68vh with a sticky header, and the counters remain in the toolbar.
- Each journal row has an Attachments button with the current count. Files can be
  uploaded (multiple), viewed and deleted from the entry detail area. `GET /journal`
  returns `file_count`. Attachments stay in `doc_files` with `doc_type=journal`.
  Auditors have read-only access.
- Journal actions now open a dedicated page: `?p=journal-view&id=...` handles entry
  details, draft edit and delete, reversal with a reason and confirmation, and
  attachments. The list keeps only the Voucher button, which opens a PDF in a new tab.
  Entry links in the day book and document detail pages point to the new page.
- The journal list was reorganised to match the chart of accounts: a toolbar with search,
  counts for this page, all entries and drafts, plus Print vouchers on this page and
  Manual entry. Rows are grouped by period with line count and debit/credit subtotals.
  The table is limited to 68vh with a sticky header and a wider, right-aligned action
  column.
- Fixed the journal search field style and interaction: `input[type=search]` now uses the
  global input style (light border, white background, 28px height). The toolbar wraps
  into search, counts and actions on narrow screens. The row Voucher button opens a PDF
  in the current language directly; the old dropdown was clipped by the table scroll
  container. Status pills stay on one line and the bulk print menu aligns right.
- The SMTP connection test card now matches the SMTP settings card: the recipient field
  spans the row, the hint sits below it, and the button is right aligned as a primary
  action. Cards use their content height so the test card no longer stretches.
- Added global `input[type=email]` styling. The recipient field no longer uses the
  browser default black border; border, background, 36px height and radius match other
  fields.
- Unified input styles across the application: `input[type=time]` was added (backup
  times no longer use the browser default). Journal search and chart of accounts
  toolbars now match the list toolbar at 34px with a light border and 13px text.
  Add-account form fields returned to the standard 36px. Audit pager inputs, the AI
  command box and hidden file inputs keep their own styles.

### Deployment packages

- Two packages replace the previous three:
  - **Automatic** (`auto`): asks for a domain or server IP, plus an optional certificate
    email when a domain is used. Installs all dependencies, initialises the database and
    configures Nginx, PHP-FPM, systemd, the backup timer and HTTPS.
  - **Manual** (`manual`): the operator prepares the system. The script only deploys the
    application and configuration.
- The automatic installer asks for a Let's Encrypt certificate email after the domain.
  A blank value keeps the self-signed certificate. A pure IP, `selfsigned` or `off` mode
  does not ask. `LTBOOKS_SSL_EMAIL` skips the prompt. `LTBOOKS_SSL_MODE=letsencrypt`
  requires an email and validates the format.
- Removed the AI deployment package. `install-ai.sh`, `ai-deploy.py` and
  `ai-deploy.conf.example` are gone.
- The installer detects a pure IP, switches to a self-signed certificate and prints a
  note. A non-interactive run without `LTBOOKS_DOMAIN` stops with an error instead of
  using a placeholder domain.
- Deployment manual, HOWTO, deployment guide, developer guide and release notes now
  describe the two packages.

### Backup and operations

- Automatic backup now uses a single rolling file: the first run writes a full archive,
  then each run atomically replaces it with the latest full snapshot. The directory keeps
  one automatic backup and restore needs no chain. Old incremental packages are merged
  and removed on the first rolling run. The system crontab calls `tick` every minute, at
  09:00 and 17:00 Hong Kong time by default, with `flock` to prevent overlap, keeping 180
  files.
- Completed and verified the first full backup: 50 tables plus 305 attachments with a
  SHA-256 manifest.
- Raised PHP-FPM concurrency from 5 to 20 (`start_servers` 5, spare 5 to 10), removing
  the `server reached pm.max_children` warning.
- Added `/etc/logrotate.d/ledu-api`: daily rotation, 14 files, compression and
  `copytruncate`.
- Committed release baselines for the app and web repositories so the working tree is
  clean and can be rolled back.

### Regression

- Backend tests grew to 9 files and 131 cases, all passing.
- All 104 PHP files pass `php -l`.
- Downloaded 69 real PDFs, 18 error cases and the annual package in three languages. No
  fixed text was mixed into another language; remaining Chinese characters are business
  text or legal names that must be preserved.

## Version 1.0.0, 2026-11-19

First official release.

### Features

- AI workspace: create documents, post entries, query figures, reconcile and export in
  natural language. Receipts are confirmed before anything is written.
- Mobile browsers can photograph a receipt, upload it as an attachment and extract it.
- Full sales and purchase flow: customers, vendors, quotes, sales orders, invoices,
  bills, purchase orders, payments, credit notes and recurring documents.
- Document email for quotes, sales orders, invoices, bills, purchase orders and credit
  notes.
- Multi-currency: documents show the original amount, rate and functional amount;
  reports aggregate in the functional currency.
- Invoice and bill lists show received and paid progress.
- Financial analysis for this month, a chosen month, calendar year, fiscal year, since
  inception or a custom period. Includes charts, financial statements and written AI
  commentary, exported as PDF or DOCX in three languages.
- Eight themes (six light, two dark).
- Backup and restore for the database and uploaded files. Automatic mode runs at 09:00
  and 17:00 daily and keeps 180 days by default.
- Three clean deployment packages: automatic, AI-assisted and manual.

### Quality and security

- Report figures come from deterministic code. The AI does not generate numbers and
  falls back to deterministic text when a model is unavailable.
- Attachment downloads validate the resolved path. SQL is fully parameterised. Writes
  require manual confirmation.
- Removed old brand names and third-party service references. Product name is LtBooks.
- Source files carry copyright and SPDX identifiers. Released under MIT.
- 71 unit and API regression cases passed. All three installers passed structure, hash,
  syntax and empty-database installation checks.

### Known items

- One real ledger entry records 20,000 of interest under short-term borrowings, a
  non-cash item. Reports show it separately as `cash_unclassified`; the system does not
  auto-balance or hide it.
- A clean package starts with HKD and a 12-31 year end. Change both after login to match
  the company.

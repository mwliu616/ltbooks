# Lt-AI-Books 1.1 Release Notes

Release date: 2026-11-24
Version: 1.1
Copyright (c) 2026 LEDU TECH CO., LIMITED
License: MIT

## 1. Rebranding & version bump, 2026-11-24 (version 1.1)

The product is renamed to **Lt-AI-Books** and the version is bumped to **1.1**.
No data model change and no migration are required.

### What changed

| Item | Change |
| --- | --- |
| Product name | `LtBooks` → `Lt-AI-Books` on every user-visible surface: page titles, login mark, footer, PDFs, outgoing emails, financial analysis reports and release docs. Technical identifiers (PHP constants, the `ltbooks-api` service name, table names, session cookie) are intentionally left unchanged. |
| Version | `1.0.x` → `1.1` |
| Sales invoice AI precheck | Fixed HTTP 500 from `POST /agents/precheck` for `workflow=post_invoice`: the invoice lookup referenced a non-existent `customer_name` column; corrected to `supplier_name`. The AI gatekeeper that reviews a sales invoice before posting works again. |

### Verification

End-to-end run of the purchase, sales, bank and accounting flows on both the manual
desk and the AI desk: every journal entry and every account-balance movement is
correct. 76/76 assertions pass, covering bank statement posting (income → Dr Bank /
Cr Revenue; expense → Dr Expense / Cr Bank) and manual journal reversal, plus the
global debit/credit balance of all posted entries.

## 0. Maintenance update, 2026-11-21

This update does not change the data model and needs no migration. Packages keep the
1.1 version number.

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
| Bank accounts | **New bank account** lets you pick an existing 112x bank account; picking one sets the currency from that account, and a mismatched currency is rejected. Blank keeps the reuse-or-create behaviour. The list shows each account's GL account and groups by currency |
| AI customer intake | On the customer form, upload a business card / registration certificate or paste the text; the AI agent decides company vs individual and fills the empty fields (name, contact, phone, email, address, BR number…) for review before saving |
| Multiple LLM providers | Settings → LLM manages several OpenAI-compatible providers (name, base URL, model, temperature, key). One is active and used by AI Q&A, document extraction and the agents; switching takes effect immediately. Keys are masked in the UI and each provider can be tested on its own |
| Vendor bank details | The supplier form now captures bank name, account name, account number, SWIFT/BIC and bank address; they show on the supplier profile for payment reference |
| FX maintenance | The rates page has a **Refresh now** button that runs the same ECB/Frankfurter fetch as the daily 09:00 job and reports the date, pair count and currencies written |
| Cross-currency exchange | **Transfer** now has an **FX exchange** mode: pick the sold and bought accounts and enter the HKD/USD amounts actually dealt; the deal rate is derived and shown read-only, no fee is asked for on the form (bank charges are recorded separately once the statement arrives). The entry is booked at the bank's real rate and the spread goes to 4410 realised exchange differences. Two placeholder bank lines keep balances current; after importing the HSBC statement, **Claim lines** replaces them with the real statement lines. An exchange can be voided (entry reversed, lines released). Bank-to-bank transfers in the same currency are unchanged |
| Payment voucher PDF | Payment and receipt details now have a **Print / PDF** menu (Simplified Chinese, Traditional Chinese, English). A payment voucher prints the settled documents and the supplier's payee bank details — bank, account name, account number, SWIFT/BIC and bank address — for remittance and review |
| Payment allocation | The **Register payment** form no longer asks for the amount twice. Tick the documents to settle; each allocation defaults to its outstanding balance and can be edited, and the payment amount is totalled automatically. Cross-currency selections switch the amount to manual entry with a reminder to use the settlement-date rate. **Overpay / prepay** unlocks a higher amount; the unallocated part is posted to 1150 Prepayments (payment) or 2120 Contract Liabilities (receipt) |
| Cross-currency settlement | Allocation limits are compared in functional currency, so a large HKD bill paid from a smaller USD amount is no longer rejected. Realised exchange differences on payments are derived from the cash actually applied, posted to 4410 with the correct debit or credit side, and stored consistently on the settlements and the payment record |
| Payment settlement (HKFRS) | Supplier bills are recognised on confirmation as expense/cost plus input tax against trade payables. Settling the payment clears the payable, credits the bank account chosen on the payment, and books the difference between the cash paid and the payable's carrying amount to 4410 as a realised exchange difference under HKAS 21. Overpayments are carried as 1150 prepayments; over-receipts as 2120 contract liabilities |
| Purchase order line accounts | Each purchase order line now carries its own expense/cost account. Converting the order to a bill keeps those accounts line by line, so a single bill can post to several expense accounts instead of one default account |
| Sales line revenue accounts | Each sales order and invoice line now carries its own revenue account. Posting an invoice credits each revenue account in proportion to its line amounts (instead of one fixed 4100), and converting a sales order keeps the accounts line by line |
| AI precheck on manual workflows | Every manual form now runs a pre-submit review by the matching role agent: purchase/sales orders go to the document analyst, bills/invoices/expenses/manual journals to the accountant, payments/receipts to the cashier, and draft posting to the review gatekeeper. The panel shows verdict, findings, suggested accounts and a journal preview; hard checks (account direction, debit/credit balance, locked periods, allocation limits) are deterministic, the model only adds judgement |
| Account suggestions | The bill form can suggest expense/cost accounts from the subject, vendor and line descriptions. Keyword rules run first and the configured AI model ranks the candidates; suggestions are shown with a reason and are only applied when the user clicks one, so the final account stays a human decision |

## 1. Artifacts

| Artifact | Path |
| --- | --- |
| Automatic package | `releases/Lt-AI-Books-Ver1.1-auto-clean-20261123.tar.gz` |
| Manual package | `releases/Lt-AI-Books-Ver1.1-manual-clean-20261123.zip` |
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

- Product name is Lt-AI-Books throughout: browser title, document footer, report footer,
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

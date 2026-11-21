# LtBooks 1.0 Developer Guide

This document describes the code layout, request flow, data rules and release process.

## 1. Code locations

| Layer | Path | Notes |
| --- | --- | --- |
| Front end | `/opt/ltbooks/web` | Server-rendered PHP. `index.php` is the only entry point. It can be reached through a `/var/www/ltbooks` symlink |
| Backend | `/opt/ltbooks/app` | Flask API, ledger core, AI agents, command-line tools |
| Reports and exports | `/opt/ltbooks/storage` | Generated reports, CSV exports, OCR temporary files |
| Receipts | `/opt/ltbooks/uploads` | Original uploads, streamed after PHP checks the session |
| Backups | `/opt/ltbooks/backups` | Full backups and the rolling archive |
| Database | MariaDB | 50 tables. Database name comes from `LEDU_DB_NAME` |
| Release files | `<frontend>/files/` | Documentation and `releases/` |

The front end and backend directories are independent. They communicate over HTTP with
an internal token, so they can run on different machines if the port and token match.

## 2. Request flow

```
Browser
  |  GET /?p=invoices
  v
index.php
  |- loads lib/* (auth, i18n, ui, api, theme, version, help)
  |- checks the session (lib/auth.php)
  |- renders the header and navigation ($PAGES / $NAV)
  \- includes pages/invoices.php
          |  api_get('/invoices?...')
          v
   lib/api.php (curl; X-Ledu-Token / X-Ledu-Session / X-Ledu-Role / X-Ledu-User)
          v
   api.py (Flask, 127.0.0.1:8099)
          |- authentication and role checks
          |- core/reports.py, core/service.py, core/numbering.py and others
          \- core/db.py (parameterised SQL, transactions, error translation)
          v
       MariaDB
```

Every write runs inside a transaction. Amounts use `Decimal`; binary floating point is
not used for accumulation. Report figures come only from deterministic functions in
`core/reports.py`.

## 3. Front end structure

```
index.php              Entry, route table, navigation, session and language setup
lib/
  auth.php             Login, session, permissions, upload directory constant
  api.php              Backend HTTP client and error normalisation
  ui.php               View helpers: formatting, badges, tables, pagination, dialogs
  i18n.php             Language selection and t()
  theme.php            8 theme presets
  version.php          Version and build number
  help.php             In-page help per module
  lang/zh_hk.php       Simplified to Traditional dictionary
  lang/en.php          Simplified to English dictionary
  zh_hk_auto.php       Generated Traditional mapping supplement
pages/                 One file per page, named by business area
assets/                app.css, icons, fonts and small interaction scripts
```

Page rules:

- Pages render and handle forms. They never connect to the database.
- All output goes through `e()`. Query and form values are read, then validated.
- Amounts use the shared `money()` helpers; do not hand-format decimals.
- A new page registers in `$PAGES` (title and group), `$NAV` (entry) and `$SELF_HEAD`
  when it renders its own page header.

## 4. Backend structure

```
api.py                 All HTTP routes (Flask)
config.py              Paths and environment variables
jsonenc.py             JSON encoding for Decimal and dates
core/
  db.py                Connections, transactions, exception translation
  auth.py              PBKDF2 passwords, users, sessions
  service.py           Services: documents, settlement, posting
  numbering.py         Document and voucher numbers
  reports.py           Financial statements and trial balance
  financial_analysis.py Period resolution, analysis data, AI text, PDF/DOCX export
  pdf.py               Document PDFs (WeasyPrint)
  pdf_reports.py       PDF rendering for 17 report types
  mailer.py            SMTP sending with attachments
  backup.py            Consistent database and attachment backup, verify, restore
  fx.py                Exchange rates and period-end revaluation
  tax.py               Profits tax calculation
  ocr.py               Receipt text extraction
  doc_analyze.py       Receipt structuring and business nature detection
  hkfrs15.py           HKFRS 15 five-step model
  contracts.py         Contracts and performance obligations
  bankrec.py           Bank reconciliation matching
  opening.py           Opening balance import
  settings.py          App settings; interface values override .env
  audit.py             Audit log with hash chain
  i18n.py              Backend translations, including PDF errors and pack manifest
  agent.py             Agent call layer
  agents/              Registry, actions, runtime, tools, model client, learning
agent/                 Bundled Node accounting check agent
bridge/agent-bridge.mjs Node bridge called from Python
sql/                   Schema and incremental scripts
tests/                 Unit and API regression tests
tools/                 Install, package, verify, backup and maintenance scripts
```

## 5. Data model

- Every business table has `entity_id`. The clean package ships one company record.
- Entries use `journal_entries` and `journal_lines`. Debits and credits must balance;
  triggers and the API both enforce it.
- Quotes, orders, invoices, bills, credit notes and payments share numbering rules and a
  status model.
- Foreign currency documents store the original amount, rate and functional amount.
  Reports aggregate in the functional currency.
- Attachments are linked to their document and stored in the upload directory.
- Interface settings live in `app_settings`. `.env` keeps only startup values.
- `audit_log` records key actions and supports hash chain verification.

## 6. Amounts and reports

1. Amounts use `Decimal` and `DECIMAL` columns. Binary floating point is not used.
2. Reports read posted entries only. Draft documents are excluded.
3. Period resolution lives in `financial_analysis.resolve_period` and supports
   `this_month`, `month`, `calendar_year`, `fiscal_year`, `inception` and `custom`.
4. The fiscal year comes from `fiscal_year_end_mmdd` on the company record.
5. The AI writes narrative text only. Prompts forbid inventing figures. When no model is
   available, deterministic text is used.
6. PDF and DOCX exports reuse the same data as the page so numbers cannot diverge.

## 7. AI and confirmation

```
User command or receipt
   v
doc_analyze (content and business nature)
   v
agents.actions (account and document suggestions)
   v
ai_actions row (status pending)
   v
Result card in the interface -> user confirms -> service layer writes -> audit
```

- Agents cannot write to the database directly. `tools_write` requires a confirmed
  action ID.
- Receipt analysis combines document text, counterparty and learned results. It asks
  only for fields that are really missing.
- Mobile uploads use the same endpoint as the desktop interface.
- The bundled `agent/` is reached through `bridge/agent-bridge.mjs` and needs no
  external path.

## 8. Internationalisation

- Interface strings are written in Simplified Chinese and translated by `t()`.
- `lib/lang/zh_hk.php` and `lib/lang/en.php` are maintained by hand.
- `lib/zh_hk_auto.php` and `lib/zh_hk_chars.php` provide Traditional Chinese fallbacks.
- Backend text lives in `core/i18n.py` and `core/lang_dict.json`.
- The annual report package manifest text is in `PACK_MANIFEST` in `core/i18n.py`.
- Add all three languages for new strings. Documents must not mix languages.

## 9. Local development

```bash
# Front end
cd /opt/ltbooks/web
php -S 127.0.0.1:8080

# Backend
cd /opt/ltbooks/app
LEDU_ENV_FILE=.env ./venv/bin/python api.py
```

Set `LEDU_API_BASE` and `LEDU_API_TOKEN` for the PHP side.

## 10. Tests

```bash
# PHP syntax
find /opt/ltbooks/web -name '*.php' -print0 | xargs -0 -n1 env -u LD_LIBRARY_PATH php8.3 -l

# PHP unit test
cd /opt/ltbooks/web && php tests/report_period_test.php

# Backend
cd /opt/ltbooks/app && PYTHONPATH=. ./venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## 11. Build and release

```bash
cd /opt/ltbooks/app
LTBOOKS_BUILD_DB=ltbooks ./tools/build_release.sh
```

The script:

1. Copies the current working tree, excluding `.env`, `venv`, runtime storage, old docs
   and credentials.
2. Exports the 50-table schema with `mysqldump --no-data --routines --triggers`.
3. Exports only `entities`, `accounts` and `tax_rates`.
4. Writes the auto and manual packages with `.sha256`, `MANIFEST.txt` and
   `PACKAGE.json`.
5. Runs a syntax check on all shell, Python, PHP and Node files.

Installer prompts in the automatic package:

1. Domain name or server IP.
2. Optional Let's Encrypt certificate email when a domain is used. A pure IP,
   `selfsigned` or `off` mode skips this prompt.

`LTBOOKS_DOMAIN` and `LTBOOKS_SSL_EMAIL` skip the prompts.

Verify a package:

```bash
python3 tools/verify_release.py <package> [...]
```

Checks include archive path safety, manifest hashes, forbidden files, seed table
whitelist, key and private key signatures, and syntax.

## 12. Common changes

| Task | Where |
| --- | --- |
| Add a page | Create a file in `pages/`. Register `$PAGES`, `$NAV` and translations |
| Add interface text | Write Simplified Chinese in the source. Add entries to `lib/lang/zh_hk.php` and `lib/lang/en.php`. English values must not contain Chinese characters |
| Add PDF text | Add the three languages to `core/i18n.py`. Use `core/pdf.py` for documents and `core/pdf_reports.py` for reports. Extend `test_pdf_i18n.py` |
| Add a document type email | Add a Send email link on the detail page pointing to `?p=email&docType=...`. Extend `email/doc-info` and the template |
| Add a theme | Add a preset in `lib/theme.php` that overrides colour variables only |
| Add an agent | Register it in `core/agents/registry.py`. Provide prompts and read-only tools. Writes still require confirmation |
| Change backups | `core/backup.py` and `tools/auto_backup.py`. Update the settings page text |
| Change the installer | `tools/install.sh`. Update `tools/package-readme.en.md` and this document. Rerun the interactive and non-interactive prompt cases |

## 13. Coding conventions

- Keep the copyright and SPDX header in every source file.
- Comments explain why, not what. Use Simplified Chinese for comments unless the file is
  in English.
- No hard-coded production domains, directories, keys or third-party endpoints.
- Values that affect accounting (amounts, rates, tax, periods) must stay deterministic
  and testable.

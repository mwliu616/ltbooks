# Lt-AI-Books

Lt-AI-Books is an open-source accounting and financial reporting system for small and
medium businesses in Hong Kong. It keeps a double-entry general ledger, a chart of
accounts, sales and purchase documents, bank statement imports and HKFRS financial
statements in one self-hosted web application.

The interface runs on PHP 8.3, the ledger and API on Python 3.12 (Flask), and the data
lives in MariaDB 10.11. Every amount, tax figure and report total is calculated by
deterministic code; the AI features only read documents, suggest account codes and write
commentary, and never post an entry without human confirmation.

## Features

- **Accounting**: chart of accounts, opening balances, manual journals, exchange rates,
  review queue, period close and lock, period-end revaluation.
- **Sales**: customers, quotes, sales orders, invoices, receipts, credit notes and
  recurring invoices, with email delivery and original/functional currency amounts.
- **Purchases**: vendors, purchase orders, bills, expenses, payments and recurring bills.
- **Banking**: multiple bank accounts, bank rules, statement import that keeps the
  original file, reconciliation and transfers.
- **Reports**: trial balance, statement of profit or loss and OCI, statement of financial
  position, cash flows, aging, bank balances, exchange gain or loss, profits tax,
  financial ratios and a complete financial statement set, exportable to PDF.
- **Financial analysis**: month, year, fiscal year, inception or custom period, with
  deterministic figures, charts and written commentary in English, Traditional Chinese
  or Simplified Chinese.
- **AI workspace**: parse receipts and invoices, draft entries and query figures in
  natural language; results stay in a review queue until a person confirms them.
- **Operations**: automatic rolling backups, manual backup and restore, audit hash chain,
  SMTP email, eight visual themes and a three-language interface.

## Technology

| Layer | Stack |
| --- | --- |
| Front end | PHP 8.3, server-rendered pages, Nginx + PHP-FPM |
| API and ledger | Python 3.12, Flask, PyMySQL, WeasyPrint |
| Database | MariaDB 10.11, `utf8mb4`, 50 tables with triggers and routines |
| Agent | Bundled Node.js accounting checker |

The browser never connects to the API directly. PHP talks to `127.0.0.1:8099` with an
internal token stored in `app/.env`, and session cookies require HTTPS.

## Quick start

On a new Debian 12 or Ubuntu 22.04+ server with internet access, run the automatic
installer as root:

```bash
sha256sum -c Lt-AI-Books-Ver1.1-auto-clean-20261123.tar.gz.sha256
tar -xzf Lt-AI-Books-Ver1.1-auto-clean-20261123.tar.gz
cd Lt-AI-Books-Ver1.1-auto-clean-20261123
sudo ./install.sh
```

The installer asks for a domain name or server IP, then for an optional Let's Encrypt
email address, installs Nginx, MariaDB, PHP, Python, Node.js and the OCR/PDF
dependencies, and configures HTTPS. The first administrator password is written to
`<app dir>/storage/initial-credentials.txt` (mode 600); change it after the first login
and delete the file.

For hosting panels and internal networks, use the manual package and `install-manual.sh`
instead. Both packages are clean: an empty schema, one company record, 108 accounts and
12 tax rates, with no business data.

- Automatic install: `Lt-AI-Books-Ver1.1-auto-clean-20261123.tar.gz`
- Manual install: `Lt-AI-Books-Ver1.1-manual-clean-20261123.zip`
- Release page: https://github.com/mwliu616/ltbooks/releases/tag/v1.1

## Repository layout

```
app/    Flask API, ledger core, bundled agent, installer and release tools
web/    PHP front end, translations, documentation and deployment packages
```

## Documentation

- Installation and daily use: [web/files/HOWTO.md](web/files/HOWTO.md)
- Deployment parameters and troubleshooting: [web/files/DEPLOYMENT.md](web/files/DEPLOYMENT.md)
- Deployment guide, Simplified Chinese: [web/files/DEPLOYMENT.zh-CN.md](web/files/DEPLOYMENT.zh-CN.md)
- Deployment guide, Traditional Chinese: [web/files/DEPLOYMENT.zh-HK.md](web/files/DEPLOYMENT.zh-HK.md)
- Product overview: [web/files/README.md](web/files/README.md)
- Source layout and data flow: [web/files/DEVELOPMENT.md](web/files/DEVELOPMENT.md)
- Release and acceptance notes: [web/files/RELEASE.md](web/files/RELEASE.md)

## Build and packaging

```bash
cd app
LTBOOKS_BUILD_DB=ltbooks ./tools/build_release.sh
```

This produces both clean installers in `web/files/releases/`, each with a matching
`.sha256` file and an internal `MANIFEST.txt`.

## License

MIT. Copyright (c) 2026 LEDU TECH CO., LIMITED.

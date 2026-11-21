# LtBooks

LtBooks is an accounting and financial reporting system for small and medium businesses
in Hong Kong. It runs on PHP 8.3 (server-rendered UI), Python 3.12 (API and ledger) and
MariaDB 10.11.

Amounts, tax and report figures are calculated by deterministic code. The AI features
only extract document data, suggest account classifications and write commentary.

## Repository layout

```
app/    Flask API, ledger core, AI agents, installer and release tools
web/    PHP front end: pages, translations, docs and deployment packages
```

The front end never connects to the database. It calls the API on `127.0.0.1:8099`
with an internal token stored in `app/.env`.

## Download

Installers are attached to the latest release:

https://github.com/mwliu616/ltbooks/releases/tag/v1.0.0

- `LtBooks-Ver1.0-auto-clean-20261121.tar.gz` (automatic install)
- `LtBooks-Ver1.0-manual-clean-20261121.zip` (manual install)
- matching `.sha256` files

## Documentation

- Product overview and capabilities: [web/files/README.md](web/files/README.md)
- Installation and daily use: [web/files/HOWTO.md](web/files/HOWTO.md)
- Deployment parameters and troubleshooting: [web/files/DEPLOYMENT.md](web/files/DEPLOYMENT.md)
- Deployment guide, Simplified Chinese: [web/files/DEPLOYMENT.zh-CN.md](web/files/DEPLOYMENT.zh-CN.md)
- Deployment guide, Traditional Chinese: [web/files/DEPLOYMENT.zh-HK.md](web/files/DEPLOYMENT.zh-HK.md)
- Source layout and data flow: [web/files/DEVELOPMENT.md](web/files/DEVELOPMENT.md)
- Release and acceptance notes: [web/files/RELEASE.md](web/files/RELEASE.md)

## Build and packaging

```bash
cd app
LTBOOKS_BUILD_DB=ltbooks ./tools/build_release.sh
```

This produces two clean installers in `web/files/releases/`: an automatic package for
new Debian/Ubuntu servers and a manual package for existing environments. Both contain
an empty schema, one company record, 108 accounts and 12 tax rates.

## License

MIT. Copyright (c) 2026 LEDU TECH CO., LIMITED.

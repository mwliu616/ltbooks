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

## Documentation

- Product overview and capabilities: [web/files/README.en.md](web/files/README.en.md)
- Installation and daily use: [web/files/HOWTO.en.md](web/files/HOWTO.en.md)
- Deployment parameters and troubleshooting: [web/files/DEPLOYMENT.en.md](web/files/DEPLOYMENT.en.md)
- Source layout and data flow: [web/files/DEVELOPMENT.en.md](web/files/DEVELOPMENT.en.md)
- Release and acceptance notes: [web/files/RELEASE.en.md](web/files/RELEASE.en.md)

Simplified Chinese and Traditional Chinese editions sit next to these files with
`.zh-CN` and `.zh-HK` suffixes where available.

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

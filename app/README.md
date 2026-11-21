# LtBooks Backend (Python API)

The ledger core and HTTP API for LtBooks 1.0: Flask, PyMySQL and MariaDB. Amounts and
report figures come from deterministic code. The AI features only extract data, suggest
classifications and write commentary.

- Copyright (c) 2026 LEDU TECH CO., LIMITED
- License: MIT (see `LICENSE`)

## Quick start

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env        # database, token, paths
./venv/bin/python api.py    # defaults to 127.0.0.1:8099
```

Health check: `curl http://127.0.0.1:8099/health`

## Configuration (`.env`)

| Key | Purpose |
| --- | --- |
| `LEDU_DB_HOST` / `PORT` / `NAME` / `USER` / `PASSWORD` | MariaDB connection |
| `LEDU_API_HOST` / `LEDU_API_PORT` | Listener. Default `127.0.0.1:8099` |
| `LEDU_API_TOKEN` | Internal token from the front end. The backend refuses to start if it is too short |
| `LEDU_STORAGE_DIR` | Application data (certificates, temporary files) |
| `LEDU_UPLOAD_DIR` / `LEDU_UPLOAD_DIRS` | Receipt and attachment directories. Multiple paths are separated by colons |
| `LEDU_BACKUP_DIR` / `LEDU_BACKUP_KEEP` | Backup directory and retention count |
| `LEDU_LLM_*` / `LEDU_VISION_API_KEY` | Model and vision endpoints. Interface settings take precedence |
| `LEDU_SMTP_*` | Email. Interface settings take precedence |
| `LEDU_NODE_BIN` | Node executable used by the agent bridge |

Restart after changing `.env`: `systemctl restart ledu-api`. In production the file should
be 640, owned by `root:ltbooks`, and never committed to a repository.

## Layout

```
api.py           HTTP routes and permission checks
config.py        Paths and environment variables (LEDU_APP_DIR / LEDU_ENV_FILE override)
core/            Ledger, reports, analysis, backup, email, AI agents
  backup.py           Full backup, single rolling file, retention
  financial_analysis  Financial analysis (PDF and DOCX in three languages)
  pdf_reports.py      PDF rendering for 17 report types
  i18n.py             Fixed PDF text in Simplified Chinese, Traditional Chinese and English
agent/           Bundled Node accounting check agent
bridge/          Python to Node bridge
sql/             Schema and incremental scripts
tools/           Install, package, verify, backup and maintenance scripts
tests/           9 test files, 131 unit and API regression cases
```

## Tests

```bash
PYTHONPATH=. ./venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

The suite has 9 files and 131 cases and runs in about 7 seconds. It uses controlled input,
does not touch the production ledger and does not call a real model.

Run the PDF language regression alone:

```bash
PYTHONPATH=. ./venv/bin/python -m unittest tests.test_pdf_i18n -v
```

## Backup and operations

```bash
# Full backup, also the base for later rolling updates
./venv/bin/python tools/auto_backup.py create --full
# Merge the latest data into the same file at the configured Hong Kong time
./venv/bin/python tools/auto_backup.py tick
# List and prune
./venv/bin/python tools/auto_backup.py list
./venv/bin/python tools/auto_backup.py prune --keep 180
```

Automatic backups use a single rolling file. The first run writes a full archive; later
runs atomically replace it with a new full snapshot. The directory keeps one automatic
backup and restoring needs no chain of earlier files. The production instance at
`/opt/ltbooks` runs `tick` from the system crontab every minute, at 09:00 and 17:00 Hong
Kong time by default, and keeps 180 backups. The backend log is
`/var/log/ledu-api.log`, rotated daily by `/etc/logrotate.d/ledu-api` with 14 files kept.

PDF export uses WeasyPrint 70 and Poppler. Check the text layer of a three-language PDF
with `pdftotext`. Fixed PDF error text follows the requested language; business text
(company name, descriptions, document numbers) stays as entered.

## Deployment and release

- Two clean installers: `tools/install.sh` (automatic, asks for domain or IP and an
  optional certificate email) and `tools/install-manual.sh` (manual).
- Build: `tools/build_release.sh`
- Static checks: `tools/verify_release.py`
- Documentation: in the front end repository under `files/`. README, HOWTO, deployment
  guide (with Simplified and Traditional Chinese editions), developer guide and release
  notes.

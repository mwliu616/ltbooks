# Lt-AI-Books Front End (PHP Rendering Layer)

The browser side of Lt-AI-Books 1.1: PHP 8.1+ server-side rendering, login required, and a
three-language interface (Simplified Chinese, Traditional Chinese and English). All data
and business logic come from the Python API on the same machine. This directory does not
connect to the database.

- Copyright (c) 2026 LEDU TECH CO., LIMITED
- License: MIT (see `LICENSE` in the repository root)

## Layout

```
index.php        Single entry: routing, navigation, session, language, page shell
lib/             Auth, API client, view helpers, translations, themes, help
pages/           One file per page (invoices, bills, reports, settings, AI workspace)
assets/          app.css, icons, fonts and small interaction scripts
files/           Product documentation and the two deployment packages (releases/)
```

## Requirements

- PHP 8.1+ (8.3 recommended), with `curl`, `mbstring` and `xml`
- Nginx or another web server that forwards to PHP-FPM
- HTTPS. Session cookies use `Secure`, so plain HTTP cannot sign in

PHP-FPM needs these environment values:

```
LEDU_API_BASE=http://127.0.0.1:8099
LEDU_API_TOKEN=<same as the backend .env>
LEDU_UPLOAD_DIR=<receipt and attachment directory>
```

## Local checks

```bash
for f in *.php lib/*.php pages/*.php pdf/*.php; do php -l "$f"; done
php tests/report_period_test.php
```

## Production layout (example)

| Item | Value |
| --- | --- |
| Site root | `/opt/ltbooks/web` (symlinked from `/www/wwwroot/finance.example.com`) |
| Domain | `finance.example.com` |
| PHP-FPM | 8.3, pool `www`, `pm.max_children = 20` |
| Backend | `ledu-api.service` on `127.0.0.1:8099` |
| Backend log | `/var/log/ledu-api.log`, rotated daily by `/etc/logrotate.d/ledu-api`, 14 files kept |
| Automatic backup | system crontab running `auto_backup.py tick` every minute, 09:00 and 17:00 by default |
| Certificate | Let's Encrypt, renewed by acme.sh |

```bash
systemctl is-active nginx php8.3-fpm ledu-api
curl -fsS http://127.0.0.1:8099/health
crontab -l | grep auto_backup
```

## Language consistency

Switch the interface with `?lang=zh_cn`, `?lang=zh_hk` or `?lang=en`, or from the
session setting. `<html lang>` follows the choice. New fixed text must be added to all
three dictionaries:

- Simplified Chinese: the source text
- Traditional Chinese: `lib/lang/zh_hk.php`, with the character fallback in
  `lib/zh_hk_chars.php`
- English: `lib/lang/en.php`. Values must not contain Chinese characters

PDF downloads live under `pdf/`. Error messages follow the `lang` parameter. Business
text (company names, customer and vendor names, manual descriptions, document numbers,
currencies, HKFRS/HKAS terms) is not translated.

## Documentation

Full installation, usage, deployment and release documentation is under
[`files/`](files/README.md). Installation steps are in [`files/HOWTO.md`](files/HOWTO.md)
and the deployment guide is [`files/DEPLOYMENT.md`](files/DEPLOYMENT.md), with Simplified
and Traditional Chinese editions alongside it.

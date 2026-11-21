# LtBooks 前端（PHP 渲染层）

LtBooks Ver 1.0 的浏览器端：PHP 8.1+ 服务端渲染，强制登录，简中 / 繁中 / English
三语界面。数据与业务逻辑全部由同机 Python API 提供，本目录不直接连接数据库。

- 版权：Copyright (c) 2026 LEDU TECH CO., LIMITED
- 许可：MIT（见仓库根目录 `LICENSE`）

## 目录

```
index.php        唯一入口：路由、导航、会话、语言、页面骨架
lib/             认证、API 客户端、视图辅助、翻译、主题、帮助
pages/           每页一个文件（发票、账单、报表、设置、AI 工作台等）
assets/          app.css、图标、字体与少量交互脚本
files/           产品文档与两种部署包（releases/）
```

## 运行要求

- PHP 8.1+（推荐 8.3），扩展 `curl`、`mbstring`、`xml`
- Nginx 或其它能转发到 PHP-FPM 的 Web 服务器
- HTTPS（会话 Cookie 带 `Secure`，纯 HTTP 无法登录）

PHP-FPM 需要注入：

```
LEDU_API_BASE=http://127.0.0.1:8099
LEDU_API_TOKEN=<与后端 .env 一致>
LEDU_UPLOAD_DIR=<票据附件目录>
```

## 本地检查

```bash
for f in *.php lib/*.php pages/*.php pdf/*.php; do php -l "$f"; done
php tests/report_period_test.php
```

## 集中部署运维（示例）

| 项目 | 值 |
| --- | --- |
| 站点根目录 | `/opt/ltbooks/web`（`/www/wwwroot/finance.example.com` 为软链） |
| 域名 | `finance.example.com` |
| PHP-FPM | 8.3，pool `www`，`pm.max_children = 20` |
| 后端 | `ledu-api.service`，`127.0.0.1:8099` |
| 后端日志 | `/var/log/ledu-api.log`（`/etc/logrotate.d/ledu-api` 每日轮转，保留 14 份） |
| 自动备份 | 系统 crontab 每分钟 `auto_backup.py tick`，默认 09:00 / 17:00 |
| 证书 | Let's Encrypt，acme.sh 自动续期 |

```bash
systemctl is-active nginx php8.3-fpm ledu-api
curl -fsS http://127.0.0.1:8099/health
crontab -l | grep auto_backup
```

## 三语一致性检查

界面语言由 `?lang=zh_cn|zh_hk|en` 或会话设置切换，`<html lang>` 随之变化。
新增固定文案时，三个词典都要补齐：

- 简中：源码原文
- 繁体：`lib/lang/zh_hk.php` + 逐字兜底 `lib/zh_hk_chars.php`
- 英文：`lib/lang/en.php`（值中不得出现汉字）

PDF 下载入口在 `pdf/` 下，错误提示已按 `lang` 参数输出对应语言。业务原文
（公司名、客户/供应商名、手工摘要、单号、币种、HKFRS/HKAS）不翻译。

## 文档

完整安装、使用、开发与发布说明在 [`files/README.md`](files/README.md)。

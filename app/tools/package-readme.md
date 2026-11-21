# LtBooks Ver 1.0 干净部署包

版权所有 (c) 2026 LEDU TECH CO., LIMITED。依据 MIT License 发布。

本包包含当前 PHP 前端、Python 后端、会计校验智能体、数据库结构与通用会计主数据。
**不包含**客户、供应商、单据、分录、银行流水、汇率缓存、业务账号、票据附件、备份、
导出文件、真实口令或 API 密钥。

提供两种部署包，按服务器条件二选一：

| 包 | 文件 | 适用场景 |
| --- | --- | --- |
| 自动化部署包 | `LtBooks-Ver1.0-auto-clean-*.tar.gz` | 全新 Debian 12 / Ubuntu 22.04+，可联网。输入域名/IP 与可选证书邮箱，其余全自动 |
| 人工部署包 | `LtBooks-Ver1.0-manual-clean-*.zip` | 已有 Web 面板、内网、离线或需要自行控制每个组件的环境 |

---

## 一、自动化部署包（推荐）

只需一台干净的 Linux 服务器和 root 权限，运行后按提示输入**域名或服务器 IP**，
域名部署时再输入**证书通知邮箱**（可留空），安装器会自动检查系统、安装全部依赖并完成部署。

```bash
tar -xzf LtBooks-Ver1.0-auto-clean-*.tar.gz
cd LtBooks-Ver1.0-auto-clean-*
sudo ./install.sh
```

运行后会出现提示：

```text
请输入要部署的域名或服务器 IP（例如 finance.example.com 或 203.0.113.10）：
> finance.example.com

请输入用于 Let's Encrypt 证书通知的邮箱（可留空，留空则使用自签名 HTTPS）：
> admin@example.com
```

邮箱用于证书到期提醒；留空则使用自签名 HTTPS。纯 IP 部署不会询问邮箱。
也可以用环境变量跳过交互：

```bash
sudo LTBOOKS_DOMAIN=finance.example.com LTBOOKS_SSL_EMAIL=admin@example.com ./install.sh
```

安装器依次完成：

1. 检查系统版本、架构、磁盘空间与是否 root；
2. 安装 Nginx、MariaDB、PHP-FPM、Python、Node.js 20、OCR、PDF 字体与 Certbot；
3. 创建 `ltbooks` 服务账号与目录，生成随机数据库口令和内部 API 令牌；
4. 建库并导入空 schema、108 个科目与 12 个税率，创建初始管理员；
5. 安装后端虚拟环境与前端站点；
6. 写 PHP-FPM pool、Nginx 站点、`ltbooks-api.service` 与 `ltbooks-backup.timer`；
7. 配置 HTTPS 并自检，最后输出访问地址与初始凭据位置。

### 域名与 IP 的差别

| 输入 | HTTPS | 说明 |
| --- | --- | --- |
| 已解析到本机的域名 + 邮箱 | Let's Encrypt 公开证书 | 浏览器直接受信 |
| 域名 + 邮箱留空 | 自签名证书 | 首次访问需手动信任；之后可用 `LTBOOKS_SSL_EMAIL` 重新申请 |
| 纯 IP（如 `203.0.113.10`） | 自签名证书 | Let's Encrypt 不支持纯 IP；绑定域名后可重新运行并设置 `LTBOOKS_SSL_EMAIL` 申请公开证书 |

### 可用参数（环境变量，写在命令前）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LTBOOKS_DOMAIN` | 交互输入 | 域名或 IP；非交互运行时必填 |
| `LTBOOKS_SSL_EMAIL` | 交互输入（可留空） | 填写后为域名申请 Let's Encrypt 证书 |
| `LTBOOKS_SSL_MODE` | `auto` | `auto` / `letsencrypt` / `selfsigned` / `off` |
| `LTBOOKS_APP_DIR` | `/opt/ltbooks` | 后端目录 |
| `LTBOOKS_WEB_ROOT` | `/var/www/ltbooks` | 前端目录 |
| `LTBOOKS_UPLOAD_DIR` | `/var/lib/ltbooks/uploads` | 票据附件目录 |
| `LTBOOKS_BACKUP_DIR` | `/var/backups/ltbooks` | 备份目录 |
| `LTBOOKS_DB_NAME` | `ltbooks` | 数据库名 |
| `LTBOOKS_DB_USER` | `ltbooks_app` | 数据库用户 |

安装器发现目标库已存在 LtBooks 表时立即停止，不会覆盖既有业务账套。

---

## 二、人工部署包

适用于已有主机面板、内网服务器，或希望自己控制系统软件版本的环境。
**系统环境由你手动准备**，脚本只负责部署应用与初始化数据库。

### 1. 手动准备环境

以 Debian / Ubuntu 为例：

```bash
# Web 与运行时
sudo apt-get update
sudo apt-get install -y nginx php8.2-fpm php8.2-cli php8.2-mysql \
  php8.2-curl php8.2-mbstring php8.2-xml php8.2-gd php8.2-zip \
  python3 python3-venv python3-pip rsync openssl curl nodejs

# 数据库
sudo apt-get install -y mariadb-server mariadb-client
sudo systemctl enable --now mariadb nginx php8.2-fpm

# OCR 与 PDF（票据识别与导出需要）
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-sim \
  tesseract-ocr-eng fonts-noto-cjk libpango-1.0-0 libpangoft2-1.0-0 libcairo2
```

版本要求：

| 组件 | 最低 | 推荐 |
| --- | --- | --- |
| PHP | 8.1 | 8.2 / 8.3 |
| Python | 3.10 | 3.12 |
| Node.js | 18 | 20 |
| MariaDB | 10.6 | 10.11 |

PHP 必需扩展：`curl`、`mbstring`、`xml`、`pdo_mysql`。`gd` 仅用于可选图像处理。

确认版本：

```bash
php -v && python3 -V && node -v && mysql --version
php -r '$m=["curl","mbstring","xml","pdo_mysql"];foreach($m as $x){echo $x,": ",extension_loaded($x)?"ok":"MISSING","\n";}'
```

### 2. 部署应用

```bash
unzip LtBooks-Ver1.0-manual-clean-*.zip
cd LtBooks-Ver1.0-manual-clean-*
./install-manual.sh
```

脚本只做四件事：建目录、初始化数据库、安装前后端、生成配置示例。
**不安装系统软件、不创建系统账号、不启动服务。**

完成后按需指定位置：

```bash
LTBOOKS_APP_DIR=/srv/ltbooks \
LTBOOKS_WEB_ROOT=/var/www/ltbooks \
LTBOOKS_UPLOAD_DIR=/srv/ltbooks/uploads \
LTBOOKS_BACKUP_DIR=/srv/ltbooks/backups \
./install-manual.sh
```

### 3. 接入 Web 与 HTTPS

包内 `setup/` 提供 Nginx、PHP-FPM、systemd 与备份定时任务示例。按实际路径修改后
接入你的面板或手工复制到对应位置：

```bash
sudo cp setup/nginx-ltbooks.conf.example /etc/nginx/sites-available/ltbooks.conf
sudo ln -s /etc/nginx/sites-available/ltbooks.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

自行启动后端：

```bash
<应用目录>/venv/bin/python <应用目录>/api.py
```

> HTTPS 是硬性要求：登录会话 Cookie 带 `Secure`，纯 HTTP 浏览器不会回传 Cookie。
> 请务必配置证书（面板一键 SSL 或 Certbot 均可）。

### 4. 手工导入数据库（可选）

不使用 `install-manual.sh` 时，也可以按 `docs/HOWTO.md` 自行执行：

```bash
mysql -uroot -p -e "CREATE DATABASE ltbooks CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -uroot -p ltbooks < sql/01-schema.sql
mysql -uroot -p ltbooks < sql/02-master-data.sql
```

---

## 首次登录

管理员名称默认为 `admin`，随机首次口令保存在：

```text
<应用目录>/storage/initial-credentials.txt
```

该文件权限为 600。首次登录后立即修改口令并删除此文件。公司资料、银行账户、真实汇率、
SMTP 和大模型设置均在登录后维护。

## 部署后建议

```bash
# 服务与健康
systemctl is-active nginx php*-fpm ltbooks-api
curl -fsS http://127.0.0.1:8099/health

# 首份完整备份（建立滚动更新的文件）
<应用目录>/venv/bin/python <应用目录>/tools/auto_backup.py create --full

# 备份调度是否生效（自动包）
systemctl list-timers ltbooks-backup.timer
```

- 自动备份为单文件滚动：首次完整包，之后每次合并最新数据进同一个文件。
- PHP-FPM 并发：用户较多时把 `pm.max_children` 调到 20 左右，改后重载。
- 日志轮转：为后端日志添加 `/etc/logrotate.d/` 规则（每日、保留 14 份）。

## 完整性验证

每个压缩包附带同名 `.sha256` 文件。包内 `MANIFEST.txt` 保存逐文件 SHA-256；
`PACKAGE.json` 标记版本和安装类型。两个安装脚本都不会导入任何生产基线或演示账套。

```bash
sha256sum -c LtBooks-Ver1.0-auto-clean-*.tar.gz.sha256
```

## 许可

见 `LICENSE`。MIT 许可要求保留版权和许可声明；软件按“现状”提供，不附担保。

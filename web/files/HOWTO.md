# LtBooks Ver 1.0 使用与运维手册（HOWTO）

本手册面向部署与日常使用，按「安装 → 初始化 → 日常操作 → 备份恢复 → 排错」顺序编排。
开发与二次开发请看 [开发全路径.md](开发全路径.md)。

---

## 一、安装

提供两种部署包，按服务器条件二选一。

### 1. 自动化部署包（推荐）

适用：全新 Debian 12 / Ubuntu 22.04+ 服务器，可联网，以 root 操作。
**输入域名或服务器 IP；域名部署时再填证书通知邮箱（可留空）**，其余全部自动完成。

```bash
tar -xzf LtBooks-Ver1.0-auto-clean-20261121.tar.gz
cd LtBooks-Ver1.0-auto-clean-20261121
sha256sum -c ../LtBooks-Ver1.0-auto-clean-20261121.tar.gz.sha256  # 如已单独下载校验文件
sudo ./install.sh
```

运行后提示：

```text
请输入要部署的域名或服务器 IP（例如 finance.example.com 或 203.0.113.10）：
> finance.example.com

请输入用于 Let's Encrypt 证书通知的邮箱（可留空，留空则使用自签名 HTTPS）：
> admin@example.com
```

邮箱用于证书到期提醒；直接回车留空则改用自签名 HTTPS，后续仍可通过
`LTBOOKS_SSL_EMAIL` 重新申请。纯 IP 部署不会询问邮箱。

也可以用环境变量跳过交互：

```bash
sudo LTBOOKS_DOMAIN=finance.example.com LTBOOKS_SSL_EMAIL=admin@example.com ./install.sh
```

安装器依次完成：

1. 检查系统版本、架构、磁盘空间与 root 权限，安装缺失的 Nginx、MariaDB、PHP-FPM、Python、Node.js、OCR/PDF 字体与 Certbot；
2. 创建 `ltbooks` 服务账号与目录，生成随机数据库口令和内部 API 令牌；
3. 建库并导入空 schema、108 个科目与 12 个税率，创建初始管理员；
4. 安装后端虚拟环境与前端站点；
5. 写 PHP-FPM pool、Nginx 站点、`ltbooks-api.service` 与 `ltbooks-backup.timer`；
6. 配置 HTTPS 并自检，输出访问地址与初始凭据位置。

**域名与 IP 的差别：**

| 输入 | HTTPS | 说明 |
| --- | --- | --- |
| 已解析到本机的域名 + 邮箱 | Let's Encrypt 公开证书 | 浏览器直接受信 |
| 域名 + 邮箱留空 | 自签名证书 | 首次访问需手动信任；之后可用 `LTBOOKS_SSL_EMAIL` 重新申请 |
| 纯 IP | 自签名证书 | Let's Encrypt 不支持纯 IP；绑定域名后重新运行并设置 `LTBOOKS_SSL_EMAIL` 即可申请公开证书 |

常用参数（环境变量，写在命令前）：

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

安装器不会覆盖已有业务库：发现目标库已存在 LtBooks 表时立即停止，不改动任何数据。

### 2. 人工部署包

适用：已有面板管理的主机、内网服务器，或不允许自动安装系统软件的环境。
**环境由你手动安装**，脚本只负责部署应用、初始化数据库与生成配置。

#### 2.1 手动安装环境

以 Debian / Ubuntu 为例：

```bash
sudo apt-get update
sudo apt-get install -y nginx php8.2-fpm php8.2-cli php8.2-mysql \
  php8.2-curl php8.2-mbstring php8.2-xml php8.2-gd php8.2-zip \
  python3 python3-venv python3-pip rsync openssl curl nodejs \
  mariadb-server mariadb-client poppler-utils tesseract-ocr \
  tesseract-ocr-chi-sim tesseract-ocr-eng fonts-noto-cjk \
  libpango-1.0-0 libpangoft2-1.0-0 libcairo2
sudo systemctl enable --now mariadb nginx php8.2-fpm
```

| 组件 | 最低 | 推荐 |
| --- | --- | --- |
| PHP | 8.1 | 8.2 / 8.3 |
| Python | 3.10 | 3.12 |
| Node.js | 18 | 20 |
| MariaDB | 10.6 | 10.11 |

PHP 必需扩展：`curl`、`mbstring`、`xml`、`pdo_mysql`。自检：

```bash
php -v && python3 -V && node -v && mysql --version
php -r '$m=["curl","mbstring","xml","pdo_mysql"];foreach($m as $x){echo $x,": ",extension_loaded($x)?"ok":"MISSING","\n";}'
```

#### 2.2 部署应用

```bash
unzip LtBooks-Ver1.0-manual-clean-20261121.zip
cd LtBooks-Ver1.0-manual-clean-20261121
./install-manual.sh
```

脚本只做：建目录、初始化数据库、安装前后端、生成示例配置；**不安装系统软件、
不创建系统账号、不启动服务**。可用 `LTBOOKS_APP_DIR`、`LTBOOKS_WEB_ROOT`、
`LTBOOKS_UPLOAD_DIR`、`LTBOOKS_BACKUP_DIR` 指定位置。

安装后把 `setup/` 下的 Nginx、PHP-FPM 示例配置按实际路径接入面板，并自行启动后端：

```bash
<应用目录>/venv/bin/python <应用目录>/api.py
```

> HTTPS 是硬性要求：登录会话 Cookie 带 `Secure`，纯 HTTP 浏览器不会回传 Cookie，
> 表现为「登录后又跳回登录页」。

### 3. 首次登录与初始化

1. 打开 `https://<域名>/`；
2. 用户名 `admin`，口令见 `<应用目录>/storage/initial-credentials.txt`；
3. 立即在「设置 → 账号」修改口令，然后删除该文件；
4. 在「设置 → 公司信息」填写公司名称、地址、联系方式、功能货币与财务年结日；
5. 在「会计 → 会计科目」确认科目表与语言名称，在「会计 → 汇率维护」补录所需汇率；
6. 如需邮件，在「设置 → 邮件」填写 SMTP；如需 AI，在「设置 → 大模型」填写接口。

---

## 二、日常操作

### 1. AI 工作台

入口：左侧「AI 工作台」。识别、建单、记账、查数、对账与导出都在同一页面完成，
不需要跳到人工界面。

- **文字指令**：例如「记录一张 8 月租金 12,000 HKD 的账单」；系统先返回结果卡片，
  列出单据、科目、金额与凭证号，确认后才写入。
- **票据识别**：上传或拍摄发票、收据、银行回单。系统先读取内容、判断业务性质与
  建议科目，再给出待确认卡片；不会用固定话术反问「支出性质」这类本应由系统判断
  的问题。
- **字段缺失**：仅当票面确实无法判断（如无金额、无日期、收付款方不明）时才提问，
  且问题指向具体缺失项。
- **手机端**：同一页面在手机浏览器提供拍摄入口，可直接拍照或选择文件作为附件上传
  并识别；识别结果同样进入确认卡片。

### 2. 单据与邮件

报价单、销售订单、发票、账单、采购订单、贷记单的详情页都有「发送邮件」。
邮件正文与附件 PDF 使用与打印件相同的模板：

- 外币单据同时显示原币金额、汇率与折算后的功能货币金额；
- 语言跟随当前界面语言，整份单据只用一种语言，不混排；
- 发件人名称取「设置 → 邮件」中的 From Name。

### 3. 收付款进度

发票与账单列表新增「收款进度 / 付款进度」列，直接显示已核销比例与剩余金额，
不必再自行比对核销记录。点击可进入核销工作台处理差额。

### 4. 银行月结单导入

「银行 → 导入月结单」默认显示**已导入的月结单列表**，按导入时间倒序：

| 列 | 说明 |
| --- | --- |
| 导入时间 | 该批次写入系统的时间 |
| 文件名 | 上传时的原始文件名 |
| 银行账户 | 导入到的账户 |
| 期间 | 对账单的起止日期 |
| 行数 | 该批次的明细行数 |
| 操作 | 「查看」跳到该账户流水；「下载」取回原始文件（未保留时不显示） |

导入步骤：

1. 点右上角「＋ 导入月结单」，进入独立上传界面（当前页切换，不含列表）；
2. 选择银行账户与文件（CSV / XLSX / XLS / PDF，上限 20MB），点「上传并解析」；
3. 识别内容显示在下方，核对预览与算术校验：期初 + 贷方 − 借方 必须等于期末；
4. 点「导入并校验」，在确认框中确认后才写入系统——余额与期间由识别结果自动带出；
5. 点「← 返回列表」，新记录出现在最上方。

同一文件按 SHA-256 去重，不会重复入账。解析只读取文件、不写库；只有通过算术校验
才写入流水。原始月结单保存在 `<应用目录>/storage/bank-statements/<实体>/`，按
SHA-256 命名；升级前导入的历史记录没有保留原文件，因此没有「下载」按钮。

### 5. 报表与报表中心

左侧「报表」只保留三个入口：报表中心、财务报表、利得税。所有明细报表从报表中心
进入，避免同一报表出现两套入口。报表页统一带期间工具条（预设、自定义、对比），
金额来自已过账分录。

### 6. 财务分析报告

仪表盘不再内嵌「完整财务分析报告」，页面保持简洁。分析能力与导出接口保留，
按以下期间生成：

| 期间 | 说明 |
| --- | --- |
| 本月 | 当前自然月 |
| 指定月份 | 任选年月 |
| 自然年 | 任选公历年 |
| 财务年 | 按公司信息中的年结日计算 |
| 开业至今 | 从首条已过账分录至今 |
| 自定义 | 任选起止日期 |

报告包含：核心指标与图表、财务报表（损益、财务状况、现金流量等）、AI 定性解读。
数字全部来自确定性报表函数；AI 只写不含量化数字的分析文字，模型不可用时回退为
确定性文案，并在报告中标注数据来源与期间。

导出：PDF 与 Word（DOCX），支持简中、繁中、English 三种语言。

### 7. 外观与配色

「设置 → 外观与配色」提供 8 套方案：科技蓝、暖纸灰、雾蓝低对比、墨绿沉静、
冰川青、赤陶暖棕（浅色）与石墨夜色、午夜靛蓝（深色）。主题只改颜色变量，
不影响布局、数据与报表内容，选择结果保存在当前浏览器。

### 8. 月结与复核

「会计 → 待复核」处理待确认分录；「会计 → 月结」检查未过账单据、未核销项与
期间异常后锁定期间。锁定后该期间禁止再写入，需要调整时先在「期间锁定」解锁。

### 9. 日记账与分录详情

「会计 → 日记账」列表的「明细」「附件」「编辑」按钮都打开独立的分录详情页
（`?p=journal-view&id=…`），列表本身不再内嵌操作面板；行内「凭证」直接在新标签打开
当前界面语言的 PDF（多语言导出在详情页与「打印本页凭证」菜单）。列表顶部可搜索
分录号 / 摘要 / 来源，并显示本页、全部与草稿数量；表格按期间分组，组头给出本页
该期间的笔数与借贷小计。详情页提供：

- 分录信息与明细行，已冲销/冲销分录会显示与原凭证的关联；
- 草稿：编辑草稿、删除草稿（删除后回列表，审计日志保留）；
- 已过账：填写「冲销原因」后点「冲销」，在确认框确认后生成反向分录，原凭证保留；
- 附件：点「附件」定位到附件卡，可上传（多选）、查看、删除；单文件上限 20MB，
  上传时记录 SHA-256 便于追溯。

审计角色只能查看，不能编辑、删除、冲销或改动附件。

---

## 三、语言与 PDF 导出

### 1. 三语切换

界面支持简中、繁中、English，右上角切换或访问 `?lang=zh_cn|zh_hk|en`，
`<html lang>` 同步变化。切换后整页固定文案统一为目标语言，不与其它语言混排。

以下内容**按原样保留**，不做翻译：公司法定名称、客户/供应商名称、手工摘要、
单据编号、币种代码、HKFRS/HKAS 等准则名称。

新增界面文案时必须同时补齐三份词典：

- 简中：源码原文；
- 繁中：`lib/lang/zh_hk.php`，逐字兜底在 `lib/zh_hk_chars.php`；
- 英文：`lib/lang/en.php`，值中不得残留汉字。

### 2. PDF 导出

单据、17 类报表、财务报表套件、税务、凭证、财务分析与年度报表包均支持三语。
导出时语言随当前界面；年度包内 `MANIFEST.txt` 也会输出对应语言。

PDF 中的固定表头、状态与错误提示会翻译；业务原文同上保留。需要核对文字层时：

```bash
pdftotext -layout <文件>.pdf - | head -50
```

## 四、备份与恢复

### 1. 自动备份

自动模式下 systemd timer（或面板计划任务）**每分钟**调用一次
`tools/auto_backup.py tick`，由它按界面里设置的香港时间到点执行；默认 **09:00、17:00**，
可在「设置 → 备份与恢复 → 自动备份设置」里修改（最多 4 个时间，留空表示不启用）。
备份保留最近 180 份：

- **自动备份为单文件滚动**：首次生成一份完整包，之后每次把最新全量原子重写进
  同一个文件，目录中自动备份始终只有一个；恢复时直接读这个文件，无需回溯链条；
- 没有可用基线（首次部署、文件被删或校验不一致）时，自动重新生成一份完整备份；
- **手动备份始终为完整备份**，保存全部数据库与附件，并成为后续自动备份合并的文件；
- 手动与自动备份在界面上分列两个列表，可分别下载与删除。

> 滚动更新需要整包重写，因此每次备份的读写量与备份包大小相当（当前约 62M）。
> 这样换来的是目录中只有一个文件、恢复逻辑最简单；若数据量继续增大，可改为手动
> 完整备份 + 更长的间隔。

检查状态：

```bash
# 安装包默认：systemd timer
systemctl list-timers ltbooks-backup.timer
systemctl status ltbooks-backup.service
journalctl -u ltbooks-backup.service -n 50
```

```bash
# 集中部署：系统 crontab 每分钟调用 tick
crontab -l | grep auto_backup
tail -n 50 /opt/ltbooks/backups/auto-backup.log
ls -lh /opt/ltbooks/backups/
```

集中部署还可用一条命令确认备份状态（列出类型、大小、合并次数）：

```bash
cd /opt/ltbooks/app && ./venv/bin/python tools/auto_backup.py list
```

手工模式不注册 timer，可用面板计划任务每分钟调用同一命令；如需强制完整备份，加 `--full`：

```bash
<应用目录>/venv/bin/python <应用目录>/tools/auto_backup.py tick
<应用目录>/venv/bin/python <应用目录>/tools/auto_backup.py create
<应用目录>/venv/bin/python <应用目录>/tools/auto_backup.py create --full
```

### 2. 界面备份与恢复

「设置 → 备份与恢复」可立即创建完整备份、下载备份、查看类型与清单、删除单个备份并恢复。
自动备份会显示为「自动滚动」，并标注已合并次数；**手动备份始终为完整备份**，并成为
后续自动备份合并的文件。恢复流程：

1. 系统先强制生成一份**完整**安全备份；
2. 校验备份清单与每个文件的 SHA256；
3. 恢复该文件的数据库与附件（滚动包已是完整快照，无需再叠加其他文件）；
4. 失败时报告原因，安全备份保留在备份目录；
5. 恢复完成后清除滚动状态，下一次自动备份重新从完整包开始。

### 3. 备份内容

滚动包与完整备份内容一致：全部业务表、上传票据与附件、备份清单；包内附带
`rolling` 标记与已合并次数。两者都不包含：`.env`、大模型与 SMTP 密钥、会话。
迁移服务器时需单独复制 `.env` 或重新填写设置。

---

## 五、安全与权限

- 所有写操作要求登录会话；管理类接口额外校验管理员角色。
- 前端到后端使用内部令牌，浏览器不可见；令牌长度不足或缺失时后端拒绝启动。
- 附件下载做真实路径边界校验，不能借路径穿越读取目录外文件。
- 登录表单、AI 上传、附件上传均限制大小与类型；上传目录不在 Web 根目录内。
- 生产环境必须 HTTPS；自签名证书仅用于内网或验收。

---

## 六、排错

| 现象 | 排查 |
| --- | --- |
| 登录后又回到登录页 | 未启用 HTTPS，Secure Cookie 未回传；检查证书与 `X-Forwarded-Proto` |
| 502 Bad Gateway | 后端未启动或端口不符：`systemctl status ltbooks-api`，检查 `.env` 的 `LEDU_API_PORT` |
| 页面提示内部令牌错误 | `.env` 的 `LEDU_API_TOKEN` 与后端不一致，重启后端 |
| 邮件发送失败 | 「设置 → 邮件」主机/端口/加密方式/账号；465 用 SSL，587 用 STARTTLS |
| 票据识别不可用 | 未配置大模型或视觉接口；在「设置 → 大模型」填写后重试 |
| 报表数字为空 | 期间内无已过账分录；核对期间与「会计 → 日记账」 |
| 备份任务未执行 | 安装包看 timer 状态；集中部署看 `crontab -l` 是否含 `auto_backup.py tick`，以及 `/opt/ltbooks/backups/auto-backup.log` |
| 备份目录为空 | 首次部署尚无基线，执行 `auto_backup.py create --full`；确认 `LEDU_BACKUP_DIR` 可写 |
| 页面偶发超时 / 502 | PHP-FPM 并发打满：`grep pm.max_children /etc/php/8.3/fpm/pool.d/www.conf`（生产为 20），必要时提高后 `systemctl reload php8.3-fpm` |
| 后端反复重启 | 查看 `/var/log/ledu-api.log` 的 Traceback；多为 `.env` 令牌/数据库配置错误或代码与进程版本不一致，改后 `systemctl restart ledu-api` |
| 日志占满磁盘 | 后端日志由 `/etc/logrotate.d/ledu-api` 每日轮转保留 14 份；确认 `logrotate.timer` 在运行 |
| 安装时报缺少 PHP 扩展 | 需要 `curl`、`mbstring`、`xml`；`gd` 非必需，仅用于可选图像处理 |

日志位置：

```bash
journalctl -u ltbooks-api -n 100      # 安装包后端
tail -n 100 /var/log/ledu-api.log     # 集中部署后端
tail -n 100 /var/log/nginx/error.log  # Web 服务器
```

---

## 七、升级与回滚

1. 升级前在「备份与恢复」创建一次备份，并记录当前版本号；
2. 解压新版本包，按相同 `LTBOOKS_*` 参数执行安装脚本；已有数据库会保留；
3. 若需回滚，恢复升级前备份，并把应用目录替换为上一版本源码；
4. 回滚后重启后端服务。

---

## 八、许可

Copyright (c) 2026 LEDU TECH CO., LIMITED。以 MIT 许可发布，条款见 `LICENSE`。

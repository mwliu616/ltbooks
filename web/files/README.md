# LtBooks Ver 1.0

LtBooks 是面向香港中小型企业的会计与财务分析系统：PHP 8.3 服务端渲染界面、
Python 3.12 记账内核、MariaDB 10.11 数据库。金额、税额与报表数字全部由确定性
代码计算；AI 只做识别、分类建议与文字解读，不会凭空生成数字。

- 版权：Copyright (c) 2026 LEDU TECH CO., LIMITED
- 许可：MIT（见 `LICENSE`）
- 版本：Ver 1.0.0（2026-11-21 维护更新，版本号不变）

English version: [README.en.md](README.en.md)

## 1. 能做什么

| 范围 | 主要能力 |
| --- | --- |
| AI 工作台 | 自然语言建单、记账、查数、对账与导出；票据拍摄/上传后自动识别内容与业务性质，先出结果卡片，人工确认后才写入 |
| 销售 | 客户档案、报价单、销售订单、发票、收款、贷记单、经常性发票；单据可发邮件，外币显示功能货币折算与汇率 |
| 采购 | 供应商档案、采购订单、账单、费用、付款、经常性账单；同样支持邮件与外汇报价 |
| 银行 | 银行账户、银行规则、月结单导入（已导入列表可查看与下载原始文件）、交易记录、对账工作区、账户间转账 |
| 会计 | 会计科目、期初余额、手工分录、日记账、汇率维护、待复核、月结与期间锁定、期末重估 |
| 报表 | 试算表、损益及其他全面收益表、财务状况表、现金流量表、账龄、银行余额、汇兑损益、利得税、财务比率、客户/供应商余额、总分类账、日记簿、销售/采购明细、财务报表套件 |
| 财务分析 | 按本月、指定月份、自然年、财务年、开业至今或自定义期间生成公司财务分析：确定性财务数据 + 图表 + AI 定性解读，支持三语 PDF / Word 导出（仪表盘不再内嵌该组件） |
| 设置 | 公司信息、账号、大模型、外观与配色（8 套主题）、邮件、备份与恢复、智能体管理、审计探索器、使用说明 |

多币种：单据与报表均按「原币金额 × 汇率 = 功能货币金额」显示，功能货币取
公司信息中的设置；单据三语（简中 / 繁中 / English）按当前界面语言整体切换，
不混排。

## 2. 两种部署包

发布目录：`files/releases/`。两个包都是**干净、无业务数据**的安装包，只含：

- 50 张表的空 schema、触发器与例程；
- 一个可改名的公司实体壳（`My Company`，功能货币 HKD，财务年结日 12-31）；
- 108 个会计科目与 12 个税率；
- 源码、依赖清单、许可与安装脚本。

不包含客户、供应商、单据、分录、银行流水、账户、汇率缓存、用户口令、票据、
备份文件或任何 API 密钥。

| 包 | 文件 | 适用场景 |
| --- | --- | --- |
| 自动化部署包 | `LtBooks-Ver1.0-auto-clean-20261121.tar.gz` | Debian / Ubuntu 新服务器。root 运行 `./install.sh`，输入**域名或服务器 IP**；域名部署时再填证书通知邮箱（可留空），自动检查并安装 Nginx、MariaDB、PHP、Python、Node、OCR/PDF 依赖与 HTTPS |
| 人工部署包 | `LtBooks-Ver1.0-manual-clean-20261121.zip` | 已有 Web 面板、内网或需要自行控制系统软件版本。人工安装全部环境后运行 `./install-manual.sh`，仅初始化目录、数据库与配置，不改系统服务 |

两种包按服务器条件二选一，不要混用。旧的 AI 部署包已取消。

纯 IP 或邮箱留空时使用自签名 HTTPS；只有「已解析域名 + 邮箱」才会申请
Let's Encrypt 公开证书。

每个包旁有同名 `.sha256`，包内 `MANIFEST.txt` 记录逐文件哈希，`PACKAGE.json`
记录变体、构建日期与文件数。校验方式：

```bash
sha256sum -c LtBooks-Ver1.0-auto-clean-20261121.tar.gz.sha256
```

安装步骤见 [HOWTO.md](HOWTO.md)；部署参数、目录与排查见
[部署指南-v1.0.0.md](部署指南-v1.0.0.md)（繁體版：[部署指南-繁體-v1.0.0.md](部署指南-繁體-v1.0.0.md)）。
源码结构、数据流与扩展方式见
[开发全路径.md](开发全路径.md)；本次整改与验收记录见
[版本发布说明-v1.0.0.md](版本发布说明-v1.0.0.md)。

## 3. 运行架构

```
浏览器
  │  HTTPS
  ▼
Nginx ──► PHP-FPM（index.php，服务端渲染 + 会话）
              │  内部 HTTP + X-Ledu-Token
              ▼
        Python API（127.0.0.1:8099，Flask）
              │  参数化 SQL，事务内写入
              ▼
        MariaDB（生产 ltbooks / 新部署 ltbooks）
              │
              ├─ 票据与附件（生产 /opt/ltbooks/uploads）
              └─ 自动备份（生产 /opt/ltbooks/backups，默认 09:00 / 17:00）
```

> 图中括号内为集中部署示例的实际值；安装包默认布局见第 4 节对照表。
> 两种布局的服务名不同：安装包用 `ltbooks-*`，集中部署用 `ledu-api` / `php8.3-fpm`。

- 前端只通过内部令牌访问后端，令牌存于 `.env`，浏览器拿不到。
- 会话 Cookie 强制 `Secure` + `HttpOnly` + `SameSite=Lax`，因此必须启用 HTTPS。
- 自动备份采用单文件滚动：首次生成完整包，之后每次把最新全量原子重写进同一个文件，
  目录中始终只有一个自动备份；手动备份始终为完整备份，并成为后续自动更新的文件；
  手动与自动备份在界面上分开两个列表；恢复滚动包无需回溯链条。

## 4. 目录

| 路径 | 安装包默认 | 集中部署示例 |
| --- | --- | --- |
| 后端与虚拟环境 | `/opt/ltbooks` | `/opt/ltbooks/app` |
| PHP 前端 | `/var/www/ltbooks` | `/opt/ltbooks/web`（`/www/wwwroot/finance.example.com` 为软链） |
| 票据与附件 | `/var/lib/ltbooks/uploads` | `/opt/ltbooks/uploads` |
| 自动与手工备份 | `/var/backups/ltbooks` | `/opt/ltbooks/backups` |
| 后端服务 | `ltbooks-api.service` | `ledu-api.service`（日志 `/var/log/ledu-api.log`） |
| 备份调度 | `ltbooks-backup.timer` | 系统 crontab 每分钟 `auto_backup.py tick` |

手工模式不写系统目录，位置由 `LTBOOKS_APP_DIR` / `LTBOOKS_WEB_ROOT` 等变量决定。

## 5. 首次登录

安装完成后，初始管理员账号与随机口令保存在
`<应用目录>/storage/initial-credentials.txt`（权限 600）。首次登录后请立即修改口令
并删除该文件。系统不会重置已存在账号的口令，重复安装是安全的。

## 6. 许可与第三方

本项目以 MIT 许可发布，完整条款见 `LICENSE`。运行依赖（Flask、PyMySQL、
WeasyPrint、python-docx、openpyxl 等）分别遵循其自身许可，清单见
`backend/requirements.txt`。产品文档与代码中不包含任何特定云厂商、邮件服务商
或主机面板的绑定信息。

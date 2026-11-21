# LtBooks 后端（Python API）

LtBooks Ver 1.0 的记账内核与 HTTP API：Flask + PyMySQL + MariaDB，金额与报表全部由
确定性代码计算，AI 仅负责识别、分类建议与定性解读。

- 版权：Copyright (c) 2026 LEDU TECH CO., LIMITED
- 许可：MIT（见 `LICENSE`）

## 快速开始

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env        # 填数据库、令牌、路径
./venv/bin/python api.py    # 默认 127.0.0.1:8099
```

健康检查：`curl http://127.0.0.1:8099/health`

## 配置（`.env`）

| 键 | 说明 |
| --- | --- |
| `LEDU_DB_HOST` / `PORT` / `NAME` / `USER` / `PASSWORD` | MariaDB 连接 |
| `LEDU_API_HOST` / `LEDU_API_PORT` | 监听地址，默认 `127.0.0.1:8099` |
| `LEDU_API_TOKEN` | 前端到后端的内部令牌，不足长度时拒绝启动 |
| `LEDU_STORAGE_DIR` | 应用数据（证书、临时文件） |
| `LEDU_UPLOAD_DIR` / `LEDU_UPLOAD_DIRS` | 票据附件目录，可多路径（冒号分隔） |
| `LEDU_BACKUP_DIR` / `LEDU_BACKUP_KEEP` | 备份目录与保留份数 |
| `LEDU_LLM_*` / `LEDU_VISION_API_KEY` | 模型与识别接口，界面设置优先 |
| `LEDU_SMTP_*` | 邮件，界面设置优先 |
| `LEDU_NODE_BIN` | Node 可执行文件（智能体桥接用） |

修改 `.env` 后必须重启：`systemctl restart ledu-api`。生产环境文件权限应为 640，
属主 `root:ltbooks`，不得提交到版本库。

## 结构

```
api.py           HTTP 路由与权限校验
config.py        路径与环境变量（LEDU_APP_DIR / LEDU_ENV_FILE 可覆盖）
core/            记账、报表、分析、备份、邮件、AI 智能体
  backup.py           完整备份、单文件滚动更新、保留策略
  financial_analysis  财务分析报告（三语 PDF / DOCX）
  pdf_reports.py      17 类报表 PDF 渲染
  i18n.py             PDF 固定文案三语映射（简中 / 繁中 / English）
agent/           随包会计校验智能体（Node）
bridge/          Python → Node 桥接
sql/             建表与增量脚本
tools/           安装、打包、校验、备份与维护脚本
tests/           9 个测试文件、131 个单元与接口回归用例
```

## 测试

```bash
PYTHONPATH=. ./venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

当前 **9 个测试文件、131 个用例**，约 7 秒跑完。测试使用受控输入，不依赖生产账套，
也不调用真实大模型。

单独跑三语 PDF 相关回归：

```bash
PYTHONPATH=. ./venv/bin/python -m unittest tests.test_pdf_i18n -v
```

## 备份与运维

```bash
# 完整备份（同时成为后续滚动更新的文件）
./venv/bin/python tools/auto_backup.py create --full
# 按界面设置的香港时间到点，把最新数据合并进同一个备份文件（cron 每分钟调用）
./venv/bin/python tools/auto_backup.py tick
# 查看 / 清理
./venv/bin/python tools/auto_backup.py list
./venv/bin/python tools/auto_backup.py prune --keep 180
```

自动备份采用**单文件滚动**：首次生成完整包，之后每次把最新全量原子重写进同一个
文件，目录中始终只有一个自动备份，恢复无需回溯链条。生产实例（`/opt/ltbooks`）由
系统 crontab 每分钟调用 `tick`，默认 09:00 / 17:00（香港时间）执行，保留 180 份。
后端日志为 `/var/log/ledu-api.log`，由 `/etc/logrotate.d/ledu-api` 每日轮转、保留 14 份。

PDF 导出使用 WeasyPrint 70 + Poppler；三语 PDF 的文字层可用 `pdftotext` 校验。
PDF 接口的固定错误文案随请求语言输出，业务原文（公司名、摘要、单号）保持原样。

## 部署与发布

- 两种干净安装包：`tools/install.sh`（自动化，输入域名/IP 与可选证书邮箱）、`tools/install-manual.sh`（人工）
- 构建：`tools/build_release.sh`
- 静态校验：`tools/verify_release.py`
- 文档：前端仓库 `files/` 下的 README、HOWTO、部署指南、开发全路径与发布说明

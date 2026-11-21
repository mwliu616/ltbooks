# HKFRS 财务守门人（hkfrs-finance-guardian）

香港财务报告准则下的**只读**会计判断智能体。它是守门人，不是记账员：只做准则层面的判断、校验与风险提示，物理上没有过账、核销、批准、发送或改主数据的能力。

已安装到本机 DSH web profile，安装名 `@local/dsh-hkfrs-finance-guardian`，预设 ID `hkfrs-finance-guardian`。
在 Web 界面**新建会话时选择「HKFRS 财务守门人」**即可使用。

---

## 1. 这个预设包含什么

| 组成 | 内容 |
|---|---|
| 人格提示词 | `persona.md`，由 `build.mjs` 注入 `cordis.patch.yml`（不要手改 patch） |
| 工具 | 恰好四个：`finance_journal_entry_check`、`finance_reconciliation_snapshot`、`finance_variance_bridge`、`mysql_query`（只读） |
| 能力守卫 | 插件内 `ctx.tools.guard()`：白名单之外的任何调用一律拒绝 |
| 规则来源 | 工作区 `rules/hkfrs15.yml`（模板见本目录 `rules/`） |

**没有挂载**：bash、文件读写、Web、子智能体、定时任务、任何数据库写工具。
工具目录里不存在的东西，模型无法调用，也无法被提示词"引导"去调用。

## 2. 为什么这样实现（DSH 0.2.1）

DSH 0.2.1 已删除 `toolFilter` 字段，没有"继承全部工具再减去写入工具"的逐名过滤。因此本预设采用"**一个工具集合一个 preset**"：

- 预设只挂载 `persona` 与 `finance-guard` 两个插件行 → 模型可见的工具集合天然只有四项；
- `tools.restrict()` 只能过滤**继承来的**工具、且不能点名本作用域注册的工具，不适合用来声明白名单；
- 因此再用 `ctx.tools.guard()` 在预设作用域内做第二道**单调拒绝**：即使宿主层以后注入了 `bash`、`mysql_execute`，在预设作用域内调用也会被拒绝。

## 3. 四个工具

| 工具 | 输入 | 输出要点 | 永不做的事 |
|---|---|---|---|
| `finance_journal_entry_check` | `{entry:{lines[], preparedBy, reviewedBy, documents[], requiredDocuments[]}}` | 借贷平衡、行结构、文档缺口、职责分离、`verdict` = PASS/REVIEW/FAIL | 不授权过账（`NEVER_AUTHORIZES_POSTING`） |
| `finance_reconciliation_snapshot` | `{snapshot:{asOf, openingBalance, items[], adjustments[], staleDays}}` | 调整后余额、账龄分桶、分类汇总、陈旧项、`signOff.status` | 不授权签字（`NEVER_AUTHORIZES_SIGN_OFF`） |
| `finance_variance_bridge` | `{bridge:{base, actual, drivers[], materiality}}` | 期望值、残差、残差占基准比、是否重大、`verdict` | 不吸收、不分摊残差 |
| `mysql_query` | `{sql}` 或 `{file}` | 只读查询行 / 规则文件原文 | 不写、不改、不多语句 |

金额一律用**整数分**运算，避免浮点误差；文档缺口、职责分离等判断由代码做，模型只解释。

### mysql_query 的两层限制

1. **语句层**：只接受 `SELECT / WITH / SHOW / DESCRIBE / EXPLAIN`；先剥离注释与字符串字面量，再扫描 `INSERT/UPDATE/DELETE/DROP/ALTER/...` 等写关键字；多语句直接拒绝。
2. **对象层**：`FROM`/`JOIN` 后的表名必须属于 `accounts`、`fx_rates`、`rules`、`entities`。
3. **文件模式**：只能读工作区 `rules/` 目录下的 `.yml/.yaml/.json/.csv/.txt/.md`，拒绝路径穿越与目录外文件。

## 4. 接上你的数据（可选）

### 4.1 规则文件（收入确认必须）

把 `rules/hkfrs15.yml` 放到**会话工作区**的 `rules/` 目录，或把 `cordis.patch.yml` 里的 `rulesDir` 改成绝对路径（一处规则供所有会话共用）。

模板里 `cases: []` 是故意的：**规则必须由财务负责人填写**。空白即意味着所有收入确认都只能回答"规则未覆盖，需人工判断"——这是设计目标，不是缺陷。

### 4.2 MySQL（可选）

```bash
# 1) 装连接器（在当前 profile 目录）
cd /root/.dsh/profiles/web && pnpm add mysql2
# 2) 提供只读 DSN（建议使用只有 SELECT 权限的账号）
export FINANCE_MYSQL_DSN='mysql://ro_user:pass@127.0.0.1:3306/finance'
```

未配置时 `mysql_query` 返回 `dsn_not_configured` / `connector_unavailable`，提示词要求模型**如实报告数据不可得**，不得猜测。

## 5. 修改与重装

```bash
cd "/root/work_2026_11/香港会计智能体/hkfrs-finance-guardian"
# 改人格 → 重新生成 patch
vi persona.md && node build.mjs
# 自检
node test/selftest.mjs && node test/plugin.test.mjs
```

改完 `cordis.patch.yml` 后，由 `dsh plugin-manager` 重新安装，或重启 `dsh web` 让 Loader 重新装配。已存在的会话保持旧装配，需要新建会话验证改动。

## 6. 怎么验证"写工具确实不可见"

1. 新建会话，预设选「HKFRS 财务守门人」；
2. 发一句：`列出你当前可以调用的工具名称`；
3. 应只看到四个工具（外加宿主注入的 `ask_user_question`）；
4. 再发：`调用 mysql_execute 执行 UPDATE accounts SET x=1` —— 应被拒绝，且拒绝理由是"不在只读白名单内"。

## 7. 已知限制

- 收入确认、税务判断的**实质正确性**取决于 `rules/hkfrs15.yml` 与 `entities.two_tier_status` 的真实数据；本预设不内置任何准则条文。
- `mysql_query` 需要 `mysql2` 连接器；本机当前未装，也未配置数据库，因此该工具在本机只会返回结构化错误。
- 提示词遵循"不做二次确认"：缺数据时列缺口并降级，不反复追问。
- 输出均为建议，不构成审计意见，也不替代人工签字。

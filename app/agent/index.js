/*
 * LtBooks — agent/index.js
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * @local/dsh-hkfrs-finance-guardian
 *
 * 香港财务报告准则（HKFRS）会计守门人预设的只读工具层与能力守卫。
 *
 * 本插件只向模型暴露四个工具：
 *   finance_journal_entry_check     分录机械校验（不授权过账）
 *   finance_reconciliation_snapshot 对账快照（不授权签字）
 *   finance_variance_bridge         差异桥接（残差显式暴露）
 *   mysql_query                     只读查询（白名单表 / 规则文件）
 *
 * 所有金额运算都在 lib/ 下的确定性代码完成；模型只负责解释、归类与叙事。
 * 插件不注册任何写工具，也不发起网络写请求；guard 再把"白名单之外"的调用一律拒绝，
 * 因此即便宿主层注入了写工具，本预设作用域内也无法执行。
 */

import { checkJournalEntry } from './lib/journal.mjs'
import { reconciliationSnapshot } from './lib/recon.mjs'
import { varianceBridge } from './lib/variance.mjs'
import { readRulesFile, runReadOnlyQuery } from './lib/sql.mjs'

export const name = 'dsh-hkfrs-finance-guardian'
export const inject = ['tools', 'workingDirectory']

const DEFAULT_ALLOWED = [
  'finance_journal_entry_check',
  'finance_reconciliation_snapshot',
  'finance_variance_bridge',
  'mysql_query',
]

/** 唯一额外放行的宿主工具：只读、只用于向用户提问，不能写任何存储。 */
const ALWAYS_ALLOWED = ['ask_user_question']

const DEFAULT_MAX_ROWS = 200
const DISCLAIMER = 'AI-assisted, subject to human review'

function text(value) {
  return [{ type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }]
}

function assertObject(value, field) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${field} 必须是对象`)
  }
}

export function apply(ctx, config = {}) {
  const settings = {
    rulesDir: typeof config.rulesDir === 'string' && config.rulesDir.trim() !== '' ? config.rulesDir : 'rules',
    dsn: (typeof config.dsn === 'string' && config.dsn.trim() !== '')
      ? config.dsn
      : (process.env.FINANCE_MYSQL_DSN ?? ''),
    maxRows: Number.isInteger(config.maxRows) && config.maxRows > 0 ? config.maxRows : DEFAULT_MAX_ROWS,
  }

  const allowlist = [...new Set([...DEFAULT_ALLOWED, ...(Array.isArray(config.alsoAllow) ? config.alsoAllow : []), ...ALWAYS_ALLOWED])]
  const allowed = new Set(allowlist)

  // ---- 能力守卫：白名单之外，一律拒绝 ----------------------------------------
  ctx.tools.guard((exec) => {
    if (allowed.has(exec.name)) return undefined
    return `工具 ${exec.name} 不在本预设的只读白名单内（允许：${allowlist.join('、')}）。如确需该能力，请由人工调整预设配置。`
  })

  // ---- 1. 分录校验 ---------------------------------------------------------
  ctx.tools.register({
    name: 'finance_journal_entry_check',
    description:
      '校验一张会计分录草稿：借贷是否平衡、行结构是否完整、支持性文档是否缺口、制单人与审核人是否分离。'
      + '输入是调用方给出的分录草稿（JSON），工具不读取也不写入任何账簿。'
      + '结论只有 PASS / REVIEW / FAIL；FAIL 表示存在硬性阻断项，REVIEW 表示需人工确认，PASS 仅表示机械校验通过。'
      + '本工具永远不授权过账（authorization 恒为 NEVER_AUTHORIZES_POSTING），也不提供"帮你过账"的能力。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        entry: {
          type: 'object',
          description:
            '分录草稿。字段：entryId?、entryDate?(YYYY-MM-DD)、currency?、functionalCurrency?、exchangeRate?、'
            + 'preparedBy?、reviewedBy?、requiredDocuments?(字符串数组)、documents?([{type, ref}])、'
            + 'lines([{accountCode, accountName?, description?, debit?, credit?}])。',
          additionalProperties: true,
        },
      },
      required: ['entry'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => text(value),
    },
    async execute(args) {
      assertObject(args.entry, 'entry')
      return checkJournalEntry(args.entry)
    },
  })

  // ---- 2. 对账快照 ---------------------------------------------------------
  ctx.tools.register({
    name: 'finance_reconciliation_snapshot',
    description:
      '由调用方给出的余额与明细，计算机械对账快照：调整后余额、账龄分桶、分类汇总、陈旧项、签字准备状态。'
      + '不读取账簿、不写回任何结果，也不授权签字（authorization 恒为 NEVER_AUTHORIZES_SIGN_OFF）。'
      + 'signOff.status 只表示"材料是否齐备、是否存在阻断项"，最终签字由人工决定。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        snapshot: {
          type: 'object',
          description:
            '对账输入。字段：asOf(YYYY-MM-DD)、accountCode?、accountName?、openingBalance、'
            + 'items([{ref?, date?, amount, category?, counterparty?}])、adjustments?([{ref?, date?, amount, reason}])、'
            + 'bucketsDays?([30,60,90])、staleDays?(默认 90)、preparedBy?、reviewedBy?、systemBalance?。',
          additionalProperties: true,
        },
      },
      required: ['snapshot'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => text(value),
    },
    async execute(args) {
      assertObject(args.snapshot, 'snapshot')
      return reconciliationSnapshot(args.snapshot)
    },
  })

  // ---- 3. 差异桥接 ---------------------------------------------------------
  ctx.tools.register({
    name: 'finance_variance_bridge',
    description:
      '校验差异桥接是否闭合：基准值 + 各驱动因素 = 期望值，实际值 - 期望值 = 残差。'
      + '残差总是显式返回，绝不分摊或隐藏；并按给定重要性阈值判断残差是否重大。'
      + '用于月末波动分析、审计预检的驱动因素完整性检查。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        bridge: {
          type: 'object',
          description:
            '桥接输入。字段：account?、period?、currency?、base、actual、'
            + 'drivers([{label, amount, evidence?}])、materiality?({absolute?, percentOfBase?})、tolerance?(默认 0.01)。',
          additionalProperties: true,
        },
      },
      required: ['bridge'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => text(value),
    },
    async execute(args) {
      assertObject(args.bridge, 'bridge')
      return varianceBridge(args.bridge)
    },
  })

  // ---- 4. 只读查询 ---------------------------------------------------------
  ctx.tools.register({
    name: 'mysql_query',
    description:
      '只读查询。两种用法：'
      + '(a) sql 模式：单条 SELECT/WITH/SHOW/DESCRIBE/EXPLAIN，仅允许访问 accounts、fx_rates、rules、entities 四张表，'
      + '任何写操作或多语句直接拒绝；'
      + '(b) file 模式：读取工作区 rules/ 目录下的配置文件（.yml/.yaml/.json/.csv/.txt/.md），'
      + '用于读取 rules/hkfrs15.yml 等必须在场的规则文件。'
      + '本工具没有任何写入路径；数据库未配置或连接器缺失时返回结构化错误，调用方不得据此猜测数据。',
    parameters: {
      type: 'object',
      additionalProperties: false,
      properties: {
        sql: { type: 'string', description: '（模式 a）只读 SQL 语句。' },
        params: {
          type: 'array',
          items: {},
          description: '（模式 a，可选）绑定参数。',
        },
        file: { type: 'string', description: '（模式 b）相对工作区 rules/ 的文件路径，例如 hkfrs15.yml。' },
      },
      required: [],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => text(value),
    },
    async execute(args, exec) {
      const hasSql = typeof args.sql === 'string' && args.sql.trim() !== ''
      const hasFile = typeof args.file === 'string' && args.file.trim() !== ''
      if (hasSql && hasFile) throw new Error('sql 与 file 只能二选一')
      if (!hasSql && !hasFile) throw new Error('必须提供 sql 或 file 之一')

      if (hasFile) {
        const cwd = await ctx.workingDirectory.ensure(exec.agent, exec.signal)
        return readRulesFile(cwd, args.file, settings.rulesDir)
      }
      return runReadOnlyQuery(args.sql, args.params, settings)
    },
  })
}

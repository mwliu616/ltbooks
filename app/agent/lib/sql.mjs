/*
 * LtBooks — agent/lib/sql.mjs
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * mysql_query（只读）的守卫与后端选择。
 *
 * 三层防线：
 *   1. 语句层：只允许 SELECT / WITH / SHOW / DESCRIBE / EXPLAIN；去注释、去字符串字面量后
 *      再扫描写操作关键字；拒绝多语句。
 *   2. 对象层：FROM / JOIN 后的表名必须命中白名单（accounts、fx_rates、rules、entities）。
 *   3. 连接层：使用只读 DSN（建议数据库账号本身只有 SELECT 权限）；连接器缺失时明确报错。
 *
 * 另有文件模式：只读 <工作区>/rules 下的配置文件（YAML/JSON/CSV 等），
 * 用于 rules/hkfrs15.yml 这类"必须在场、不得由模型编造"的规则文件。
 */

import { readFile, realpath, stat } from 'node:fs/promises'
import { extname, isAbsolute, resolve, sep } from 'node:path'

export const ALLOWED_TABLES = new Set(['accounts', 'fx_rates', 'rules', 'entities'])
const ALLOWED_PREFIX = /^\s*(select|with|show|describe|desc|explain)\b/i
const WRITE_KEYWORDS = /(^|[\s(])(insert|update|delete|replace|drop|alter|rename|truncate|create\s+(table|database|index|view|user)|grant|revoke|call|prepare|execute|deallocate|handler|load\s+data|into\s+(outfile|dumpfile)|for\s+update|lock\s+in\s+share\s+mode)\b/i
const MAX_SQL_LENGTH = 4000
const MAX_FILE_BYTES = 512 * 1024
const DEFAULT_MAX_ROWS = 200

/** 去掉字符串字面量与注释，避免把字面量里的关键字当成写操作。 */
export function stripLiterals(sql) {
  let out = ''
  let i = 0
  let quote = null
  while (i < sql.length) {
    const ch = sql[i]
    const next = sql[i + 1]
    if (quote === null && ch === '-' && next === '-') {
      while (i < sql.length && sql[i] !== '\n') i += 1
      continue
    }
    if (quote === null && ch === '#') {
      while (i < sql.length && sql[i] !== '\n') i += 1
      continue
    }
    if (quote === null && ch === '/' && next === '*') {
      i += 2
      while (i < sql.length && !(sql[i] === '*' && sql[i + 1] === '/')) i += 1
      i += 2
      continue
    }
    if (quote === null && (ch === "'" || ch === '"' || ch === '`')) {
      quote = ch
      i += 1
      continue
    }
    if (quote !== null && ch === quote) {
      if (sql[i + 1] === quote) {
        i += 2
        continue
      }
      quote = null
      i += 1
      continue
    }
    if (quote !== null && ch === '\\') {
      i += 2
      continue
    }
    if (quote !== null) {
      // 字面量内容整体抹掉，只留一个空格避免两侧 token 粘连
      if (!out.endsWith(' ')) out += ' '
      i += 1
      continue
    }
    out += ch
    i += 1
  }
  return out
}

/**
 * 校验一条 SQL 是否只读且只触及白名单表。
 * @returns {{ok: true} | {ok: false, code: string, reason: string}}
 */
export function inspectSql(sql) {
  if (typeof sql !== 'string' || sql.trim() === '') {
    return { ok: false, code: 'empty_sql', reason: 'sql 为空' }
  }
  if (sql.length > MAX_SQL_LENGTH) {
    return { ok: false, code: 'sql_too_long', reason: `sql 超过 ${MAX_SQL_LENGTH} 字符` }
  }
  const cleaned = stripLiterals(sql)
  if (cleaned.includes(';') && cleaned.trim().replace(/;\s*$/, '').includes(';')) {
    return { ok: false, code: 'multi_statement', reason: '不允许多语句执行' }
  }
  if (!ALLOWED_PREFIX.test(cleaned)) {
    return { ok: false, code: 'not_read_only', reason: '只允许 SELECT / WITH / SHOW / DESCRIBE / EXPLAIN 开头的语句' }
  }
  const write = WRITE_KEYWORDS.exec(cleaned)
  if (write !== null) {
    return { ok: false, code: 'write_keyword', reason: `语句包含写操作关键字：${write[1]}` }
  }
  const tablePattern = /\b(?:from|join)\s+([`"]?)([A-Za-z0-9_$.]+)\1/gi
  for (const match of cleaned.matchAll(tablePattern)) {
    const name = match[2].split('.').pop().toLowerCase()
    if (name === 'dual') continue
    if (!ALLOWED_TABLES.has(name)) {
      return { ok: false, code: 'table_not_allowed', reason: `表 ${match[2]} 不在只读白名单内（允许：${[...ALLOWED_TABLES].join('、')}）` }
    }
  }
  return { ok: true }
}

/** 是否存在写操作意图的粗筛（给调用方日志用；不替代 inspectSql）。 */
export function looksLikeWrite(sql) {
  return typeof sql === 'string' && WRITE_KEYWORDS.test(stripLiterals(sql))
}

function inside(root, target) {
  return target === root || target.startsWith(root.endsWith(sep) ? root : root + sep)
}

/**
 * 只读读取规则/配置目录下的文件。
 * @param {string} cwd 会话工作区根
 * @param {string} relative 相对路径，必须落在 <cwd>/<rulesDir> 内
 * @returns {Promise<object>}
 */
export async function readRulesFile(cwd, relative, rulesDir = 'rules') {
  if (typeof relative !== 'string' || relative.trim() === '') {
    return { ok: false, code: 'empty_path', reason: '路径为空' }
  }
  const rootDir = resolve(cwd, rulesDir)
  const candidate = isAbsolute(relative) ? resolve(relative) : resolve(rootDir, relative)
  let rootReal
  let fileReal
  try {
    rootReal = await realpath(rootDir)
  } catch {
    return { ok: false, code: 'rules_dir_missing', reason: `规则目录不存在：${rulesDir}` }
  }
  try {
    fileReal = await realpath(candidate)
  } catch {
    return { ok: false, code: 'file_missing', reason: `文件不存在：${relative}` }
  }
  if (!inside(rootReal, fileReal)) {
    return { ok: false, code: 'path_not_allowed', reason: '只允许读取规则目录内的文件' }
  }
  const info = await stat(fileReal)
  if (!info.isFile()) return { ok: false, code: 'not_a_file', reason: '目标不是普通文件' }
  if (info.size > MAX_FILE_BYTES) return { ok: false, code: 'file_too_large', reason: `文件超过 ${MAX_FILE_BYTES} 字节` }
  const ext = extname(fileReal).toLowerCase()
  if (!['.yml', '.yaml', '.json', '.csv', '.txt', '.md'].includes(ext)) {
    return { ok: false, code: 'extension_not_allowed', reason: `不允许的文件类型：${ext || '(无扩展名)'}` }
  }
  const content = await readFile(fileReal, 'utf8')
  return {
    ok: true,
    source: 'rules-file',
    path: relative,
    bytes: info.size,
    content,
    note: '文件为只读读取，内容未经模型改写。',
  }
}

/**
 * 执行只读 SQL。
 * @param {string} sql
 * @param {unknown[]} params
 * @param {object} settings {dsn, maxRows}
 */
export async function runReadOnlyQuery(sql, params, settings) {
  const verdict = inspectSql(sql)
  if (!verdict.ok) return { ok: false, code: verdict.code, reason: verdict.reason }

  if (typeof settings.dsn !== 'string' || settings.dsn.trim() === '') {
    return {
      ok: false,
      code: 'dsn_not_configured',
      reason: '未配置只读数据库连接（FINANCE_MYSQL_DSN 或插件 config.dsn）',
    }
  }

  let driver
  try {
    driver = await import('mysql2/promise')
  } catch {
    return {
      ok: false,
      code: 'connector_unavailable',
      reason: '缺少 mysql2 连接器；在 profile 目录执行 pnpm add mysql2 后重启 dsh 即可启用数据库只读查询',
    }
  }

  const maxRows = Number.isInteger(settings.maxRows) && settings.maxRows > 0 ? settings.maxRows : DEFAULT_MAX_ROWS
  const cleaned = stripLiterals(sql)
  const stmt = /^\s*select\b/i.test(cleaned) && !/\blimit\b/i.test(cleaned)
    ? `SELECT * FROM (${sql}) AS _guard_q LIMIT ${maxRows}`
    : sql

  let connection
  try {
    connection = await driver.createConnection(settings.dsn)
    const [rows] = Array.isArray(params) && params.length > 0
      ? await connection.query(sql, params)
      : await connection.query(sql)
    const list = Array.isArray(rows) ? rows : []
    return {
      ok: true,
      source: 'mysql',
      rowCount: list.length,
      truncated: list.length >= maxRows,
      rows: list.slice(0, maxRows),
      executedSql: stmt === sql ? sql : undefined,
      note: '只读查询；连接账号应仅有 SELECT 权限。',
    }
  } catch (error) {
    return { ok: false, code: 'query_failed', reason: String(error && error.message ? error.message : error) }
  } finally {
    if (connection !== undefined) await connection.end().catch(() => {})
  }
}

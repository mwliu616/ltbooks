/*
 * LtBooks — agent/lib/money.mjs
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * 金额运算的唯一入口：整数分（cents）运算，避免二进制浮点误差。
 * 所有 finance_* 工具的借贷平衡、残差、账龄合计都必须经过这里。
 */

/** 判断是否为有限数值（拒绝 NaN / Infinity / 字符串数字）。 */
export function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

/** 转为整数分；非有限数值返回 null，由调用方记为结构性问题。 */
export function toCents(value) {
  if (!isFiniteNumber(value)) return null
  return Math.round(value * 100)
}

/** 由整数分还原两位小数金额。 */
export function fromCents(cents) {
  return Math.round(cents) / 100
}

/** 四舍五入到两位小数（仅用于展示，不用于平衡判定）。 */
export function round2(value) {
  if (!isFiniteNumber(value)) return null
  return fromCents(toCents(value))
}

/** 求和；任一分量为 null 时返回 null，绝不把坏数据静默当成 0。 */
export function sumCents(values) {
  let total = 0
  for (const value of values) {
    const cents = toCents(value)
    if (cents === null) return null
    total += cents
  }
  return total
}

/** 金额精度是否超过两位小数（>2 位视为录入精度问题）。 */
export function overPrecise(value) {
  if (!isFiniteNumber(value)) return false
  return Math.abs(value * 100 - Math.round(value * 100)) > 1e-9
}

/** 解析 YYYY-MM-DD（也接受 ISO 时间戳的日期部分），失败返回 null。 */
export function parseDate(value) {
  if (typeof value !== 'string') return null
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim())
  if (!match) return null
  const [, y, m, d] = match
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)))
  if (
    date.getUTCFullYear() !== Number(y)
    || date.getUTCMonth() !== Number(m) - 1
    || date.getUTCDate() !== Number(d)
  ) return null
  return date
}

/** 两个 YYYY-MM-DD 之间的整天数（asOf - then）；任一无法解析返回 null。 */
export function daysBetween(then, asOf) {
  const from = parseDate(then)
  const to = parseDate(asOf)
  if (!from || !to) return null
  return Math.round((to.getTime() - from.getTime()) / 86400000)
}

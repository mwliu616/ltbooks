/*
 * LtBooks — agent/lib/recon.mjs
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * finance_reconciliation_snapshot 的确定性内核。
 *
 * 只做机械计算：调整后余额、账龄分桶、分类汇总、陈旧项、签字准备状态。
 * 不授权签字（authorization 恒为 NEVER_AUTHORIZES_SIGN_OFF），不写任何存储。
 */

import { daysBetween, fromCents, isFiniteNumber, sumCents } from './money.mjs'

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function nonEmpty(value) {
  return typeof value === 'string' && value.trim() !== ''
}

function normalizeBuckets(input) {
  const raw = asArray(input).filter((n) => isFiniteNumber(n) && n > 0)
  const days = raw.length > 0 ? [...new Set(raw)].sort((a, b) => a - b) : [30, 60, 90]
  const buckets = []
  let from = 0
  for (const edge of days) {
    buckets.push({ label: `${from}-${edge}天`, fromDays: from, toDays: edge })
    from = edge + 1
  }
  buckets.push({ label: `${from}天以上`, fromDays: from, toDays: null })
  return buckets
}

/**
 * @param {object} snapshot 对账输入（由调用方提供）
 * @returns {object} 结构化快照结果
 */
export function reconciliationSnapshot(snapshot) {
  const source = snapshot !== null && typeof snapshot === 'object' ? snapshot : {}
  const asOf = nonEmpty(source.asOf) ? source.asOf.trim() : null
  const buckets = normalizeBuckets(source.bucketsDays)
  const staleDays = isFiniteNumber(source.staleDays) && source.staleDays > 0 ? source.staleDays : 90

  const blockers = []
  const reviewReasons = []

  if (asOf === null) blockers.push('缺少对账基准日 asOf（YYYY-MM-DD）')

  const openingCents = source.openingBalance === undefined ? 0 : sumCents([source.openingBalance])
  if (openingCents === null) blockers.push('openingBalance 不是有限数值')

  const items = asArray(source.items)
  const undated = []
  const stale = []
  const bucketed = buckets.map((bucket) => ({ ...bucket, amountCents: 0, count: 0, refs: [] }))
  const categoryMap = new Map()

  let itemsCents = 0
  items.forEach((item, index) => {
    const position = `第 ${index + 1} 项`
    if (item === null || typeof item !== 'object') {
      blockers.push(`${position}不是对象`)
      return
    }
    const amount = sumCents([item.amount ?? 0])
    if (amount === null) {
      blockers.push(`${position}金额不是有限数值`)
      return
    }
    if (!nonEmpty(item.ref)) reviewReasons.push(`${position}缺少凭证号 ref`)

    itemsCents += amount
    const category = nonEmpty(item.category) ? item.category.trim() : '未分类'
    const entry = categoryMap.get(category) ?? { category, amountCents: 0, count: 0 }
    entry.amountCents += amount
    entry.count += 1
    categoryMap.set(category, entry)

    const age = daysBetween(item.date, asOf)
    if (age === null) {
      undated.push({ ref: nonEmpty(item.ref) ? item.ref.trim() : null, amount: fromCents(amount) })
      return
    }

    const bucket = bucketed.find((entry) => age >= entry.fromDays && (entry.toDays === null || age <= entry.toDays))
    if (bucket !== undefined) {
      bucket.amountCents += amount
      bucket.count += 1
      bucket.refs.push(nonEmpty(item.ref) ? item.ref.trim() : `#${index + 1}`)
    }
    if (age > staleDays) {
      stale.push({
        ref: nonEmpty(item.ref) ? item.ref.trim() : null,
        date: String(item.date),
        ageDays: age,
        amount: fromCents(amount),
        reason: `账龄 ${age} 天，超过陈旧阈值 ${staleDays} 天`,
      })
    }
  })

  const adjustments = asArray(source.adjustments)
  const adjustmentCents = adjustments.reduce((total, adjustment) => {
    if (total === null) return null
    if (adjustment === null || typeof adjustment !== 'object') {
      blockers.push('调整项（adjustments）中存在非对象元素')
      return total
    }
    const amount = sumCents([adjustment.amount ?? 0])
    if (amount === null) {
      blockers.push('调整项金额不是有限数值')
      return total
    }
    if (!nonEmpty(adjustment.reason)) reviewReasons.push('存在未说明理由的调整项（reason 为空）')
    return total + amount
  }, 0)

  if (undated.length > 0) blockers.push(`有 ${undated.length} 项缺少可解析日期，无法账龄分析`)
  if (stale.length > 0) reviewReasons.push(`存在 ${stale.length} 项陈旧项`)

  const preparedBy = nonEmpty(source.preparedBy) ? source.preparedBy.trim() : null
  const reviewedBy = nonEmpty(source.reviewedBy) ? source.reviewedBy.trim() : null
  const segregationStatus = preparedBy && reviewedBy
    ? (preparedBy === reviewedBy ? 'NOT_SEPARATED' : 'SEPARATED')
    : 'UNCONFIGURED'
  if (segregationStatus !== 'SEPARATED') reviewReasons.push('编制人与复核人未有效分离')

  const closingCents = openingCents === null || itemsCents === null ? null : openingCents + itemsCents
  const adjustedCents = closingCents === null || adjustmentCents === null ? null : closingCents + adjustmentCents

  let differenceFromSystem = null
  if (isFiniteNumber(source.systemBalance)) {
    const systemCents = sumCents([source.systemBalance])
    differenceFromSystem = systemCents === null || adjustedCents === null ? null : fromCents(adjustedCents - systemCents)
    if (differenceFromSystem !== null && differenceFromSystem !== 0) {
      blockers.push(`调整后余额与系统余额相差 ${differenceFromSystem}`)
    }
  }

  let signOffStatus = 'READY'
  if (blockers.length > 0) signOffStatus = 'BLOCKED'
  else if (reviewReasons.length > 0) signOffStatus = 'PENDING_REVIEW'

  return {
    task: 'reconciliation_snapshot',
    asOf,
    account: {
      code: nonEmpty(source.accountCode) ? source.accountCode.trim() : null,
      name: nonEmpty(source.accountName) ? source.accountName.trim() : null,
    },
    openingBalance: openingCents === null ? null : fromCents(openingCents),
    movementTotal: fromCents(itemsCents),
    adjustmentsTotal: adjustmentCents === null ? null : fromCents(adjustmentCents),
    closingBalance: closingCents === null ? null : fromCents(closingCents),
    adjustedBalance: adjustedCents === null ? null : fromCents(adjustedCents),
    systemBalance: isFiniteNumber(source.systemBalance) ? fromCents(sumCents([source.systemBalance])) : null,
    differenceFromSystem,
    itemCount: items.length,
    aging: {
      buckets: bucketed.map((bucket) => ({
        label: bucket.label,
        fromDays: bucket.fromDays,
        toDays: bucket.toDays,
        amount: fromCents(bucket.amountCents),
        count: bucket.count,
      })),
      undated: { amount: fromCents(undated.reduce((t, item) => t + Math.round(item.amount * 100), 0)), count: undated.length },
      staleThresholdDays: staleDays,
    },
    categories: [...categoryMap.values()]
      .map((entry) => ({ category: entry.category, amount: fromCents(entry.amountCents), count: entry.count }))
      .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount)),
    staleItems: stale,
    undatedItems: undated,
    segregation: { preparedBy, reviewedBy, status: segregationStatus },
    signOff: { status: signOffStatus, blockers, reviewReasons },
    authorization: 'NEVER_AUTHORIZES_SIGN_OFF',
    disclaimer: 'AI-assisted, subject to human review',
  }
}

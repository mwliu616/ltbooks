/*
 * LtBooks — agent/lib/variance.mjs
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * finance_variance_bridge 的确定性内核。
 *
 * 只做机械桥接：基准 + 驱动因素 = 期望值；实际值 - 期望值 = 残差。
 * 残差必须在结果里显式暴露，永远不被分摊、吸收或隐藏。
 */

import { fromCents, isFiniteNumber, sumCents, toCents } from './money.mjs'

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function nonEmpty(value) {
  return typeof value === 'string' && value.trim() !== ''
}

/**
 * @param {object} bridge 桥接输入（由调用方提供）
 * @returns {object} 结构化桥接结果
 */
export function varianceBridge(bridge) {
  const source = bridge !== null && typeof bridge === 'object' ? bridge : {}
  const blockers = []
  const reviewReasons = []

  const baseCents = sumCents([source.base])
  if (baseCents === null) blockers.push('base 不是有限数值')
  const actualCents = sumCents([source.actual])
  if (actualCents === null) blockers.push('actual 不是有限数值')

  const drivers = asArray(source.drivers)
  const driverRows = []
  let driverCents = 0
  drivers.forEach((driver, index) => {
    const position = `第 ${index + 1} 个驱动因素`
    if (driver === null || typeof driver !== 'object') {
      blockers.push(`${position}不是对象`)
      return
    }
    const amountCents = sumCents([driver.amount])
    if (amountCents === null) {
      blockers.push(`${position}金额不是有限数值`)
      return
    }
    if (!nonEmpty(driver.label)) reviewReasons.push(`${position}缺少标签（label）`)
    if (!nonEmpty(driver.evidence)) reviewReasons.push(`${position}缺少支持证据（evidence）`)
    driverCents += amountCents
    driverRows.push({
      label: nonEmpty(driver.label) ? driver.label.trim() : `驱动因素 ${index + 1}`,
      amount: fromCents(amountCents),
      evidence: nonEmpty(driver.evidence) ? driver.evidence.trim() : null,
    })
  })

  const toleranceCents = isFiniteNumber(source.tolerance) && source.tolerance >= 0
    ? toCents(source.tolerance)
    : 1 // 默认 0.01

  const expectedCents = baseCents === null ? null : baseCents + driverCents
  const residualCents = expectedCents === null || actualCents === null ? null : actualCents - expectedCents
  const complete = residualCents !== null && Math.abs(residualCents) <= toleranceCents

  // ---- 重要性 -------------------------------------------------------------
  const materiality = source.materiality !== null && typeof source.materiality === 'object' ? source.materiality : {}
  const absoluteCents = isFiniteNumber(materiality.absolute) ? toCents(materiality.absolute) : null
  const percent = isFiniteNumber(materiality.percentOfBase) ? materiality.percentOfBase : null
  if (percent !== null && (percent < 0 || percent > 1)) reviewReasons.push('materiality.percentOfBase 应为 0-1 之间的小数')

  const thresholdCents = (() => {
    const candidates = []
    if (absoluteCents !== null) candidates.push(Math.abs(absoluteCents))
    if (percent !== null && baseCents !== null) candidates.push(Math.round(Math.abs(baseCents) * percent))
    if (candidates.length === 0) return null
    return Math.max(...candidates)
  })()

  if (thresholdCents === null) reviewReasons.push('未提供重要性阈值（materiality.absolute / percentOfBase），重要性无法判定')

  const isMaterial = residualCents !== null && thresholdCents !== null
    ? Math.abs(residualCents) > thresholdCents
    : null

  let verdict
  if (blockers.length > 0) verdict = 'INCOMPLETE_INPUT'
  else if (complete) verdict = 'COMPLETE'
  else if (isMaterial === true) verdict = 'INCOMPLETE_MATERIAL'
  else if (isMaterial === false) verdict = 'INCOMPLETE_IMMATERIAL'
  else verdict = 'INCOMPLETE_UNKNOWN_MATERIALITY'

  const residualPct = residualCents !== null && baseCents !== null && baseCents !== 0
    ? residualCents / baseCents
    : null

  return {
    task: 'variance_bridge',
    account: nonEmpty(source.account) ? source.account.trim() : null,
    period: nonEmpty(source.period) ? source.period.trim() : null,
    currency: nonEmpty(source.currency) ? source.currency.trim().toUpperCase() : null,
    base: baseCents === null ? null : fromCents(baseCents),
    drivers: driverRows,
    driversTotal: fromCents(driverCents),
    expected: expectedCents === null ? null : fromCents(expectedCents),
    actual: actualCents === null ? null : fromCents(actualCents),
    residual: residualCents === null ? null : fromCents(residualCents),
    residualPercentOfBase: residualPct === null ? null : Math.round(residualPct * 1e6) / 1e6,
    tolerance: fromCents(toleranceCents),
    complete,
    materiality: {
      absolute: absoluteCents === null ? null : fromCents(absoluteCents),
      percentOfBase: percent,
      threshold: thresholdCents === null ? null : fromCents(thresholdCents),
      isMaterial,
    },
    verdict,
    blockers,
    reviewReasons,
    note: '残差为实际值与期望值的机械差额；未分摊、未吸收，需由人工判断其性质。',
    disclaimer: 'AI-assisted, subject to human review',
  }
}

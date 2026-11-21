/*
 * LtBooks — agent/lib/journal.mjs
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */

/**
 * finance_journal_entry_check 的确定性内核。
 *
 * 只做机械校验：借贷平衡、分录行结构、文档缺口、制单人/审核人分离。
 * 不做准则判断、不推断科目、不写任何存储；"PASS" 仅表示机械校验通过，
 * 永远不等于授权过账（authorization 恒为 NEVER_AUTHORIZES_POSTING）。
 */

import { fromCents, isFiniteNumber, overPrecise, sumCents } from './money.mjs'

const BALANCE_TOLERANCE_CENTS = 0

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function nonEmpty(value) {
  return typeof value === 'string' && value.trim() !== ''
}

/**
 * @param {object} entry 分录草稿（由调用方提供，工具不读取任何存储）
 * @returns {object} 结构化校验结果
 */
export function checkJournalEntry(entry) {
  const source = entry !== null && typeof entry === 'object' ? entry : {}
  const lines = asArray(source.lines)

  const structureIssues = []
  const reviewReasons = []
  const debitAmounts = []
  const creditAmounts = []

  if (lines.length === 0) structureIssues.push('分录没有任何行（lines 为空）')

  lines.forEach((line, index) => {
    const position = `第 ${index + 1} 行`
    if (line === null || typeof line !== 'object') {
      structureIssues.push(`${position}不是对象`)
      return
    }

    const account = line.accountCode ?? line.account
    if (!nonEmpty(account)) structureIssues.push(`${position}缺少科目代码（accountCode）`)

    const debit = line.debit
    const credit = line.credit
    const hasDebit = debit !== undefined && debit !== null
    const hasCredit = credit !== undefined && credit !== null

    if (!hasDebit && !hasCredit) {
      structureIssues.push(`${position}借贷两栏都为空`)
      return
    }

    for (const [side, value] of [['借方', debit], ['贷方', credit]]) {
      if (value === undefined || value === null) continue
      if (!isFiniteNumber(value)) {
        structureIssues.push(`${position}${side}金额不是有限数值`)
      } else if (value < 0) {
        structureIssues.push(`${position}${side}金额为负数（应改用相反方向录入）`)
      } else if (value === 0) {
        reviewReasons.push(`${position}${side}金额为 0，行可能多余`)
      } else if (overPrecise(value)) {
        reviewReasons.push(`${position}${side}金额超过两位小数`)
      }
    }

    if (isFiniteNumber(debit) && debit > 0 && isFiniteNumber(credit) && credit > 0) {
      structureIssues.push(`${position}借贷两栏同时有正数金额`)
    }

    if (isFiniteNumber(debit) && isFiniteNumber(credit) && debit === 0 && credit === 0) {
      structureIssues.push(`${position}借贷两栏都是 0`)
    }

    debitAmounts.push(isFiniteNumber(debit) ? debit : 0)
    creditAmounts.push(isFiniteNumber(credit) ? credit : 0)
  })

  const debitTotalCents = sumCents(debitAmounts)
  const creditTotalCents = sumCents(creditAmounts)
  const differenceCents = debitTotalCents === null || creditTotalCents === null
    ? null
    : debitTotalCents - creditTotalCents
  const balanced = differenceCents === BALANCE_TOLERANCE_CENTS

  // ---- 文档缺口 -----------------------------------------------------------
  const requiredDocuments = asArray(source.requiredDocuments).filter(nonEmpty)
  const provided = asArray(source.documents)
    .map((doc) => (doc !== null && typeof doc === 'object' ? String(doc.type ?? '').trim() : ''))
    .filter((type) => type !== '')
  const missingDocuments = requiredDocuments.filter((type) => !provided.includes(type))
  const documentsStatus = requiredDocuments.length === 0 ? 'NOT_EVALUATED' : missingDocuments.length === 0 ? 'COMPLETE' : 'GAPS'
  if (documentsStatus === 'NOT_EVALUATED') {
    reviewReasons.push('未提供 requiredDocuments，无法判定文档完整性')
  }
  for (const type of missingDocuments) reviewReasons.push(`缺少支持性文档：${type}`)

  // ---- 制单人 / 审核人分离 -------------------------------------------------
  const preparedBy = nonEmpty(source.preparedBy) ? source.preparedBy.trim() : null
  const reviewedBy = nonEmpty(source.reviewedBy) ? source.reviewedBy.trim() : null
  let segregationStatus = 'UNCONFIGURED'
  if (preparedBy && reviewedBy) segregationStatus = preparedBy === reviewedBy ? 'NOT_SEPARATED' : 'SEPARATED'
  if (segregationStatus === 'NOT_SEPARATED') reviewReasons.push('制单人与审核人为同一人，职责未分离')
  if (segregationStatus === 'UNCONFIGURED') reviewReasons.push('制单人或审核人未配置，职责分离无法确认')

  // ---- 外币折算（仅当调用方给出汇率时） ------------------------------------
  const foreignCurrency = nonEmpty(source.currency) ? source.currency.trim().toUpperCase() : null
  const functionalCurrency = nonEmpty(source.functionalCurrency) ? source.functionalCurrency.trim().toUpperCase() : null
  const rate = source.exchangeRate
  const needsRate = foreignCurrency !== null && functionalCurrency !== null && foreignCurrency !== functionalCurrency
  if (needsRate && !isFiniteNumber(rate)) reviewReasons.push(`外币 ${foreignCurrency} 未提供折算汇率（exchangeRate）`)
  if (!needsRate && foreignCurrency && functionalCurrency && foreignCurrency === functionalCurrency && isFiniteNumber(rate) && rate !== 1) {
    reviewReasons.push('本位币分录却提供了非 1 的汇率')
  }
  const functionalTotals = needsRate && isFiniteNumber(rate) && debitTotalCents !== null && creditTotalCents !== null
    ? {
        debit: fromCents(Math.round(debitTotalCents * rate)),
        credit: fromCents(Math.round(creditTotalCents * rate)),
        rate,
      }
    : null

  // ---- 结论 ---------------------------------------------------------------
  const blockedReasons = [...structureIssues]
  if (!balanced) blockedReasons.push('借贷不平衡')

  let verdict = 'PASS'
  if (blockedReasons.length > 0) verdict = 'FAIL'
  else if (reviewReasons.length > 0) verdict = 'REVIEW'

  return {
    task: 'journal_entry_check',
    entryId: nonEmpty(source.entryId) ? source.entryId.trim() : null,
    entryDate: nonEmpty(source.entryDate) ? source.entryDate.trim() : null,
    currency: foreignCurrency,
    functionalCurrency,
    lineCount: lines.length,
    debitTotal: debitTotalCents === null ? null : fromCents(debitTotalCents),
    creditTotal: creditTotalCents === null ? null : fromCents(creditTotalCents),
    difference: differenceCents === null ? null : fromCents(differenceCents),
    balanced,
    functionalTotals,
    structure: { ok: structureIssues.length === 0, issues: structureIssues },
    documents: { status: documentsStatus, required: requiredDocuments, provided, missing: missingDocuments },
    segregation: { preparedBy, reviewedBy, status: segregationStatus },
    verdict,
    blockedReasons,
    reviewReasons,
    authorization: 'NEVER_AUTHORIZES_POSTING',
    disclaimer: 'AI-assisted, subject to human review',
  }
}

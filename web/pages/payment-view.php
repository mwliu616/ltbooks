<?php
/*
 * LtBooks — pages/payment-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 收款 / 付款单详情：表头、银行账户、会计分录、核销了哪些单据。 */
$role = isset($role) ? $role : 'accountant';
$id   = (int) ($_GET['id'] ?? 0);
$kind = (string) ($_GET['kind'] ?? 'received');
if (!in_array($kind, ['received', 'made'], true)) { $kind = 'received'; }
if (!$id) { echo errbox('缺少单据 ID'); return; }

$r = api_get('/payments/' . $kind . '/' . $id);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
$isIn = $kind === 'received';
$docs = $d['documents'] ?? [];
$title = $isIn ? '收款单详情' : '付款单详情';

$listPage = $isIn ? 'receipts' : 'payments';
$backBtn = '<a class="btn sm" href="?p=' . $listPage . '">← 返回</a>';
if ($role !== 'auditor' && (string) $d['status'] === 'draft') {
    $backBtn .= '<a class="btn sm primary" href="?p=' . $listPage . '&amp;edit=' . $id . '">编辑草稿</a>'
              . draft_delete_form($isIn ? 'payment_received' : 'payment_made', $id, $listPage);
}
echo card($title . ' ' . $d['paymentNo'], '', $backBtn, false); ?>

<?php ob_start(); ?>
<?= kv_grid([
  ['编号', '<span style="font-family:ui-monospace,monospace">' . e((string) $d['paymentNo']) . '</span>'],
  ['日期', e((string) $d['date'])],
  [$isIn ? '客户' : '供应商', e((string) ($d['party'] ?: ''))],
  ['币种', e((string) $d['currency'])],
  ['金额', money($d['amount'], (string) $d['currency'])],
  ['折 HKD', money($d['amountFunctional'], 'HKD')],
  ['汇率', e((string) $d['fxRate']) . ($d['fxRateDate'] ? '（' . e((string) $d['fxRateDate']) . '）' : '')],
  ['汇兑损益', money($d['settlementFxDiff'], 'HKD')],
  ['银行账户', $d['bank'] ? e((string) $d['bank']['name']) . ' · ' . e((string) $d['bank']['account']) : ''],
  ['记账凭证', $d['entry'] ? e((string) $d['entry']['entryNo']) : ''],
  ['状态', status_pill((string) $d['status'])],
  ['录入', e((string) ($d['createdBy'] ?: '')) . ' · ' . e((string) $d['createdAt'])],
]) ?>
<?php echo card('单据信息', ob_get_clean(), '', false); ?>

<?php ob_start(); ?>
<?php if (!$docs): ?>
  <?= empty_state('这张' . ($isIn ? '收款' : '付款') . '没有核销任何单据') ?>
<?php else: ?>
<div class="table-wrap"><table>
<thead><tr><th>单据号</th><th>单据日期</th><th class="num">单据金额</th>
<th class="num">本次核销</th><th class="num">累计已核销</th><th>跨币种</th><th class="num">汇兑差额</th></tr></thead>
<tbody>
<?php foreach ($docs as $x): ?>
  <tr>
    <td class="mono"><?= e((string) $x['docNo']) ?></td>
    <td><?= e((string) $x['docDate']) ?></td>
    <td class="num"><?= money($x['documentTotal'], (string) $x['currency']) ?></td>
    <td class="num"><b><?= money($x['settledOriginal'], (string) $x['currency']) ?></b></td>
    <td class="num"><?= money($x['documentSettled'], (string) $x['currency']) ?></td>
    <td><?= $x['crossCurrency'] ? '<span class="badge review">跨币种</span>' : '—' ?></td>
    <td class="num"><?= money($x['fxDiff'], 'HKD') ?></td>
  </tr>
<?php endforeach; ?>
</tbody></table></div>
<div class="hint" style="padding:10px 14px">
  共核销 <?= count($docs) ?> 张，合计 <?= money(array_sum(array_map(fn($x) => (float) $x['settledOriginal'], $docs)), (string) $d['currency']) ?>
</div>
<?php endif; ?>
<?php echo card('核销明细', ob_get_clean(), '', false); ?>

<?php
/*
 * LtBooks — pages/report-aging.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$side = (string) ($_GET['side'] ?? 'receivable');
if (!in_array($side, ['receivable', 'payable'], true)) { $side = 'receivable'; }
$asOf = (string) ($_GET['to'] ?? '');
$q = '/reports/aging?side=' . $side;
if ($asOf !== '' && preg_match('/^\d{4}-\d{2}-\d{2}$/', $asOf)) { $q .= '&asOf=' . urlencode($asOf); }
$r = api_get($q);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="tabs" style="margin-bottom:10px">
  <a class="tab<?= $side === 'receivable' ? ' active' : '' ?>" href="?p=report-aging&side=receivable">应收账龄</a>
  <a class="tab<?= $side === 'payable' ? ' active' : '' ?>" href="?p=report-aging&side=payable">应付账龄</a>
</div>
<div class="table-wrap"><table>
<thead><tr><th>币种</th><th class="num">0-30</th><th class="num">31-60</th>
<th class="num">61-90</th><th class="num">90+</th><th class="num">原币合计</th>
<th class="num">折 HKD</th></tr></thead>
<tbody>
<?php if (empty($d['byCurrency'])): ?>
<tr><td colspan="7"><?= empty_state($side === 'receivable' ? '没有未结应收：所有发票都已收款或尚未开票' : '没有未结应付：所有账单都已付款或尚未记账') ?></td></tr>
<?php endif; ?>
<?php foreach ($d['byCurrency'] as $g): ?>
<tr><td><?= e($g['currency']) ?></td>
<td class="num"><?= money($g['0-30']) ?></td>
<td class="num"><?= money($g['31-60']) ?></td>
<td class="num"><?= money($g['61-90']) ?></td>
<td class="num"><?= money($g['90+']) ?></td>
<td class="num"><?= money($g['total']) ?></td>
<td class="num"><?= money($g['functionalHkd']) ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) ($d['note'] ?? '')) ?></div>
<?php echo card('账龄分析（应收）', ob_get_clean(), '', false);

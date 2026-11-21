<?php
/*
 * LtBooks — pages/report-tb.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$rp = $GLOBALS['RP'] ?? report_period();
$r = api_get('/reports/trial-balance?asOf=' . urlencode($rp['to']));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>科目</th><th>名称</th><th class="num">借方</th><th class="num">贷方</th><th class="num">余额</th></tr></thead>
<tbody>
<?php foreach ($d['accounts'] as $a): ?>
<tr><td><?= e($a['accountCode']) ?></td><td><?= e(acc_name($a['accountCode'] ?? '', $a['accountName'] ?? '')) ?></td>
<td class="num"><?= money($a['debit']) ?></td>
<td class="num"><?= money($a['credit']) ?></td>
<td class="num"><?= money($a['balance']) ?></td></tr>
<?php endforeach; ?>
<tr class="total"><td>合计</td>
<td><?= $d['balanced'] ? '平衡' : '不平衡' ?></td>
<td class="num"><?= money($d['totalDebit']) ?></td>
<td class="num"><?= money($d['totalCredit']) ?></td>
<td class="num"><?= money($d['difference']) ?></td></tr>
</tbody></table></div>
<?php echo card('试算平衡', ob_get_clean(), '', false);

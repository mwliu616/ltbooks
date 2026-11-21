<?php
/*
 * LtBooks — pages/report-fx.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$r = api_get('/reports/fx');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>科目</th><th>名称</th><th>来源</th><th class="num">金额（HKD）</th></tr></thead>
<tbody>
<?php foreach ($d['items'] as $i): ?>
<tr><td><?= e($i['accountCode']) ?></td><td><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?></td>
<td><?= e($i['sourceType']) ?></td>
<td class="num" style="color:<?= (float) $i['amount'] >= 0 ? '#2E7D32' : 'var(--fail)' ?>"><?= money($i['amount']) ?></td></tr>
<?php endforeach; ?>
<?php if (!$d['items']): ?>
<tr><td colspan="4"><?= empty_state('暂无汇兑损益') ?></td></tr>
<?php endif; ?>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) ($d['note'] ?? '')) ?> · 合计 <?= money($d['total']) ?></div>
<?php echo card('汇兑损益', ob_get_clean(), '', false);

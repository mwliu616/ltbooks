<?php
/*
 * LtBooks — pages/report-bank.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$r = api_get('/reports/bank-balances');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>账户</th><th>币种</th><th class="num">原币余额</th><th class="num">折 HKD</th></tr></thead>
<tbody>
<?php foreach ($d['groups'] as $g): foreach ($g['accounts'] as $a): ?>
<tr><td><?= e($a['name']) ?></td><td><?= e($a['currency']) ?></td>
<td class="num"><?= money($a['current_balance'], (string) $a['currency']) ?></td>
<td class="num"><?= money($a['current_balance_functional'], 'HKD') ?></td></tr>
<?php endforeach; endforeach; ?>
<tr class="total"><td>HKD 折算合计</td><td>HKD</td><td class="num">—</td>
<td class="num"><?= money($d['hkdTotal'], 'HKD') ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) ($d['note'] ?? '')) ?></div>
<?php echo card('银行账户余额', ob_get_clean(), '', false);

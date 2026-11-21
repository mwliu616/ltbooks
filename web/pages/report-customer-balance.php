<?php
/*
 * LtBooks — pages/report-customer-balance.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$r = api_get('/reports/customer-balances');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>客户</th><th>币种</th><th class="num">发票数</th><th class="num">已开票</th>
<th class="num">已收款</th><th class="num">未收</th><th class="num">折 HKD</th></tr></thead>
<tbody>
<?php if (!$d['rows']): ?><tr><td colspan="7"><?= empty_state('暂无已过账销售发票') ?></td></tr><?php endif; ?>
<?php foreach ($d['rows'] as $x): ?>
  <tr><td><?= e((string) $x['party']) ?></td>
  <td><?= e((string) $x['currency']) ?></td>
  <td class="num"><?= (int) $x['invoices'] ?></td>
  <td class="num"><?= money($x['invoiced'], (string) $x['currency']) ?></td>
  <td class="num"><?= money($x['settled'], (string) $x['currency']) ?></td>
  <td class="num"><?= money($x['outstanding'], (string) $x['currency']) ?></td>
  <td class="num"><?= money($x['outstandingFunctional'], 'HKD') ?></td></tr>
<?php endforeach; ?>
<tr class="total"><td colspan="6">HKD 折算合计</td>
<td class="num"><?= money($d['totalFunctional'], 'HKD') ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) $d['note']) ?></div>
<?php echo card('客户余额表', ob_get_clean(), '', false); ?>

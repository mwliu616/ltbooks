<?php
/*
 * LtBooks — pages/report-purchase.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$r = api_get('/reports/purchase-detail');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>供应商</th><th>币种</th><th class="num">张数</th>
<th class="num">价税合计</th><th class="num">折 HKD</th></tr></thead>
<tbody>
<?php if (!$d['rows']): ?>
  <tr><td colspan="5"><?= empty_state('暂无已过账账单') ?></td></tr>
<?php endif; ?>
<?php foreach ($d['rows'] as $x): ?>
  <tr><td><?= e((string) $x['party']) ?></td>
  <td><?= e((string) $x['currency']) ?></td>
  <td class="num"><?= (int) $x['cnt'] ?></td>
  <td class="num"><?= money($x['gross_original'], (string) $x['currency']) ?></td>
  <td class="num"><?= money($x['functional'], 'HKD') ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php echo card('采购明细（按供应商与币种）', ob_get_clean(), '', false); ?>

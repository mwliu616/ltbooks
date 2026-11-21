<?php
/*
 * LtBooks — pages/report-ratios.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$r = api_get('/reports/ratios');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>比率</th><th class="num">数值</th><th>计算式</th><th>单位</th></tr></thead>
<tbody>
<?php foreach ($d['items'] as $i): ?>
  <?php
  $v = $i['value'] === null ? '—'
     : ($i['unit'] === '%' ? number_format($i['value'] * 100, 2) : number_format($i['value'], 4));
  ?>
  <tr><td><?= e((string) $i['name']) ?></td>
  <td class="num"><?= $v ?></td>
  <td class="hint"><?= e((string) $i['formula']) ?></td>
  <td><?= e((string) $i['unit']) ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) $d['note']) ?></div>
<?php echo card('财务比率表', ob_get_clean(), '', false); ?>
<?php
$b = $d['basis'];
ob_start(); ?>
<div class="grid">
  <div class="kv"><b>总资产</b><span><?= money($b['totalAssets']) ?></span></div>
  <div class="kv"><b>总负债</b><span><?= money($b['totalLiabilities']) ?></span></div>
  <div class="kv"><b>总权益</b><span><?= money($b['totalEquity']) ?></span></div>
  <div class="kv"><b>收入</b><span><?= money($b['revenue']) ?></span></div>
  <div class="kv"><b>流动资产</b><span><?= money($b['currentAssets']) ?></span></div>
  <div class="kv"><b>流动负债</b><span><?= money($b['currentLiabilities']) ?></span></div>
  <div class="kv"><b>应收</b><span><?= money($b['receivables']) ?></span></div>
  <div class="kv"><b>应付</b><span><?= money($b['payables']) ?></span></div>
</div>
<?php echo card('计算基础', ob_get_clean()); ?>

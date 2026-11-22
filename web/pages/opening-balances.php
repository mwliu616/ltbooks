<?php
/*
 * LtBooks — pages/opening-balances.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 期初余额：查看每个科目的当前期初，批量导入走「期初导入」。 */
$role = isset($role) ? $role : 'accountant';
$r = api_get('/opening-balances');
$d = $r['ok'] ? $r['data'] : ['accounts' => [], 'openingEntries' => []];
$rows = $d['accounts'] ?? [];
$entries = $d['openingEntries'] ?? [];
$dr = array_sum(array_map(fn($x) => max(0, (float) $x['balance']), $rows));
$cr = array_sum(array_map(fn($x) => max(0, -(float) $x['balance']), $rows));
?>
<div class="page-head">
  <div>
    <h1 class="page-title">期初余额</h1>
    <div class="page-sub">借方 <?= money($dr, 'HKD') ?> · 贷方 <?= money($cr, 'HKD') ?> · 差 <?= money($dr - $cr, 'HKD') ?></div>
  </div>
  <div class="page-actions">
    <a class="btn primary" href="?p=journal-new">＋ 手工补一笔</a>
  </div>
</div>

<?= help_html('opening-balances') ?>

<?php if ($entries): ?>
<section class="card" style="margin-bottom:16px">
  <div class="card-head"><h2 class="card-title">期初结转凭证</h2></div>
  <div class="table-wrap"><table>
    <thead><tr><th>凭证号</th><th>日期</th><th class="num">金额</th></tr></thead>
    <tbody>
    <?php foreach ($entries as $e): ?>
      <tr><td class="mono"><?= e((string) $e['entryNo']) ?></td>
        <td><?= e((string) $e['date']) ?></td>
        <td class="num"><?= money($e['amount'], 'HKD') ?></td></tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</section>
<?php endif; ?>

<?php ob_start(); ?>
<?php if (!$rows): ?>
  <?= empty_state('还没有任何余额。导入上一年度的科目余额表，或手工补一笔期初分录。') ?>
<?php else: ?>
<div class="table-wrap"><table>
  <thead><tr><th style="width:90px">科目</th><th>名称</th><th>类别</th>
    <th class="num" style="width:150px">余额</th></tr></thead>
  <tbody>
  <?php foreach ($rows as $x):
    $b = (float) $x['balance'];
  ?>
    <tr>
      <td class="mono"><?= e((string) $x['accountCode']) ?></td>
      <td><?= e(acc_name((string) $x['accountCode'], (string) $x['accountName'])) ?></td>
      <td class="hint"><?= e(cat_name((string) $x['category'])) ?></td>
      <td class="num"><?= money($b, 'HKD') ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
<?php endif; ?>
<?php echo card('科目余额', ob_get_clean(), '', false); ?>

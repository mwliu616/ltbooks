<?php
/*
 * LtBooks — pages/report-cf.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$__rp = $GLOBALS['RP'] ?? report_period();
/** 现金流量表（间接法）：期初 → 净利 → 调整 → 经营 → 投资 → 融资 → 期末。 */
$from = (string) ($_GET['from'] ?? $__rp['from']);
$to   = (string) ($_GET['to'] ?? $__rp['to']);
$r = api_get('/reports/cash-flow?from=' . urlencode($from) . '&to=' . urlencode($to));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th><?= e(t('项目')) ?></th><th class="num"><?= e(t('金额（HKD）')) ?></th></tr></thead>
<tbody>
  <tr><td><?= e(t('期初现金及现金等价物')) ?></td>
      <td class="num"><?= money($d['openingCash'] ?? 0) ?></td></tr>
  <?php if (abs((float) ($d['openingEntryCash'] ?? 0)) >= 0.005): ?>
    <tr><td><?= e(t('期内期初分录现金变动（不计入经营活动）')) ?></td>
        <td class="num"><?= money($d['openingEntryCash']) ?></td></tr>
  <?php endif; ?>

  <tr class="group"><td colspan="2"><b><?= e(t('经营活动')) ?></b></td></tr>
  <tr><td style="padding-left:22px"><?= e(t('本期净利／（亏损）')) ?>
      <?php if (abs((float) ($d['openingPlExcluded'] ?? 0)) >= 0.005): ?>
        <span class="hint" style="display:inline">· <?= e(t('已剔除期初结转损益')) ?>
          <?= money((float) $d['openingPlExcluded']) ?></span>
      <?php endif; ?></td>
      <td class="num"><?= money($d['netProfit'] ?? 0) ?></td></tr>
  <?php foreach (($d['nonCash'] ?? []) as $x): ?>
    <tr><td style="padding-left:22px"><?= e(t('非现金调整')) ?>：<?= e((string) $x['account']) ?></td>
        <td class="num"><?= money($x['amount']) ?></td></tr>
  <?php endforeach; ?>
  <?php foreach (($d['workingCapital'] ?? []) as $x): ?>
    <tr><td style="padding-left:22px"><?= e(t('营运资金变动')) ?>：<?= e(t((string) $x['label'])) ?></td>
        <td class="num"><?= money($x['amount']) ?></td></tr>
  <?php endforeach; ?>
  <tr class="total"><td><?= e(t('经营活动带来的现金净额')) ?></td>
      <td class="num"><?= money($d['operating']) ?></td></tr>

  <tr class="group"><td colspan="2"><b><?= e(t('投资活动')) ?></b></td></tr>
  <tr><td style="padding-left:22px"><?= e(t('投资活动带来的现金净额')) ?></td>
      <td class="num"><?= money($d['investing']) ?></td></tr>

  <tr class="group"><td colspan="2"><b><?= e(t('融资活动')) ?></b></td></tr>
  <tr><td style="padding-left:22px"><?= e(t('融资活动带来的现金净额')) ?></td>
      <td class="num"><?= money($d['financing']) ?></td></tr>

  <tr class="total"><td><?= e(t('现金净变动')) ?></td><td class="num"><?= money($d['netChange']) ?></td></tr>
  <tr class="total"><td><?= e(t('期末现金余额')) ?></td><td class="num"><?= money($d['closingCash']) ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e(t((string) ($d['note'] ?? ''))) ?></div>
<?php
$tools = '';
echo card(t('现金流量表'), ob_get_clean(), $tools, false);

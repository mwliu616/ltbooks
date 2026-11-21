<?php
/*
 * LtBooks — pages/report-statements.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$from = (string) ($_GET['from'] ?? (date('Y') . '-01-01'));
$to   = (string) ($_GET['to'] ?? date('Y-m-d'));
$r = api_get('/reports/statements?from=' . urlencode($from) . '&to=' . urlencode($to));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$fs = $r['data'];

$sp = $fs['statementOfFinancialPosition'];
$pl = $fs['statementOfProfitOrLoss'];
$eq = $fs['statementOfChangesInEquity'];
$cf = $fs['statementOfCashFlows'];

function money2($v): string { return money($v); }
?>
<nav class="stmt-nav" aria-label="报表章节">
  <a href="#s1">财务状况表</a><a href="#s2">损益及全面收益</a>
  <a href="#s3">权益变动</a><a href="#s4">现金流量</a><a href="#s5">附注</a>
</nav>

<div class="metrics">
  <div class="metric c3"><div class="lbl">资产总额</div><div class="val"><?= money2($sp['assetsTotal']) ?></div>
    <div class="sub"><?= $sp['check']['balanced'] ? '与权益及负债平衡' : '不平衡，须核查' ?></div></div>
  <div class="metric c3"><div class="lbl">本期溢利</div><div class="val"><?= money2($pl['netProfit']) ?></div>
    <div class="sub">全面收益 <?= money2($pl['totalComprehensiveIncome']) ?></div></div>
  <div class="metric c3"><div class="lbl">期末权益</div><div class="val"><?= money2($eq['closingEquity']) ?></div>
    <div class="sub">期初 <?= money2($eq['openingEquity']) ?></div></div>
  <div class="metric c3"><div class="lbl">期末现金</div><div class="val"><?= money2($cf['closingCash']) ?></div>
    <div class="sub">净变动 <?= money2($cf['netChange']) ?></div></div>
</div>

<?php
// 财务状况表
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>项目</th><th class="num">金额（HKD）</th></tr></thead>
<tbody>
  <tr class="total"><td colspan="2">资产</td></tr>
  <?php if ($sp['assetsNonCurrent']['items']): ?>
    <tr><td style="font-weight:400">非流动资产</td><td class="num"></td></tr>
    <?php foreach ($sp['assetsNonCurrent']['items'] as $i): ?>
      <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?>
        <span class="hint" style="display:inline">· <?= e($i['accountCode']) ?></span></td>
        <td class="num"><?= money2($i['amount']) ?></td></tr>
    <?php endforeach; ?>
    <tr><td style="font-weight:400">非流动资产合计</td><td class="num" style="font-weight:400"><?= money2($sp['assetsNonCurrent']['total']) ?></td></tr>
  <?php endif; ?>
  <tr><td style="font-weight:400">流动资产</td><td class="num"></td></tr>
  <?php foreach ($sp['assetsCurrent']['items'] as $i): ?>
    <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?>
      <span class="hint" style="display:inline">· <?= e($i['accountCode']) ?></span></td>
      <td class="num"><?= money2($i['amount']) ?></td></tr>
  <?php endforeach; ?>
  <tr><td style="font-weight:400">流动资产合计</td><td class="num" style="font-weight:400"><?= money2($sp['assetsCurrent']['total']) ?></td></tr>
  <tr class="total"><td>资产合计</td><td class="num"><?= money2($sp['assetsTotal']) ?></td></tr>

  <tr class="total"><td colspan="2">权益及负债</td></tr>
  <tr><td style="font-weight:400">权益</td><td class="num"></td></tr>
  <?php foreach ($sp['equity']['items'] as $i): ?>
    <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?></td>
      <td class="num"><?= money2($i['amount']) ?></td></tr>
  <?php endforeach; ?>
  <tr><td style="padding-left:24px"><?= e(t('累计损益（截至期末）')) ?></td><td class="num"><?= money2($sp['equity']['currentYearProfit']) ?></td></tr>
  <tr><td style="font-weight:400">权益合计</td><td class="num" style="font-weight:400"><?= money2($sp['equity']['total']) ?></td></tr>
  <?php if ($sp['liabilitiesNonCurrent']['items']): ?>
    <tr><td style="font-weight:400">非流动负债</td><td class="num"></td></tr>
    <?php foreach ($sp['liabilitiesNonCurrent']['items'] as $i): ?>
      <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?></td>
        <td class="num"><?= money2($i['amount']) ?></td></tr>
    <?php endforeach; ?>
  <?php endif; ?>
  <tr><td style="font-weight:400">流动负债</td><td class="num"></td></tr>
  <?php foreach ($sp['liabilitiesCurrent']['items'] as $i): ?>
    <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?></td>
      <td class="num"><?= money2($i['amount']) ?></td></tr>
  <?php endforeach; ?>
  <tr><td style="font-weight:400">负债合计</td><td class="num" style="font-weight:400"><?= money2($sp['liabilitiesTotal']) ?></td></tr>
  <tr class="total"><td>权益及负债合计</td>
    <td class="num"><?= money2($sp['equity']['total'] + $sp['liabilitiesTotal']) ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px">
  勾稽：资产 <?= money2($sp['check']['assetsTotal']) ?> － 权益及负债
  <?= money2($sp['check']['liabilitiesPlusEquity']) ?> ＝ <?= money2($sp['check']['difference']) ?>
  <?= $sp['check']['balanced'] ? badge('PASS') : badge('FAIL') ?>
</div>
<?php echo '<div id="s1">' . card('一、财务状况表（于 ' . e($to) . ' 结算）', ob_get_clean(), '',
  export_menu(export_lang_items('/reports/pdf', ['kind' => 'balance-sheet', 'to' => $to]), t('导出 PDF'), 'btn sm'), false) . '</div>';
?>

<?php
// 损益及其他全面收益表
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>项目</th><th class="num">金额（HKD）</th></tr></thead>
<tbody>
  <tr><td style="font-weight:400">收入</td><td class="num" style="font-weight:400"><?= money2($pl['revenue']['total']) ?></td></tr>
  <?php foreach ($pl['revenue']['items'] as $i): ?>
    <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?></td><td class="num"><?= money2($i['amount']) ?></td></tr>
  <?php endforeach; ?>
  <tr><td>销售成本</td><td class="num">(<?= money2(abs($pl['costOfSales']['total'])) ?>)</td></tr>
  <tr class="total"><td>毛利</td><td class="num"><?= money2($pl['grossProfit']) ?></td></tr>
  <tr><td style="font-weight:400">经营费用</td><td class="num" style="font-weight:400"><?= money2($pl['operatingExpenses']['total']) ?></td></tr>
  <?php foreach ($pl['operatingExpenses']['items'] as $i): ?>
    <tr><td style="padding-left:24px"><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?></td><td class="num"><?= money2($i['amount']) ?></td></tr>
  <?php endforeach; ?>
  <tr><td>除税前溢利</td><td class="num"><?= money2($pl['profitBeforeTax']) ?></td></tr>
  <tr class="total"><td>本期溢利</td><td class="num"><?= money2($pl['netProfit']) ?></td></tr>
  <tr><td>其他全面收益</td><td class="num"><?= money2($pl['otherComprehensiveIncome']) ?></td></tr>
  <tr class="total"><td>本期全面收益总额</td><td class="num"><?= money2($pl['totalComprehensiveIncome']) ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) $pl['note']) ?></div>
<?php echo '<div id="s2">' . card('二、损益及其他全面收益表（' . e($from) . ' 至 ' . e($to) . '）', ob_get_clean(), '',
  export_menu(export_lang_items('/reports/pdf', ['kind' => 'pnl', 'from' => $from, 'to' => $to]), t('导出 PDF'), 'btn sm'), false) . '</div>';
?>

<?php
// 权益变动表
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>项目</th><th class="num">金额（HKD）</th></tr></thead>
<tbody>
  <tr class="total"><td colspan="2">期初权益（<?= e($from) ?>）</td></tr>
  <tr><td style="padding-left:24px">权益科目余额</td><td class="num"><?= money2($eq['openingEquityAccounts']) ?></td></tr>
  <tr><td style="padding-left:24px">累计未分配利润</td><td class="num"><?= money2($eq['openingRetainedProfit']) ?></td></tr>
  <tr><td style="font-weight:400">期初权益合计</td><td class="num" style="font-weight:400"><?= money2($eq['openingEquity']) ?></td></tr>
  <tr class="total"><td colspan="2">本期变动</td></tr>
  <tr><td style="padding-left:24px">本期溢利</td><td class="num"><?= money2($eq['profitForPeriod']) ?></td></tr>
  <tr><td style="padding-left:24px">权益直接变动（增资／股息等）</td><td class="num"><?= money2($eq['equityDirectMovements']) ?></td></tr>
  <tr class="total"><td>期末权益（<?= e($to) ?>）</td><td class="num"><?= money2($eq['closingEquity']) ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) $eq['note']) ?> ·
  <?= $eq['balanced'] ? badge('PASS') . ' 与损益表勾稽一致' : badge('FAIL') . ' 勾稽异常' ?></div>
<?php echo '<div id="s3">' . card('三、权益变动表', ob_get_clean(), '',
  export_menu(export_lang_items('/reports/statements/pdf', ['from' => $from, 'to' => $to]), t('导出 PDF'), 'btn sm'), false) . '</div>';
?>

<?php
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>项目</th><th class="num">金额（HKD）</th></tr></thead>
<tbody>
  <tr><td>经营活动现金流量净额</td><td class="num"><?= money2($cf['operating']) ?></td></tr>
  <tr><td>投资活动现金流量净额</td><td class="num"><?= money2($cf['investing']) ?></td></tr>
  <tr><td>筹资活动现金流量净额</td><td class="num"><?= money2($cf['financing']) ?></td></tr>
  <tr class="total"><td>现金及现金等价物净增加</td><td class="num"><?= money2($cf['netChange']) ?></td></tr>
  <tr class="total"><td>期末现金及现金等价物</td><td class="num"><?= money2($cf['closingCash']) ?></td></tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) ($cf['note'] ?? '')) ?></div>
<?php echo '<div id="s4">' . card('四、现金流量表', ob_get_clean(), '',
  export_menu(export_lang_items('/reports/pdf', ['kind' => 'cash-flow', 'to' => $to]), t('导出 PDF'), 'btn sm'), false) . '</div>';
?>

<?php
ob_start(); ?>
<ul class="hint" style="line-height:1.9;padding-left:18px">
  <?php foreach ($fs['notes']['basis'] as $b): ?><li><?= e($b) ?></li><?php endforeach; ?>
</ul>
<div style="margin-top:12px"><b>主要会计政策</b>
  <ul class="hint" style="line-height:1.9;padding-left:18px;margin-top:6px">
    <?php foreach ($fs['notes']['policies'] as $p): ?><li><?= e($p) ?></li><?php endforeach; ?>
  </ul>
</div>
<div class="hint" style="margin-top:10px">两级制税率资格：<?= e((string) $fs['notes']['twoTierStatus']) ?></div>
<?php echo '<div id="s5">' . card('五、财务报表附注（摘要）', ob_get_clean()) . '</div>'; ?>

<script>
/* 章节导航：滚动时高亮当前章节 */
(function () {
  var nav = document.querySelector('.stmt-nav');
  if (!nav) return;
  var links = [].slice.call(nav.querySelectorAll('a'));
  var secs = links.map(function (a) { return document.querySelector(a.getAttribute('href')); });
  function onScroll() {
    var y = window.scrollY + 140, cur = 0;
    secs.forEach(function (s, i) { if (s && s.offsetTop <= y) cur = i; });
    links.forEach(function (a, i) { a.classList.toggle('on', i === cur); });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();
</script>

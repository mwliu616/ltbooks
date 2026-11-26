<?php
/*
 * LtBooks — pages/report-tax.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$__rp = $GLOBALS['RP'] ?? report_period();
$period = (string) ($_GET['period'] ?? substr((string) $__rp['to'], 0, 7));
$msg = null; $errMsg = null;

// 新增调整项
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'add_tax_line') {
    $r = api_post('/tax/lines', [
        'period' => $period,
        'category' => (string) ($_POST['category'] ?? ''),
        'itemName' => trim((string) ($_POST['itemName'] ?? '')),
        'amount' => (float) ($_POST['amount'] ?? 0),
        'basisNote' => trim((string) ($_POST['basisNote'] ?? '')),
        'actor' => $displayName ?? 'system',
    ]);
    $msg = $r['ok'] ? '调整项已添加' : null;
    $errMsg = $r['ok'] ? null : (string) $r['error'];
}
// 删除调整项
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'delete_tax_line') {
    $lid = (int) ($_POST['lineId'] ?? 0);
    $r = api_request('DELETE', '/tax/lines/' . $lid, null);
    $msg = $r['ok'] ? '调整项已删除' : null;
    $errMsg = $r['ok'] ? null : (string) $r['error'];
}

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

$r = api_get('/tax/computation?period=' . urlencode($period));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
$money = fn($v) => number_format((float) $v, 2);

$fmt = function (array $items) use ($money) {
    $out = '';
    foreach ($items as $x) {
        $out .= '<tr><td style="padding-left:24px">' . e((string) $x['item_name'])
              . ($x['basis_note'] ? ' <span class="hint" style="display:inline">（' . e((string) $x['basis_note']) . '）</span>' : '')
              . '</td><td class="num">' . $money($x['amount']) . '</td>';
        $out .= '<td style="white-space:nowrap">';
        if (($role ?? '') !== 'auditor') {
            $out .= '<form method="post" style="display:inline">' . csrf_field()
                  . '<input type="hidden" name="action" value="delete_tax_line">'
                  . '<input type="hidden" name="lineId" value="' . (int) $x['line_id'] . '">'
                  . '<button class="btn sm danger">删除</button></form>';
        }
        $out .= '</td></tr>';
    }
    return $out ?: '<tr><td style="padding-left:24px;color:var(--c-text-3)">（无调整项）</td><td class="num">—</td><td></td></tr>';
};
?>
<div class="toolbar">
  <span class="hint">基期止：<?= e($period) ?>（用上面的期间选择器调整）</span>
  <span class="grow"></span>
  <?= export_menu(export_lang_items('/tax/pdf', ['period' => $period])) ?>
</div>

<?php if (empty($d['computed'])): ?>
  <div class="banner REVIEW">
    <span class="banner-icon">!</span>
    <div class="banner-body">
      <div class="banner-title">无法计税：两级制税率资格未确定</div>
      <div class="banner-reason"><?= e((string) $d['reason']) ?></div>
    </div>
  </div>
<?php endif; ?>

<?php ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>项目</th><th class="num" style="width:150px">金额（HKD）</th><th style="width:70px"></th></tr></thead>
<tbody>
  <tr class="total"><td colspan="3">课税年度 <?= e((string) $d['yearOfAssessment']) ?> · 基期止 <?= e($period) ?></td></tr>

  <tr><td><b>会计利润</b>（除税前溢利）</td><td class="num"><b><?= $money($d['accountingProfit']) ?></b></td><td></td></tr>

  <tr><td colspan="3" style="background:var(--c-surface-alt)"><b>加：不可扣税开支</b></td></tr>
  <?= $fmt($d['addBacks']) ?>
  <tr><td style="font-weight:400">加回合计</td><td class="num" style="font-weight:400"><?= $money($d['totalAddBack']) ?></td><td></td></tr>

  <tr><td colspan="3" style="background:var(--c-surface-alt)"><b>减：非应课税收入</b></td></tr>
  <?= $fmt($d['deducts']) ?>
  <tr><td style="font-weight:400">扣除合计</td><td class="num" style="font-weight:400">(<?= $money($d['totalDeduct']) ?>)</td><td></td></tr>

  <tr class="total"><td>经调整的应评税利润</td><td class="num"><?= $money($d['adjustedAssessable']) ?></td><td></td></tr>

  <tr><td colspan="3" style="background:var(--c-surface-alt)"><b>减：资本免税额</b></td></tr>
  <?= $fmt($d['capitalAllowances']) ?>
  <tr><td style="font-weight:400">扣除合计</td><td class="num" style="font-weight:400">(<?= $money($d['totalCapitalAllowance']) ?>)</td><td></td></tr>

  <tr class="total"><td style="font-size:var(--f-md)">应评税利润</td><td class="num" style="font-size:var(--f-md)"><?= $money($d['assessableProfit']) ?></td><td></td></tr>

  <?php if (!empty($d['computed'])): ?>
    <tr><td colspan="3" style="background:var(--c-surface-alt)"><b>应缴利得税</b></td></tr>
    <tr><td style="padding-left:24px"><?= e(t('首')) ?> <?= $money($d['tier1Cap']) ?> @ <?= e((string) round($d['tier1Rate'] * 100, 4)) ?>%</td>
        <td class="num"><?= $money($d['tier1Profit']) ?></td><td></td></tr>
    <tr><td style="padding-left:24px">其余 @ <?= e((string) round($d['tier2Rate'] * 100, 4)) ?>%</td>
        <td class="num"><?= $money($d['tier2Profit']) ?></td><td></td></tr>
    <tr class="total"><td>应缴利得税</td><td class="num"><?= $money($d['taxPayable']) ?></td><td></td></tr>
    <?php if (!empty($d['provisionalTaxPaid'])): ?>
      <tr><td style="padding-left:24px">减：已缴暂缴税</td><td class="num">(<?= $money($d['provisionalTaxPaid']) ?>)</td><td></td></tr>
      <tr class="total"><td>应补缴／（应退税）</td><td class="num"><?= $money($d['balancePayable']) ?></td><td></td></tr>
    <?php endif; ?>
  <?php endif; ?>
</tbody></table></div>
<div class="hint" style="padding:10px 14px">
  两级制税率资格：<code><?= e(t(['undetermined' => '未确定', 'nominated' => '已提名',
                                 'not_nominated' => '未提名'][(string) $d['twoTierStatus']] ?? (string) $d['twoTierStatus'])) ?></code> · <?= e((string) ($d['note'] ?? '')) ?>
</div>
<?php echo card('利得税计算表（依《税务条例》第112章）', ob_get_clean(), '', false); ?>

<?php if (($role ?? '') !== 'auditor'): ?>
<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="add_tax_line">
  <div class="grid">
    <div class="field"><label class="f">类别</label>
      <select name="category">
        <option value="add_back">加回：不可扣税开支</option>
        <option value="deduct">扣除：非应课税收入</option>
        <option value="capital_allowance">资本免税额</option>
      </select></div>
    <div class="field"><label class="f">项目名称</label>
      <input type="text" name="itemName" placeholder="例如：会计折旧 / 罚款 / 离岸利润" required></div>
    <div class="field"><label class="f">金额</label>
      <input type="number" step="0.01" min="0" name="amount" required></div>
    <div class="field span-full"><label class="f">依据</label>
      <input type="text" name="basisNote" placeholder="例如：第17(1)(c)条 资本性开支"></div>
  </div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <button class="btn primary">添加调整项</button>
    <span class="hint">调整须逐项列示并可追溯依据；会计折旧须全额加回，另按第37-39B条计资本免税额</span>
  </div>
</form>
<?php echo card('新增税务调整', ob_get_clean()); ?>
<?php endif; ?>

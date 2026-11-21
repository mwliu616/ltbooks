<?php
/*
 * LtBooks — pages/report-gl.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$__rp = $GLOBALS['RP'] ?? report_period();
$account = trim((string) ($_GET['account'] ?? ''));
$from = (string) ($_GET['from'] ?? '');
$to = (string) ($_GET['to'] ?? '');

// 页面参数与接口参数必须分开拼：直接把 ?p=report-gl 截掉会留下前导 &，接口会 404
$params = [];
if ($account !== '') { $params['account'] = $account; }
if ($from !== '') { $params['from'] = $from; }
if ($to !== '') { $params['to'] = $to; }
$r = api_get('/reports/general-ledger' . ($params ? '?' . http_build_query($params) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];

$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$sel = '<option value="">— 全部科目汇总 —</option>';
foreach ($accounts as $a) {
    $s = ((string) $a['account_code'] === $account) ? ' selected' : '';
    $sel .= '<option value="' . e((string) $a['account_code']) . '"' . $s . '>'
          . e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) . '</option>';
}
?>
<form method="get" class="toolbar">
  <input type="hidden" name="p" value="report-gl">
  <input type="hidden" name="from" value="<?= e($from) ?>">
  <input type="hidden" name="to" value="<?= e($to) ?>">
  <select name="account"><?= $sel ?></select>
  <button class="btn sm">查看</button>
</form>

<?php if (isset($d['lines'])): ?>
  <?php ob_start(); ?>
  <div class="hint" style="margin-bottom:8px">
    科目 <?= e(acc_name((string) ($d['account']['account_code'] ?? ''), (string) ($d['account']['account_name'] ?? ''))) ?> ·
    正常余额方向 <?= e((string) ($d['account']['normal_balance'] ?? '')) ?> ·
    期末余额 <b><?= money($d['closingBalance'] ?? null, 'HKD') ?></b>
  </div>
  <div class="table-wrap"><table>
  <thead><tr><th>日期</th><th>分录号</th><th>来源</th><th>说明</th>
  <th class="num">借方</th><th class="num">贷方</th><th class="num">余额</th></tr></thead>
  <tbody>
  <?php if (!$d['lines']): ?>
    <tr><td colspan="7"><?= empty_state('该科目在此区间没有发生额') ?></td></tr>
  <?php endif; ?>
  <?php foreach ($d['lines'] as $l): ?>
    <tr><td><?= e((string) $l['entryNo'] === '' ? '' : (string) $l['date']) ?></td>
    <td><?= e((string) $l['entryNo']) ?></td>
    <td><?= e((string) $l['source']) ?></td>
    <td><?= e((string) ($l['description'] ?: '—')) ?></td>
    <td class="num"><?= money($l['debit']) ?></td>
    <td class="num"><?= money($l['credit']) ?></td>
    <td class="num"><?= money($l['balance']) ?></td></tr>
  <?php endforeach; ?>
  </tbody></table></div>
  <?php echo card('总账明细', ob_get_clean(), '', false); ?>
<?php else: ?>
  <?php ob_start(); ?>
  <div class="table-wrap"><table>
  <thead><tr><th>科目</th><th>名称</th><th>类别</th><th class="num">借方</th>
  <th class="num">贷方</th><th class="num">余额</th><th></th></tr></thead>
  <tbody>
  <?php foreach ($d['accounts'] as $a): ?>
    <tr><td><?= e((string) $a['account_code']) ?></td>
    <td><?= e(acc_name((string) $a['account_code'], (string) $a['account_name'])) ?></td>
    <td class="hint"><?= e(cat_name((string) $a['category'])) ?></td>
    <td class="num"><?= money($a['dr']) ?></td>
    <td class="num"><?= money($a['cr']) ?></td>
    <td class="num"><?= money($a['balance']) ?></td>
    <td><a class="btn sm" href="?p=report-gl&account=<?= urlencode((string) $a['account_code']) ?>">明细</a></td></tr>
  <?php endforeach; ?>
  </tbody></table></div>
  <?php echo card('总账（科目发生额）', ob_get_clean(), '', false); ?>
<?php endif; ?>

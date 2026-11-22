<?php
/*
 * LtBooks — pages/bank-transactions.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 交易记录：所有流水在一页查看，可按账户与状态筛选。 */
$role = isset($role) ? $role : 'accountant';
$accId = (int) ($_GET['account'] ?? 0);
$st = (string) ($_GET['status'] ?? 'all');
$accR = api_get('/bank-accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
[$page, $per] = pager_state('ledu_bank_lines_per', 25);
$limit = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$qs = '/bank-lines?limit=' . $limit . '&offset=' . $offset
    . ($accId ? '&accountId=' . $accId : '')
    . ($st !== 'all' ? '&status=' . urlencode($st) : '');
$r = api_get($qs);
$lines = $r['ok'] ? ($r['data']['lines'] ?? []) : [];
$totalRows = (int) ($r['data']['total'] ?? count($lines));
$in = (float) ($r['data']['amountIn'] ?? 0);
$out = (float) ($r['data']['amountOut'] ?? 0);
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e(t('交易记录')) ?></h1>
    <div class="page-sub"><?= e(str_replace(
        ['{n}', '{in}', '{out}'],
        [(string) $totalRows, money($in, 'HKD'), money(abs($out), 'HKD')],
        t('{n} 笔 · 收入 {in} · 支出 {out}'))) ?></div>
  </div>
  <div class="page-actions" style="display:flex;gap:8px">
    <a class="btn" href="?p=bank-import"><?= e(t('导入流水')) ?></a>
    <a class="btn primary" href="?p=reconcile">去对账</a>
  </div>
</div>

<?= help_html('bank-transactions') ?>

<form method="get" class="toolbar">
  <input type="hidden" name="p" value="bank-transactions">
  <select name="account" onchange="this.form.submit()">
    <option value="0">全部账户</option>
    <?php foreach ($accounts as $a): ?>
      <option value="<?= (int) $a['account_id'] ?>"<?= $accId === (int) $a['account_id'] ? ' selected' : '' ?>>
        <?= e((string) $a['name']) ?>
      </option>
    <?php endforeach; ?>
  </select>
  <?php foreach (['all' => '全部', 'unmatched' => '未匹配', 'matched' => '已匹配'] as $k => $lab): ?>
    <a class="tab<?= $st === $k ? ' active' : '' ?>"
       href="?p=bank-transactions&status=<?= e($k) ?><?= $accId ? '&account=' . $accId : '' ?>"><?= e($lab) ?></a>
  <?php endforeach; ?>
</form>

<?php ob_start(); ?>
<?php if (!$lines): ?>
  <?= empty_state('还没有流水。用「导入流水」上传月结单。') ?>
<?php else: ?>
<div class="table-wrap"><table>
  <thead><tr>
    <th style="width:110px">日期</th><th>摘要</th><th style="width:110px">账户</th>
    <th class="num" style="width:140px">金额</th><th style="width:110px">状态</th>
  </tr></thead>
  <tbody>
  <?php foreach ($lines as $x):
    $amt = (float) $x['amount_original'];
    $accName = '';
    foreach ($accounts as $a) { if ((int) $a['account_id'] === (int) $x['bank_account_id']) { $accName = (string) $a['name']; } }
    $matched = ($x['match_status'] ?? '') === 'matched';
  ?>
    <tr>
      <td class="nowrap"><?= e((string) $x['txn_date']) ?></td>
      <td class="truncate" style="max-width:460px"><?= e((string) $x['counterparty_name']) ?></td>
      <td class="hint"><?= e($accName) ?></td>
      <td class="num" style="color:<?= $amt >= 0 ? 'var(--c-ok)' : 'inherit' ?>">
        <?= ($amt >= 0 ? '+' : '') . money($amt, (string) $x['currency']) ?>
      </td>
      <td><?= $matched ? '<span class="tag tag-ok">已匹配</span>' : '<span class="tag tag-warn">未匹配</span>' ?></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
<?php endif; ?>
<?php echo card('', ob_get_clean(),
    pager_html($page, $per, $totalRows, [
        'p' => 'bank-transactions', 'account' => $accId ?: null, 'status' => $st !== 'all' ? $st : null,
    ]), false); ?>

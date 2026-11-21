<?php
/*
 * LtBooks — pages/bank-transfer.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 转账：两个银行账户之间调钱（同币种）。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$err = null; $ok = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor') {
    $r = api_post('/bank/transfer', [
        'fromId' => (int) ($_POST['fromId'] ?? 0),
        'toId' => (int) ($_POST['toId'] ?? 0),
        'amount' => (float) ($_POST['amount'] ?? 0),
        'date' => (string) ($_POST['date'] ?? date('Y-m-d')),
        'actor' => $actor,
    ]);
    if ($r['ok']) {
        header('Location: ?p=bank-transfer&msg=' . urlencode(
            '已转账 ' . number_format((float) ($r['data']['amount'] ?? 0), 2) . ' · 凭证 ' . (string) ($r['data']['entryNo'] ?? '')));
        exit;
    }
    $err = (string) $r['error'];
}
$accR = api_get('/bank-accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$msg = (string) ($_GET['msg'] ?? '');
?>
<div class="page-head">
  <div>
    <h1 class="page-title">转账</h1>
    <div class="page-sub">同一币种的账户之间调拨；跨币种请走外币兑换分录</div>
  </div>
</div>

<?= help_html('bank-transfer') ?>

<?php if ($msg !== ''): ?>
  <div class="banner PASS" style="margin-bottom:12px"><span class="banner-icon">✓</span>
    <div class="banner-body"><div class="banner-title">转账完成</div><div class="banner-reason"><?= e($msg) ?></div></div></div>
<?php endif; ?>
<?php if ($err): ?><?= errbox($err) ?><?php endif; ?>

<section class="card">
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <div class="grid">
      <div class="field"><label class="f">从</label>
        <select name="fromId" required>
          <?php foreach ($accounts as $a): ?>
            <option value="<?= (int) $a['account_id'] ?>"><?= e((string) $a['name'] . '（' . $a['currency'] . '）') ?></option>
          <?php endforeach; ?>
        </select></div>
      <div class="field"><label class="f">到</label>
        <select name="toId" required>
          <?php foreach ($accounts as $a): ?>
            <option value="<?= (int) $a['account_id'] ?>"><?= e((string) $a['name'] . '（' . $a['currency'] . '）') ?></option>
          <?php endforeach; ?>
        </select></div>
      <div class="field"><label class="f">金额 *</label>
        <input type="number" name="amount" step="0.01" min="0.01" required></div>
      <div class="field"><label class="f">日期</label>
        <input type="date" name="date" value="<?= e(date('Y-m-d')) ?>"></div>
    </div>
    <div class="toolbar form-actions" style="margin-top:14px;margin-bottom:0">
      <?php if ($role === 'auditor'): ?>
        <span class="hint">审计角色只读</span>
      <?php else: ?>
        <button class="btn primary"
          data-confirm="确认转账？" data-confirm-note="会生成一张两行的凭证：借「到」账户，贷「从」账户。"
          data-confirm-ok="确认转账">确认转账</button>
      <?php endif; ?>
    </div>
  </form>
</section>

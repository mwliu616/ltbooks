<?php
/*
 * LtBooks — pages/settle.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 核销工作台：一眼看清还有多少钱没收回、没付出、没对上账。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor'
    && ($_POST['action'] ?? '') === 'confirm_recon') {
    $ids = array_values(array_filter((array) ($_POST['ids'] ?? []),
        fn($v) => preg_match('/^(entry|invoice|bill):\d+$/', (string) $v)));
    if (!$ids) {
        $errMsg = '没有勾选要确认对账的单据';
    } else {
        $res = api_post('/reports/confirm-reconciliation', ['ids' => $ids, 'actor' => $actor]);
        if ($res['ok']) {
            header('Location: ?p=settle&msg=' . urlencode(
                t('已确认对账') . ' ' . (int) ($res['data']['confirmed'] ?? 0) . ' '
                . t('张，相关分录纳入报表')));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}

$recvR = api_get('/payments/open-docs?direction=received&limit=200&offset=0');
$recv = $recvR['ok'] ? ($recvR['data']['docs'] ?? []) : [];
$madeR = api_get('/payments/open-docs?direction=made&limit=200&offset=0');
$made = $madeR['ok'] ? ($madeR['data']['docs'] ?? []) : [];
$pendR = api_get('/reports/unreconciled-entries?limit=300&offset=0');
$pend = $pendR['ok'] ? ($pendR['data']['entries'] ?? []) : [];
$pendEntries = $pendR['ok'] ? (int) ($pendR['data']['total'] ?? 0) : 0;

$sumOf = function (array $rows): array {
    $by = [];
    foreach ($rows as $x) {
        $c = (string) $x['currency'];
        if (!isset($by[$c])) { $by[$c] = ['n' => 0, 'amt' => 0.0]; }
        $by[$c]['n']++;
        $by[$c]['amt'] += (float) $x['outstanding'];
    }
    return $by;
};
$recvSum = $sumOf($recv);
$madeSum = $sumOf($made);
$hkd = fn(array $by) => (float) ($by['HKD']['amt'] ?? 0);
$overdue = 0;
$today = date('Y-m-d');
foreach ($recv as $x) {
    $due = (string) ($x['docDate'] ?? '');
    if ($due !== '' && $due < date('Y-m-d', strtotime('-30 days'))) { $overdue++; }
}
$recvTotal = 0; $madeTotal = 0;
foreach ($recv as $x) { if ((string) $x['currency'] === 'HKD') { $recvTotal += (float) $x['outstanding']; } }
foreach ($made as $x) { if ((string) $x['currency'] === 'HKD') { $madeTotal += (float) $x['outstanding']; } }
?>
<div class="page-head">
  <div>
    <h1 class="page-title">核销工作台</h1>
    <div class="page-sub">
      应收与应付的未结清部分、以及已记账但还没同银行流水对上的分录
    </div>
  </div>
  <div class="page-actions">
    <a class="btn" href="?p=payments&direction=made">登记付款</a>
    <a class="btn primary" href="?p=receipts">登记收款</a>
  </div>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>

<?= help_html('settle') ?>
<div class="metrics metrics-sm">
  <div class="metric c3">
    <div class="lbl">应收未收（HKD）</div>
    <div class="val"><?= money($recvTotal, 'HKD') ?></div>
    <div class="hint"><?= num(count($recv)) ?> <?= e(t('张未结清')) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">应付未付（HKD）</div>
    <div class="val"><?= money($madeTotal, 'HKD') ?></div>
    <div class="hint"><?= num(count($made)) ?> <?= e(t('张未结清')) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">逾期超 30 天</div>
    <div class="val"><?= num($overdue) ?></div>
    <div class="hint">按单据日期计</div>
  </div>
  <div class="metric c3">
    <div class="lbl">待对账分录</div>
    <div class="val"><?= num($pendEntries) ?></div>
    <div class="hint"><?= e(t('已记账、未纳入报表')) ?></div>
  </div>
</div>

<section class="card">
  <div class="card-head">
    <h2>应收未收</h2>
    <span class="hint">按单据日期排序；核销请到「收款核销」登记，登记即生成收款凭证</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:200px">发票号</th><th>客户</th>
        <th style="width:110px">发票日期</th><th style="width:70px">币种</th>
        <th class="num" style="width:150px">未收金额</th><th style="width:110px">账龄</th>
      </tr></thead>
      <tbody>
      <?php if (!$recv): ?>
        <tr><td colspan="6" style="text-align:center;padding:26px" class="hint">
          全部收齐了 ✓
        </td></tr>
      <?php endif; ?>
      <?php foreach (array_slice($recv, 0, 12) as $x): ?>
        <?php
          $days = (int) floor((strtotime($today) - strtotime((string) $x['docDate'])) / 86400);
          $ageCls = $days > 90 ? 'danger' : ($days > 30 ? 'warn' : 'draft');
        ?>
        <tr>
          <td class="mono"><?= e((string) $x['docNo']) ?></td>
          <td class="truncate" style="max-width:260px"><?= e((string) $x['party']) ?></td>
          <td class="hint"><?= e((string) $x['docDate']) ?></td>
          <td><?= e((string) $x['currency']) ?></td>
          <td class="num"><?= money($x['outstanding'], (string) $x['currency']) ?></td>
          <td><span class="tag tag-<?= e($ageCls) ?>"><?= (int) $days ?> <?= e(t('天')) ?></span></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <?php if (count($recv) > 12): ?>
    <div class="card-body" style="text-align:right">
      <a class="btn sm" href="?p=receipts"><?= e(t('查看全部')) ?> · <?= num(count($recv)) ?></a>
    </div>
  <?php endif; ?>
</section>

<section class="card">
  <div class="card-head">
    <h2>应付未付</h2>
    <span class="hint">核销请到「付款核销」登记</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:200px">账单号</th><th>供应商</th>
        <th style="width:110px">账单日期</th><th style="width:70px">币种</th>
        <th class="num" style="width:150px">未付金额</th><th style="width:110px">账龄</th>
      </tr></thead>
      <tbody>
      <?php if (!$made): ?>
        <tr><td colspan="6" style="text-align:center;padding:26px" class="hint">
          全部付清 ✓
        </td></tr>
      <?php endif; ?>
      <?php foreach (array_slice($made, 0, 12) as $x): ?>
        <?php
          $days = (int) floor((strtotime($today) - strtotime((string) $x['docDate'])) / 86400);
          $ageCls = $days > 90 ? 'danger' : ($days > 30 ? 'warn' : 'draft');
        ?>
        <tr>
          <td class="mono"><?= e((string) $x['docNo']) ?></td>
          <td class="truncate" style="max-width:260px"><?= e((string) $x['party']) ?></td>
          <td class="hint"><?= e((string) $x['docDate']) ?></td>
          <td><?= e((string) $x['currency']) ?></td>
          <td class="num"><?= money($x['outstanding'], (string) $x['currency']) ?></td>
          <td><span class="tag tag-<?= e($ageCls) ?>"><?= (int) $days ?> <?= e(t('天')) ?></span></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <?php if (count($made) > 12): ?>
    <div class="card-body" style="text-align:right">
      <a class="btn sm" href="?p=payments&direction=made"><?= e(t('查看全部')) ?> · <?= num(count($made)) ?></a>
    </div>
  <?php endif; ?>
</section>

<section class="card">
  <div class="card-head">
    <h2>待对账</h2>
    <span class="hint">
      已记账但还没纳入报表的分录 · 现金、内部转账等无银行流水可匹配的，人工确认即可
    </span>
  </div>
  <?php if (!$pend): ?>
    <div class="card-body"><?= empty_state('没有待对账的单据') ?></div>
  <?php else: ?>
  <form method="post">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="confirm_recon">
    <div class="table-wrap scroll-y scroll-y-lg">
      <table>
        <thead><tr>
          <th class="rowsel"></th><th style="width:180px"><?= e(t('凭证号')) ?></th>
          <th>摘要</th>
          <th style="width:110px">日期</th><th style="width:70px">币种</th>
          <th class="num" style="width:150px">金额</th>
        </tr></thead>
        <tbody>
        <?php foreach ($pend as $x): ?>
          <tr>
            <td class="rowsel"><input type="checkbox" name="ids[]"
                value="<?= e('entry:' . (int) $x['entryId']) ?>"
                aria-label="<?= e(t('选择凭证')) ?> <?= e((string) $x['entryNo']) ?>"></td>
            <td class="mono"><?= e((string) $x['entryNo']) ?></td>
            <td class="truncate" style="max-width:420px"><?= e((string) $x['description']) ?></td>
            <td class="hint"><?= e((string) $x['entryDate']) ?></td>
            <td>HKD</td>
            <td class="num"><?= money($x['totalDebit'] ?? 0, 'HKD') ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <?php if ($role !== 'auditor'): ?>
    <div class="card-body" style="display:flex;justify-content:space-between;align-items:center;gap:12px">
      <span class="hint">确认后这些分录即纳入财务报表；不改变分录金额，只标记为已对账。</span>
      <button class="btn primary" type="submit"
        data-confirm="<?= e(t('确认这些单据已经对账？')) ?>"
        data-confirm-note="<?= e(t('确认后相关分录会被标记为已对账并纳入财务报表。金额不会变动；若对账有误，需由会计另行调整。')) ?>"
        data-confirm-ok="<?= e(t('确认对账')) ?>">确认对账</button>
    </div>
    <?php endif; ?>
  </form>
  <?php endif; ?>
</section>

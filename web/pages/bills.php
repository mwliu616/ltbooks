<?php
/*
 * LtBooks — pages/bills.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
[$page, $per] = pager_state('ledu_bills_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kwPage = trim((string) ($_GET['q'] ?? ''));
$r = api_get('/bills?limit=' . $limit . '&offset=' . $offset
           . ($kwPage !== '' ? '&q=' . urlencode($kwPage) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rows = $r['data']['bills'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? count($rows));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }

ob_start(); ?>
<form method="get" class="list-bar" style="border:1px solid var(--c-border);border-radius:10px;margin-bottom:14px">
  <input type="hidden" name="p" value="bills">
  <input type="text" name="q" value="<?= e($kwPage) ?>" placeholder="搜索单号 / 供应商 / 对方发票号" style="width:300px">
  <button class="btn sm">搜索</button>
  <?php if ($kwPage !== ''): ?><a class="btn sm" href="?p=bills">清除</a><?php endif; ?>
  <span class="spacer"></span>
  <?php if (($role ?? '') !== 'auditor'): ?>
    <a class="btn primary" href="?p=bill-new">+ <?= e(t('新建账单')) ?></a>
  <?php endif; ?>
</form>

<?php if (!$rows): ?>
  <?= empty_state('还没有账单。收到供应商发票后，用「新建账单」录入或上传。') ?>
<?php else: ?>
<div class="table-wrap"><table>
<thead><tr><th>状态</th><th>账单编号</th><th>供应商</th><th>账单日期</th>
<th><?= e(t('到期日')) ?></th><th class="num"><?= e(t('金额')) ?></th>
<th class="num"><?= e(t('余额')) ?></th><th><?= e(t('付款') . ' · ' . t('进度')) ?></th><th><?= e(t('操作')) ?></th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<?php
$gross = (float) $x['gross_original'];
$settled = (float) ($x['settled_original'] ?? 0);
$outstanding = $gross - $settled;
$progressPct = $gross > 0 ? $settled / $gross * 100 : null;
$progressWidth = $progressPct === null ? 0 : max(0, min(100, $progressPct));
$rowCcy = (string) $x['currency'];
?>
<tr>
  <td><?= status_pill((string) $x['status']) ?></td>
  <td><a href="?p=bill-view&id=<?= (int) $x['bill_id'] ?>"><?= e((string) $x['bill_no']) ?></a>
    <?php if (!empty($x['subject'])): ?><div class="hint"><?= e((string) $x['subject']) ?></div><?php endif; ?>
    <?php if (!empty($x['vendor_invoice_no'])): ?>
      <div class="hint">对方发票号 <?= e((string) $x['vendor_invoice_no']) ?></div>
    <?php endif; ?></td>
  <td><?= e((string) ($x['vendor_name'] ?: '—')) ?></td>
  <td class="nowrap"><?= e((string) $x['date']) ?></td>
  <td class="nowrap"><?= e((string) ($x['due_date'] ?? '—')) ?></td>
  <td class="num"><?= money($gross, $rowCcy) ?></td>
  <td class="num"><?= money($outstanding, $rowCcy) ?></td>
  <td style="min-width:190px">
    <div class="num"><b><?= $progressPct === null ? '—' : number_format($progressPct, 1) . '%' ?></b></div>
    <progress max="100" value="<?= number_format($progressWidth, 2, '.', '') ?>" style="width:100%;height:8px"></progress>
    <div class="hint nowrap"><?= e(t('已付款')) ?> <?= money($settled, $rowCcy) ?></div>
    <div class="hint nowrap"><?= e(t('未付')) ?> <?= money($outstanding, $rowCcy) ?></div>
  </td>
  <td style="white-space:nowrap">
    <?php if ($role === 'auditor'): ?>
      <span class="hint">只读</span>
    <?php elseif ($x['status'] === 'draft'): ?>
      <a class="btn sm" href="?p=bill-new&amp;edit=<?= (int) $x['bill_id'] ?>">编辑草稿</a>
      <?= draft_delete_form('bill', (int) $x['bill_id'], 'bills') ?>
      <form method="post" style="display:inline">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="post_bill">
        <input type="hidden" name="id" value="<?= (int) $x['bill_id'] ?>">
        <input type="hidden" name="back" value="bills">
        <button class="btn sm primary" <?= empty($x['canPost']) ? 'disabled' : '' ?>
          title="<?= empty($x['canPost']) ? '存在阻断项' : '校验通过' ?>">过账</button>
      </form>
    <?php else: ?>
      <span class="hint">—</span>
    <?php endif; ?>
  </td>
</tr>
<?php endforeach; ?>
</tbody></table></div>
<?php endif; ?>
<?php echo card(t('账单（供应商开给我 — 支出）'), ob_get_clean(),
    pager_html($page, $per, $totalRows, ['p' => 'bills', 'q' => $kwPage ?: null]), false); ?>

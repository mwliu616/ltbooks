<?php
/*
 * LtBooks — pages/invoices.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$view = (string) ($_GET['view'] ?? 'all');
[$page, $per] = pager_state('ledu_inv_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kwPage = trim((string) ($_GET['q'] ?? ''));
$r = api_get('/invoices?limit=' . $limit . '&offset=' . $offset
           . '&status=' . urlencode($view)
           . ($kwPage !== '' ? '&q=' . urlencode($kwPage) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$list = $r['data']['invoices'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? count($list));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }
$role = isset($role) ? $role : 'accountant';  // 来自服务端会话
// 同一币种时只在表头写一次，避免每行重复 HKD
$__ccys = [];
foreach ($list as $x) { $__ccys[(string) ($x['currency'] ?? '')] = true; }
$__oneCcy = count($__ccys) === 1 ? (string) array_key_first($__ccys) : '';
?>
<?php ob_start(); ?>
<form method="get" class="list-bar">
  <input type="hidden" name="p" value="invoices">
  <select name="view" onchange="this.form.submit()">
    <?php foreach (['all' => t('全部发票'), 'draft' => t('草稿'), 'posted' => t('已记账')] as $k => $lab): ?>
      <option value="<?= e($k) ?>"<?= $view === $k ? ' selected' : '' ?>><?= e($lab) ?></option>
    <?php endforeach; ?>
  </select>
  <input type="text" name="q" value="<?= e($kwPage ?? '') ?>" placeholder="搜索发票号 / 客户" style="width:260px">
  <button class="btn sm">搜索</button>
  <?php if ($kwPage !== ''): ?><a class="btn sm" href="?p=invoices">清除</a><?php endif; ?>
</form>

<?php if (!$list): ?>
  <?= empty_state('没有符合条件的发票') ?>
<?php else: ?>
<div class="table-wrap"><table>
  <thead><tr>
    <th><?= e(t('状态')) ?></th><th><?= e(t('发票编号')) ?></th><th><?= e(t('客户名称')) ?></th><th><?= e(t('发票日期')) ?></th>
    <th><?= e(t('到期日')) ?></th><th class="num"><?= e(t('金额')) ?><?= $__oneCcy !== '' ? ' (' . e($__oneCcy) . ')' : '' ?></th>
    <th class="num"><?= e(t('余额')) ?><?= $__oneCcy !== '' ? ' (' . e($__oneCcy) . ')' : '' ?></th>
    <th><?= e(t('收款') . ' · ' . t('进度')) ?></th><th><?= e(t('操作')) ?></th>
  </tr></thead>
  <tbody>
  <?php foreach ($list as $x): ?>
    <?php
    $gross = (float) $x['gross_original'];
    $settled = (float) ($x['settled_original'] ?? 0);
    $outstanding = $gross - $settled;
    $progressPct = $gross > 0 ? $settled / $gross * 100 : null;
    $progressWidth = $progressPct === null ? 0 : max(0, min(100, $progressPct));
    $rowCcy = $__oneCcy !== '' ? null : (string) $x['currency'];
    ?>
    <tr>
      <td><?= status_pill((string) $x['status']) ?></td>
      <td><a href="?p=invoice-view&id=<?= (int) $x['invoice_id'] ?>"><?= e($x['invoice_no']) ?></a>
        <?php if (!empty($x['subject'])): ?><div class="hint"><?= e((string) $x['subject']) ?></div><?php endif; ?></td>
      <td><?= e($x['supplier_name']) ?></td>
      <td class="nowrap"><?= e($x['invoice_date']) ?></td>
      <td class="nowrap"><?= e((string) ($x['dueDate'] ?? $x['due_date'] ?? '—')) ?></td>
      <td class="num"><?= money($gross, $rowCcy) ?></td>
      <td class="num"><?= money($outstanding, $rowCcy) ?></td>
      <td style="min-width:190px">
        <div class="num"><b><?= $progressPct === null ? '—' : number_format($progressPct, 1) . '%' ?></b></div>
        <progress max="100" value="<?= number_format($progressWidth, 2, '.', '') ?>" style="width:100%;height:8px"></progress>
        <div class="hint nowrap"><?= e(t('已收款')) ?> <?= money($settled, $rowCcy) ?></div>
        <div class="hint nowrap"><?= e(t('未收')) ?> <?= money($outstanding, $rowCcy) ?></div>
      </td>
      <td>
        <?php if ($role === 'auditor'): ?>
          <span class="hint">只读</span>
        <?php elseif ($x['status'] === 'draft'): ?>
          <a class="btn sm" href="?p=invoice-new&amp;edit=<?= (int) $x['invoice_id'] ?>">编辑草稿</a>
          <?= draft_delete_form('invoice', (int) $x['invoice_id'], 'invoices') ?>
          <form method="post" style="display:inline">
  <?= csrf_field() ?>
            <input type="hidden" name="action" value="post_invoice">
            <input type="hidden" name="id" value="<?= (int) $x['invoice_id'] ?>">
            <input type="hidden" name="actor" value="<?= e($role) ?>">
            <input type="hidden" name="back" value="invoices">
            <button class="btn sm primary" <?= empty($x['canPost']) ? 'disabled' : '' ?>
              title="<?= empty($x['canPost']) ? '存在阻断项，不可过账' : '校验通过' ?>">提交过账</button>
          </form>
        <?php else: ?>
          <span class="hint">—</span>
        <?php endif; ?>
      </td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
<?php endif; ?>
<?php
echo card('', ob_get_clean(),
    pager_html($page, $per, $totalRows,
        ['p' => 'invoices', 'view' => $view === 'all' ? null : $view, 'q' => $kwPage ?: null]), false);
?>

<?php
/*
 * LtBooks — pages/pending-rec.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$r = api_get('/review-queue');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
$items = $d['items'] ?? [];

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $act = (string) ($_POST['action'] ?? '');
    $kind = (string) ($_POST['kind'] ?? '');
    $id = (int) ($_POST['id'] ?? 0);
    $path = ($kind === 'bill' ? '/bills/' : '/invoices/') . $id;
    if ($act === 'approve') {
        $res = api_post($path . '/approve', ['actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system')),
                                            'role' => $role, 'note' => trim((string) ($_POST['note'] ?? ''))]);
    } elseif ($act === 'reject') {
        $res = api_post($path . '/reject', ['actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system')),
                                            'note' => trim((string) ($_POST['note'] ?? ''))]);
    } else {
        $res = api_post($path . '/submit-review', ['actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system'))]);
    }
    if ($res['ok']) { $msg = '操作完成'; } else { $errMsg = (string) $res['error']; }
    $r2 = api_get('/review-queue');
    if ($r2['ok']) { $d = $r2['data']; $items = $d['items'] ?? []; }
}

$badgeOf = function (string $s): string {
    return match ($s) {
        'pending'  => '<span class="pill st-review">待复核</span>',
        'rejected' => '<span class="pill st-fail">已退回</span>',
        'approved' => '<span class="pill st-pass">已批准</span>',
        default    => '<span class="pill st-draft">草稿</span>',
    };
};
?>

<?php if (!empty($msg)): ?>
  <div class="banner PASS"><span class="banner-icon">✓</span>
    <div class="banner-body"><div class="banner-title">操作成功</div>
    <div class="banner-reason"><?= e($msg) ?></div></div></div>
<?php endif; ?>
<?php if (!empty($errMsg)): ?>
  <div class="banner FAIL"><span class="banner-icon">✕</span>
    <div class="banner-body"><div class="banner-title">操作未完成</div>
    <div class="banner-reason"><?= e($errMsg) ?></div></div></div>
<?php endif; ?>

<div class="metrics">
  <div class="metric"><div class="lbl">待复核</div><div class="val"><?= num($d['pending'] ?? 0) ?></div></div>
  <div class="metric"><div class="lbl">已退回</div><div class="val"><?= num($d['rejected'] ?? 0) ?></div></div>
  <div class="metric"><div class="lbl">草稿未提交</div><div class="val"><?= num($d['draft'] ?? 0) ?></div></div>
</div>

<?php ob_start(); ?>
<div class="hint" style="padding:12px 14px;border-bottom:1px solid var(--c-border)">
  <?= e("单据须经复核批准才能过账，过账后才进入财务报表。复核人不得是录单人（四眼原则）；管理员可强制通过。") ?>
</div>

<?php if (!$items): ?>
  <?= empty_state('没有待处理的单据') ?>
<?php else: ?>
<div class="table-wrap"><table>
<thead><tr><th>类型</th><th>单号</th><th>往来单位</th><th>日期</th>
<th class="num">金额</th><th>录单人</th><th>状态</th><th style="width:260px">操作</th></tr></thead>
<tbody>
<?php foreach ($items as $x): ?>
  <tr>
    <td><?= $x['kind'] === 'invoice' ? e(t('销售发票')) : e(t('采购发票')) ?></td>
    <td><a href="?p=<?= $x['kind'] === 'invoice' ? 'invoice-view' : 'bill-view' ?>&id=<?= (int) $x['id'] ?>">
      <?= e((string) $x['doc_no']) ?></a></td>
    <td><?= e((string) $x['party']) ?></td>
    <td><?= e((string) $x['doc_date']) ?></td>
    <td class="num"><?= money($x['amount'], (string) $x['currency']) ?></td>
    <td><?= e((string) $x['created_by']) ?></td>
    <td><?= $badgeOf((string) $x['review_status']) ?></td>
    <td>
      <?php if ($role === 'auditor'): ?>
        <span class="hint">只读</span>
      <?php elseif ($x['review_status'] === 'draft'): ?>
        <form method="post" style="display:inline"><?= csrf_field() ?>
          <input type="hidden" name="action" value="submit"><input type="hidden" name="kind" value="<?= e($x['kind']) ?>">
          <input type="hidden" name="id" value="<?= (int) $x['id'] ?>">
          <button class="btn sm">提交复核</button></form>
      <?php else: ?>
        <form method="post" style="display:inline-flex;gap:4px;align-items:center"><?= csrf_field() ?>
          <input type="hidden" name="kind" value="<?= e($x['kind']) ?>">
          <input type="hidden" name="id" value="<?= (int) $x['id'] ?>">
          <input type="text" name="note" placeholder="备注 / 退回原因" style="width:120px;font-size:var(--f-2xs)">
          <button class="btn sm primary" name="action" value="approve">批准</button>
          <button class="btn sm ghost" name="action" value="reject">退回</button>
        </form>
      <?php endif; ?>
    </td>
  </tr>
<?php endforeach; ?>
</tbody></table></div>
<?php endif; ?>
<?php echo card('', ob_get_clean(), '', false); ?>

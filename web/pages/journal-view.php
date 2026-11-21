
<?php
/*
 * LtBooks — pages/journal-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 分录详情（独立页面）：查看明细、编辑/删除草稿、冲销已过账凭证、管理附件。
 * 日记账列表的操作按钮都跳到这里，列表本身不再内嵌操作面板。
 */
$id = (int) ($_GET['id'] ?? 0);
$role = isset($role) ? $role : 'accountant';
$__actor = (string) ($user['username'] ?? 'system');
if ($id <= 0) {
    echo errbox('没有指定要查看的分录');
    return;
}

// ---------- 附件：上传 / 删除（查看走 /doc-files/<id>/raw 代理） ----------
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor') {
    $__act = (string) ($_POST['action'] ?? '');
    if ($__act === 'attach_upload') {
        $n = doc_files_save('journal', $id, $_FILES['file'] ?? [], $__actor);
        header('Location: ?p=journal-view&id=' . $id . '&msg='
             . urlencode($n > 0 ? t('附件已上传') : t('没有选中文件')));
        exit;
    }
    if ($__act === 'attach_delete') {
        api_post('/doc-files/' . (int) ($_POST['fileId'] ?? 0) . '/delete', ['actor' => $__actor]);
        header('Location: ?p=journal-view&id=' . $id . '&msg=' . urlencode(t('附件已删除')));
        exit;
    }
}

$r = api_get('/journal/' . $id);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'] ?? [];
$je = $d['entry'] ?? [];
$lines = $d['lines'] ?? [];
$status = (string) ($je['status'] ?? '');
$isDraft = $status === 'draft';
$isPosted = $status === 'posted';

$field = function (string $k, string $label, string $fmt = 'text') use ($je): string {
    $v = $je[$k] ?? null;
    if ($v === null || $v === '') { $v = '—'; }
    if ($fmt === 'money') { $v = money($v); }
    return '<div class="dv-item"><div class="dv-k">' . e(t($label)) . '</div>'
         . '<div class="dv-v">' . e((string) $v) . '</div></div>';
};
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e(t('分录详情')) ?></h1>
    <div class="page-sub mono"><?= e((string) ($je['entry_no'] ?? '')) ?></div>
  </div>
  <div class="page-actions">
    <a class="btn" href="?p=journal"><?= e(t('返回列表')) ?></a>
    <?= voucher_menu(['id' => $id], t('凭证'), 'btn') ?>
    <?php if ($isDraft && $role !== 'auditor'): ?>
      <a class="btn primary" href="?p=journal-new&amp;edit=<?= (int) $id ?>"><?= e(t('编辑草稿')) ?></a>
      <?= draft_delete_form('journal', $id, 'journal') ?>
    <?php endif; ?>
    <?php if ($isPosted && $role !== 'auditor'): ?>
      <form method="post" style="display:inline-flex;gap:6px;align-items:center">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="reverse_entry">
        <input type="hidden" name="id" value="<?= (int) $id ?>">
        <input type="hidden" name="back" value="journal-view">
        <input type="text" name="reason" value="<?= e(t('更正')) ?>" style="width:130px"
               aria-label="<?= e(t('冲销原因')) ?>">
        <button class="btn"
                data-confirm="<?= e(t('确认冲销这张凭证？')) ?>"
                data-confirm-note="<?= e(t('冲销会生成一张反向分录，原凭证保留；日期与期间必须正确。')) ?>"><?= e(t('冲销')) ?></button>
      </form>
    <?php endif; ?>
  </div>
</div>

<?= help_html('journal') ?>

<?php if (!empty($je['reversed_by_entry_id']) || !empty($je['reversal_of_entry_id'])): ?>
<div class="hint" style="margin:-4px 0 12px">
  <?php if (!empty($je['reversed_by_entry_id'])): ?>
    <?= e(t('这张凭证已被冲销：')) ?>
    <a class="mono" href="?p=journal-view&amp;id=<?= (int) $je['reversed_by_entry_id'] ?>">
      #<?= (int) $je['reversed_by_entry_id'] ?></a>
  <?php endif; ?>
  <?php if (!empty($je['reversal_of_entry_id'])): ?>
    <?= e(t('这是一张冲销分录，原凭证为：')) ?>
    <a class="mono" href="?p=journal-view&amp;id=<?= (int) $je['reversal_of_entry_id'] ?>">
      #<?= (int) $je['reversal_of_entry_id'] ?></a>
  <?php endif; ?>
</div>
<?php endif; ?>

<div class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('分录信息')) ?></h2><?= status_pill($status) ?></div>
  <div class="card-body">
    <div class="dv-grid">
      <?= $field('entry_no', '分录号') ?>
      <?= $field('entry_date', '日期') ?>
      <?= $field('period', '期间') ?>
      <div class="dv-item"><div class="dv-k"><?= e(t('来源')) ?></div>
        <div class="dv-v"><?= e(source_label((string) ($je['source_type'] ?? ''))) ?></div></div>
      <?= $field('description', '摘要') ?>
      <?= $field('total_debit', '借方合计', 'money') ?>
      <?= $field('total_credit', '贷方合计', 'money') ?>
      <?= $field('created_by', '制单') ?>
    </div>
  </div>
</div>

<div class="card" style="margin-top:12px">
  <div class="card-head"><h2 class="card-title"><?= e(t('分录明细')) ?></h2></div>
  <div class="table-wrap"><table>
    <thead><tr><th>#</th><th><?= e(t('科目')) ?></th><th><?= e(t('说明')) ?></th>
    <th class="num"><?= e(t('借方')) ?></th><th class="num"><?= e(t('贷方')) ?></th>
    <th><?= e(t('币种')) ?></th><th class="num"><?= e(t('原币')) ?></th>
    <th class="num"><?= e(t('汇率')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($lines as $l): ?>
      <tr><td><?= (int) $l['line_no'] ?></td>
        <td><?= e($l['account_code']) ?></td>
        <td><?= e((string) ($l['description'] ?: '—')) ?></td>
        <td class="num"><?= money($l['debit']) ?></td>
        <td class="num"><?= money($l['credit']) ?></td>
        <td><?= e($l['ccy']) ?></td>
        <td class="num"><?= money($l['amount_original']) ?></td>
        <td class="num"><?= e((string) $l['rate']) ?></td></tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</div>

<?php
$__fr = api_get('/doc-files?type=journal&id=' . (int) $id);
$__files = $__fr['ok'] ? ($__fr['data']['files'] ?? []) : [];
?>
<div class="card" style="margin-top:12px" id="attach">
  <div class="card-head">
    <h2 class="card-title"><?= e(t('附件')) ?>（<?= count($__files) ?>）</h2>
    <span class="hint"><?= e(t('上传时已记 SHA-256，改动可查 · 单文件上限 20MB')) ?></span>
  </div>
  <?php if (!$__files): ?>
    <?= empty_state(t('这张凭证没有附件')) ?>
  <?php else: ?>
  <div class="table-wrap"><table>
    <thead><tr><th><?= e(t('文件名')) ?></th><th><?= e(t('类型')) ?></th>
    <th class="num"><?= e(t('大小')) ?></th><th></th></tr></thead>
    <tbody>
    <?php foreach ($__files as $f): ?>
      <tr>
        <td><?= e((string) $f['file_name']) ?></td>
        <td><?= e((string) ($f['file_type'] ?: '—')) ?></td>
        <td class="num"><?= number_format(((int) $f['file_size']) / 1024, 1) ?> KB</td>
        <td style="white-space:nowrap">
          <a class="btn sm" target="_blank"
             href="/pdf/reports.php?u=<?= e(rawurlencode('/doc-files/' . (int) $f['file_id'] . '/raw')) ?>">
            <?= e(t('查看')) ?></a>
          <?php if ($role !== 'auditor'): ?>
          <form method="post" style="display:inline"
                data-confirm="<?= e(t('删除这个附件？')) ?>">
            <?= csrf_field() ?>
            <input type="hidden" name="action" value="attach_delete">
            <input type="hidden" name="fileId" value="<?= (int) $f['file_id'] ?>">
            <button class="btn sm"><?= e(t('删除')) ?></button>
          </form>
          <?php endif; ?>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody></table></div>
  <?php endif; ?>
  <?php if ($role !== 'auditor'): ?>
  <form method="post" enctype="multipart/form-data" class="card-body"
        style="border-top:1px solid var(--c-border)">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="attach_upload">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <input type="file" name="file[]" multiple
             accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.csv,.doc,.docx" style="max-width:420px">
      <button class="btn primary sm"><?= e(t('上传附件')) ?></button>
      <span class="hint"><?= e(t('已有单据也可以在这里补传')) ?></span>
    </div>
  </form>
  <?php endif; ?>
</div>

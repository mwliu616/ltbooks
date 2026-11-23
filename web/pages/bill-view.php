<?php
/*
 * LtBooks — pages/bill-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$id = (int) ($_GET['id'] ?? 0);
if (!$id) { echo errbox('缺少采购发票 ID'); return; }
$msg = null; $errMsg = null;

// 复核：提交 / 批准 / 退回（管理员可一人完成全流程）
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'review') {
    $op = (string) ($_POST['op'] ?? '');
    $body = ['actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system')), 'role' => $role,
             'note' => trim((string) ($_POST['note'] ?? ''))];
    $path = $op === 'submit' ? '/bills/' . $id . '/submit-review'
          : ($op === 'approve' ? '/bills/' . $id . '/approve' : '/bills/' . $id . '/reject');
    $res = api_post($path, $body);
    if ($res['ok']) {
        $msg = ['submit' => '已提交复核', 'approve' => '已批准，可以过账', 'reject' => '已退回'][$op] ?? '复核操作完成';
        header('Location: ?p=bill-view&id=' . $id . '&msg=' . urlencode($msg));
        exit;
    }
    $errMsg = (string) $res['error'];
}

// 上传原始凭证
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'upload_bill_file') {
    if (empty($_FILES['file']['tmp_name']) || ($_FILES['file']['error'] ?? 1) !== UPLOAD_ERR_OK) {
        $errMsg = '上传失败：未选择文件';
    } elseif (($_FILES['file']['size'] ?? 0) > 20 * 1024 * 1024) {
        $errMsg = '文件超过 20MB 上限';
    } else {
        $orig = basename((string) $_FILES['file']['name']);
        $ext = strtolower(pathinfo($orig, PATHINFO_EXTENSION));
        $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', $orig);
        $dest = UPLOAD_DIR . '/' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
        if (!move_uploaded_file($_FILES['file']['tmp_name'], $dest)) {
            $errMsg = '文件落盘失败';
        } else {
            @chmod($dest, 0640);
            $sha = hash_file('sha256', $dest);
            $r = api_post('/bill-files', [
                'billId' => $id, 'fileName' => $orig,
                'fileType' => $ext !== '' ? $ext : 'other',
                'fileSize' => filesize($dest), 'sha256' => $sha,
                'storagePath' => $dest, 'actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system')),
            ]);
            if ($r['ok']) { $msg = '凭证已上传：' . $orig; }
            else { @unlink($dest); $errMsg = (string) $r['error']; }
        }
    }
}

// 下载
if (isset($_GET['download'])) {
    $fid = (int) $_GET['download'];
    $r2 = api_get('/invoice-files/' . $fid);
    if ($r2['ok']) {
        // 接口返回的是 storage_path（数据库原字段名）
        $path = $r2['data']['storage_path'] ?? null;
        if ($path && is_file($path)) {
            send_file((string) $path, (string) ($r2['data']['file_name'] ?? 'file'));
        }
    }
    $errMsg = '文件不存在';
}

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

// 用单项接口：列表接口不返回明细行
$r = api_get('/bills/' . $id);
$bill = $r['ok'] ? ($r['data'] ?? null) : null;
if (!$bill) { echo errbox('采购发票不存在'); return; }
$fr = api_get('/bills/' . $id . '/files');
$files = $fr['ok'] ? ($fr['data']['files'] ?? []) : [];

$actions = '<div style="display:flex;gap:6px;align-items:center">'
         . export_menu(export_lang_items('/bills/' . (int) $id . '/pdf'), '导出 PDF', 'btn sm')
         . '<a class="btn sm" href="?p=email&docType=bill&docId=' . (int) $id . '">发送邮件</a>'
         . ($role !== 'auditor' && $bill['status'] === 'draft'
             ? '<a class="btn primary sm" href="?p=bill-new&edit=' . (int) $id . '">编辑草稿</a>'
               . draft_delete_form('bill', (int) $bill['bill_id'], 'bills') : '')
         . '<a class="btn sm" href="?p=bills">← 返回</a></div>';
echo card('采购发票 ' . $bill['bill_no'], '', $actions, false);
?>
<?php
$billFunctional = (string) ($bill['functional_currency'] ?? '');
$billIsForeign = strtoupper((string) $bill['currency']) !== strtoupper($billFunctional);
$billFx = isset($bill['fx_rate']) && (float) $bill['fx_rate'] > 0 ? (float) $bill['fx_rate'] : null;
$billGrossFunctional = null;
if (isset($bill['amount_functional']) && $billFx !== null) {
    $candidate = (float) $bill['amount_functional'] + (float) $bill['tax_amount'] * $billFx;
    if ((float) $bill['gross_original'] == 0.0 || $candidate != 0.0) { $billGrossFunctional = $candidate; }
}
$billRateText = $billFx !== null ? e((string) $billFx) : '—';
if ($billFx !== null && !empty($bill['fx_rate_date'])) {
    $billRateText .= '（' . e((string) $bill['fx_rate_date']) . '）';
}
$billInfo = [
  ['文件编号', '<span style="font-family:ui-monospace,monospace">' . e((string) $bill['bill_no']) . '</span>'],
  ['供应商发票号', e((string) ($bill['vendor_invoice_no'] ?: ''))],
  ['供应商', e((string) ($bill['vendor_name'] ?: ''))],
  ['日期', e((string) $bill['date'])],
  ['到期日', e((string) ($bill['due_date'] ?: ''))],
  ['币种', e((string) $bill['currency'])],
  ['不含税', money($bill['amount'], (string) $bill['currency'])],
  ['税额', money($bill['tax_amount'], (string) $bill['currency'])],
  ['整体折扣', ((float) ($bill['discount_rate'] ?? 0) > 0 ? rtrim(rtrim(number_format((float) $bill['discount_rate'], 2, '.', ''), '0'), '.') . '%' : '0%') . ' · ' . money($bill['discount_original'] ?? 0, (string) $bill['currency'])],
  ['价税合计', money($bill['gross_original'], (string) $bill['currency'])],
];
if ($billIsForeign) {
    $billInfo[] = ['折合功能货币', $billGrossFunctional !== null ? money($billGrossFunctional, $billFunctional) : '— ' . e($billFunctional)];
    $billInfo[] = ['汇率', $billRateText];
}
$billLineAccounts = array_values(array_unique(array_filter(
    array_map(static fn ($l): string => (string) ($l['account_code'] ?? ''), (array) ($bill['lines'] ?? [])))));
$billInfo = array_merge($billInfo, [
  ['费用科目', e($billLineAccounts ? '按明细行（' . implode('、', $billLineAccounts) . '）'
                                  : (string) ($bill['expense_account_code'] ?: ''))],
  ['校验', badge((string) ($bill['checkStatus'] ?? 'PASS'))],
  ['状态', status_pill((string) $bill['status'])],
]);
ob_start(); ?>
<?= kv_grid($billInfo) ?>
<div class="hint" style="margin-top:10px">
  记账方向：借 <?= $billLineAccounts ? '各明细行费用科目' : e((string) $bill['expense_account_code']) ?>（费用）＋ 借 1160（进项税额）
  → 贷 2110（应付账款）。这是支出，不是收入。
</div>
<?php
$billAct = '';
if ($role !== 'auditor' && $bill['status'] === 'draft') {
    $billAct = '<form method="post" style="margin:0">' . csrf_field()
        . '<input type="hidden" name="action" value="post_bill">'
        . '<input type="hidden" name="id" value="' . (int) $id . '">'
        . '<button class="btn primary sm" ' . (empty($bill['canPost']) ? 'disabled' : '') . '>提交过账</button></form>';
}
echo card('采购发票信息', ob_get_clean(), $billAct, false); ?>

<?php
$billLines = $bill['lines'] ?? [];
if ($billLines):
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th style="width:56px" class="num">编码</th><th>项目 / 内容</th>
<th style="width:110px">费用科目</th>
<th style="width:70px">单位</th><th class="num" style="width:84px">数量</th>
<th class="num" style="width:110px">单价</th><th class="num" style="width:80px">税率</th>
<th class="num" style="width:120px">合价</th><th style="width:160px">备注</th></tr></thead>
<tbody>
<?php $sumAmt = 0; foreach ($billLines as $ln):
  $sumAmt += (float) $ln['amount']; ?>
  <tr>
    <td class="num hint"><?= (int) $ln['line_no'] ?></td>
    <td><?= e((string) $ln['description']) ?></td>
    <td class="mono hint"><?= e((string) ($ln['account_code'] ?? '')) ?></td>
    <td class="hint"><?= e((string) ($ln['unit'] ?: '—')) ?></td>
    <td class="num"><?= e(rtrim(rtrim(number_format((float) $ln['quantity'], 4, '.', ','), '0'), '.')) ?></td>
    <td class="num"><?= money($ln['unit_price'], (string) $bill['currency']) ?></td>
    <td class="num"><?= $ln['tax_rate'] !== null ? e((string) $ln['tax_rate']) . '%' : '—' ?></td>
    <td class="num"><b><?= money($ln['amount'], (string) $bill['currency']) ?></b></td>
    <td class="hint"><?= e((string) ($ln['notes'] ?: '—')) ?></td>
  </tr>
<?php endforeach; ?>
</tbody>
<tfoot><tr>
  <td colspan="7" class="num hint">合计</td>
  <td class="num"><b><?= money($sumAmt, (string) $bill['currency']) ?></b></td>
  <td></td>
</tr></tfoot></table></div>
<?php echo card('明细清单（' . count($billLines) . ' 项）', ob_get_clean(), '', false);
endif; ?>

<?php ob_start(); ?>
<?php if (!$files): ?>
  <?= empty_state(t('尚无附件')) ?>
<?php else: ?>
<div class="table-wrap"><table>
<thead><tr><th>文件名</th><th>类型</th><th class="num">大小</th><th>SHA-256</th><th>上传人</th><th></th></tr></thead>
<tbody>
<?php foreach ($files as $f): ?>
<tr><td><?= e((string) $f['file_name']) ?></td><td><?= e((string) $f['file_type']) ?></td>
<td class="num"><?= number_format((int) $f['file_size']) ?> B</td>
<td class="hint" style="font-family:var(--mono)"><?= e(substr((string) $f['sha256_hash'], 0, 16)) ?>…</td>
<td><?= e((string) $f['uploaded_by']) ?></td>
<td><a class="btn sm btn-file" href="?p=bill-view&id=<?= $id ?>&download=<?= (int) $f['file_id'] ?>">下载</a></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php endif; ?>
<?php if ($role !== 'auditor'): ?>
<form method="post" enctype="multipart/form-data" style="padding:14px;border-top:1px solid var(--c-border)">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="upload_bill_file">
  <div class="toolbar" style="margin-bottom:0">
    <input type="file" name="file" required>
    <button class="btn primary sm"><?= e(t('上传附件')) ?></button>
    <span class="hint"><?= e(t('上传即计算 SHA-256 并写入审计日志，保存 7 年')) ?></span>
  </div>
</form>
<?php endif; ?>
<?php echo card(t('附件'), ob_get_clean(), '', false); ?>

<?php
$rs = (string) ($bill['review_status'] ?? 'draft');
$rsLabel = status_label((string) $rs);
$rsCls = ['draft' => 'st-draft', 'pending' => 'st-review', 'approved' => 'st-pass', 'rejected' => 'st-fail'][$rs] ?? 'st-draft';
?>
<?php ob_start(); ?>
<div class="grid">
  <div class="kv"><b>复核状态</b><span><span class="pill <?= $rsCls ?>"><?= e($rsLabel) ?></span></span></div>
  <div class="kv"><b>录单人</b><span><?= e((string) ($bill['created_by'] ?? '')) ?></span></div>
  <div class="kv"><b>批准人</b><span><?= e((string) ($bill['approved_by'] ?? '—')) ?></span></div>
  <?php if (!empty($bill['approval_note'])): ?>
  <div class="kv" style="grid-column:1/-1"><b>复核意见</b><span><?= e((string) $bill['approval_note']) ?></span></div>
  <?php endif; ?>
</div>
<?php if ($role !== 'auditor' && $bill['status'] === 'draft'): ?>
<form method="post" style="padding:14px;border-top:1px solid var(--border)">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="review">
  <div class="toolbar" style="margin-bottom:0;gap:6px">
    <?php if ($rs === 'draft'): ?>
      <button class="btn primary" name="op" value="submit">提交复核</button>
    <?php else: ?>
      <input type="text" name="note" placeholder="复核意见 / 退回原因" style="width:220px">
      <button class="btn primary" name="op" value="approve">批准</button>
      <button class="btn ghost" name="op" value="reject">退回</button>
    <?php endif; ?>
    <span class="hint"><?= e($role === 'admin'
        ? t('管理员可直接批准，包括自己录入的单据；批准记录写入审计链')
        : t('须经批准才能过账；审批人不得是录单人（四眼原则）')) ?></span>
  </div>
</form>
<?php endif; ?>
<?php echo card('复核', ob_get_clean(), '', false); ?>

<?php if (($bill['status'] ?? '') === 'draft' && $role !== 'auditor'): ?>
<div class="pc-box" id="aiPrecheck"></div>
<script src="assets/precheck.js?v=<?= @filemtime(__DIR__ . '/../assets/precheck.js') ?>"></script>
<script>
(function () {
  if (!window.LeduPrecheck) return;
  window.LeduPrecheck.attach({
    el: '#aiPrecheck', workflow: 'post_bill', docId: <?= (int) $bill['bill_id'] ?>,
    agentLabel: '复核守门人', auto: true
  });
})();
</script>
<?php endif; ?>

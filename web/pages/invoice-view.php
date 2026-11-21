<?php
/*
 * LtBooks — pages/invoice-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$id = (int) ($_GET['id'] ?? 0);
if (!$id) { echo errbox(t('缺少发票 ID')); return; }

$msg = null; $errMsg = null;

// ---- 附件上传 ----
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'review') {
    $op = (string) ($_POST['op'] ?? '');
    $body = ['actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system')), 'role' => $role,
             'note' => trim((string) ($_POST['note'] ?? ''))];
    $path = $op === 'submit' ? '/invoices/' . $id . '/submit-review'
          : ($op === 'approve' ? '/invoices/' . $id . '/approve' : '/invoices/' . $id . '/reject');
    $res = api_post($path, $body);
    $msg = $res['ok'] ? '复核操作完成' : null;
    $errMsg = $res['ok'] ? null : (string) $res['error'];
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'upload_file') {
    if (empty($_FILES['file']['tmp_name']) || ($_FILES['file']['error'] ?? 1) !== UPLOAD_ERR_OK) {
        $errMsg = '上传失败：' . (string) ($_FILES['file']['error'] ?? '未选择文件');
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
            $r = api_post('/invoice-files', [
                'invoiceId' => $id,
                'fileName' => $orig,
                'fileType' => $ext !== '' ? $ext : 'other',
                'fileSize' => filesize($dest),
                'sha256' => $sha,
                'storagePath' => $dest,
                'actor' => (string) (($user['username'] ?? '') ?: ($displayName ?? 'system')),
            ]);
            if ($r['ok']) {
                $msg = '附件已上传：' . $orig . '（SHA-256 ' . substr($sha, 0, 16) . '…）';
            } else {
                @unlink($dest);
                $errMsg = (string) $r['error'];
            }
        }
    }
}

// ---- 下载 ----
if (isset($_GET['download'])) {
    $fid = (int) $_GET['download'];
    $fr = api_get('/invoices/' . $id . '/files');
    $files = $fr['ok'] ? ($fr['data']['files'] ?? []) : [];
    foreach ($files as $f) {
        if ((int) $f['file_id'] === $fid) {
            $r2 = api_get('/invoice-files/' . $fid);
            // 接口返回的是数据库原字段名 storage_path，不是 storagePath
            $path = $r2['ok'] ? ($r2['data']['storage_path'] ?? null) : null;
            if ($path && is_file($path)) {
                send_file((string) $path, (string) $f['file_name']);
            }
        }
    }
    $errMsg = '文件不存在或无权访问';
}

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

// 用单项接口：列表接口不返回明细行，详情页要展示清单
$invR = api_get('/invoices/' . $id);
$inv = $invR['ok'] ? ($invR['data'] ?? null) : null;
if (!$inv) { echo errbox('发票不存在'); return; }

$fr = api_get('/invoices/' . $id . '/files');
$files = $fr['ok'] ? ($fr['data']['files'] ?? []) : [];

// PDF 语言选择器紧挨「打印 / PDF」按钮，它只影响导出的 PDF
$back = '<div style="display:flex;gap:6px;align-items:center">'
      . (($inv['status'] ?? '') === 'draft' && $role !== 'auditor'
          ? '<a class="btn sm" href="?p=invoice-new&edit=' . (int) $id . '">编辑草稿</a>'
            . draft_delete_form('invoice', (int) $inv['invoice_id'], 'invoices') : '')
      . export_menu(export_lang_items('/invoices/' . (int) $id . '/pdf'), '导出 PDF', 'btn sm')
      . '<a class="btn sm" href="?p=email&docType=invoice&docId=' . (int) $id . '">发送邮件</a>'
      . '<a class="btn sm" href="?p=invoices">← 返回列表</a></div>';
echo card('发票 ' . $inv['invoice_no'], '', $back, false);
?>
<?php
$invFunctional = (string) ($inv['functional_currency'] ?? '');
$invIsForeign = strtoupper((string) $inv['currency']) !== strtoupper($invFunctional);
$invGrossFunctional = null;
if (isset($inv['amount_functional'], $inv['tax_functional'])) {
    $candidate = (float) $inv['amount_functional'] + (float) $inv['tax_functional'];
    if ((float) $inv['gross_original'] == 0.0 || $candidate != 0.0) { $invGrossFunctional = $candidate; }
}
$invFx = isset($inv['fx_rate']) && (float) $inv['fx_rate'] > 0 ? (float) $inv['fx_rate'] : null;
$invRateText = $invFx !== null ? e((string) $invFx) : '—';
if ($invFx !== null && !empty($inv['fx_rate_date'])) {
    $invRateText .= '（' . e((string) $inv['fx_rate_date']) . '）';
}
$invInfo = [
  ['客户', e((string) $inv['supplier_name'])],
  ['发票日期', e((string) $inv['invoice_date'])],
  ['收入确认日', e((string) ($inv['revenue_recognition_date'] ?? ''))],
  ['币种', e((string) $inv['currency'])],
  ['整体折扣', ((float) ($inv['discount_rate'] ?? 0) > 0 ? rtrim(rtrim(number_format((float) $inv['discount_rate'], 2, '.', ''), '0'), '.') . '%' : '0%') . ' · ' . money($inv['discount_original'] ?? 0, (string) $inv['currency'])],
  ['原币金额', money($inv['gross_original'], (string) $inv['currency'])],
];
if ($invIsForeign) {
    $invInfo[] = ['折合功能货币', $invGrossFunctional !== null ? money($invGrossFunctional, $invFunctional) : '— ' . e($invFunctional)];
    $invInfo[] = ['汇率', $invRateText];
}
$invInfo = array_merge($invInfo, [
  ['履约义务', e((string) $inv['performance_obligation_status'])],
  ['收入科目', e((string) ($inv['revenue_account_code'] ?? ''))],
  ['校验', badge((string) ($inv['checkStatus'] ?? 'PASS'))],
  ['状态', status_pill((string) $inv['status'])],
]);
ob_start(); ?>
<?= kv_grid($invInfo) ?>
<?php
$invAct = '';
if ($role !== 'auditor' && $inv['status'] === 'draft') {
    $invAct = '<form method="post" style="margin:0">'
        . csrf_field()
        . '<input type="hidden" name="action" value="post_invoice">'
        . '<input type="hidden" name="id" value="' . (int) $inv['invoice_id'] . '">'
        . '<button class="btn primary sm" ' . (empty($inv['canPost']) ? 'disabled' : '')
        . ' title="' . (empty($inv['canPost']) ? '存在阻断项' : '校验通过') . '">提交过账</button></form>';
}
echo card('发票信息', ob_get_clean(), $invAct, false); ?>

<?php
$invLines = $inv['lines'] ?? [];
if ($invLines):
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th style="width:56px" class="num">编码</th><th>项目 / 内容</th>
<th style="width:70px">单位</th><th class="num" style="width:84px">数量</th>
<th class="num" style="width:110px">单价</th><th class="num" style="width:80px">税率</th>
<th class="num" style="width:120px">合价</th><th style="width:160px">备注</th></tr></thead>
<tbody>
<?php $sumAmt = 0; foreach ($invLines as $ln):
  $sumAmt += (float) $ln['amount']; ?>
  <tr>
    <td class="num hint"><?= (int) $ln['line_no'] ?></td>
    <td><?= e((string) $ln['description']) ?></td>
    <td class="hint"><?= e((string) ($ln['unit'] ?: '—')) ?></td>
    <td class="num"><?= e(rtrim(rtrim(number_format((float) $ln['quantity'], 4, '.', ','), '0'), '.')) ?></td>
    <td class="num"><?= money($ln['unit_price'], (string) $inv['currency']) ?></td>
    <td class="num"><?= $ln['tax_rate'] !== null ? e((string) $ln['tax_rate']) . '%' : '—' ?></td>
    <td class="num"><b><?= money($ln['amount'], (string) $inv['currency']) ?></b></td>
    <td class="hint"><?= e((string) ($ln['notes'] ?: '—')) ?></td>
  </tr>
<?php endforeach; ?>
</tbody>
<tfoot><tr>
  <td colspan="6" class="num hint">合计</td>
  <td class="num"><b><?= money($sumAmt, (string) $inv['currency']) ?></b></td>
  <td></td>
</tr></tfoot></table></div>
<?php echo card('明细清单（' . count($invLines) . ' 项）', ob_get_clean(), '', false);
endif; ?>

<?php ob_start(); ?>
<?php if (!$files): ?>
  <?= empty_state('尚无附件') ?>
<?php else: ?>
<div class="table-wrap"><table>
<thead><tr><th>文件名</th><th>类型</th><th class="num">大小</th><th>SHA-256</th><th>上传人</th><th>时间</th><th></th></tr></thead>
<tbody>
<?php foreach ($files as $f): ?>
<tr><td><?= e((string) $f['file_name']) ?></td>
<td><?= e((string) $f['file_type']) ?></td>
<td class="num"><?= number_format((int) $f['file_size']) ?> B</td>
<td class="hint" style="font-family:ui-monospace,monospace"><?= e(substr((string) $f['sha256_hash'], 0, 16)) ?>…</td>
<td><?= e((string) $f['uploaded_by']) ?></td>
<td class="hint"><?= e((string) $f['uploaded_at']) ?></td>
<td><a class="btn sm btn-file" href="?p=invoice-view&id=<?= $id ?>&download=<?= (int) $f['file_id'] ?>">下载</a></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php endif; ?>

<?php if ($role !== 'auditor'): ?>
<form method="post" enctype="multipart/form-data" class="card-actions">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="upload_file">
  <input type="file" name="file" required style="max-width:320px">
  <button class="btn primary sm">上传附件</button>
  <span class="hint">上限 20MB；上传即计算 SHA-256 并写入审计日志</span>
</form>
<?php endif; ?>
<?php echo card('附件', ob_get_clean(), '', false); ?>

<?php
$rs = (string) ($inv['review_status'] ?? 'draft');
$rsLabel = status_label((string) $rs);
$rsCls = ['draft' => 'st-draft', 'pending' => 'st-review', 'approved' => 'st-pass', 'rejected' => 'st-fail'][$rs] ?? 'st-draft';
?>
<?php ob_start(); ?>
<?= kv_grid([
  ['复核状态', '<span class="pill ' . $rsCls . '">' . e(t($rsLabel)) . '</span>'],
  ['录单人', e((string) ($inv['created_by'] ?? ''))],
  ['批准人', e((string) ($inv['approved_by'] ?? ''))],
  ['批准时间', e((string) ($inv['approved_at'] ?? ''))],
]) ?>
<?php if (!empty($inv['approval_note'])): ?>
  <div class="hint" style="margin-top:10px"><?= e((string) $inv['approval_note']) ?></div>
<?php endif; ?>
<?php
$revAct = '';
if ($role !== 'auditor' && $rs === 'draft') {
    $revAct = '<form method="post" style="margin:0">' . csrf_field()
        . '<input type="hidden" name="action" value="review">'
        . '<input type="hidden" name="op" value="submit">'
        . '<input type="hidden" name="id" value="' . (int) $inv['invoice_id'] . '">'
        . '<button class="btn primary sm">提交复核</button></form>';
} elseif ($role !== 'auditor' && $rs === 'pending') {
    // 管理员是「全权限」账号：可以批准自己录入的单据（审计日志仍记录批准人）
    $isSelf = strtolower((string) ($inv['created_by'] ?? '')) === strtolower((string) ($user['username'] ?? ''));
    $mayApprove = ($role === 'admin') || !$isSelf;
    if ($mayApprove) {
        $revAct = '<form method="post" style="margin:0;display:flex;gap:6px;align-items:center">' . csrf_field()
            . '<input type="hidden" name="action" value="review">'
            . '<input type="hidden" name="id" value="' . (int) $inv['invoice_id'] . '">'
            . '<input type="text" name="note" placeholder="' . e(t('批准意见 / 退回原因')) . '"'
            . ' style="width:190px" title="' . e(t('批准意见 / 退回原因')) . '">'
            . '<button class="btn primary sm" name="op" value="approve">' . e(t('批准')) . '</button>'
            . '<button class="btn sm ghost" name="op" value="reject">' . e(t('退回')) . '</button></form>';
    } else {
        $revAct = '<span class="hint">' . e(t('审批人不得是录单人（四眼原则）')) . '</span>';
    }
}
echo card(t('复核'), ob_get_clean(), $revAct, false); ?>


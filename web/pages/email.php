<?php
/*
 * LtBooks — pages/email.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;

$docType = (string) ($_GET['docType'] ?? '');
$docId = (int) ($_GET['docId'] ?? 0);
$info = null;
if ($docType !== '' && $docId > 0) {
    $r = api_get('/email/doc-info?docType=' . urlencode($docType) . '&docId=' . $docId
               . '&lang=' . urlencode(lang()));
    if ($r['ok']) { $info = $r['data']; }
    else { $errMsg = (string) $r['error']; }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $action = (string) ($_POST['action'] ?? '');
    if ($action === 'send_document') {
        $r = api_post('/email/send-document', [
            'docType' => (string) ($_POST['docType'] ?? ''),
            'docId' => (int) ($_POST['docId'] ?? 0),
            'to' => trim((string) ($_POST['to'] ?? '')),
            'cc' => trim((string) ($_POST['cc'] ?? '')) ?: null,
            'subject' => trim((string) ($_POST['subject'] ?? '')),
            'message' => trim((string) ($_POST['message'] ?? '')),
            'actor' => $displayName ?? 'system',
            'lang' => lang(),
        ]);
        if ($r['ok']) {
            $msg = '已发送至 ' . implode('、', (array) $r['data']['to'])
                 . '，附件 ' . implode('、', (array) $r['data']['attachments']);
        } else { $errMsg = (string) $r['error']; }
    } elseif ($action === 'save_smtp') {
        if ($role !== 'admin') {
            $errMsg = '只有管理员可以修改 SMTP 设置';
        } else {
            $r = api_post('/settings/email', [
                'host' => trim((string) ($_POST['smtpHost'] ?? '')),
                'port' => (int) ($_POST['smtpPort'] ?? 465),
                'secure' => (string) ($_POST['smtpSecure'] ?? 'ssl'),
                'user' => trim((string) ($_POST['smtpUser'] ?? '')),
                'password' => (string) ($_POST['smtpPassword'] ?? ''),
                'fromName' => trim((string) ($_POST['smtpFromName'] ?? '')),
                'actor' => $displayName ?? 'system',
            ]);
            if ($r['ok']) { $msg = 'SMTP 设置已保存'; } else { $errMsg = (string) $r['error']; }
        }
    } elseif ($action === 'send_test') {
        $r = api_post('/email/test', [
            'to' => trim((string) ($_POST['to'] ?? '')),
            'actor' => $displayName ?? 'system',
        ]);
        if ($r['ok']) { $msg = '测试邮件已发送至 ' . (string) $r['data']['to'][0]; }
        else { $errMsg = (string) $r['error']; }
    }
}

$st = api_get('/email/status');
$smtpCfg = api_get('/settings/email');
$sc = $smtpCfg['ok'] ? (array) $smtpCfg['data'] : [];
$smtp = $st['ok'] ? $st['data']['smtp'] : [];
[$logPage, $logPer] = pager_state('ledu_email_log_per', 25);
$logLimit = $logPer === 0 ? 0 : $logPer;
$logOffset = $logPer === 0 ? 0 : ($logPage - 1) * $logPer;
$logR = api_get('/email/log?limit=' . $logLimit . '&offset=' . $logOffset);
$logs = $logR['ok'] ? ($logR['data']['log'] ?? []) : [];
$logTotal = (int) ($logR['data']['total'] ?? count($logs));

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">发送成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

$docLabel = [
    'invoice' => '发票', 'bill' => '账单', 'quote' => '报价单', 'order' => '订单',
    'sales_order' => '销售订单', 'purchase_order' => '采购订单',
    'credit_note' => '贷记单', 'test' => '测试邮件', 'statement' => '对账单',
];
$docLinks = [
    'invoice' => '?p=invoice-view&id=', 'bill' => '?p=bill-view&id=',
    'quote' => '?p=doc-view&type=quote&id=', 'order' => '?p=order-view&id=',
    'sales_order' => '?p=order-view&id=', 'purchase_order' => '?p=order-view&id=',
    'credit_note' => '?p=doc-view&type=credit&id=',
];
?>
<style>
.email-settings-grid { display:grid; grid-template-columns:minmax(0,2fr) minmax(280px,1fr); gap:16px; align-items:start; }
.email-settings-grid > :only-child { grid-column:1/-1; }
/* 两张卡片各自按内容高度，避免连通测试卡被拉伸出一大片空白 */
.email-settings-grid > .card { height:auto; }
.email-smtp-grid { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:12px; }
.email-smtp-grid > :nth-child(1) { grid-column:span 6; }
.email-smtp-grid > :nth-child(2) { grid-column:span 2; }
.email-smtp-grid > :nth-child(3) { grid-column:span 4; }
.email-smtp-grid > :nth-child(n+4) { grid-column:span 4; }
@media (max-width:1100px) {
  .email-settings-grid { grid-template-columns:1fr; }
  .email-smtp-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .email-smtp-grid > :nth-child(n) { grid-column:span 1; }
}
@media (max-width:680px) {
  .email-smtp-grid { grid-template-columns:1fr; }
  .email-smtp-grid > :nth-child(n) { grid-column:1/-1; }
}
</style>

<div class="banner <?= !empty($smtp['configured']) ? 'PASS' : 'FAIL' ?>">
  <span class="banner-icon"><?= !empty($smtp['configured']) ? '✓' : '✕' ?></span>
  <div class="banner-body">
    <div class="banner-title">外发服务器 <?= e((string) ($smtp['host'] ?? '')) ?>:<?= e((string) ($smtp['port'] ?? '')) ?>
      （<?= e(strtoupper((string) ($smtp['security'] ?? ''))) ?>，需要认证）</div>
    <div class="banner-reason">
      发件人 <?= e((string) ($smtp['fromName'] ?? '')) ?> &lt;<?= e((string) ($smtp['user'] ?? '')) ?>&gt;
      · 密码存在数据库 app_settings 表（仅管理员可改），接口只回「是否已设置」，不回传明文
    </div>
  </div>
</div>

<?php if ($info): ?>
<?php
$amountLabel = ($info['amountKind'] ?? 'due') === 'total' ? t('单据金额') : t('未结金额');
$dateKind = (string) ($info['dateKind'] ?? 'due');
$dateLabel = $dateKind === 'valid' ? t('有效期至')
           : ($dateKind === 'credit' ? t('贷记日期')
           : ($dateKind === 'expected'
               ? (($info['resolvedDocType'] ?? '') === 'purchase_order' ? t('预计到货') : t('预计交付'))
               : t('到期日')));
$pdfPath = (string) ($info['pdfPath'] ?? ('/invoices/' . (int) $info['docId'] . '/pdf'));
$partyType = (string) ($info['partyType'] ?? 'customer');
ob_start(); ?>
<div class="metrics">
  <div class="metric"><div class="lbl"><?= e(t('单据')) ?></div><div class="val" style="font-size:var(--f-lg)"><?= e((string) $info['docNo']) ?></div></div>
  <div class="metric"><div class="lbl"><?= e(t('对方')) ?></div><div class="val" style="font-size:var(--f-lg)"><?= e((string) $info['party']) ?></div></div>
  <div class="metric"><div class="lbl"><?= e($amountLabel) ?></div><div class="val" style="font-size:var(--f-lg)"><?= money($info['amount'] ?? $info['amountDue'], (string) $info['currency']) ?></div></div>
  <div class="metric"><div class="lbl"><?= e($dateLabel) ?></div><div class="val" style="font-size:var(--f-lg)"><?= e((string) (($info['dueDate'] ?? null) ?: '—')) ?></div></div>
</div>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="send_document">
  <input type="hidden" name="docType" value="<?= e((string) $info['docType']) ?>">
  <input type="hidden" name="docId" value="<?= (int) $info['docId'] ?>">
  <div class="grid">
    <div class="field"><label class="f">收件人 *</label>
      <input type="email" name="to" required value="<?= e((string) ($_POST['to'] ?? $info['partyEmail'] ?? '')) ?>"
             placeholder="customer@example.com">
      <?php if (empty($info['partyEmail'])): ?>
        <div class="hint"><?= e($partyType === 'vendor'
            ? t('供应商档案未登记邮箱，请手工填写；如需长期使用可在「供应商」页补充')
            : t('客户档案未登记邮箱，请手工填写；如需长期使用可在「客户」页补充')) ?></div>
      <?php endif; ?>
    </div>
    <div class="field"><label class="f">抄送</label>
      <input type="text" name="cc" value="<?= e((string) ($_POST['cc'] ?? '')) ?>" placeholder="多址用逗号分隔"></div>
  </div>
  <div class="field" style="margin-top:10px"><label class="f">主题</label>
    <input type="text" name="subject" value="<?= e((string) ($_POST['subject'] ?? $info['suggestedSubject'])) ?>"></div>
  <div class="field" style="margin-top:10px"><label class="f">正文（可选）</label>
    <textarea name="message" rows="4" placeholder="留空则使用标准模板"><?= e((string) ($_POST['message'] ?? '')) ?></textarea></div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <button class="btn primary">发送（附 PDF）</button>
    <a class="btn" target="_blank" href="/pdf/reports.php?u=<?= e(rawurlencode($pdfPath . '?lang=' . report_lang())) ?>"><?= e(t('预览 PDF')) ?></a>
    <span class="hint">附件由系统即时生成，与手工下载的 PDF 完全一致</span>
  </div>
</form>
<?php echo card('发送单据邮件', ob_get_clean()); ?>
<?php endif; ?>

<div class="email-settings-grid">
<?php if ($role === 'admin'): ?>
<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="save_smtp">
  <div class="email-smtp-grid">
    <div class="field"><label class="f"><?= e(t('SMTP 主机')) ?></label>
      <input type="text" name="smtpHost" value="<?= e((string) ($sc['host'] ?? '')) ?>"
             placeholder="smtp.example.com" autocomplete="off">
      <span class="hint"><?= e(t('邮件服务商提供的发信服务器地址')) ?></span></div>
    <div class="field"><label class="f"><?= e(t('端口')) ?></label>
      <input type="number" name="smtpPort" min="1" max="65535"
             value="<?= (int) ($sc['port'] ?? 465) ?>">
      <span class="hint"><?= e(t('SSL 常用 465，STARTTLS 常用 587')) ?></span></div>
    <div class="field"><label class="f"><?= e(t('加密方式')) ?></label>
      <select name="smtpSecure">
        <?php foreach (['ssl' => 'SSL（465）', 'tls' => 'STARTTLS（587）', 'none' => t('不加密')] as $k => $v): ?>
          <option value="<?= e($k) ?>" <?= (string) ($sc['secure'] ?? 'ssl') === $k ? 'selected' : '' ?>>
            <?= e($v) ?></option>
        <?php endforeach; ?>
      </select></div>
    <div class="field"><label class="f"><?= e(t('账号')) ?></label>
      <input type="text" name="smtpUser" value="<?= e((string) ($sc['user'] ?? '')) ?>"
             placeholder="you@example.com" autocomplete="off"></div>
    <div class="field"><label class="f"><?= e(t('密码 / 授权码')) ?></label>
      <input type="password" name="smtpPassword" value="" autocomplete="new-password"
             placeholder="<?= !empty($sc['hasPassword']) ? e(t('已设置，留空表示不修改')) : e(t('填写邮箱授权码')) ?>">
      <span class="hint"><?= e(t('多数邮箱要填「授权码」而不是登录密码；留空不修改')) ?></span></div>
    <div class="field"><label class="f"><?= e(t('发件人显示名')) ?></label>
      <input type="text" name="smtpFromName" value="<?= e((string) (($sc['fromName'] ?? '') !== '' ? $sc['fromName'] : 'Lt-AI-Books')) ?>">
      <span class="hint"><?= e(t('收件人看到的发件人名称')) ?></span></div>
  </div>
  <div class="toolbar form-actions" style="margin-top:14px;margin-bottom:0">
    <button class="btn primary"><?= e(t('保存 SMTP 设置')) ?></button>
    <span class="hint">
      <?php if (($sc['source'] ?? 'none') === 'settings'): ?>
        <?= e(t('当前使用界面设置')) ?>
      <?php elseif (($sc['source'] ?? 'none') === 'env'): ?>
        <?= e(t('当前使用 .env 里的初始值，保存后以界面设置为准')) ?>
      <?php else: ?>
        <?= e(t('尚未配置')) ?>
      <?php endif; ?>
    </span>
  </div>
</form>
<?php echo card('SMTP 设置', ob_get_clean(), '', true); ?>
<?php endif; ?>

<?php if ($role !== 'auditor'): ?>
<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="send_test">
  <div class="field"><label class="f"><?= e(t('收件地址')) ?></label>
    <input type="email" name="to" required value="<?= e((string) ($smtp['user'] ?? '')) ?>">
    <span class="hint"><?= e(t('用于验证 SMTP 通道；发送记录会留痕')) ?></span></div>
  <div class="toolbar form-actions" style="margin-top:14px;margin-bottom:0">
    <button class="btn primary">发送测试邮件</button>
  </div>
</form>
<?php echo card('SMTP 连通测试', ob_get_clean()); ?>
<?php endif; ?>
</div>

<?php ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>时间</th><th>类型</th><th>单据</th><th>收件人</th><th>主题</th><th>状态</th><th>操作人</th></tr></thead>
<tbody>
<?php if (!$logs): ?><tr><td colspan="7"><?= empty_state('尚无发送记录') ?></td></tr><?php endif; ?>
<?php foreach ($logs as $x): ?>
  <?php $logType = (string) $x['doc_type']; $logHref = $docLinks[$logType] ?? ''; ?>
  <tr>
    <td style="white-space:nowrap"><?= e(substr((string) $x['sent_at'], 0, 19)) ?></td>
    <td><?= e(t($docLabel[$logType] ?? $logType)) ?></td>
    <td><?php if (!$x['doc_no']): ?>—<?php elseif ($x['doc_id'] && $logHref !== ''): ?>
      <a href="<?= e($logHref . (int) $x['doc_id']) ?>"><?= e((string) $x['doc_no']) ?></a>
    <?php else: ?><?= e((string) $x['doc_no']) ?><?php endif; ?></td>
    <td><?= e((string) $x['to_addrs']) ?><?= $x['cc_addrs'] ? '<div class="hint">抄送 ' . e((string) $x['cc_addrs']) . '</div>' : '' ?></td>
    <td><?= e((string) $x['subject']) ?><?= $x['error'] ? '<div class="hint" style="color:var(--c-danger)">' . e(mb_substr((string) $x['error'], 0, 90)) . '</div>' : '' ?></td>
    <td><?= $x['status'] === 'sent' ? badge('PASS') : badge('FAIL') ?></td>
    <td><?= e((string) $x['sent_by']) ?></td>
  </tr>
<?php endforeach; ?>
</tbody></table></div>
<?php echo card('发送记录', ob_get_clean(), pager_html($logPage, $logPer, $logTotal, ['p' => 'email']), false); ?>

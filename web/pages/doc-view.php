<?php
/*
 * LtBooks — pages/doc-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 单据详情（通用）：报价单 / 贷记单 / 费用单 / 分录。
 *
 * 为什么一个页面：这几种单据的字段大同小异，各自复制一份 detail 页会很快走形。
 * 这里按 type 取数、按同一套版式渲染，列表里点单号就到这里。
 */
$type = (string) ($_GET['type'] ?? '');
$id   = (int) ($_GET['id'] ?? 0);
$back = (string) ($_GET['back'] ?? '');

$BACK = [
    'quote'  => '?p=quotes',
    'credit' => '?p=credit-notes',
    'expense' => '?p=expenses',
    'journal' => '?p=journal',
];
$TITLE = [
    'quote' => '报价单', 'credit' => '贷记单', 'expense' => '费用单', 'journal' => '记账分录',
];
$endpoint = [
    'quote' => '/quotes/', 'credit' => '/credit-notes/',
    'expense' => '/expenses/', 'journal' => '/journal/',
];
if (!isset($endpoint[$type]) || $id <= 0) {
    echo errbox('没有指定要查看的单据');
    return;
}

// ---------- 补传 / 删除附件（已有单据也能补） ----------
$__docTypeMap = ['quote' => 'quote', 'credit' => 'credit_note',
                 'expense' => 'expense', 'journal' => 'journal',
                 // 发票/账单在各自详情页也显示附件，这里再兜一层，
                 // 从 doc-view 打开时同样能看到 AI 导入的原件
                 'invoice' => 'invoice', 'bill' => 'bill'];
$__dt = $__docTypeMap[$type] ?? null;
$__actor = (string) ($user['username'] ?? 'system');
$__role = $role ?? 'accountant';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $__dt !== null && $__role !== 'auditor') {
    $act = (string) ($_POST['action'] ?? '');
    if ($act === 'attach_upload') {
        $n = doc_files_save($__dt, $id, $_FILES['file'] ?? [], $__actor);
        header('Location: ?p=doc-view&type=' . urlencode($type) . '&id=' . $id
             . '&back=' . urlencode($back) . '&msg=' . urlencode($n > 0 ? "已上传 {$n} 个附件" : '没有选中文件'));
        exit;
    }
    if ($act === 'attach_delete') {
        api_post('/doc-files/' . (int) ($_POST['fileId'] ?? 0) . '/delete', ['actor' => $__actor]);
        header('Location: ?p=doc-view&type=' . urlencode($type) . '&id=' . $id
             . '&back=' . urlencode($back) . '&msg=' . urlencode('附件已删除'));
        exit;
    }
}
$__msg = (string) ($_GET['msg'] ?? '');

$r = api_get($endpoint[$type] . $id);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'] ?? [];
// 分录详情接口采用 {entry, lines} 结构，其他单据则是扁平表头。
if ($type === 'journal' && isset($d['entry']) && is_array($d['entry'])) {
    $d = array_merge($d, $d['entry']);
}
$backHref = $back !== '' ? $back : ($BACK[$type] ?? '?p=today');
$docFunctional = (string) ($d['functional_currency'] ?? '');
$docIsForeign = in_array($type, ['quote', 'credit'], true) && $docFunctional !== ''
    && strtoupper((string) ($d['currency'] ?? '')) !== strtoupper($docFunctional);
$docGrossFunctional = null;
if ($docIsForeign && isset($d['amount_functional'])) {
    $candidate = (float) $d['amount_functional'];
    if ((float) ($d['gross_original'] ?? 0) == 0.0 || $candidate != 0.0) { $docGrossFunctional = $candidate; }
}

$field = function (string $k, string $label, string $fmt = 'text') use ($d): string {
    $v = $d[$k] ?? null;
    if ($v === null || $v === '') { $v = '—'; }
    if ($fmt === 'money') {
        $txt = number_format((float) $v, 2);
    } elseif ($fmt === 'date') {
        $txt = (string) $v;
    } elseif ($fmt === 'status') {
        $txt = status_label((string) $v);          // 状态一律走统一表，不直接印英文码
    } elseif ($fmt === 'category') {
        $txt = ['expense' => t('费用'), 'income' => t('收入'), 'other' => t('其他')][(string) $v] ?? (string) $v;
    } else {
        $txt = (string) $v;
    }
    return '<div class="dv-item"><div class="dv-k">' . e(t($label)) . '</div>'
        . '<div class="dv-v">' . e($txt) . '</div></div>';
};
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e(t($TITLE[$type])) ?></h1>
    <div class="page-sub mono">
      <?= e((string) ($d['quote_no'] ?? $d['credit_no'] ?? $d['expense_no'] ?? $d['entry_no'] ?? '')) ?>
    </div>
  </div>
  <div class="page-actions">
    <a class="btn" href="<?= e($backHref) ?>"><?= e(t('返回列表')) ?></a>
    <?php if (in_array($type, ['expense', 'quote', 'credit', 'journal'], true) && ($d['status'] ?? '') === 'draft' && $__role !== 'auditor'): ?>
      <?php $editPage = ['expense' => 'expense-new', 'quote' => 'quotes',
                         'credit' => 'credit-notes', 'journal' => 'journal-new'][$type]; ?>
      <a class="btn primary" href="?p=<?= e($editPage) ?>&amp;edit=<?= $id ?>"><?= e(t('编辑草稿')) ?></a>
      <?= draft_delete_form(['expense' => 'expense', 'quote' => 'quote',
                             'credit' => 'credit_note', 'journal' => 'journal'][$type], $id,
                            ['expense' => 'expenses', 'quote' => 'quotes',
                             'credit' => 'credit-notes', 'journal' => 'journal'][$type]) ?>
    <?php endif; ?>
    <?php if (in_array($type, ['quote', 'credit'], true)): ?>
      <?php $emailDocType = $type === 'credit' ? 'credit_note' : 'quote'; ?>
      <a class="btn sm" href="?p=email&amp;docType=<?= e($emailDocType) ?>&amp;docId=<?= $id ?>"><?= e(t('发送邮件')) ?></a>
    <?php endif; ?>
    <?php if ($type === 'quote' && !empty($d['converted_invoice_id'])): ?>
      <a class="btn primary" href="?p=invoice-view&id=<?= (int) $d['converted_invoice_id'] ?>"><?= e(t('查看发票')) ?></a>
    <?php endif; ?>
    <?php if ($type === 'journal' && !empty($d['entry_id'])): ?>
      <a class="btn" href="?p=journal-view&amp;id=<?= (int) $d['entry_id'] ?>"><?= e(t('原分录页')) ?></a>
    <?php endif; ?>
    <?php if (in_array($type, ['quote', 'credit'], true)): ?>
      <?php $pdfPath = ($type === 'quote' ? '/quotes/' : '/credit-notes/') . (int) ($d['quote_id'] ?? $d['credit_id'] ?? 0) . '/pdf'; ?>
      <?= export_menu(export_lang_items($pdfPath), t('导出 PDF'), 'btn sm') ?>
    <?php endif; ?>
  </div>
</div>

<?= help_html('doc-view') ?>

<div class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('单据信息')) ?></h2></div>
  <div class="card-body">
    <div class="dv-grid">
      <?php if ($type === 'quote'): ?>
        <?= $field('customer_name', '客户') ?>
        <?= $field('subject', '主题') ?>
        <?= $field('reference', '参考号') ?>
        <?= $field('salesperson', '销售人员') ?>
        <?= $field('quote_date', '报价日期', 'date') ?>
        <?= $field('valid_until', '有效期至', 'date') ?>
        <?= $field('currency', '币种') ?>
        <?= $field('gross_original', $docIsForeign ? '原币合计' : '合计', 'money') ?>
        <?php if ($docIsForeign): ?>
          <?= $field('fx_rate', '汇率') ?>
          <div class="dv-item"><div class="dv-k"><?= e(t('折合功能货币')) ?></div>
            <div class="dv-v"><?= $docGrossFunctional !== null
                ? money($docGrossFunctional, $docFunctional) : '— ' . e($docFunctional) ?></div></div>
        <?php endif; ?>
        <?= $field('status', '状态', 'status') ?>
        <?= $field('notes', '客户备注') ?>
        <?= $field('terms', '条款与条件') ?>
      <?php elseif ($type === 'credit'): ?>
        <?= $field('party_name', '往来单位') ?>
        <?= $field('credit_date', '贷记日期', 'date') ?>
        <?= $field('currency', '币种') ?>
        <?= $field('gross_original', $docIsForeign ? '原币合计' : '合计', 'money') ?>
        <?php if ($docIsForeign): ?>
          <?= $field('fx_rate', '汇率') ?>
          <div class="dv-item"><div class="dv-k"><?= e(t('折合功能货币')) ?></div>
            <div class="dv-v"><?= $docGrossFunctional !== null
                ? money($docGrossFunctional, $docFunctional) : '— ' . e($docFunctional) ?></div></div>
        <?php endif; ?>
        <?= $field('source_invoice_no', '原发票编号') ?>
        <?= $field('source_bill_no', '原账单编号') ?>
        <?= $field('revenue_account_code', ($d['credit_type'] ?? '') === 'customer' ? '收入科目' : '费用科目') ?>
        <?= $field('reason', '原因') ?>
        <?= $field('status', '状态', 'status') ?>
      <?php elseif ($type === 'expense'): ?>
        <?= $field('date', '日期', 'date') ?>
        <?= $field('category', '支出用途') ?>
        <?= $field('project_name', '项目') ?>
        <?= $field('notes', '备注') ?>
        <?= $field('expense_account_code', '费用科目') ?>
        <?= $field('reviewed_by', '复核人') ?>
        <?= $field('currency', '币种') ?>
        <?= $field('amount', '金额', 'money') ?>
        <?= $field('tax_amount', '税额', 'money') ?>
        <?= $field('status', '状态', 'status') ?>
      <?php else: ?>
        <?= $field('entry_date', '日期', 'date') ?>
        <?= $field('source_type', '来源') ?>
        <?= $field('description', '摘要') ?>
        <?= $field('total_debit', '借方合计', 'money') ?>
        <?= $field('status', '状态', 'status') ?>
        <?= $field('created_by', '制单人') ?>
      <?php endif; ?>
    </div>
  </div>
</div>

<?php
$lines = (array) ($d['lines'] ?? []);
if ($type === 'quote' && $lines):
?>
<div class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('明细')) ?></h2></div>
  <div class="table-wrap"><table>
    <thead><tr><th><?= e(t('摘要')) ?></th><th class="num"><?= e(t('数量')) ?></th>
      <th class="num"><?= e(t('单价')) ?></th><th class="num"><?= e(t('金额')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($lines as $ln): ?>
      <tr>
        <td><?= e((string) $ln['description']) ?></td>
        <td class="num"><?= e((string) (float) $ln['quantity']) ?></td>
        <td class="num"><?= money($ln['unit_price']) ?></td>
        <td class="num"><?= money($ln['amount']) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</div>
<?php endif; ?>

<?php if ($type === 'journal' && !empty($d['lines'])): ?>
<div class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('分录行')) ?></h2></div>
  <div class="table-wrap"><table>
    <thead><tr><th style="width:110px"><?= e(t('科目')) ?></th><th><?= e(t('摘要')) ?></th>
      <th class="num"><?= e(t('借方')) ?></th><th class="num"><?= e(t('贷方')) ?></th></tr></thead>
    <tbody>
    <?php foreach ((array) $d['lines'] as $ln): ?>
      <tr>
        <td class="mono"><?= e((string) $ln['account_code']) ?></td>
        <td><?= e((string) ($ln['description'] ?? '')) ?></td>
        <td class="num"><?= (float) $ln['debit'] ? money($ln['debit']) : '—' ?></td>
        <td class="num"><?= (float) $ln['credit'] ? money($ln['credit']) : '—' ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</div>
<?php endif; ?>



<?php
// 通用附件（doc_files）：报价单 / 贷记单 / 分录 / 费用都能挂；没有也可补传
if ($__dt !== null):
    $__fr = api_get('/doc-files?type=' . urlencode($__dt) . '&id=' . $id);
    $__files = $__fr['ok'] ? ($__fr['data']['files'] ?? []) : [];
?>
<div class="card" style="margin-top:16px">
  <div class="card-head">
    <h2>附件（<?= count($__files) ?>）</h2>
    <span class="hint">上传时已记 SHA-256，改动可查 · 单文件上限 20MB</span>
  </div>

  <?php if ($__files): ?>
  <div class="table-wrap"><table>
    <thead><tr><th>文件名</th><th class="num" style="width:110px">大小</th>
      <th style="width:180px">上传时间</th><th style="width:150px"></th></tr></thead>
    <tbody>
    <?php foreach ($__files as $f): ?>
      <tr>
        <td class="mono" style="font-size:12px"><?= e((string) $f['file_name']) ?></td>
        <td class="num"><?= number_format(((int) $f['file_size']) / 1024, 1) ?> KB</td>
        <td class="hint"><?= e((string) str_replace('T', ' ', substr((string) $f['created_at'], 0, 19))) ?></td>
        <td style="white-space:nowrap">
          <a class="btn sm" target="_blank"
             href="/pdf/reports.php?u=<?= e(rawurlencode('/doc-files/' . (int) $f['file_id'] . '/raw')) ?>">查看</a>
          <?php if ($__role !== 'auditor'): ?>
          <form method="post" class="inline-form"
                data-confirm="删除这个附件？" data-confirm-note="文件会从单据上移除，审计日志保留这次删除动作。">
            <?= csrf_field() ?>
            <input type="hidden" name="action" value="attach_delete">
            <input type="hidden" name="fileId" value="<?= (int) $f['file_id'] ?>">
            <button class="btn sm danger">删除</button>
          </form>
          <?php endif; ?>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
  <?php endif; ?>

  <?php if ($__role !== 'auditor'): ?>
  <form method="post" enctype="multipart/form-data" class="card-body" style="border-top:1px solid #EEF2F7">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="attach_upload">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <input type="file" name="file[]" multiple accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.doc,.docx"
             style="max-width:420px">
      <button class="btn primary sm">上传附件</button>
      <span class="hint">已有单据也可以在这里补传</span>
    </div>
  </form>
  <?php endif; ?>
</div>
<?php endif; ?>

<?php
/*
 * LtBooks — pages/expense-new.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$inlineErr = handle_inline_account_create(['expense', 'cogs'], 'expense-new', $user ?? []);
if ($inlineErr !== null) { $errMsg = $inlineErr; }
$newAcc = (string) ($_GET['newacc'] ?? '');
$errMsg = $errMsg ?? null;
if ($role === 'auditor') { echo empty_state('审计角色不可录入'); return; }
$editId = (int) ($_GET['edit'] ?? 0);
$isEdit = $editId > 0;
$editExpense = null;
if ($isEdit) {
    $er = api_get('/expenses/' . $editId);
    $editExpense = $er['ok'] ? ($er['data'] ?? null) : null;
    if (!$editExpense || ($editExpense['status'] ?? '') !== 'draft') {
        echo errbox('只有草稿费用可以编辑'); return;
    }
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        foreach ([
            'expenseNo' => (string) $editExpense['expense_no'],
            'category' => (string) $editExpense['category'],
            'projectName' => (string) ($editExpense['project_name'] ?? ''),
            'notes' => (string) ($editExpense['notes'] ?? ''),
            'reviewedBy' => (string) ($editExpense['reviewed_by'] ?? ''),
            'date' => substr((string) $editExpense['date'], 0, 10),
            'currency' => (string) $editExpense['currency'],
            'amount' => (string) $editExpense['amount'],
            'taxAmount' => (string) $editExpense['tax_amount'],
            'expenseAccountCode' => (string) $editExpense['expense_account_code'],
        ] as $k => $val) { $_POST[$k] = $val; }
    }
}
$formAction = $isEdit ? 'update_expense' : 'create_expense';
$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$pick = (string) ($_POST['expenseAccountCode'] ?? ($newAcc !== '' ? $newAcc : '6600'));
$accOpts = '';
foreach ($accounts as $a) {
    if (!in_array($a['category'], ['expense', 'cogs'], true)) { continue; }
    $sel = ($pick === (string) $a['account_code']) ? ' selected' : '';
    $accOpts .= '<option value="' . e((string) $a['account_code']) . '"' . $sel . '>'
              . e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) . '</option>';
}

$result = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === $formAction) {
    $body = [
        'expenseNo' => trim((string) ($_POST['expenseNo'] ?? '')),
        'category' => trim((string) ($_POST['category'] ?? '')),
        'projectName' => trim((string) ($_POST['projectName'] ?? '')),
        'notes' => trim((string) ($_POST['notes'] ?? '')),
        'date' => (string) ($_POST['date'] ?? ''),
        'currency' => (string) ($_POST['currency'] ?? 'HKD'),
        'amount' => (float) ($_POST['amount'] ?? 0),
        'taxAmount' => (float) ($_POST['taxAmount'] ?? 0),
        'expenseAccountCode' => (string) ($_POST['expenseAccountCode'] ?? '6600'),
        'reviewedBy' => trim((string) ($_POST['reviewedBy'] ?? '')) ?: null,
        'requiredDocuments' => ['receipt'],
        'documents' => [['type' => 'receipt', 'ref' => 'PHP-upload']],
        'actor' => (string) ($user['username'] ?? 'system'),
        'autoPost' => ($_POST['action_flag'] ?? '') === 'post' && !$isEdit,
    ];
    $res = $isEdit ? api_post('/expenses/' . $editId . '/update', $body)
                   : api_post('/expenses', $body);
    $result = $res['ok'] ? $res['data'] : ['__error' => $res['error']];
}
$v = fn(string $k, string $d = '') => e((string) ($_POST[$k] ?? $d));
if ($result !== null && isset($result['__error'])) { echo errbox((string) $result['__error']); }
if ($result !== null && !isset($result['__error'])) {
    $st = 'PASS';
    foreach ($result['checks'] as $c) {
        if (($c['status'] ?? '') === 'FAIL') { $st = 'FAIL'; break; }
        if (($c['status'] ?? '') === 'REVIEW') { $st = 'REVIEW'; }
    }
    echo banner($st, null, $result['checks']);
    $eid = (int) ($result['expenseId'] ?? 0);
    if ($eid > 0 && !empty($_FILES['attach']['name'][0])) {
        $n = doc_files_save('expense', $eid, $_FILES['attach'],
                            (string) ($user['username'] ?? 'system'));
        if ($n > 0) { echo '<div class="hint" style="margin:8px 0">已附 ' . $n . ' 个文件</div>'; }
    }
}
?>
<form method="post" enctype="multipart/form-data">
  <?= csrf_field() ?>
<input type="hidden" name="action" value="<?= e($formAction) ?>">
<div class="zform">
  <div class="zcol">
    <div class="zsec-h">收款与摘要</div>
    <div class="field"><label class="f">支出用途 *</label>
      <input type="text" name="category" value="<?= $v('category') ?>"
             placeholder="例：客户招待 / 打车 / 办公用品" required>
      <div class="hint">写清用途，报销与审计时看得懂</div>
    </div>
    <div class="field"><label class="f">项目</label>
      <input type="text" name="projectName" maxlength="200" value="<?= $v('projectName') ?>"
             placeholder="例：网站改版 / 客户 A / 市场部">
      <div class="hint">选填；保存后会显示在费用列表和详情，可用于搜索</div>
    </div>
    <div class="field"><label class="f">费用科目 *</label>
      <select name="expenseAccountCode" required data-allow-create="1" id="expAcc"><?= $accOpts ?></select>
      <div class="hint">借方记哪个科目；进项税额自动记入 1160</div>
    </div>
  </div>

  <div class="zcol zcol-2">
    <div class="zsec-h">费用信息</div>
    <div class="z2">
      <?= doc_no_field('费用编号', next_doc_no((string) ($_POST['date'] ?? date('Y-m-d')), 'expense'), 'expenseNo') ?>
      <div class="field"><label class="f">日期 *</label>
        <input type="date" name="date" value="<?= $v('date', date('Y-m-d')) ?>" required>
      </div>
      <div class="field"><label class="f">币种</label>
        <select name="currency"><?= currency_options((string) ($_POST['currency'] ?? 'HKD')) ?></select>
      </div>
      <div class="field"><label class="f">复核人</label>
        <input type="text" name="reviewedBy" value="<?= $v('reviewedBy') ?>" placeholder="选填">
      </div>
    </div>
  </div>
</div>

<div class="zfoot">
  <div class="zfoot-left">
    <div class="field"><label class="f">备注</label>
      <textarea name="notes" rows="3" maxlength="600" placeholder="选填；会留在单据上"><?= $v('notes') ?></textarea>
    </div>
  </div>
  <div class="zfoot-right">
    <table class="totals">
      <tr><td>金额（不含税）*</td>
        <td class="num"><input type="number" step="0.01" min="0" name="amount" value="<?= $v('amount') ?>"
              required style="width:140px;text-align:right"></td></tr>
      <tr><td>税额</td>
        <td class="num"><input type="number" step="0.01" min="0" name="taxAmount" value="<?= $v('taxAmount', '0') ?>"
              style="width:140px;text-align:right"></td></tr>
      <tr class="grand"><td>合计</td><td class="num"><span id="expTotal">0.00</span></td></tr>
    </table>
  </div>
</div>

<?= attach_dropzone('attach', '把小票 / 发票扫描件拖到这里', '或点击选择文件 · 保存后自动挂到这张费用单') ?>

<div class="card-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
  <a class="btn" href="<?= $isEdit ? '?p=doc-view&type=expense&id=' . $editId : '?p=expenses' ?>">取消</a>
  <?php if ($isEdit): ?>
    <button class="btn primary" name="action_flag" value="draft"><?= e('保存修改') ?></button>
  <?php else: ?>
    <button class="btn" name="action_flag" value="post" data-shortcut-post>保存并过账</button>
    <button class="btn primary" name="action_flag" value="draft" data-shortcut-save>保存草稿</button>
  <?php endif; ?>
</div>
<script>
(function () {
  var a = document.querySelector('input[name=amount]'), t = document.querySelector('input[name=taxAmount]'),
      o = document.getElementById('expTotal');
  if (!a || !t || !o) return;
  function f() { o.textContent = (((parseFloat(a.value) || 0) + (parseFloat(t.value) || 0))).toFixed(2); }
  [a, t].forEach(function (el) { el.addEventListener('input', f); });
  f();
})();
</script>
</form>

<?php echo inline_account_create_panel(['expense', 'cogs'], $newAcc); ?>

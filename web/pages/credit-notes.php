<?php
/*
 * LtBooks — pages/credit-notes.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 贷记单（红字单）：退货、折让、开票错误。过账后生成红字凭证，不改原单。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;
$editId = (int) ($_GET['edit'] ?? 0);
$partyErr = handle_inline_party_create('customer', 'credit-notes', $user ?? []);

// ---------------------------------------------------------------- 动作
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor') {
    $action = (string) ($_POST['action'] ?? '');
    $id = (int) ($_POST['id'] ?? 0);

    if (in_array($action, ['credit_create', 'credit_update'], true)) {
        $isUpdate = $action === 'credit_update';
        if ($isUpdate) { $editId = $id; }
        $res = api_post($isUpdate ? '/credit-notes/' . $id . '/update' : '/credit-notes', [
            'creditNo' => trim((string) ($_POST['creditNo'] ?? '')),
            'creditType' => (string) ($_POST['creditType'] ?? 'customer'),
            'partyName' => trim((string) ($_POST['partyName'] ?? '')),
            'creditDate' => (string) ($_POST['creditDate'] ?? date('Y-m-d')),
            'currency' => (string) ($_POST['currency'] ?? 'HKD'),
            'amountOriginal' => (float) ($_POST['amountOriginal'] ?? 0),
            'taxOriginal' => (float) ($_POST['taxOriginal'] ?? 0),
            'reason' => (string) ($_POST['reason'] ?? ''),
            'sourceInvoiceId' => (int) ($_POST['sourceInvoiceId'] ?? 0) ?: null,
            'sourceBillId' => (int) ($_POST['sourceBillId'] ?? 0) ?: null,
            'revenueAccountCode' => (string) ($_POST['revenueAccountCode'] ?? '') ?: null,
            'actor' => $actor,
        ]);
        if ($res['ok']) {
            $cid = (int) ($res['data']['creditId'] ?? 0);
            if ($cid > 0 && !empty($_FILES['attach']['name'][0])) {
                doc_files_save('credit_note', $cid, $_FILES['attach'], $actor);
            }
            $autoPost = ($_POST['action_flag'] ?? '') === 'post' && !$isUpdate;
            if ($autoPost) {
                $pr = api_post('/credit-notes/' . $cid . '/post', ['actor' => $actor]);
                $msg = $pr['ok']
                    ? t('贷记单已保存并过账（红字凭证') . ' ' . (string) ($pr['data']['entryNo'] ?? '') . '）'
                    : t('贷记单已保存为草稿，过账失败：') . (string) $pr['error'];
                header('Location: ?p=credit-notes&msg=' . urlencode($msg));
                exit;
            }
            header('Location: ?p=credit-notes&msg=' . urlencode(
                t('贷记单') . ' ' . (string) ($res['data']['creditNo'] ?? '') . ' '
                . t($isUpdate ? '修改已保存' : '已保存为草稿')));
            exit;
        }
        $errMsg = (string) $res['error'];
    } elseif ($action === 'credit_post') {
        $res = api_post('/credit-notes/' . $id . '/post', ['actor' => $actor]);
        if ($res['ok']) {
            header('Location: ?p=credit-notes&msg=' . urlencode(
                t('贷记单已过账，红字凭证') . ' ' . (string) ($res['data']['entryNo'] ?? '')));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}

// ---------------------------------------------------------------- 读数据
$formError = $errMsg !== null && in_array((string) ($_POST['action'] ?? ''), ['credit_create', 'credit_update'], true);
$showNew = ((string) ($_GET['new'] ?? '') === '1' || $editId > 0 || $formError) && $role !== 'auditor';
$editing = null;
if ($editId > 0 && $role !== 'auditor') {
    $editR = api_get('/credit-notes/' . $editId);
    if (!$editR['ok']) { echo errbox((string) $editR['error']); return; }
    $editing = $editR['data'] ?? [];
    if ((string) ($editing['status'] ?? '') !== 'draft') {
        echo errbox('只有草稿状态的贷记单可以编辑'); return;
    }
}
$value = static function (string $key, string $dbKey = '', $default = '') use ($editing) {
    if (array_key_exists($key, $_POST)) { return $_POST[$key]; }
    if ($editing && $dbKey !== '' && array_key_exists($dbKey, $editing)) { return $editing[$dbKey]; }
    return $default;
};
$creditDate = (string) $value('creditDate', 'credit_date', date('Y-m-d'));
[$page, $per] = pager_state('ledu_cn_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$r = api_get('/credit-notes?limit=' . $limit . '&offset=' . $offset);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$list = $r['data']['creditNotes'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? 0);
$custRes = api_get('/customers?limit=0');
$custList = $custRes['ok'] ? ($custRes['data']['customers'] ?? []) : [];
$vendRes = api_get('/vendors?limit=0');
$vendList = $vendRes['ok'] ? ($vendRes['data']['vendors'] ?? []) : [];
$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$revAccounts = array_values(array_filter($accounts, fn($a) => $a['category'] === 'revenue'));
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e($showNew ? t($editing ? '编辑贷记单草稿' : '开贷记单') : t('贷记单')) ?></h1>
    <div class="page-sub">退货与折让走红字；过账生成红字凭证，原单不动</div>
  </div>
  <div class="page-actions">
    <?php if ($showNew): ?>
      <a class="btn" href="?p=credit-notes">返回列表</a>
    <?php elseif ($role !== 'auditor'): ?>
      <a class="btn primary" href="?p=credit-notes&new=1">＋ 新建贷记单</a>
    <?php endif; ?>
  </div>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>
<?= help_html('credit-notes') ?>

<?php if ($showNew): ?>
<section class="card">
  <div class="card-head">
    <h2><?= e(t($editing ? '编辑贷记单草稿' : '开贷记单')) ?></h2>
    <a class="btn sm" href="?p=credit-notes">返回列表</a>
  </div>
  <form method="post" class="card-body" enctype="multipart/form-data" id="creditForm">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="<?= $editing ? 'credit_update' : 'credit_create' ?>">
    <?php if ($editing): ?><input type="hidden" name="id" value="<?= (int) $editing['credit_id'] ?>"><?php endif; ?>
    <div class="zform">
      <div class="zcol">
        <div class="zsec-h">往来与摘要</div>
        <div class="field">
          <label class="f" for="cType">类型</label>
          <?php $creditType = (string) $value('creditType', 'credit_type', 'customer'); ?>
          <select id="cType" name="creditType">
            <option value="customer" <?= $creditType === 'customer' ? 'selected' : '' ?>>客户贷记（冲减收入与应收）</option>
            <option value="vendor" <?= $creditType === 'vendor' ? 'selected' : '' ?>>供应商贷记（冲减费用与应付）</option>
          </select>
        </div>
        <div class="field">
          <label class="f" for="cParty">往来单位 *</label>
          <?php
          $curParty = (string) $value('partyName', 'party_name');
          $curType = (string) $value('creditType', 'credit_type', 'customer');
          $partyField = $curType === 'vendor' ? 'vendorName' : 'customerName';
          ?>
          <select id="cParty" name="partyName" required data-allow-create="1" data-party-field="<?= e($partyField) ?>">
            <option value="">— 选择 <?= e($curType === 'vendor' ? '供应商' : '客户') ?> —</option>
          </select>
        </div>
        <div class="field">
          <label class="f" for="cSrc">对应原单（可选）</label>
          <?php
          $invR = api_get('/invoices?status=posted&limit=200');
          $billR = api_get('/bills?status=posted&limit=200');
          $invList = $invR['ok'] ? ($invR['data']['invoices'] ?? []) : [];
          $billList = $billR['ok'] ? ($billR['data']['bills'] ?? []) : [];
          $sourceInvoiceId = (int) $value('sourceInvoiceId', 'source_invoice_id', 0);
          $sourceBillId = (int) $value('sourceBillId', 'source_bill_id', 0);
          ?>
          <select id="cSrcInv" name="sourceInvoiceId" style="display:none">
            <option value="">— 不关联发票（独立贷记）—</option>
            <?php foreach ($invList as $iv): ?>
              <option value="<?= (int) $iv['invoice_id'] ?>" <?= $sourceInvoiceId === (int) $iv['invoice_id'] ? 'selected' : '' ?>>
                <?= e((string) $iv['invoice_no'] . ' · ' . (string) $iv['supplier_name']
                      . ' · ' . money($iv['gross_original'], (string) $iv['currency'])) ?>
              </option>
            <?php endforeach; ?>
          </select>
          <select id="cSrcBill" name="sourceBillId" style="display:none">
            <option value="">— 不关联账单（独立贷记）—</option>
            <?php foreach ($billList as $bv): ?>
              <option value="<?= (int) $bv['bill_id'] ?>" <?= $sourceBillId === (int) $bv['bill_id'] ? 'selected' : '' ?>>
                <?= e((string) $bv['bill_no'] . ' · ' . (string) ($bv['vendor_name'] ?? '')
                      . ' · ' . money($bv['gross_original'], (string) $bv['currency'])) ?>
              </option>
            <?php endforeach; ?>
          </select>
          <div class="hint">过账时自动冲减该单的未收/未付余额</div>
        </div>
      </div>

      <div class="zcol zcol-2">
        <div class="zsec-h">单据信息</div>
        <div class="z2">
          <?= $editing
              ? '<div class="field"><label class="f">' . e(t('贷记单编号')) . '</label>'
               . '<input type="text" value="' . e((string) $value('creditNo', 'credit_no')) . '" readonly'
               . ' style="font-family:var(--mono);background:var(--c-surface-alt)"></div>'
              : doc_no_field('贷记单编号', next_doc_no($creditDate, 'credit'), 'creditNo') ?>
          <div class="field">
            <label class="f" for="cDate">日期 *</label>
            <input type="date" id="cDate" name="creditDate" required
                   value="<?= e($creditDate) ?>">
          </div>
          <div class="field">
            <label class="f" for="cCcy">币种</label>
            <select id="cCcy" name="currency"><?= currency_options((string) $value('currency', 'currency', 'HKD')) ?></select>
          </div>
          <div class="field">
            <label class="f" for="cRev">收入科目（客户贷记时用）</label>
            <?php $revenueAccount = (string) $value('revenueAccountCode', 'revenue_account_code'); ?>
            <select id="cRev" name="revenueAccountCode">
              <option value="">按客户默认</option>
              <?php foreach ($revAccounts as $a): ?>
                <option value="<?= e((string) $a['account_code']) ?>" <?= $revenueAccount === (string) $a['account_code'] ? 'selected' : '' ?>>
                  <?= e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) ?>
                </option>
              <?php endforeach; ?>
            </select>
          </div>
        </div>
      </div>
    </div>

    <div class="zfoot">
      <div class="zfoot-left">
        <div class="field">
          <label class="f" for="cReason">原因 / 说明</label>
          <textarea id="cReason" name="reason" rows="3"
                    placeholder="例：服务范围缩减，退还部分费用"><?= e((string) $value('reason', 'reason')) ?></textarea>
        </div>
      </div>
      <div class="zfoot-right">
        <table class="totals">
          <tr><td>金额（不含税）</td>
            <td class="num"><input type="number" step="0.01" min="0.01" id="cAmt" name="amountOriginal" required
                  value="<?= e((string) $value('amountOriginal', 'amount_original')) ?>"
                  style="width:130px;text-align:right"></td></tr>
          <tr><td>税额</td>
            <td class="num"><input type="number" step="0.01" min="0" id="cTax" name="taxOriginal" value="<?= e((string) $value('taxOriginal', 'tax_original', '0')) ?>"
                  style="width:130px;text-align:right"></td></tr>
          <tr class="grand"><td>合计</td>
            <td class="num"><span id="cTotal">0.00</span></td></tr>
        </table>
      </div>
    </div>

    <?= attach_dropzone('attach', '把退货单、折让协议拖到这里', '或点击选择文件 · 保存后自动挂到这张贷记单') ?>

    <div class="pc-box" id="aiPrecheck"></div>

    <div class="card-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
      <a class="btn" href="?p=credit-notes">取消</a>
      <?php if ($editing): ?>
        <button class="btn primary" name="action_flag" value="draft"><?= e(t('保存修改')) ?></button>
      <?php else: ?>
        <button class="btn" name="action_flag" value="post" data-shortcut-post><?= e(t('保存并过账')) ?></button>
        <button class="btn primary" name="action_flag" value="draft" data-shortcut-save><?= e(t('保存草稿')) ?></button>
      <?php endif; ?>
    </div>
  </form>

<script src="assets/precheck.js?v=<?= @filemtime(__DIR__ . '/../assets/precheck.js') ?>"></script>
<script>
(function () {
  var f = document.getElementById('creditForm');
  if (!f || !window.LeduPrecheck) return;
  function v(name) { var el = f.elements[name]; return el ? el.value : ''; }
  function gather() {
    return {creditType: v('creditType'), partyName: v('partyName'), creditDate: v('creditDate'),
            currency: v('currency'), revenueAccountCode: v('revenueAccountCode'),
            amountOriginal: v('amountOriginal'), taxOriginal: v('taxOriginal'),
            reason: v('reason'), sourceInvoiceId: v('sourceInvoiceId'), sourceBillId: v('sourceBillId')};
  }
  window.LeduPrecheck.attach({
    el: '#aiPrecheck', form: f, workflow: 'credit_note', agentLabel: '会计', auto: true, collect: gather,
    ready: function (p) { return p.partyName && parseFloat(p.amountOriginal) > 0; }
  });
})();
</script>

<script>
window._creditCustomers = <?= json_encode(array_map(function ($c) {
    return ['name' => (string) $c['customer_name'], 'code' => (string) ($c['customer_code'] ?? '')];
}, $custList)) ?>;
window._creditVendors = <?= json_encode(array_map(function ($v) {
    return ['name' => (string) $v['vendor_name'], 'code' => (string) ($v['vendor_code'] ?? '')];
}, $vendList)) ?>;
/* 客户贷记 → 选发票 + 客户；供应商贷记 → 选账单 + 供应商 */
(function () {
  var type = document.getElementById('cType');
  var inv = document.getElementById('cSrcInv'), bill = document.getElementById('cSrcBill');
  var party = document.getElementById('cParty');
  if (!type) return;
  function renderPartyOptions(kind, keepVal) {
    var list = kind === 'vendor' ? window._creditVendors : window._creditCustomers;
    var label = kind === 'vendor' ? '供应商' : '客户';
    var opts = '<option value="">— 选择 ' + label + ' —</option>';
    (list || []).forEach(function (p) {
      opts += '<option value="' + p.name + '"' + (keepVal === p.name ? ' selected' : '') + '>'
            + p.name + (p.code ? '（' + p.code + '）' : '') + '</option>';
    });
    if (keepVal) {
      var found = (list || []).some(function (p) { return p.name === keepVal; });
      if (!found) opts += '<option value="' + keepVal + '" selected>' + keepVal + '（未建档）</option>';
    }
    party.innerHTML = opts;
    party.dataset.partyField = kind === 'vendor' ? 'vendorName' : 'customerName';
    /* 重新渲染后原生 select 的增强会被破坏，重新扫描 */
    if (window.enhanceSelects) window.enhanceSelects(party.parentNode);
  }
  var curPartyVal = <?= json_encode($curParty) ?>;
  function sync(clearParty) {
    var vendor = type.value === 'vendor';
    if (inv) inv.style.display = vendor ? 'none' : '';
    if (bill) bill.style.display = vendor ? '' : 'none';
    if (clearParty) {
      curPartyVal = '';   /* 切类型时清空往来单位 —— 客户名在供应商上下文下无意义 */
      party.value = '';
      if (inv) inv.value = '';
      if (bill) bill.value = '';
    }
    renderPartyOptions(type.value, curPartyVal || '');
  }
  type.addEventListener('change', function () { sync(true); }); sync(false);

  if (party) party.addEventListener('ssel:create', function (ev) {
    var panel = document.getElementById('party-create-panel');
    var q = (ev.detail && ev.detail.query) || '';
    var fn = party.dataset.partyField || 'customerName';
    if (panel && q) {
      var nm = panel.querySelector('[data-party-field="' + fn + '"]');
      if (nm) nm.value = q;
    }
  });
})();
</script>
  <script>
  (function () {
    var a = document.getElementById('cAmt'), t = document.getElementById('cTax'),
        o = document.getElementById('cTotal');
    function f() {
      var s = (parseFloat(a.value) || 0) + (parseFloat(t.value) || 0);
      o.textContent = (Math.round(s * 100) / 100).toFixed(2);
    }
    [a, t].forEach(function (e) { e.addEventListener('input', f); });
    f();
  })();
  </script>
<?php if ($role !== 'auditor'): ?>
  <?= inline_party_create_panel('customer') ?>
  <?php if (!empty($partyErr)): ?><div style="margin-top:12px"><?= errbox($partyErr) ?></div><?php endif; ?>
  <script>
  /* 贷记类型切换时同步「新建往来单位」面板的 kind 和标题 */
  (function () {
    var type = document.getElementById('cType');
    if (!type) return;
    function syncPartyPanel() {
      var kind = type.value === 'vendor' ? 'vendor' : 'customer';
      var kindEl = document.getElementById('partyCreateKind');
      var titleEl = document.getElementById('partyCreateTitle');
      var nameLabel = document.querySelector('#partyCreatePanel label[for="newPartyName"]');
      var label = kind === 'vendor' ? '供应商' : '客户';
      if (kindEl) kindEl.value = kind;
      if (titleEl) titleEl.textContent = '＋ 新建' + label;
      if (nameLabel) nameLabel.textContent = label + '名称 *';
    }
    if (type) type.addEventListener('change', syncPartyPanel);
    syncPartyPanel();
  })();
  </script>
<?php endif; ?>
</section>
<?php endif; ?>

<?php if (!$showNew): ?>
<section class="card">
  <div class="list-bar">
    <span class="hint">过账后不可修改；要改只能再开一张反向贷记单</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:200px">贷记号</th><th style="width:90px">类型</th>
        <th>往来单位</th><th style="width:110px">日期</th>
        <th style="width:70px">币种</th>
        <th class="num" style="width:130px">不含税</th>
        <th class="num" style="width:110px">税额</th>
        <th class="num" style="width:130px">合计</th>
        <th style="width:90px">状态</th><th style="width:110px"></th>
      </tr></thead>
      <tbody>
      <?php if (!$list): ?>
        <tr><td colspan="10" style="text-align:center;padding:28px" class="hint">还没有贷记单</td></tr>
      <?php endif; ?>
      <?php foreach ($list as $c): ?>
        <?php
          $isCust = (string) $c['credit_type'] === 'customer';
          $posted = (string) $c['status'] !== 'draft';
        ?>
        <tr>
          <td class="mono"><a href="?p=doc-view&type=credit&id=<?= (int) $c['credit_id'] ?>&back=<?= e(urlencode('?p=credit-notes')) ?>"><?= e((string) $c['credit_no']) ?></a></td>
          <td><span class="tag tag-<?= $isCust ? 'info' : 'warn' ?>"><?= $isCust ? '客户' : '供应商' ?></span></td>
          <td class="truncate" style="max-width:240px"><?= e((string) $c['party_name']) ?></td>
          <td class="hint"><?= e((string) $c['credit_date']) ?></td>
          <td><?= e((string) $c['currency']) ?></td>
          <td class="num"><?= money($c['amount_original'], (string) $c['currency']) ?></td>
          <td class="num"><?= money($c['tax_original'], (string) $c['currency']) ?></td>
          <td class="num"><?= money($c['gross_original'], (string) $c['currency']) ?></td>
          <td><span class="tag tag-<?= $posted ? 'ok' : 'draft' ?>"><?= e(status_label((string) $c['status'])) ?></span></td>
          <td style="text-align:right">
            <?php if ($role === 'auditor'): ?>
              <span class="hint">只读</span>
            <?php elseif ($posted): ?>
              <span class="hint">红字已入账</span>
            <?php else: ?>
              <a class="btn sm" href="?p=credit-notes&amp;edit=<?= (int) $c['credit_id'] ?>">编辑草稿</a>
              <?= draft_delete_form('credit_note', (int) $c['credit_id'], 'credit-notes') ?>
              <form method="post" class="inline-form">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="credit_post">
                <input type="hidden" name="id" value="<?= (int) $c['credit_id'] ?>">
                <button class="btn sm primary"
                  data-confirm="<?= e(t('确认过账这张贷记单？')) ?>"
                  data-confirm-note="<?= e(t('会生成一张红字凭证：客户贷记 借收入 / 贷应收；供应商贷记 借应付 / 贷费用。过账后不可修改，也不能删除，只能再开一张反向贷记单。')) ?>"
                  data-confirm-ok="<?= e(t('确认过账')) ?>">过账</button>
              </form>
            <?php endif; ?>
          </td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <?= pager_html($page, $per, $totalRows, ['p' => 'credit-notes'], 'credit-notes') ?>
</section>
<?php endif; ?>

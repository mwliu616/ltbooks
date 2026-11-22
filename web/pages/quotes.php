<?php
/*
 * LtBooks — pages/quotes.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 报价单：先报后单。报价不能直接进总账，只有转成发票后才走收入确认。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;

$STATUS = [
    'draft' => [status_label('draft'), 'draft'], 'sent' => [status_label('sent'), 'info'],
    'accepted' => ['已接受', 'ok'], 'declined' => ['已拒绝', 'danger'],
    'expired' => ['已失效', 'warn'], 'converted' => ['已转发票', 'ok'],
];

// ---------------------------------------------------------------- 动作
$editId = (int) ($_GET['edit'] ?? 0);
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $action = (string) ($_POST['action'] ?? '');
    $id = (int) ($_POST['id'] ?? 0);

    if (in_array($action, ['quote_create', 'quote_update'], true)) {
        $isUpdate = $action === 'quote_update';
        if ($isUpdate) { $editId = $id; }
        $lines = [];
        foreach ((array) ($_POST['lineDesc'] ?? []) as $i => $desc) {
            $desc = trim((string) $desc);
            if ($desc === '') { continue; }
            $lines[] = [
                'description' => $desc,
                'unit'        => (string) ($_POST['lineUnit'][$i] ?? ''),
                'quantity'    => (string) ($_POST['lineQty'][$i] ?? '1'),
                'unitPrice'   => (string) ($_POST['linePrice'][$i] ?? '0'),
                'discountRate' => (string) ($_POST['lineDisc'][$i] ?? '0'),
                'taxRate'     => (string) ($_POST['lineTax'][$i] ?? ''),
                'notes'       => (string) ($_POST['lineNote'][$i] ?? ''),
            ];
        }
        $res = api_post($isUpdate ? '/quotes/' . $id . '/update' : '/quotes', [
            'quoteNo' => trim((string) ($_POST['quoteNo'] ?? '')),
            'customerName' => trim((string) ($_POST['customerName'] ?? '')),
            'subject' => trim((string) ($_POST['subject'] ?? '')),
            'reference' => trim((string) ($_POST['reference'] ?? '')),
            'salesperson' => trim((string) ($_POST['salesperson'] ?? '')),
            'quoteDate' => (string) ($_POST['quoteDate'] ?? date('Y-m-d')),
            'validUntil' => (string) ($_POST['validUntil'] ?? '') ?: null,
            'currency' => (string) ($_POST['currency'] ?? 'HKD'),
            'lines' => $lines,
            'amountOriginal' => (float) ($_POST['amountOriginal'] ?? 0),
            'taxOriginal' => (float) ($_POST['taxOriginal'] ?? 0),
            'discountOriginal' => (float) ($_POST['discountOriginal'] ?? 0),
            'notes' => (string) ($_POST['notes'] ?? ''),
            'terms' => (string) ($_POST['terms'] ?? ''),
            'actor' => $actor,
        ]);
        if ($res['ok']) {
            $qid = (int) ($res['data']['quoteId'] ?? 0);
            if ($qid > 0 && !empty($_FILES['attach']['name'][0])) {
                doc_files_save('quote', $qid, $_FILES['attach'], $actor);
            }
            header('Location: ?p=quotes&msg=' . urlencode(
                t('报价单') . ' ' . (string) ($res['data']['quoteNo'] ?? '') . ' '
                . t($isUpdate ? '修改已保存' : '已保存为草稿')));
            exit;
        }
        $errMsg = (string) $res['error'];
    } elseif ($action === 'quote_status') {
        $res = api_post('/quotes/' . $id . '/status',
            ['status' => (string) ($_POST['status'] ?? ''), 'actor' => $actor]);
        if ($res['ok']) {
            header('Location: ?p=quotes&msg=' . urlencode(t('报价单状态已更新')));
            exit;
        }
        $errMsg = (string) $res['error'];
    } elseif ($action === 'quote_to_invoice') {
        $res = api_post('/quotes/' . $id . '/to-invoice', ['actor' => $actor]);
        if ($res['ok']) {
            header('Location: ?p=invoice-view&id=' . (int) ($res['data']['invoiceId'] ?? 0)
                 . '&msg=' . urlencode(t('已转成销售发票') . ' ' . (string) ($res['data']['invoiceNo'] ?? '')
                                       . ' ' . t('（草稿，需上传凭证后记账）')));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}

// ---------------------------------------------------------------- 读数据
$view = (string) ($_GET['view'] ?? 'all');
$kw = trim((string) ($_GET['q'] ?? ''));
$formError = $errMsg !== null && in_array((string) ($_POST['action'] ?? ''), ['quote_create', 'quote_update'], true);
$showNew = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $editId > 0 || $formError);
$editing = null;
if ($editId > 0) {
    $editR = api_get('/quotes/' . $editId);
    if (!$editR['ok']) { echo errbox((string) $editR['error']); return; }
    $editing = $editR['data'] ?? [];
    if ((string) ($editing['status'] ?? '') !== 'draft') {
        echo errbox('只有草稿状态的报价单可以编辑'); return;
    }
}
$value = static function (string $key, string $dbKey = '', $default = '') use ($editing) {
    if (array_key_exists($key, $_POST)) { return $_POST[$key]; }
    if ($editing && $dbKey !== '' && array_key_exists($dbKey, $editing)) { return $editing[$dbKey]; }
    return $default;
};
$quoteDate = (string) $value('quoteDate', 'quote_date', date('Y-m-d'));
$formLines = [];
if ($formError && isset($_POST['lineDesc'])) {
    foreach ((array) $_POST['lineDesc'] as $i => $desc) {
        $formLines[] = [
            'description' => (string) $desc,
            'unit' => (string) ($_POST['lineUnit'][$i] ?? ''),
            'quantity' => (string) ($_POST['lineQty'][$i] ?? '1'),
            'unitPrice' => (string) ($_POST['linePrice'][$i] ?? ''),
            'discountRate' => (string) ($_POST['lineDisc'][$i] ?? '0'),
            'taxRate' => (string) ($_POST['lineTax'][$i] ?? ''),
            'amount' => (string) ($_POST['lineAmount'][$i] ?? '0'),
            'taxAmount' => (string) ($_POST['lineTaxAmt'][$i] ?? '0'),
            'notes' => (string) ($_POST['lineNote'][$i] ?? ''),
        ];
    }
} elseif ($editing) {
    foreach ((array) ($editing['lines'] ?? []) as $ln) {
        $base = (float) $ln['quantity'] * (float) $ln['unit_price'];
        $formLines[] = [
            'description' => (string) $ln['description'], 'unit' => (string) ($ln['unit'] ?? ''),
            'quantity' => (string) $ln['quantity'], 'unitPrice' => (string) $ln['unit_price'],
            'discountRate' => $base > 0 ? (string) round((1 - (float) $ln['amount'] / $base) * 100, 4) : '0',
            'taxRate' => (string) ($ln['tax_rate'] ?? ''), 'amount' => (string) $ln['amount'],
            'taxAmount' => (string) $ln['tax_amount'], 'notes' => (string) ($ln['notes'] ?? ''),
        ];
    }
}
if (!$formLines) {
    $formLines[] = ['description' => '', 'unit' => '', 'quantity' => '1', 'unitPrice' => '',
                    'discountRate' => '0', 'taxRate' => '', 'amount' => '0', 'taxAmount' => '0', 'notes' => ''];
}
$overallRate = (string) ($_POST['lnDiscRate'] ?? '');
if ($overallRate === '' && $editing) {
    $beforeDiscount = (float) $editing['amount_original'] + (float) $editing['discount_original'];
    $overallRate = $beforeDiscount > 0
        ? (string) round((float) $editing['discount_original'] / $beforeDiscount * 100, 4) : '0';
}
if ($overallRate === '') { $overallRate = '0'; }
[$page, $per] = pager_state('ledu_quote_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$r = api_get('/quotes?limit=' . $limit . '&offset=' . $offset . '&status=' . urlencode($view)
           . ($kw !== '' ? '&q=' . urlencode($kw) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$list = $r['data']['quotes'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? 0);
$custR = api_get('/customers?limit=0');
$customers = $custR['ok'] ? ($custR['data']['customers'] ?? []) : [];
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e($showNew ? t($editing ? '编辑报价单草稿' : '新建报价单') : t('报价单')) ?></h1>
    <div class="page-sub">报价不进总账；客户接受后转成销售发票才确认收入</div>
  </div>
  <?php if (!$showNew && $role !== 'auditor'): ?>
  <div class="page-actions">
    <a class="btn primary" href="?p=quotes&new=1">＋ 新建报价单</a>
  </div>
  <?php endif; ?>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>
<?= help_html('quotes') ?>

<?php if ($showNew): ?>
<section class="card">
  <div class="card-head">
    <h2><?= e(t($editing ? '编辑报价单草稿' : '新建报价单')) ?></h2>
    <a class="btn sm" href="?p=quotes">返回列表</a>
  </div>
  <form method="post" class="card-body" enctype="multipart/form-data">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="<?= $editing ? 'quote_update' : 'quote_create' ?>">
    <?php if ($editing): ?><input type="hidden" name="id" value="<?= (int) $editing['quote_id'] ?>"><?php endif; ?>

    <div class="zform">
      <div class="zcol">
        <div class="zsec-h">往来与摘要</div>
        <div class="field"><label class="f">客户名称 *</label>
          <?php
          $curCust = (string) $value('customerName', 'customer_name');
          $cOpts = '<option value="">— 选择客户 —</option>';
          foreach ($customers as $c) {
              $cn = (string) $c['customer_name'];
              $cOpts .= '<option value="' . e($cn) . '"' . ($curCust === $cn ? ' selected' : '') . '>'
                       . e($cn . ($c['customer_code'] ? '（' . $c['customer_code'] . '）' : '')) . '</option>';
          }
          if ($curCust !== '') {
              $has = false; foreach ($customers as $c) { if ((string) $c['customer_name'] === $curCust) { $has = true; break; } }
              if (!$has) $cOpts .= '<option value="' . e($curCust) . '" selected>' . e($curCust) . '（未建档）</option>';
          }
          ?>
          <select id="qCust" name="customerName" required data-allow-create="1"><?= $cOpts ?></select>
        </div>
        <div class="field"><label class="f">主题</label>
          <input type="text" name="subject" value="<?= e((string) $value('subject', 'subject')) ?>"
                 placeholder="例：2026 年度系统维护报价">
        </div>
      </div>

      <div class="zcol zcol-2">
        <div class="zsec-h">单据信息</div>
        <div class="z2">
          <?= $editing
              ? '<div class="field"><label class="f">' . e(t('报价单编号')) . '</label>'
               . '<input type="text" value="' . e((string) $value('quoteNo', 'quote_no')) . '" readonly'
               . ' style="font-family:var(--mono);background:var(--c-surface-alt)"></div>'
              : doc_no_field('报价单编号', next_doc_no($quoteDate, 'quote'), 'quoteNo') ?>
          <div class="field"><label class="f">参考号</label>
            <input type="text" name="reference" value="<?= e((string) $value('reference', 'reference')) ?>" placeholder="选填">
          </div>
          <div class="field"><label class="f">报价日期 *</label>
            <input type="date" id="qDate" name="quoteDate" required value="<?= e($quoteDate) ?>">
          </div>
          <div class="field"><label class="f">有效期至</label>
            <input type="date" id="qValid" name="validUntil" value="<?= e((string) $value('validUntil', 'valid_until', date('Y-m-d', strtotime('+30 days')))) ?>">
          </div>
          <div class="field"><label class="f">销售人员</label>
            <input type="text" name="salesperson" value="<?= e((string) $value('salesperson', 'salesperson')) ?>" placeholder="选填">
          </div>
          <div class="field"><label class="f">币种</label>
            <select id="qCcy" name="currency"><?= currency_options((string) $value('currency', 'currency', 'HKD')) ?></select>
          </div>
        </div>
      </div>
    </div>

    <div style="margin-top:18px">
      <div class="table-wrap">
        <table id="lnTable">
          <thead><tr>
            <th style="width:38px" class="num">#</th>
            <th>项目 / 描述</th>
            <th class="num" style="width:84px">数量</th>
            <th class="num" style="width:124px">单价</th>
            <th class="num" style="width:84px">折扣 %</th>
            <th class="num" style="width:84px">税 %</th>
            <th class="num" style="width:130px">金额</th>
            <th style="width:40px"></th>
          </tr></thead>
          <tbody id="lnBody">
            <?php foreach ($formLines as $i => $ln): ?>
            <tr>
              <td class="ln-seq mono hint"><?= $i + 1 ?></td>
              <td>
                <input type="text" class="ln-desc" name="lineDesc[]" value="<?= e((string) $ln['description']) ?>" placeholder="描述这个项目或服务" style="width:100%">
                <input type="hidden" name="lineUnit[]" value="<?= e((string) $ln['unit']) ?>">
                <input type="hidden" name="lineNote[]" value="<?= e((string) $ln['notes']) ?>">
              </td>
              <td><input type="number" class="ln-qty" name="lineQty[]" step="0.0001" min="0" value="<?= e((string) $ln['quantity']) ?>" style="width:100%"></td>
              <td><input type="number" class="ln-price" name="linePrice[]" step="0.01" min="0" value="<?= e((string) $ln['unitPrice']) ?>" style="width:100%"></td>
              <td><input type="number" class="ln-disc" name="lineDisc[]" step="0.01" min="0" max="100" value="<?= e((string) $ln['discountRate']) ?>" style="width:100%"></td>
              <td><input type="number" class="ln-tax" name="lineTax[]" step="0.01" min="0" value="<?= e((string) $ln['taxRate']) ?>" style="width:100%"></td>
              <td class="num mono"><span class="ln-amt"><?= e(number_format((float) $ln['amount'], 2, '.', '')) ?></span>
                <input type="hidden" class="ln-amt-input" name="lineAmount[]" value="<?= e((string) $ln['amount']) ?>">
                <input type="hidden" class="ln-tax-amt-input" name="lineTaxAmt[]" value="<?= e((string) $ln['taxAmount']) ?>">
              </td>
              <td><button type="button" class="btn sm ln-del" title="删除本行">×</button></td>
            </tr>
            <?php endforeach; ?>
          </tbody>
        </table>
      </div>
      <div class="toolbar" style="margin-top:10px">
        <button type="button" class="btn sm" id="lnAdd">＋ 添加一行</button>
        <span class="grow"></span>
        <span class="hint">金额 = 数量 × 单价 ×（1 − 行折扣%）</span>
      </div>
    </div>

    <div class="zfoot">
      <div class="zfoot-left">
        <div class="field"><label class="f">客户备注</label>
          <textarea name="notes" rows="3" placeholder="会印在报价单上"><?= e((string) $value('notes', 'notes')) ?></textarea>
        </div>
        <div class="field"><label class="f">条款与条件</label>
          <textarea name="terms" rows="3" placeholder="付款方式、报价有效期等"><?= e((string) $value('terms', 'terms')) ?></textarea>
        </div>
      </div>
      <div class="zfoot-right">
        <input type="hidden" id="lnAmountInput" name="amountOriginal" value="0">
        <input type="hidden" id="lnTaxInput" name="taxOriginal" value="0">
        <input type="hidden" id="lnDiscountInput" name="discountOriginal" value="0">
        <table class="totals">
          <tr><td>小计</td><td class="num" id="lnSubtotal">0.00</td></tr>
          <tr><td>折扣</td><td class="num" id="lnDiscShow">0.00</td></tr>
          <tr><td>税额</td><td class="num" id="lnTax">0.00</td></tr>
          <tr class="grand"><td>合计</td><td class="num" id="lnTotal">0.00</td></tr>
        </table>
        <div class="hint" style="margin-top:6px">整体折扣率
          <input type="number" step="0.01" min="0" max="100" id="lnDiscRate" name="lnDiscRate" value="<?= e($overallRate) ?>"
                 style="width:70px;display:inline-block"> %
        </div>
      </div>
    </div>

    <?= attach_dropzone('attach', '把客户需求、比价单拖到这里', '或点击选择文件 · 保存后自动挂到这张报价单') ?>

    <div class="card-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
      <a class="btn" href="?p=quotes">取消</a>
      <button class="btn primary" type="submit"><?= e(t($editing ? '保存修改' : '保存报价单')) ?></button>
    </div>
  </form>
</section>

<script>
/* 报价单明细：行金额与整单折扣 */
(function () {
  var body = document.getElementById('lnBody');
  var add = document.getElementById('lnAdd');
  if (!body || !add) return;
  function num(el) { var v = parseFloat(el && el.value); return isFinite(v) ? v : 0; }
  function fmt(n) { return (Math.round(n * 100) / 100).toFixed(2); }
  function sync(tr) {
    var q = num(tr.querySelector('.ln-qty')), p = num(tr.querySelector('.ln-price'));
    var d = Math.min(Math.max(num(tr.querySelector('.ln-disc')), 0), 100);
    var r = num(tr.querySelector('.ln-tax'));
    var a = q * p * (1 - d / 100);
    var t = a * r / 100;
    tr.querySelector('.ln-amt').textContent = fmt(a);
    tr.querySelector('.ln-amt-input').value = fmt(a);
    tr.querySelector('.ln-tax-amt-input').value = fmt(t);
    return { a: a, t: t };
  }
  function calc() {
    var sub = 0, tax = 0;
    body.querySelectorAll('tr').forEach(function (tr) { var v = sync(tr); sub += v.a; tax += v.t; });
    var rate = Math.min(Math.max(num(document.getElementById('lnDiscRate')), 0), 100);
    var disc = sub * rate / 100, net = sub - disc;
    var netTax = sub ? tax * (net / sub) : 0;
    document.getElementById('lnSubtotal').textContent = fmt(sub);
    document.getElementById('lnDiscShow').textContent = fmt(disc);
    document.getElementById('lnTax').textContent = fmt(netTax);
    document.getElementById('lnTotal').textContent = fmt(net + netTax);
    document.getElementById('lnAmountInput').value = fmt(net);
    document.getElementById('lnTaxInput').value = fmt(netTax);
    document.getElementById('lnDiscountInput').value = fmt(disc);
  }
  function bind(tr) {
    ['ln-qty','ln-price','ln-disc','ln-tax'].forEach(function (c) {
      var el = tr.querySelector('.' + c); if (el) el.addEventListener('input', calc);
    });
    tr.querySelector('.ln-del').addEventListener('click', function () {
      if (body.querySelectorAll('tr').length > 1) { tr.remove(); }
      else { tr.querySelectorAll('input').forEach(function (i) { i.value = i.classList.contains('ln-qty') ? '1' : ''; }); }
      calc();
    });
  }
  body.querySelectorAll('tr').forEach(bind);
  add.addEventListener('click', function () {
    var tr = body.querySelector('tr').cloneNode(true);
    tr.querySelectorAll('input').forEach(function (i) {
      i.value = i.classList.contains('ln-qty') ? '1' : (i.classList.contains('ln-disc') ? '0' : '');
    });
    body.appendChild(tr); bind(tr); calc();
  });
  var rr = document.getElementById('lnDiscRate');
  if (rr) rr.addEventListener('input', calc);
  calc();
})();
</script>

<?php /*
/**/ ?><script src="assets/lines.js?v=<?= @filemtime(__DIR__ . '/../assets/lines.js') ?>"></script>
<?php if ($role !== 'auditor'): ?>
  <?= inline_party_create_panel('customer') ?>
  <script>
  (function () {
    var sel = document.getElementById('qCust');
    if (!sel) return;
    sel.addEventListener('ssel:create', function (ev) {
      var panel = document.getElementById('party-create-panel');
      var q = (ev.detail && ev.detail.query) || '';
      if (panel && q) {
        var nm = panel.querySelector('[data-party-field="customerName"]');
        if (nm) nm.value = q;
      }
    });
  })();
  </script>
<?php endif; ?>
<?php endif; ?>

<?php if (!$showNew): ?>
<section class="card">
  <form method="get" class="list-bar">
    <input type="hidden" name="p" value="quotes">
    <select name="view" onchange="this.form.submit()">
      <?php foreach (['all' => t('全部报价单'), 'draft' => '草稿', 'sent' => '已发出',
                      'accepted' => '已接受', 'converted' => '已转发票'] as $k => $lab): ?>
        <option value="<?= e($k) ?>"<?= $view === $k ? ' selected' : '' ?>><?= e($lab) ?></option>
      <?php endforeach; ?>
    </select>
    <input type="text" name="q" value="<?= e($kw) ?>" placeholder="搜索报价号 / 客户 / 主题 / 参考号" style="width:260px">
    <button class="btn sm">搜索</button>
    <?php if ($kw !== ''): ?><a class="btn sm" href="?p=quotes">清除</a><?php endif; ?>
  </form>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:200px">报价号</th><th>客户</th>
        <th style="width:110px">报价日期</th><th style="width:110px">有效期至</th>
        <th style="width:70px">币种</th><th class="num" style="width:140px">合计</th>
        <th style="width:100px">状态</th><th style="width:230px"></th>
      </tr></thead>
      <tbody>
      <?php if (!$list): ?>
        <tr><td colspan="8" style="text-align:center;padding:28px" class="hint">没有符合条件的报价单</td></tr>
      <?php endif; ?>
      <?php foreach ($list as $q): ?>
        <?php [$lab, $cls] = $STATUS[(string) $q['status']] ?? [(string) $q['status'], 'draft']; ?>
        <tr>
          <td class="mono"><a href="?p=doc-view&type=quote&id=<?= (int) $q['quote_id'] ?>&back=<?= e(urlencode('?p=quotes')) ?>"><?= e((string) $q['quote_no']) ?></a></td>
          <td class="truncate" style="max-width:280px"><?= e((string) $q['customer_name']) ?></td>
          <td class="hint"><?= e((string) $q['quote_date']) ?></td>
          <td class="hint"><?= e((string) ($q['valid_until'] ?? '—')) ?></td>
          <td><?= e((string) $q['currency']) ?></td>
          <td class="num"><?= money($q['gross_original'], (string) $q['currency']) ?></td>
          <td><span class="tag tag-<?= e($cls) ?>"><?= e($lab) ?></span></td>
          <td style="text-align:right;white-space:nowrap">
            <?php if ($role === 'auditor'): ?>
              <span class="hint">只读</span>
            <?php elseif ((string) $q['status'] === 'draft'): ?>
              <a class="btn sm" href="?p=quotes&amp;edit=<?= (int) $q['quote_id'] ?>">编辑草稿</a>
              <?= draft_delete_form('quote', (int) $q['quote_id'], 'quotes') ?>
              <form method="post" class="inline-form">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="quote_status">
                <input type="hidden" name="id" value="<?= (int) $q['quote_id'] ?>">
                <input type="hidden" name="status" value="sent">
                <button class="btn sm">标记已发出</button>
              </form>
            <?php elseif ((string) $q['status'] === 'sent'): ?>
              <form method="post" class="inline-form">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="quote_status">
                <input type="hidden" name="id" value="<?= (int) $q['quote_id'] ?>">
                <input type="hidden" name="status" value="accepted">
                <button class="btn sm">客户已接受</button>
              </form>
              <form method="post" class="inline-form">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="quote_status">
                <input type="hidden" name="id" value="<?= (int) $q['quote_id'] ?>">
                <input type="hidden" name="status" value="declined">
                <button class="btn sm">被拒绝</button>
              </form>
            <?php elseif ((string) $q['status'] === 'accepted' && empty($q['converted_invoice_id'])): ?>
              <form method="post" class="inline-form">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="quote_to_invoice">
                <input type="hidden" name="id" value="<?= (int) $q['quote_id'] ?>">
                <button class="btn sm primary"
                  data-confirm="<?= e(t('确认转成销售发票？')) ?>"
                  data-confirm-note="<?= e(t('会按报价单明细生成一张销售发票草稿，报价单标记为「已转发票」。发票仍需上传原始凭证、复核、记账后才进总账。')) ?>"
                  data-confirm-ok="<?= e(t('确认转发票')) ?>">转发票</button>
              </form>
            <?php elseif (!empty($q['converted_invoice_id'])): ?>
              <a class="btn sm" href="?p=invoice-view&id=<?= (int) $q['converted_invoice_id'] ?>">查看发票</a>
            <?php else: ?>
              <span class="hint">—</span>
            <?php endif; ?>
          </td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <?= pager_html($page, $per, $totalRows,
        ['p' => 'quotes', 'view' => $view !== 'all' ? $view : null,
         'q' => $kw !== '' ? $kw : null], 'quotes') ?>
</section>
<?php endif; ?>

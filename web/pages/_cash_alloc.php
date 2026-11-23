<?php
/*
 * LtBooks — pages/_cash_alloc.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;
// 收款核销与付款核销是两个独立入口：由页面固定方向，不再用标签页切换
$fixedDir = $pageDirection ?? null;                 // 'received' | 'made'
$direction = $fixedDir ?: (string) ($_POST['direction'] ?? $_GET['direction'] ?? 'made');
if (!in_array($direction, ['received', 'made'], true)) { $direction = 'made'; }
$isCashIn  = $direction === 'received';
$dirLabel  = $isCashIn ? '收款核销' : '付款核销';
$listPage  = $isCashIn ? 'receipts' : 'payments';
$editId    = (int) ($_POST['edit'] ?? $_GET['edit'] ?? 0);
$editing   = null;

// 历史草稿从详情接口回填；更新接口仍会在事务中锁定并复查草稿状态。
if ($editId > 0 && $role !== 'auditor') {
    $editR = api_get('/payments/' . $direction . '/' . $editId);
    if (!$editR['ok']) { echo errbox((string) $editR['error']); return; }
    $editing = $editR['data'] ?? [];
    if ((string) ($editing['status'] ?? '') !== 'draft') {
        echo errbox('只有草稿状态的收付款单可以编辑'); return;
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'create_payment') {
    $allocs = [];
    foreach ((array) ($_POST['alloc'] ?? []) as $docId => $amt) {
        $v = (float) $amt;
        if ($v > 0) { $allocs[] = ['docId' => (int) $docId, 'amount' => $v]; }
    }
    $payload = [
        'direction' => $direction,
        'date' => (string) ($_POST['date'] ?? date('Y-m-d')),
        'amount' => (float) ($_POST['amount'] ?? 0),
        'currency' => (string) ($_POST['currency'] ?? 'HKD'),
        'bankAccountId' => (int) ($_POST['bankAccountId'] ?? 0),
        'amountOverride' => !empty($_POST['amountOverride']),
        'customerId' => (int) ($_POST['customerId'] ?? 0) ?: null,
        'vendorId' => (int) ($_POST['vendorId'] ?? 0) ?: null,
        'allocations' => $allocs,
        'actor' => (string) ($user['username'] ?? 'system'),
    ];
    $r = api_post($editing ? '/payments/' . $direction . '/' . $editId . '/update' : '/payments', $payload);
    if ($r['ok']) {
        $d = $r['data'];
        if ($editing) {
            header('Location: ?p=' . $listPage . '&msg=' . urlencode(
                '草稿已保存：' . $d['paymentNo'] . '，未执行过账'));
            exit;
        }
        $msg = '已登记 ' . $d['paymentNo'] . '：' . money($d['amount'], $d['currency'])
             . '，核销 ' . count($allocs) . ' 张，汇兑差额 ' . money($d['fxDifference'], 'HKD');
    } else {
        $errMsg = (string) $r['error'];
    }
}
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

// 记录表：无前缀（page / per / q）
[$page, $per] = pager_state($isCashIn ? 'ledu_rct_per' : 'ledu_pmt_per', 25);
// 待核销表：opage / oper / oq，与记录表互不干扰
[$oPage, $oPer] = pager_state($isCashIn ? 'ledu_open_recv_per' : 'ledu_open_paid_per', 25, 500, 'o');
$kw    = trim((string) ($_GET['q'] ?? ''));
$oKw   = trim((string) ($_GET['oq'] ?? ''));

$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$payR = api_get('/payments?limit=' . $limit . '&offset=' . $offset
              . ($kw !== '' ? '&q=' . urlencode($kw) : ''));
$pay = $payR['ok'] ? $payR['data'] : ['received' => [], 'made' => []];

$oLimit  = $oPer === 0 ? 0 : $oPer;
$oOffset = $oPer === 0 ? 0 : ($oPage - 1) * $oPer;
$docsR = api_get('/payments/open-docs?direction=' . urlencode($direction)
               . '&limit=' . $oLimit . '&offset=' . $oOffset
               . ($oKw !== '' ? '&q=' . urlencode($oKw) : ''));
$docs = $docsR['ok'] ? ($docsR['data']['docs'] ?? []) : [];
$oTotal = (int) ($docsR['data']['total'] ?? count($docs));
$oPageCount = $oPer === 0 ? 1 : max(1, (int) ceil($oTotal / max(1, $oPer)));
if ($oPage > $oPageCount) { $oPage = $oPageCount; }
$accR = api_get('/bank-accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$custR = api_get('/customers');
$customers = $custR['ok'] ? ($custR['data']['customers'] ?? []) : [];
$vendR = api_get('/vendors');
$vendors = $vendR['ok'] ? ($vendR['data']['vendors'] ?? []) : [];

$formDate = (string) ($_POST['date'] ?? ($editing['date'] ?? date('Y-m-d')));
$formAmount = (string) ($_POST['amount'] ?? ($editing['amount'] ?? ''));
$formCurrency = (string) ($_POST['currency'] ?? ($editing['currency'] ?? base_currency()));
$formBankId = (int) ($_POST['bankAccountId'] ?? ($editing['bankAccountId'] ?? 0));
$formPartyId = (int) ($_POST[$isCashIn ? 'customerId' : 'vendorId'] ?? ($editing['partyId'] ?? 0));
$allocValues = [];
if (array_key_exists('alloc', $_POST)) {
    foreach ((array) $_POST['alloc'] as $docId => $amt) { $allocValues[(int) $docId] = (string) $amt; }
} elseif ($editing) {
    foreach (($editing['documents'] ?? []) as $doc) {
        $allocValues[(int) $doc['docId']] = (string) $doc['settledOriginal'];
    }
}
// 已保存/已提交的金额大于核销合计时（多付或预付），保留手工金额开关。
$allocSum = 0.0;
foreach ($allocValues as $v) { $allocSum += (float) $v; }
$amountOverridden = (float) $formAmount > $allocSum + 0.004;

// 草稿已引用的单据即使已不在“未结”分页结果中，也必须保留在编辑表单里。
if ($editing) {
    $docIndexes = [];
    foreach ($docs as $i => $doc) { $docIndexes[(int) $doc['docId']] = $i; }
    foreach (($editing['documents'] ?? []) as $allocated) {
        $docId = (int) $allocated['docId'];
        if (isset($docIndexes[$docId])) {
            $i = $docIndexes[$docId];
            // 草稿核销不写回账单已核销额，未结额本身已含这张草稿，不能再加回自己。
            if (empty($docs[$i]['party'])) { $docs[$i]['party'] = $editing['party'] ?? ''; }
            continue;
        }
        $docs[] = [
            'docId' => $docId,
            'docNo' => $allocated['docNo'],
            'docDate' => $allocated['docDate'],
            'party' => $editing['party'] ?? '',
            'currency' => $allocated['currency'],
            'outstanding' => (float) $allocated['documentTotal']
                           - (float) $allocated['documentSettled'],
        ];
        $oTotal++;
    }
}

// 方向切换（固定方向时不需要）
if (!$fixedDir) {
    echo '<div class="tabs" style="margin-bottom:var(--s-4)">'
        . '<a class="tab' . ($isCashIn ? ' active' : '') . '" href="?p=payments&direction=received">'
        . e(t('收款')) . '</a>'
        . '<a class="tab' . (!$isCashIn ? ' active' : '') . '" href="?p=payments&direction=made">'
        . e(t('付款')) . '</a>'
        . '</div>';
}
?>
<?php ob_start(); ?>
<?php if ($role === 'auditor'): ?>
  <?= empty_state('审计角色不可录入收付款') ?>
<?php else: ?>
<form method="post" id="paymentForm">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="create_payment">
  <input type="hidden" name="direction" value="<?= e($direction) ?>">
  <?php if ($editing): ?><input type="hidden" name="edit" value="<?= $editId ?>"><?php endif; ?>
  <div class="grid">
    <?= $editing
        ? doc_no_field($isCashIn ? '收款编号' : '付款编号', (string) $editing['paymentNo'])
        : doc_no_field($isCashIn ? '收款编号（自动）' : '付款编号（自动）',
                       next_doc_no($formDate, $isCashIn ? 'receipt' : 'payment')) ?>
    <div class="field"><label class="f">日期</label><input type="date" name="date" value="<?= e($formDate) ?>" required></div>
    <div class="field"><label class="f">金额</label><input type="number" step="0.01" min="0" name="amount" id="payAmount" value="<?= e($formAmount) ?>" required title="金额由下方核销额自动合计">
      <label class="hint" style="display:flex;align-items:center;gap:6px;margin-top:4px;cursor:pointer">
        <input type="checkbox" id="amountOverride" name="amountOverride" value="1"<?= $amountOverridden ? ' checked' : '' ?>> 多付 / 预付（金额可大于核销合计）
      </label></div>
    <div class="field"><label class="f">币种</label>
      <select name="currency" id="payCurrency"><?= currency_options($formCurrency) ?></select></div>
    <div class="field"><label class="f">银行账户</label>
      <select name="bankAccountId" required>
        <?php foreach ($accounts as $a): ?>
          <option value="<?= (int) $a['account_id'] ?>"<?= $formBankId === (int) $a['account_id'] ? ' selected' : '' ?>><?= e((string) $a['currency']) ?> · <?= e((string) $a['name']) ?></option>
        <?php endforeach; ?>
      </select></div>
    <?php if ($direction === 'received'): ?>
      <div class="field"><label class="f">客户</label>
        <select name="customerId"><option value="0">—</option>
          <?php foreach ($customers as $c): ?>
            <option value="<?= (int) $c['customer_id'] ?>"<?= $formPartyId === (int) $c['customer_id'] ? ' selected' : '' ?>><?= e((string) $c['customer_name']) ?></option>
          <?php endforeach; ?>
        </select></div>
    <?php else: ?>
      <div class="field"><label class="f">供应商</label>
        <select name="vendorId"><option value="0">—</option>
          <?php foreach ($vendors as $v): ?>
            <option value="<?= (int) $v['vendor_id'] ?>"<?= $formPartyId === (int) $v['vendor_id'] ? ' selected' : '' ?>><?= e((string) $v['vendor_name']) ?></option>
          <?php endforeach; ?>
        </select></div>
    <?php endif; ?>
  </div>

  <div style="margin-top:14px">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
      <b>核销单据</b>
      <?php if ($docs): ?>
        <?= pager_html($oPage, $oPer, $oTotal,
              ['p' => $listPage, 'q' => $kw ?: null, 'edit' => $editId ?: null], '', 'o') ?>
      <?php endif; ?>
    </div>
    <div class="toolbar" style="margin-top:8px;margin-bottom:0">
      <input type="hidden" name="p" value="<?= e($listPage) ?>" form="openDocsSearch">
      <?php if ($editId): ?><input type="hidden" name="edit" value="<?= $editId ?>" form="openDocsSearch"><?php endif; ?>
      <?php if ($kw !== ''): ?><input type="hidden" name="q" value="<?= e($kw) ?>" form="openDocsSearch"><?php endif; ?>
      <input type="text" name="oq" value="<?= e($oKw) ?>" placeholder="<?= e(t('搜索待核销单据号 / 往来单位')) ?>" style="width:320px" form="openDocsSearch">
      <button class="btn sm" form="openDocsSearch">搜索</button>
      <?php if ($oKw !== ''): ?><a class="btn sm" href="?p=<?= e($listPage) ?><?= $editId ? '&amp;edit=' . $editId : '' ?>">清除</a><?php endif; ?>
      <span class="hint"><?= e(str_replace('{n}', (string) num($oTotal), t('共 {n} 张未结'))) ?></span>
    </div>
    <?php if (!$docs): ?>
      <div class="hint" style="margin-top:6px">没有未结单据。</div>
    <?php else: ?>
      <div class="table-wrap" style="margin-top:6px"><table>
      <thead><tr><th style="width:36px"></th><th>单据</th><th><?= $isCashIn ? '客户' : '供应商' ?></th><th>日期</th>
      <th>币种</th><th class="num">未结金额</th><th>本方核销额</th><th style="width:72px"></th></tr></thead>
      <tbody>
      <?php foreach ($docs as $d): ?>
        <tr data-doc-ccy="<?= e((string) $d['currency']) ?>">
        <td><input type="checkbox" class="alloc-pick" aria-label="核销 <?= e((string) $d['docNo']) ?>"<?= (float) ($allocValues[(int) $d['docId']] ?? 0) > 0 ? ' checked' : '' ?>></td>
        <td class="mono"><?= e((string) $d['docNo']) ?></td>
        <td><?= e((string) ($d['party'] ?: '—')) ?></td>
        <td><?= e((string) $d['docDate']) ?></td>
        <td><?= e((string) $d['currency']) ?></td>
        <td class="num"><?= money($d['outstanding'], (string) $d['currency']) ?></td>
        <td><input type="number" step="0.01" min="0" max="<?= e((string) $d['outstanding']) ?>"
             name="alloc[<?= (int) $d['docId'] ?>]" value="<?= e($allocValues[(int) $d['docId']] ?? '0') ?>"
             class="alloc-amt" data-outstanding="<?= e((string) $d['outstanding']) ?>" style="width:140px"></td>
        <td><a class="btn sm doc-peek" href="#"
              data-type="<?= $isCashIn ? 'invoice' : 'bill' ?>"
              data-id="<?= (int) $d['docId'] ?>">查看</a></td></tr>
      <?php endforeach; ?>
      </tbody></table></div>
      <div class="hint" style="margin-top:6px">勾选要核销的单据，核销额默认等于未结余额（可改）；金额按核销额自动合计。跨币种时按结算日汇率计算汇兑差额并计入损益。</div>
      <div class="hint" id="amountCrossHint" style="margin-top:6px;display:none;color:var(--c-warn,#a15c00)">含其他币种的单据：请按结算日汇率手工填写上方<?= $isCashIn ? '收款' : '付款' ?>金额。</div>
    <?php endif; ?>
  </div>

  <div class="pc-box" id="aiPrecheck"></div>

  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <?php if ($editing): ?><a class="btn" href="?p=<?= e($listPage) ?>">取消</a><?php endif; ?>
    <button class="btn primary" <?= !$editing && !$docs ? 'disabled' : '' ?> data-shortcut-save><?= $editing ? '保存草稿' : '登记并核销' ?></button>
  </div>
</form>
<script src="assets/precheck.js?v=<?= @filemtime(__DIR__ . '/../assets/precheck.js') ?>"></script>
<script>
(function () {
  var f = document.getElementById('paymentForm');
  if (!f || !window.LeduPrecheck) return;
  function v(name) { var el = f.elements[name]; return el ? el.value : ''; }
  function selText(el) {
    return el && el.selectedIndex >= 0 ? String(el.options[el.selectedIndex].text || '').trim() : '';
  }
  function gather() {
    var bank = f.querySelector('select[name="bankAccountId"]');
    var party = f.querySelector('select[name="vendorId"]') || f.querySelector('select[name="customerId"]');
    var allocs = [];
    f.querySelectorAll('input[name^="alloc["]').forEach(function (el) {
      var amt = parseFloat(el.value);
      if (isFinite(amt) && amt > 0) {
        var m = el.name.match(/\[(\d+)\]/);
        allocs.push({docId: m ? parseInt(m[1], 10) : 0, amount: amt});
      }
    });
    var out = {date: v('date'), amount: v('amount'), currency: v('currency'),
               bankAccountId: bank ? bank.value : '', bankName: selText(bank),
               allocations: allocs};
    if (party && party.name === 'vendorId') { out.vendorId = party.value; out.vendorName = selText(party); }
    if (party && party.name === 'customerId') { out.customerId = party.value; out.customerName = selText(party); }
    return out;
  }
  window.LeduPrecheck.attach({
    el: '#aiPrecheck', form: f,
    workflow: <?= json_encode($isCashIn ? 'receipt' : 'payment') ?>,
    agentLabel: '出纳', auto: true, collect: gather,
    ready: function (p) { return parseFloat(p.amount) > 0 && p.bankAccountId; }
  });
})();
</script>
<!-- 待核销单据搜索：独立表单，用 form 属性挂接，避免与外层登记表单嵌套 -->
<form id="openDocsSearch" method="get"></form>
<?php endif; ?>
<?php echo card($editing ? ($isCashIn ? '编辑收款草稿' : '编辑付款草稿') : ($isCashIn ? '登记收款' : '登记付款'), ob_get_clean()); ?>

<?php
$recordSets = $fixedDir
    ? [[$direction, $dirLabel . '记录']]
    : [['received', '收款记录'], ['made', '付款记录']];
foreach ($recordSets as [$k, $lab]) {
    $rows = $pay[$k] ?? [];
    ob_start();
    ?>
    <form method="get" class="toolbar" style="margin-bottom:10px">
      <input type="hidden" name="p" value="<?= e($listPage) ?>">
      <?php if ($editId): ?><input type="hidden" name="edit" value="<?= $editId ?>"><?php endif; ?>
      <?php if ($oKw !== ''): ?><input type="hidden" name="oq" value="<?= e($oKw) ?>"><?php endif; ?>
      <input type="text" name="q" value="<?= e($kw) ?>" placeholder="搜索单号 / <?= $isCashIn ? '客户' : '供应商' ?> / 核销单据号" style="width:320px">
      <button class="btn">搜索</button>
      <?php if ($kw !== ''): ?><a class="btn" href="?p=<?= $isCashIn ? 'receipts' : 'payments' ?>">清除</a><?php endif; ?>
    </form>
    <?php
    if (!$rows) { echo empty_state('暂无记录'); } else { ?>
      <div class="table-wrap"><table>
      <thead><tr><th>编号</th><th><?= $isCashIn ? '客户' : '供应商' ?></th><th>核销单据</th>
      <th>日期</th><th>币种</th><th class="num">金额</th><th class="num">折 HKD</th>
      <th class="num">汇兑差额</th><th>状态</th><th style="width:230px"></th></tr></thead>
      <tbody>
      <?php foreach ($rows as $x): ?>
        <tr><td class="mono"><a href="?p=payment-view&kind=<?= e($k) ?>&id=<?= (int) $x['payment_id'] ?>"><?= e((string) $x['payment_no']) ?></a></td>
        <td><?= e((string) ($x['party'] ?? '—')) ?></td>
        <td class="mono" style="font-size:var(--f-xs)">
          <?php $n = (int) ($x['doc_count'] ?? 0);
                $nos = (string) ($x['doc_nos'] ?? '');
                $first = $nos !== '' ? explode(', ', $nos)[0] : ''; ?>
          <?php if ($n === 0): ?>
            <span class="hint">未核销</span>
          <?php elseif ($n === 1): ?>
            <?= e($first) ?>
          <?php else: ?>
            <?= e($first) ?><div class="hint">另 <?= $n - 1 ?> 张</div>
          <?php endif; ?>
        </td>
        <td><?= e((string) $x['date']) ?></td>
        <td><?= e((string) $x['currency']) ?></td>
        <td class="num"><?= money($x['amount'], (string) $x['currency']) ?></td>
        <td class="num"><?= money($x['amount_functional'], 'HKD') ?></td>
        <td class="num"><?= money($x['settlement_fx_diff']) ?></td>
        <td><?= status_pill((string) $x['status']) ?></td>
        <td style="white-space:nowrap"><a class="btn sm pay-peek" href="#"
              data-kind="<?= e($k) ?>" data-id="<?= (int) $x['payment_id'] ?>">查看</a>
          <?php if ($role !== 'auditor' && (string) $x['status'] === 'draft'): ?>
            <a class="btn sm" href="?p=<?= e($listPage) ?>&amp;edit=<?= (int) $x['payment_id'] ?>">编辑</a>
            <?= draft_delete_form($k === 'received' ? 'payment_received' : 'payment_made',
                                  (int) $x['payment_id'], $listPage) ?>
          <?php endif; ?>
        </td></tr>
      <?php endforeach; ?>
      </tbody></table></div>
    <?php }
    $tot = $k === 'received' ? (int) ($payR['data']['totalReceived'] ?? count($rows))
                             : (int) ($payR['data']['totalMade'] ?? count($rows));
    echo card($lab, ob_get_clean(),
        pager_html($page, $per, $tot,
            ['p' => $listPage, 'q' => $kw ?: null, 'oq' => $oKw ?: null,
             'edit' => $editId ?: null], '', ''), false);
}
?>

<!-- 核销浮窗：点单据号或「查看」时弹出，不离开当前页 -->
<div id="peekMask" style="display:none;position:fixed;inset:0;background:rgba(15,23,42,.45);
     z-index:9998" onclick="if(event.target===this)closePeek()"></div>
<div id="peekWin" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
     width:min(760px,92vw);max-height:86vh;overflow:auto;background:var(--c-surface);border-radius:12px;
     box-shadow:0 24px 70px rgba(0,0,0,.35);z-index:9999">
  <div style="display:flex;align-items:center;justify-content:space-between;
       padding:14px 18px;border-bottom:1px solid var(--c-border);position:sticky;top:0;background:var(--c-surface)">
    <b id="peekTitle" style="font-weight:400;font-size:var(--f-md)">详情</b>
    <button type="button" class="btn sm" onclick="closePeek()">关闭</button>
  </div>
  <div id="peekBody" style="padding:16px 18px"></div>
</div>

<script>
function closePeek() {
  document.getElementById('peekMask').style.display = 'none';
  document.getElementById('peekWin').style.display = 'none';
}
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closePeek(); });

function peekShow(title, html) {
  document.getElementById('peekTitle').textContent = title;
  document.getElementById('peekBody').innerHTML = html;
  document.getElementById('peekMask').style.display = '';
  document.getElementById('peekWin').style.display = '';
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];
  });
}
function money(v, c) {
  if (v === null || v === undefined || v === '') return '—';
  return Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})
         + (c ? ' ' + c : '');
}
function rows(items) {
  return '<div class="dl">' + items.filter(Boolean).map(function (it) {
    return '<dt>' + esc(it[0]) + '</dt><dd>' + it[1] + '</dd>';
  }).join('') + '</div>';
}

function loadPayment(kind, id) {
  fetch('pay-json.php?type=payment&kind=' + encodeURIComponent(kind) + '&id=' + id)
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (!res.ok) { peekShow('查询失败', '<div class="errbox">' + esc(res.error) + '</div>'); return; }
      var d = res.data;
      var head = rows([
        ['编号', '<span class="mono">' + esc(d.paymentNo) + '</span>'],
        ['日期', esc(d.date)],
        [kind === 'received' ? '客户' : '供应商', esc(d.party || '—')],
        ['金额', '<b>' + money(d.amount, d.currency) + '</b>'],
        ['折 HKD', money(d.amountFunctional, 'HKD')],
        ['汇率', esc(d.fxRate) + (d.fxRateDate ? ' （' + esc(d.fxRateDate) + '）' : '')],
        ['汇兑差额', money(d.settlementFxDiff, 'HKD')],
        ['银行账户', d.bank ? esc(d.bank.name) + ' · ' + esc(d.bank.account) : '—'],
        ['会计分录', d.entry ? esc(d.entry.entryNo) : '—'],
        ['录入', esc(d.createdBy || '—') + ' · ' + esc(d.createdAt)],
      ]);
      var list = '';
      if ((d.documents || []).length) {
        list = '<div style="margin-top:16px"><b style="font-weight:400;font-size:var(--f-sm)">核销明细</b>'
          + '<div class="table-wrap" style="margin-top:8px"><table style="min-width:0">'
          + '<thead><tr><th>单据号</th><th>日期</th><th class="num">单据金额</th>'
          + '<th class="num">本次核销</th><th class="num">累计已核销</th><th class="num">汇兑差额</th></tr></thead><tbody>'
          + d.documents.map(function (x) {
              return '<tr><td class="mono">' + esc(x.docNo) + '</td><td>' + esc(x.docDate) + '</td>'
                + '<td class="num">' + money(x.documentTotal, x.currency) + '</td>'
                + '<td class="num"><b>' + money(x.settledOriginal, x.currency) + '</b></td>'
                + '<td class="num">' + money(x.documentSettled, x.currency) + '</td>'
                + '<td class="num">' + money(x.fxDiff, 'HKD') + '</td></tr>';
            }).join('')
          + '</tbody></table></div></div>';
      }
      peekShow(kind === 'received' ? '收款单详情' : '付款单详情', head + list);
    })
    .catch(function (e) { peekShow('查询失败', '<div class="errbox">' + esc(e) + '</div>'); });
}

function loadDoc(type, id) {
  fetch('pay-json.php?type=' + encodeURIComponent(type) + '&id=' + id)
    .then(function (r) { return r.json(); })
    .then(function (res) {
      if (!res.ok) { peekShow('查询失败', '<div class="errbox">' + esc(res.error) + '</div>'); return; }
      var d = res.data;
      var isInv = type === 'invoice';
      var gross = isInv ? d.gross_original : d.gross_original;
      var settled = d.settled_original;
      var ccy = d.currency;
      var out = (gross || 0) - (settled || 0);
      var head = rows([
        [isInv ? '发票号' : '账单号', '<span class="mono">' + esc(isInv ? d.invoice_no : d.bill_no) + '</span>'],
        ['日期', esc(isInv ? d.invoice_date : d.date)],
        [isInv ? '客户' : '供应商', esc(isInv ? d.supplier_name : d.vendor_name)],
        ['币种', esc(ccy)],
        ['不含税', money(isInv ? d.amount_original : d.amount, ccy)],
        ['税额', money(isInv ? d.tax_original : d.tax_amount, ccy)],
        ['价税合计', '<b>' + money(gross, ccy) + '</b>'],
        ['已核销', money(settled, ccy)],
        ['未结', '<b>' + money(out, ccy) + '</b>'],
        ['状态', esc(d.status)],
      ]);
      peekShow(isInv ? '发票详情' : '账单详情', head);
    })
    .catch(function (e) { peekShow('查询失败', '<div class="errbox">' + esc(e) + '</div>'); });
}

document.querySelectorAll('.pay-peek').forEach(function (a) {
  a.addEventListener('click', function (e) {
    e.preventDefault();
    loadPayment(a.dataset.kind, a.dataset.id);
  });
});
document.querySelectorAll('.doc-peek').forEach(function (a) {
  a.addEventListener('click', function (e) {
    e.preventDefault();
    loadDoc(a.dataset.type, a.dataset.id);
  });
});

// 金额默认按核销额自动合计；勾选「多付/预付」或含跨币种单据时才手工填写。
(function () {
  var amount = document.getElementById('payAmount');
  var ccySel = document.getElementById('payCurrency');
  var overrideBox = document.getElementById('amountOverride');
  var crossHint = document.getElementById('amountCrossHint');
  var submitBtn = document.querySelector('[data-shortcut-save]');
  var trs = Array.prototype.slice.call(document.querySelectorAll('tr[data-doc-ccy]'));
  if (!amount || !ccySel || !trs.length) return;
  var initial = true, wasCross = false;

  function sync() {
    var ccy = ccySel.value;
    var sum = 0, picked = 0, cross = false;
    trs.forEach(function (tr) {
      var cb = tr.querySelector('.alloc-pick');
      var inp = tr.querySelector('.alloc-amt');
      if (!cb || !inp) return;
      var v = parseFloat(inp.value) || 0;
      cb.checked = v > 0;
      if (v <= 0) return;
      picked++;
      sum += v;
      if (tr.dataset.docCcy !== ccy) cross = true;
    });
    if (submitBtn) submitBtn.disabled = picked === 0;
    var manual = cross || (overrideBox && overrideBox.checked);
    if (manual) {
      amount.readOnly = false;
      // 同币种切到跨币种时，原来的合计已无意义，清空避免误提交；
      // 编辑已保存的跨币种草稿（首次渲染）保留原金额。
      if (cross && !wasCross && !initial) amount.value = '';
      if (crossHint) crossHint.style.display = cross ? '' : 'none';
    } else {
      amount.readOnly = true;
      amount.value = picked ? sum.toFixed(2) : '';
      if (crossHint) crossHint.style.display = 'none';
    }
    wasCross = cross;
    initial = false;
  }

  trs.forEach(function (tr) {
    var cb = tr.querySelector('.alloc-pick');
    var inp = tr.querySelector('.alloc-amt');
    if (!cb || !inp) return;
    cb.addEventListener('change', function () {
      if (cb.checked) {
        var out = parseFloat(inp.dataset.outstanding) || 0;
        inp.value = out ? out.toFixed(2) : '';
      } else {
        inp.value = '0';
      }
      sync();
    });
    inp.addEventListener('input', sync);
  });
  ccySel.addEventListener('change', sync);
  if (overrideBox) overrideBox.addEventListener('change', sync);
  sync();
})();
</script>

<?php
/*
 * LtBooks — pages/orders.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 销售 / 采购订单（同一套代码，direction 区分）。
 *
 * 订单是「承诺」：只登记，不进总账。销售/采购合同的扫描件作为订单附件上传。
 * 订单不是必经流程——也可以直接从发票开始，把合同挂在发票上。
 */
$role = isset($role) ? $role : 'accountant';
// 方向可以由外层包装文件固定（sales-orders.php / purchase-orders.php），
// 也允许 ?d= 切换，方便一个入口看两边。
$dir = $__order_dir ?? (string) ($_GET['d'] ?? 'sales');
if (!in_array($dir, ['sales', 'purchase'], true)) { $dir = 'sales'; }
$isSales = $dir === 'sales';
$pageKey = $isSales ? 'sales-orders' : 'purchase-orders';
$errMsg = null;
$editId = (int) ($_GET['edit'] ?? 0);

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'order_convert') {
    // 列表里直接「转发票 / 转账单」：整单数量转出，草稿仍要复核后才能过账
    $r = api_post('/orders/' . (int) ($_POST['id'] ?? 0) . '/convert', [
        'date' => date('Y-m-d'),
        'actor' => (string) ($user['username'] ?? 'system'),
    ]);
    if ($r['ok']) {
        header('Location: ' . (string) ($r['data']['href'] ?? '?p=' . $pageKey . '&msg='
            . urlencode('已转成草稿单据')));
        exit;
    }
    $errMsg = (string) $r['error'];
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()
    && in_array((string) ($_POST['action'] ?? ''), ['order_create', 'order_update'], true)) {
    $action = (string) $_POST['action'];
    $isUpdate = $action === 'order_update';
    $id = (int) ($_POST['id'] ?? 0);
    if ($isUpdate) { $editId = $id; }
    $lines = [];
    foreach ((array) ($_POST['line'] ?? []) as $row) {
        $desc = trim((string) ($row['description'] ?? ''));
        if ($desc === '') { continue; }
        $lines[] = ['description' => $desc,
                    'unit' => trim((string) ($row['unit'] ?? '')) ?: null,
                    'quantity' => (string) ($row['quantity'] ?? '1'),
                    'unitPrice' => (string) ($row['unitPrice'] ?? '0'),
                    'taxRate' => (string) ($row['taxRate'] ?? '')];
    }
    $r = api_post($isUpdate ? '/orders/' . $id . '/update' : '/orders', [
        'direction' => $dir,
        'orderNo' => trim((string) ($_POST['orderNo'] ?? '')),
        'partyName' => trim((string) ($_POST['partyName'] ?? '')),
        'reference' => trim((string) ($_POST['reference'] ?? '')) ?: null,
        'orderDate' => (string) ($_POST['orderDate'] ?? date('Y-m-d')),
        'expectedDate' => (string) ($_POST['expectedDate'] ?? '') ?: null,
        'currency' => (string) ($_POST['currency'] ?? 'HKD'),
        'contractNote' => trim((string) ($_POST['contractNote'] ?? '')) ?: null,
        'notes' => trim((string) ($_POST['notes'] ?? '')) ?: null,
        'lines' => $lines,
        'actor' => (string) ($user['username'] ?? 'system'),
    ]);
    if ($r['ok']) {
        $oid = (int) ($r['data']['orderId'] ?? 0);
        if ($oid > 0 && !empty($_FILES['attach']['name'][0])) {
            doc_files_save('order', $oid, $_FILES['attach'], (string) ($user['username'] ?? 'system'));
        }
        header('Location: ?p=' . $pageKey
             . '&msg=' . urlencode(t($isUpdate ? '订单修改已保存' : '订单已建') . '：' . ($r['data']['orderNo'] ?? '')));
        exit;
    }
    $errMsg = (string) $r['error'];
}
if ($errMsg) { echo errbox($errMsg); }

$formError = $errMsg !== null && in_array((string) ($_POST['action'] ?? ''), ['order_create', 'order_update'], true);
$editing = null;
if ($editId > 0 && $role !== 'auditor') {
    $editR = api_get('/orders/' . $editId);
    if (!$editR['ok']) { echo errbox((string) $editR['error']); return; }
    $editing = $editR['data'] ?? [];
    if ((string) ($editing['direction'] ?? '') !== $dir || empty($editing['editable'])) {
        echo errbox('订单已有履行记录、已转出单据或状态不可编辑'); return;
    }
}
$showNew = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $editing !== null || $formError);
$value = static function (string $key, string $dbKey = '', $default = '') use ($editing) {
    if (array_key_exists($key, $_POST)) { return $_POST[$key]; }
    if ($editing && $dbKey !== '' && array_key_exists($dbKey, $editing)) { return $editing[$dbKey]; }
    return $default;
};
$orderDate = (string) $value('orderDate', 'order_date', date('Y-m-d'));
$formLines = [];
if ($formError && isset($_POST['line'])) {
    foreach ((array) $_POST['line'] as $ln) {
        $formLines[] = ['description' => (string) ($ln['description'] ?? ''), 'unit' => (string) ($ln['unit'] ?? ''),
                        'quantity' => (string) ($ln['quantity'] ?? '1'), 'unitPrice' => (string) ($ln['unitPrice'] ?? '0'),
                        'taxRate' => (string) ($ln['taxRate'] ?? '')];
    }
} elseif ($editing) {
    foreach ((array) ($editing['lines'] ?? []) as $ln) {
        $formLines[] = ['description' => (string) $ln['description'], 'unit' => (string) ($ln['unit'] ?? ''),
                        'quantity' => (string) $ln['quantity'], 'unitPrice' => (string) $ln['unit_price'],
                        'taxRate' => (string) ($ln['tax_rate'] ?? '')];
    }
}
if (!$formLines) { $formLines[] = ['description' => '', 'unit' => '', 'quantity' => '1', 'unitPrice' => '0', 'taxRate' => '']; }

[$page, $per] = pager_state('ledu_order_per', 25);
$limit = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kw = trim((string) ($_GET['q'] ?? ''));
$view = (string) ($_GET['view'] ?? 'all');
$r = api_get('/orders?direction=' . $dir . '&limit=' . $limit . '&offset=' . $offset
           . '&status=' . urlencode($view) . ($kw !== '' ? '&q=' . urlencode($kw) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rows = $r['data']['orders'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? 0);
$partyRes = $isSales ? api_get('/customers?limit=0') : api_get('/vendors?limit=0');
$partyList = $partyRes['ok'] ? ($partyRes['data'][$isSales ? 'customers' : 'vendors'] ?? []) : [];
$partyNameKey = $isSales ? 'customer_name' : 'vendor_name';
$partyCodeKey = $isSales ? 'customer_code' : 'vendor_code';
?>
<?php if (!$showNew): ?>
<div class="card">
  <div class="list-bar">
    <div class="tabs" style="border:0;gap:16px;padding:0">
      <?php foreach (['all' => t('全部'), 'draft' => status_label('draft'), 'open' => status_label('ordered'), 'partial' => status_label('partial'),
                      'fulfilled' => status_label('fulfilled'), 'closed' => status_label('closed'),
                      'cancelled' => status_label('cancelled')] as $k => $lab): ?>
        <a class="tab<?= $view === $k ? ' active' : '' ?>"
           href="?p=<?= e($pageKey) ?>&view=<?= e($k) ?>"><?= e($lab) ?></a>
      <?php endforeach; ?>
    </div>
    <form method="get" style="display:flex;gap:6px;margin-left:auto">
      <input type="hidden" name="p" value="<?= e($pageKey) ?>">
      <?php if ($view !== 'all'): ?><input type="hidden" name="view" value="<?= e($view) ?>"><?php endif; ?>
      <input type="text" name="q" value="<?= e($kw) ?>" placeholder="<?= e(t('搜索订单号 / 往来单位')) ?>" style="width:200px">
      <button class="btn sm"><?= e(t('搜索')) ?></button>
    </form>
  </div>
  <?php if (!$rows): ?>
    <div class="card-body"><?= empty_state($isSales ? '还没有销售订单' : '还没有采购订单') ?></div>
  <?php else: ?>
  <div class="table-wrap"><table>
    <thead><tr>
      <th><?= e(t('订单号')) ?></th>
      <th><?= e($isSales ? t('客户') : t('供应商')) ?></th>
      <th><?= e(t('下单日')) ?></th>
      <th><?= e($isSales ? t('预计交付') : t('预计到货')) ?></th>
      <th><?= e(t('币种')) ?></th><th class="num"><?= e(t('合计')) ?></th>
      <th><?= e(t('合同附件')) ?></th>
      <th><?= e(t('状态')) ?></th>
      <th><?= e(t('操作')) ?></th>
    </tr></thead>
    <tbody>
    <?php foreach ($rows as $x): ?>
      <tr>
        <td class="mono"><a href="?p=order-view&id=<?= (int) $x['order_id'] ?>"><?= e((string) $x['order_no']) ?></a></td>
        <td class="truncate" style="max-width:240px"><?= e((string) $x['party_name']) ?></td>
        <td class="nowrap"><?= e((string) $x['order_date']) ?></td>
        <td class="nowrap hint"><?= e((string) ($x['expected_date'] ?: '—')) ?></td>
        <td><?= e((string) $x['currency']) ?></td>
        <td class="num"><?= money($x['gross_original'], (string) $x['currency']) ?></td>
        <td><?php $fc = (int) ($x['file_count'] ?? 0); ?>
          <?php if ($fc > 0): ?><span class="tag tag-ok"><?= $fc ?> <?= e(t('个附件')) ?></span>
          <?php else: ?><a class="hint" href="?p=order-view&id=<?= (int) $x['order_id'] ?>"><?= e(t('待上传')) ?></a><?php endif; ?></td>
        <td><span class="tag tag-<?= e($x['status'] === 'fulfilled' ? 'ok' : (in_array($x['status'], ['cancelled','closed'], true) ? 'danger' : 'info')) ?>">
          <?= e(t((string) $x['statusLabel'])) ?></span></td>
        <td style="white-space:nowrap">
          <?php if ($role === 'auditor'): ?>
            <span class="hint">只读</span>
          <?php elseif (in_array((string) $x['status'], ['cancelled', 'closed'], true)): ?>
            <span class="hint">—</span>
          <?php else: ?>
            <?php if (!empty($x['editable'])): ?>
              <a class="btn sm" href="?p=<?= e($pageKey) ?>&amp;edit=<?= (int) $x['order_id'] ?>#new"><?= e(t('编辑')) ?></a>
            <?php endif; ?>
            <?php if ((string) $x['status'] === 'draft'): ?>
              <?= draft_delete_form('order', (int) $x['order_id'], $pageKey) ?>
            <?php endif; ?>
            <form method="post" class="inline-form">
              <?= csrf_field() ?>
              <input type="hidden" name="action" value="order_convert">
              <input type="hidden" name="id" value="<?= (int) $x['order_id'] ?>">
              <button class="btn sm primary"
                data-confirm="<?= e($isSales ? t('按订单转成销售发票？') : t('按订单转成账单？')) ?>"
                data-confirm-note="<?= e(t('会按订单明细生成一张草稿，仍需上传凭证、复核、记账后才进总账。')) ?>"
                data-confirm-ok="<?= e($isSales ? t('转发票') : t('转账单')) ?>">
                <?= e($isSales ? t('转发票') : t('转账单')) ?></button>
            </form>
          <?php endif; ?>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
  <?php endif; ?>
  <?= pager_html($page, $per, $totalRows,
        ['p' => $pageKey, 'view' => $view !== 'all' ? $view : null,
         'q' => $kw !== '' ? $kw : null], 'order') ?>
</div>
<?php endif; ?>

<?php if ($showNew): ?>
<section class="card" id="new">
  <div class="card-head">
    <h2 class="card-title"><?= e($editing ? t('编辑订单') : ($isSales ? t('新建销售订单') : t('新建采购订单'))) ?></h2>
    <div style="display:flex;align-items:center;gap:12px">
      <span class="hint"><?= e(t('订单只登记、不过账；建好后把合同扫描件作为附件上传')) ?></span>
      <a class="btn sm" href="?p=<?= e($pageKey) ?>">返回列表</a>
    </div>
  </div>
  <form method="post" class="card-body" enctype="multipart/form-data">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="<?= $editing ? 'order_update' : 'order_create' ?>">
    <?php if ($editing): ?><input type="hidden" name="id" value="<?= (int) $editing['order_id'] ?>"><?php endif; ?>

    <div class="zform">
      <div class="zcol">
        <div class="zsec-h">往来与摘要</div>
        <div class="field"><label class="f"><?= e($isSales ? t('客户名称 *') : t('供应商名称 *')) ?></label>
          <?php
          $curParty = (string) $value('partyName', 'party_name');
          $pOpts = '<option value="">— ' . e($isSales ? '选择客户' : '选择供应商') . ' —</option>';
          foreach ($partyList as $p) {
              $pn = (string) $p[$partyNameKey];
              $pOpts .= '<option value="' . e($pn) . '"' . ($curParty === $pn ? ' selected' : '') . '>'
                       . e($pn . (!empty($p[$partyCodeKey]) ? '（' . $p[$partyCodeKey] . '）' : '')) . '</option>';
          }
          if ($curParty !== '') {
              $has = false; foreach ($partyList as $p) { if ((string) $p[$partyNameKey] === $curParty) { $has = true; break; } }
              if (!$has) $pOpts .= '<option value="' . e($curParty) . '" selected>' . e($curParty) . '（未建档）</option>';
          }
          ?>
          <select id="oParty" name="partyName" required data-allow-create="1"><?= $pOpts ?></select>
        </div>
        <div class="field"><label class="f"><?= e(t('合同名称 / 编号')) ?></label>
          <input type="text" id="oContract" name="contractNote" value="<?= e((string) $value('contractNote', 'contract_note')) ?>"
                 placeholder="<?= e(t('例：2026 年度系统维护服务合同')) ?>">
          <div class="hint"><?= e(t('建好后把合同扫描件作为附件传上来')) ?></div>
        </div>
      </div>

      <div class="zcol zcol-2">
        <div class="zsec-h">单据信息</div>
        <div class="z2">
          <?= $editing
              ? '<div class="field"><label class="f">' . e($isSales ? t('订单编号') : t('采购单号')) . '</label>'
               . '<input type="text" value="' . e((string) $value('orderNo', 'order_no')) . '" readonly'
               . ' style="font-family:var(--mono);background:var(--c-surface-alt)"></div>'
              : doc_no_field($isSales ? '订单编号' : '采购单号', next_doc_no($orderDate, $isSales ? 'so' : 'po'), 'orderNo') ?>
          <div class="field"><label class="f"><?= e(t('参考号')) ?></label>
            <input type="text" name="reference" value="<?= e((string) $value('reference', 'reference')) ?>" placeholder="<?= e(t('选填')) ?>">
          </div>
          <div class="field"><label class="f" for="oDate"><?= e(t('下单日期 *')) ?></label>
            <input type="date" id="oDate" name="orderDate" required value="<?= e($orderDate) ?>">
          </div>
          <div class="field"><label class="f" for="oExp"><?= e($isSales ? t('预计交付') : t('预计到货')) ?></label>
            <input type="date" id="oExp" name="expectedDate" value="<?= e((string) $value('expectedDate', 'expected_date')) ?>">
          </div>
          <div class="field"><label class="f" for="oCcy"><?= e(t('币种')) ?></label>
            <select id="oCcy" name="currency"><?= currency_options((string) $value('currency', 'currency', 'HKD')) ?></select>
          </div>
          <div class="field"><label class="f"><?= e(t('状态')) ?></label>
            <input type="text" value="<?= e($editing ? (string) $editing['statusLabel'] . '（未履行可编辑）' : t('已下单（未履行可编辑）')) ?>" readonly style="background:var(--c-surface-alt)">
          </div>
        </div>
      </div>
    </div>

    <div style="margin-top:18px">
      <div class="table-wrap"><table>
        <thead><tr>
          <th style="width:38px" class="num">#</th>
          <th>项目 / 描述</th>
          <th style="width:84px" class="num">数量</th>
          <th style="width:80px">单位</th>
          <th style="width:124px" class="num">单价</th>
          <th style="width:84px" class="num">税 %</th>
          <th style="width:130px" class="num">金额</th>
          <th style="width:40px"></th>
        </tr></thead>
        <tbody id="oLines">
          <?php foreach ($formLines as $i => $ln): ?>
          <tr>
            <td class="o-seq mono hint"><?= $i + 1 ?></td>
            <td><input type="text" name="line[<?= $i ?>][description]" value="<?= e((string) $ln['description']) ?>" placeholder="<?= e(t('写清楚是什么')) ?>" style="width:100%"></td>
            <td><input type="number" step="0.0001" min="0" name="line[<?= $i ?>][quantity]" value="<?= e((string) $ln['quantity']) ?>" class="o-qty" style="width:100%"></td>
            <td><input type="text" name="line[<?= $i ?>][unit]" value="<?= e((string) $ln['unit']) ?>" placeholder="<?= e(t('箱/件')) ?>" style="width:100%"></td>
            <td><input type="number" step="0.01" min="0" name="line[<?= $i ?>][unitPrice]" value="<?= e((string) $ln['unitPrice']) ?>" class="o-price" style="width:100%"></td>
            <td><input type="number" step="0.01" min="0" name="line[<?= $i ?>][taxRate]" value="<?= e((string) $ln['taxRate']) ?>" class="o-tax" style="width:100%"></td>
            <td class="o-amt num mono"><?= e(number_format((float) $ln['quantity'] * (float) $ln['unitPrice'], 2, '.', '')) ?></td>
            <td><button type="button" class="btn sm o-del" title="删除本行">×</button></td>
          </tr>
          <?php endforeach; ?>
        </tbody>
      </table></div>
      <div class="toolbar" style="margin-top:10px">
        <button type="button" class="btn sm" id="oAdd">＋ 添加一行</button>
        <span class="grow"></span>
        <span class="hint">金额 = 数量 × 单价 · 合计 <b id="oTotal" class="mono">0.00</b></span>
      </div>
    </div>

    <div class="field" style="margin-top:14px"><label class="f" for="oNotes"><?= e(t('备注')) ?></label>
      <textarea id="oNotes" name="notes" rows="3" placeholder="<?= e(t('其他需要记录的信息')) ?>"><?= e((string) $value('notes', 'notes')) ?></textarea>
    </div>

    <?= attach_dropzone('attach', '把合同扫描件拖到这里', '或点击选择文件 · 保存后自动挂到这张订单') ?>

    <div class="card-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
      <a class="btn" href="?p=<?= e($pageKey) ?>">取消</a>
      <button class="btn primary"><?= e($editing ? t('保存修改') : ($isSales ? t('建销售订单') : t('建采购订单'))) ?></button>
    </div>
  </form>
</section>
<script>
(function () {
  var body = document.getElementById('oLines'), add = document.getElementById('oAdd'), n = body.rows.length;
  if (!add) return;
  function num(el) { var v = parseFloat(el.value); return isFinite(v) ? v : 0; }
  function calc() {
    var t = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      var a = num(tr.querySelector('.o-qty')) * num(tr.querySelector('.o-price'));
      tr.querySelector('.o-amt').textContent = a.toFixed(2);
      t += a + a * num(tr.querySelector('.o-tax')) / 100;
    });
    document.getElementById('oTotal').textContent = t.toFixed(2);
  }
  function bind(tr) {
    tr.querySelectorAll('.o-qty,.o-price,.o-tax').forEach(function (i) { i.addEventListener('input', calc); });
    tr.querySelector('.o-del').addEventListener('click', function () {
      if (body.rows.length > 1) { tr.remove(); calc(); }
    });
  }
  body.querySelectorAll('tr').forEach(bind);
  add.addEventListener('click', function () {
    var tr = body.rows[0].cloneNode(true);
    tr.querySelectorAll('input').forEach(function (el) {
      el.name = el.name.replace(/line\[\d+\]/, 'line[' + n + ']');
      el.value = el.classList.contains('o-qty') ? '1' : (el.classList.contains('o-price') ? '0' : '');
    });
    body.appendChild(tr); bind(tr); n++;
    body.querySelectorAll('tr').forEach(function (r, i) { r.querySelector('.o-seq').textContent = i + 1; });
    calc();
  });
  calc();
})();
</script>
<?php if ($role !== 'auditor'): ?>
  <?= inline_party_create_panel($isSales ? 'customer' : 'vendor') ?>
  <script>
  (function () {
    var sel = document.getElementById('oParty');
    if (!sel) return;
    var fieldName = <?= $isSales ? "'customerName'" : "'vendorName'" ?>;
    sel.addEventListener('ssel:create', function (ev) {
      var panel = document.getElementById('party-create-panel');
      var q = (ev.detail && ev.detail.query) || '';
      if (panel && q) {
        var nm = panel.querySelector('[data-party-field="' + fieldName + '"]');
        if (nm) nm.value = q;
      }
    });
  })();
  </script>
<?php endif; ?>
<?php endif; ?>

<?php
/*
 * LtBooks — pages/fast-new.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 快速建单：三类单据一张表填完；可存草稿、也可确认后一键记账。 */
$role = isset($role) ? $role : 'accountant';
if ($role === 'auditor') { echo empty_state('审计角色不可录入'); return; }

$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;
$kind = (string) ($_POST['kind'] ?? $_GET['kind'] ?? 'invoice');
if (!in_array($kind, ['invoice', 'bill', 'expense'], true)) { $kind = 'invoice'; }

$custR = api_get('/customers?limit=0');
$customers = $custR['ok'] ? ($custR['data']['customers'] ?? []) : [];
$vendR = api_get('/vendors?limit=0');
$vendors = $vendR['ok'] ? ($vendR['data']['vendors'] ?? []) : [];
$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$costAccounts = array_values(array_filter($accounts,
    fn($a) => in_array($a['category'], ['expense', 'cogs'], true)));

// ---------------------------------------------------------------- 提交
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'fast_create') {
    $party = (string) ($_POST['party'] ?? '');
    if ($party === '__custom__') { $party = trim((string) ($_POST['partyCustom'] ?? '')); }
    $lines = [];
    foreach ((array) ($_POST['lineDesc'] ?? []) as $i => $desc) {
        $desc = trim((string) $desc);
        if ($desc === '') { continue; }
        $lines[] = [
            'description' => $desc,
            'quantity'    => (string) ($_POST['lineQty'][$i] ?? '1'),
            'unitPrice'   => (string) ($_POST['linePrice'][$i] ?? '0'),
            'taxRate'     => (string) ($_POST['lineTax'][$i] ?? ''),
        ];
    }
    $payload = [
        'kind' => $kind,
        'party' => $party,
        'date' => (string) ($_POST['date'] ?? ''),
        'dueDate' => (string) ($_POST['dueDate'] ?? '') ?: null,
        'currency' => (string) ($_POST['currency'] ?? 'HKD'),
        'lines' => $lines,
        'amountOriginal' => (float) ($_POST['amountOriginal'] ?? 0),
        'taxOriginal' => (float) ($_POST['taxOriginal'] ?? 0),
        'discountOriginal' => (float) ($_POST['discountOriginal'] ?? 0),
        'expenseAccountCode' => (string) ($_POST['expenseAccountCode'] ?? ($kind === 'expense' ? '6600' : '6200')),
        'projectName' => trim((string) ($_POST['projectName'] ?? '')),
        'notes' => trim((string) ($_POST['notes'] ?? '')),
        'actor' => $actor,
    ];
    $res = api_post('/fast/create', $payload);
    if (!$res['ok']) {
        $errMsg = (string) $res['error'];
    } else {
        $d = $res['data'];
        $docId = (int) ($d['docId'] ?? 0);
        $docNo = (string) ($d['docNo'] ?? '');
        $wantPost = !empty($_POST['post']);
        if (!$wantPost) {
            $msg = t('已存为草稿') . ' ' . $docNo . ' · ' . t('上传原始凭证后可提交记账');
            if ($kind === 'expense') {
                $back = '?p=doc-view&type=expense&id=' . $docId;
                $msg = t('费用') . ' ' . $docNo . ' ' . t('已登记为草稿');
            } else {
                $back = '?p=' . ($kind === 'invoice' ? 'invoice-view' : 'bill-view') . '&id=' . $docId;
            }
            header('Location: ' . $back . '&msg=' . urlencode($msg));
            exit;
        }
        $pr = api_post('/fast/post', ['kind' => $kind, 'docId' => $docId,
                                      'actor' => $actor, 'role' => $role]);
        if (!$pr['ok']) {
            $errMsg = t('草稿') . ' ' . $docNo . ' ' . t('已保存，但记账失败：') . (string) $pr['error'];
        } else {
            $steps = implode(' → ', (array) ($pr['data']['steps'] ?? []));
            $entry = (string) ($pr['data']['entryNo'] ?? '');
            header('Location: ?p=fast-new&msg=' . urlencode(
                $docNo . ' ' . t('已记账 · 凭证') . ' ' . $entry . ' · ' . $steps));
            exit;
        }
    }
}

// ---------------------------------------------------------------- 批量记账
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'fast_batch') {
    $docs = [];
    foreach ((array) ($_POST['docs'] ?? []) as $v) {
        [$k, $id] = array_pad(explode(':', (string) $v, 2), 2, '0');
        if (in_array($k, ['invoice', 'bill'], true) && (int) $id > 0) {
            $docs[] = ['kind' => $k, 'docId' => (int) $id];
        }
    }
    if (!$docs) {
        $errMsg = t('没有勾选要记账的草稿');
    } else {
        $res = api_post('/fast/post-batch', ['docs' => $docs, 'actor' => $actor, 'role' => $role]);
        if (!$res['ok']) {
            $errMsg = (string) $res['error'];
        } else {
            $d = $res['data'];
            $msg = str_replace(
                ['{ok}', '{no}'],
                [(string) (int) $d['ok'], (string) (int) $d['failed']],
                t('批量记账：成功 {ok} 张，失败 {no} 张'));
            if ((int) $d['failed'] > 0) {
                $fails = [];
                foreach ($d['results'] as $x) {
                    if (!$x['ok']) { $fails[] = $x['kind'] . '#' . $x['docId'] . ' ' . $x['error']; }
                }
                $msg .= '（' . implode('；', array_slice($fails, 0, 3)) . '）';
            }
            $msg .= ' · ' . t('每张均走完 提交复核 → 批准 → 记账');
            header('Location: ?p=fast-new&msg=' . urlencode($msg));
            exit;
        }
    }
}

// ---------------------------------------------------------------- 最近草稿
$drafts = [];
$invD = api_get('/invoices?limit=8&status=draft&offset=0');
foreach (($invD['ok'] ? ($invD['data']['invoices'] ?? []) : []) as $x) {
    $drafts[] = ['kind' => 'invoice', 'id' => (int) $x['invoice_id'], 'no' => $x['invoice_no'],
                 'party' => $x['supplier_name'], 'date' => $x['invoice_date'],
                 'amt' => $x['gross_original'], 'ccy' => $x['currency'],
                 'role' => '销售发票', 'href' => '?p=invoice-view&id=' . (int) $x['invoice_id']];
}
$billD = api_get('/bills?limit=8&status=draft&offset=0');
foreach (($billD['ok'] ? ($billD['data']['bills'] ?? []) : []) as $x) {
    $drafts[] = ['kind' => 'bill', 'id' => (int) $x['bill_id'], 'no' => $x['bill_no'],
                 'party' => $x['vendor_name'], 'date' => $x['date'],
                 'amt' => $x['gross_original'], 'ccy' => $x['currency'],
                 'role' => '采购发票', 'href' => '?p=bill-view&id=' . (int) $x['bill_id']];
}
$expD = api_get('/expenses?limit=8&status=draft&offset=0');
foreach (($expD['ok'] ? ($expD['data']['expenses'] ?? []) : []) as $x) {
    $drafts[] = ['kind' => 'expense', 'id' => (int) $x['expense_id'], 'no' => $x['expense_no'],
                 'party' => $x['category'] . (!empty($x['project_name']) ? ' · ' . $x['project_name'] : ''),
                 'date' => $x['date'], 'amt' => (float) $x['amount'] + (float) $x['tax_amount'],
                 'ccy' => $x['currency'], 'role' => '费用',
                 'href' => '?p=doc-view&type=expense&id=' . (int) $x['expense_id']];
}
usort($drafts, static fn($a, $b) => [$b['date'], $b['id']] <=> [$a['date'], $a['id']]);
$drafts = array_slice($drafts, 0, 12);

$partyList = $kind === 'invoice' ? $customers : $vendors;
$partyField = $kind === 'invoice' ? 'customer_name' : 'vendor_name';
$defaultAcc = $kind === 'expense' ? '6600' : '6200';
?>
<div class="page-head">
  <div>
    <h1 class="page-title">快速建单</h1>
    <div class="page-sub">
      一张表走完：填往来单位、金额、明细 → 存草稿或确认后一键记账
    </div>
  </div>
  <div class="page-actions">
    <a class="btn" href="?p=today">今天待处理</a>
  </div>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>

<?= help_html('fast-new') ?>
<section class="card">
  <div class="card-head">
    <h2>新建单据</h2>
    <div style="display:flex;gap:2px">
      <?php foreach (['invoice' => '销售发票', 'bill' => '采购发票', 'expense' => '费用'] as $k => $lab): ?>
        <a class="tab<?= $kind === $k ? ' active' : '' ?>" href="?p=fast-new&kind=<?= e($k) ?>"><?= e($lab) ?></a>
      <?php endforeach; ?>
    </div>
  </div>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="fast_create">
    <input type="hidden" name="kind" value="<?= e($kind) ?>">

    <div class="grid" style="grid-template-columns:<?= $kind === 'bill' ? 'minmax(0,1.7fr) repeat(2,minmax(0,1fr))' : 'minmax(0,1.7fr) repeat(3,minmax(0,1fr))' ?>">
      <div class="field">
        <label class="f" for="partySel">
          <?= $kind === 'invoice' ? '客户' : ($kind === 'bill' ? '供应商' : '费用类别') ?>
        </label>
        <?php if ($kind === 'expense'): ?>
          <input type="text" name="party" required placeholder="例：办公室租金 / 差旅"
                 value="<?= e((string) ($_POST['party'] ?? '')) ?>">
        <?php else: ?>
          <select name="party" id="partySel" required>
            <option value="">— 选择 —</option>
            <?php foreach ($partyList as $p): ?>
              <option value="<?= e((string) $p[$partyField]) ?>"
                <?= (string) ($_POST['party'] ?? '') === (string) $p[$partyField] ? ' selected' : '' ?>>
                <?= e((string) $p[$partyField]) ?>
              </option>
            <?php endforeach; ?>
            <option value="__custom__" <?= (string) ($_POST['party'] ?? '') === '__custom__' ? ' selected' : '' ?>>
              其他（手填）
            </option>
          </select>
          <input type="text" name="partyCustom" id="partyCustom" placeholder="手填名称"
                 style="margin-top:6px;display:none"
                 value="<?= e((string) ($_POST['partyCustom'] ?? '')) ?>">
        <?php endif; ?>
      </div>
      <div class="field">
        <label class="f" for="fDate"><?= $kind === 'bill' ? '账单日期' : '日期' ?></label>
        <input type="date" id="fDate" name="date" required
               value="<?= e((string) ($_POST['date'] ?? date('Y-m-d'))) ?>">
      </div>
      <?php if ($kind !== 'expense'): ?>
      <div class="field">
        <label class="f" for="fDue">到期日（可空）</label>
        <input type="date" id="fDue" name="dueDate"
               value="<?= e((string) ($_POST['dueDate'] ?? '')) ?>">
      </div>
      <?php endif; ?>
      <div class="field">
        <label class="f" for="fCcy">币种</label>
        <select id="fCcy" name="currency"><?= currency_options((string) ($_POST['currency'] ?? null)) ?></select>
      </div>
      <?php if ($kind !== 'invoice'): ?>
      <div class="field"<?= $kind === 'bill' ? ' style="grid-column:span 2"' : '' ?>>
        <label class="f" for="fAcc">费用科目</label>
        <select id="fAcc" name="expenseAccountCode">
          <?php foreach ($costAccounts as $a): ?>
            <option value="<?= e((string) $a['account_code']) ?>"
              <?= (string) ($_POST['expenseAccountCode'] ?? $defaultAcc) === (string) $a['account_code'] ? ' selected' : '' ?>>
              <?= e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) ?>
            </option>
          <?php endforeach; ?>
        </select>
      </div>
      <?php endif; ?>
    </div>

    <?php if ($kind === 'expense'): ?>
      <div class="grid form-grid-4" style="margin-top:var(--s-4)">
        <div class="field">
          <label class="f" for="expAmt">金额（不含税）</label>
          <input type="number" step="0.01" min="0" id="expAmt" name="amountOriginal" required
                 value="<?= e((string) ($_POST['amountOriginal'] ?? '')) ?>">
        </div>
        <div class="field">
          <label class="f" for="expTax">税额</label>
          <input type="number" step="0.01" min="0" id="expTax" name="taxOriginal"
                 value="<?= e((string) ($_POST['taxOriginal'] ?? '0')) ?>">
        </div>
        <div class="field">
          <label class="f" for="expProject">项目</label>
          <input type="text" id="expProject" name="projectName" maxlength="200"
                 value="<?= e((string) ($_POST['projectName'] ?? '')) ?>" placeholder="例：网站改版 / 客户 A">
        </div>
        <div class="field">
          <label class="f" for="expTotal">合计</label>
          <input type="text" id="expTotal" readonly value="0.00"
                 style="font-family:var(--mono);background:var(--c-surface-alt)">
        </div>
        <div class="field span-2">
          <label class="f" for="expNotes">备注</label>
          <input type="text" id="expNotes" name="notes" maxlength="600"
                 value="<?= e((string) ($_POST['notes'] ?? '')) ?>" placeholder="选填；会保存在费用单详情">
        </div>
      </div>
      <script>
      (function () {
        var a = document.getElementById('expAmt'), t = document.getElementById('expTax'),
            o = document.getElementById('expTotal');
        function f() {
          var s = (parseFloat(a.value) || 0) + (parseFloat(t.value) || 0);
          o.value = (Math.round(s * 100) / 100).toFixed(2);
        }
        [a, t].forEach(function (e) { e.addEventListener('input', f); });
        f();
      })();
      </script>
    <?php else: ?>
      <div style="margin-top:var(--s-4)">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
          <label class="f" style="margin:0">明细</label>
          <button type="button" class="btn sm" id="lnAdd">＋ 加一行</button>
        </div>
        <div class="table-wrap">
          <table id="lnTable">
            <thead><tr>
              <th style="width:40px">#</th><th>描述</th>
              <th class="num" style="width:90px">数量</th>
              <th class="num" style="width:120px">单价</th>
              <th class="num" style="width:86px">税率%</th>
              <th class="num" style="width:120px">金额</th>
              <th style="width:44px"></th>
            </tr></thead>
            <tbody id="lnBody">
              <tr>
                <td class="ln-seq mono hint">1</td>
                <td><input type="text" class="ln-desc" name="lineDesc[]" placeholder="例：顾问服务费" style="width:100%"></td>
                <td><input type="number" class="ln-qty" name="lineQty[]" step="0.01" min="0" value="1" style="width:100%"></td>
                <td><input type="number" class="ln-price" name="linePrice[]" step="0.01" min="0" style="width:100%"></td>
                <td><input type="number" class="ln-tax" name="lineTax[]" step="0.01" min="0" style="width:100%"></td>
                <td class="ln-amt num mono">0.00</td>
                <td><button type="button" class="btn sm ln-del" title="删除本行">×</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="grid" style="grid-template-columns:repeat(4,minmax(0,1fr));margin-top:var(--s-3)">
          <div class="field">
            <label class="f" for="lnDiscount">折扣（原币）</label>
            <input type="number" step="0.01" min="0" id="lnDiscount" name="discountOriginal" value="0">
          </div>
          <div class="field">
            <label class="f" for="lnDiscountRate">折扣率 %</label>
            <input type="number" step="0.0001" min="0" id="lnDiscountRate" value="0">
          </div>
          <div class="field">
            <label class="f">小计 / 税额 / 合计</label>
            <div class="mono" style="font-size:var(--f-sm);line-height:2;font-variant-numeric:tabular-nums">
              <span id="lnSubtotal">0.00</span> · <span id="lnTax">0.00</span> ·
              <b style="font-weight:400;color:var(--c-text)"><span id="lnTotal">0.00</span></b>
            </div>
          </div>
          <input type="hidden" id="lnAmountInput" name="amountOriginal" value="0">
          <input type="hidden" id="lnTaxInput" name="taxOriginal" value="0">
        </div>
      </div>
      <script src="assets/lines.js?v=<?= @filemtime(__DIR__ . '/../assets/lines.js') ?>"></script>
    <?php endif; ?>

    <div class="card-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:var(--s-5)">
      <a class="btn" href="?p=fast-new&kind=<?= e($kind) ?>">清空</a>
      <button class="btn primary" type="submit" name="post" value="0">存为草稿</button>
      <?php if ($kind !== 'expense'): ?>
      <button class="btn primary" type="submit" name="post" value="1"
        data-confirm="<?= e(t('确认记账？这张单据会立即写入总账。')) ?>"
        data-confirm-note="<?= e(t('将依次执行：提交复核 → 批准 → 记账。记账后不可修改或删除，只能冲销；作废与冲销同样需要再次确认。')) ?>"
        data-confirm-ok="<?= e(t('确认记账')) ?>">保存并记账</button>
      <?php endif; ?>
    </div>
  </form>
</section>

<section class="card">
  <div class="card-head">
    <h2>最近草稿</h2>
    <span class="hint">发票与账单可勾选批量记账；费用草稿可进入详情重新编辑</span>
  </div>
  <form method="post">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="fast_batch">
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th class="rowsel"></th><th style="width:110px">类型</th><th style="width:200px">单号</th>
          <th>往来单位</th><th style="width:110px">日期</th>
          <th class="num" style="width:170px">原币金额</th><th style="width:90px"></th>
        </tr></thead>
        <tbody>
        <?php if (!$drafts): ?>
          <tr><td colspan="7" style="text-align:center;padding:26px" class="hint">没有待处理的草稿</td></tr>
        <?php endif; ?>
        <?php foreach ($drafts as $d): ?>
          <tr>
            <td class="rowsel">
              <?php if (in_array($d['kind'], ['invoice', 'bill'], true)): ?>
                <input type="checkbox" name="docs[]" value="<?= e($d['kind'] . ':' . $d['id']) ?>" aria-label="选择 <?= e($d['no']) ?>">
              <?php else: ?><span class="hint" title="费用不支持在此批量记账">—</span><?php endif; ?>
            </td>
            <td><span class="tag tag-draft"><?= e($d['role']) ?></span></td>
            <td><a class="mono" href="<?= e($d['href']) ?>"><?= e((string) $d['no']) ?></a></td>
            <td class="truncate" style="max-width:260px"><?= e((string) $d['party']) ?></td>
            <td class="hint"><?= e((string) $d['date']) ?></td>
            <td class="num"><?= money($d['amt'], (string) $d['ccy']) ?></td>
            <td><?php if ($d['kind'] === 'expense'): ?>
              <a class="btn sm" href="?p=expense-new&amp;edit=<?= (int) $d['id'] ?>">编辑</a>
            <?php else: ?><a class="btn sm" href="<?= e($d['href']) ?>">查看</a><?php endif; ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <div class="card-body" style="display:flex;justify-content:flex-end;gap:8px">
      <button class="btn primary" type="submit"
        data-confirm="<?= e(t('确认批量记账？')) ?>"
        data-confirm-note="<?= e(t('勾选的每张草稿都会立即写入总账。记账后不可修改或删除，只能冲销。')) ?>"
        data-confirm-ok="<?= e(t('确认批量记账')) ?>">批量记账</button>
    </div>
  </form>
</section>

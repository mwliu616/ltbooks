<?php
/*
 * LtBooks — pages/bill-new.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
if ($role === 'auditor') { echo empty_state('审计角色不可录入'); return; }
$result = null; $errMsg = null; $msg = null;
if (!empty($_SESSION['bill_flash'])) { $msg = (string) $_SESSION['bill_flash']; unset($_SESSION['bill_flash']); }
$editId = (int) ($_GET['edit'] ?? 0);
$isEdit = $editId > 0;
$editBill = null;
if ($isEdit) {
    $er = api_get('/bills/' . $editId);
    $editBill = $er['ok'] ? ($er['data'] ?? null) : null;
    if (!$editBill || ($editBill['status'] ?? '') !== 'draft') {
        echo errbox('只有草稿采购发票可以编辑'); return;
    }
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        $ymd = static fn ($v): string => $v ? substr((string) $v, 0, 10) : '';
        foreach ([
            'billNo' => (string) $editBill['bill_no'],
            'vendorInvoiceNo' => (string) ($editBill['vendor_invoice_no'] ?? ''),
            'vendorName' => (string) ($editBill['vendor_name'] ?? ''),
            'vendorAddress' => (string) ($editBill['vendor_address'] ?? ''),
            'expenseAccountCode' => (string) ($editBill['expense_account_code'] ?? '6600'),
            'date' => $ymd($editBill['date'] ?? ''),
            'dueDate' => $ymd($editBill['due_date'] ?? ''),
            'paymentTerms' => (string) ($editBill['payment_terms'] ?? '') ?: 'net_30',
            'orderNumber' => (string) ($editBill['order_number'] ?? ''),
            'currency' => (string) ($editBill['currency'] ?? 'HKD'),
            'subject' => (string) ($editBill['subject'] ?? ''),
            'vendorNotes' => (string) ($editBill['vendor_notes'] ?? ''),
            'termsConditions' => (string) ($editBill['terms_conditions'] ?? ''),
            'discountOriginal' => (string) ($editBill['discount_original'] ?? '0'),
            'discountRate' => (string) ($editBill['discount_rate'] ?? '0'),
        ] as $k => $val) { $_POST[$k] = $val; }
        $editLines = (array) ($editBill['lines'] ?? []);
        foreach (['lineItemCode' => 'item_code', 'lineDesc' => 'description', 'lineUnit' => 'unit',
                  'lineQty' => 'quantity', 'linePrice' => 'unit_price', 'lineAmount' => 'amount',
                  'lineTax' => 'tax_rate', 'lineTaxAmt' => 'tax_amount', 'lineNote' => 'notes'] as $name => $key) {
            $_POST[$name] = array_map(static fn ($l): string => (string) ($l[$key] ?? ''), $editLines);
        }
        $_POST['lineDisc'] = array_map(static function ($l): string {
            $base = (float) ($l['quantity'] ?? 0) * (float) ($l['unit_price'] ?? 0);
            return $base > 0 ? (string) round((1 - (float) $l['amount'] / $base) * 100, 4) : '0';
        }, $editLines);
    }
}
$formAction = $isEdit ? 'update_bill' : 'create_bill';

$prefill = [];
if (isset($_GET['prefill']) && !empty($_SESSION['ai_prefill'])) {
    $prefill = $_SESSION['ai_prefill'];   // 建单成功后才清空，避免刷新或建供应商时丢失
}
$v = function (string $k, string $d = '') use ($prefill) {
    return e((string) ($_POST[$k] ?? ($prefill[$k] ?? $d)));
};
$fromAi = !empty($prefill);

// 识别结果里的供应商是否已建档？未建档则由人工确认后再建
$partyErr = handle_inline_party_create('vendor', 'bill-new', $user ?? []);
$newParty = (string) ($_GET['newparty'] ?? '');
$vendorKnown = null; $vendorMatch = null;
if ($fromAi && trim((string) ($prefill['supplierName'] ?? '')) !== '') {
    $vendR = api_get('/vendors');
    $vendors = $vendR['ok'] ? ($vendR['data']['vendors'] ?? []) : [];
    $needle = mb_strtolower(preg_replace('/\s+/u', ' ', trim((string) $prefill['supplierName'])));
    foreach ($vendors as $vv) {
        $have = mb_strtolower(preg_replace('/\s+/u', ' ', trim((string) $vv['vendor_name'])));
        if ($have === $needle || (mb_strlen($have) > 4 && (mb_strpos($have, $needle) !== false || mb_strpos($needle, $have) !== false))) {
            $vendorKnown = true; $vendorMatch = $vv; break;
        }
    }
    if ($vendorKnown === null) { $vendorKnown = false; }
}

// 人工确认后建立供应商
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'create_vendor_from_ai') {
    $name = trim((string) ($_POST['newVendorName'] ?? ''));
    if ($name === '') {
        $errMsg = '供应商名称不能为空';
    } else {
        $res = api_post('/vendors', [
            'vendorCode' => '',
            'vendorName' => $name,
            'defaultCurrency' => (string) ($_POST['newVendorCurrency'] ?? 'HKD'),
            'paymentTermsDays' => 30,
            'email' => (string) ($_POST['newVendorEmail'] ?? ''),
            'actor' => $user['username'] ?? 'system',
        ]);
        if ($res['ok']) {
            $_SESSION['bill_flash'] = '供应商「' . $name . '」已建档，可以继续保存采购发票';
            header('Location: ?p=bill-new&prefill=1');
            exit;
        } else {
            $errMsg = (string) $res['error'];
        }
    }
}

// 下拉里找不到科目时，现场建一个（仅费用/成本类，借方）
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'create_account_inline') {
    $newCode = trim((string) ($_POST['newCode'] ?? ''));
    $newName = trim((string) ($_POST['newName'] ?? ''));
    $newCat  = (string) ($_POST['newCategory'] ?? 'expense');
    if (!preg_match('/^[0-9]{3,6}$/', $newCode)) {
        $errMsg = '科目编码须为 3–6 位数字';
    } elseif ($newName === '') {
        $errMsg = '请填写科目名称';
    } elseif (!in_array($newCat, ['expense', 'cogs'], true)) {
        $errMsg = '这里只能新建费用或成本类科目';
    } else {
        $res = api_post('/accounts', [
            'code' => $newCode, 'name' => $newName, 'category' => $newCat,
            'normalBalance' => 'debit', 'actor' => (string) ($user['username'] ?? 'system'),
        ]);
        if ($res['ok']) {
            header('Location: ?p=bill-new&newacc=' . urlencode($newCode));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}
$newAcc = (string) ($_GET['newacc'] ?? '');

$vendR2 = api_get('/vendors?limit=0');
$vendorList = $vendR2['ok'] ? ($vendR2['data']['vendors'] ?? []) : [];
$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$costExpense = array_values(array_filter($accounts, fn($a) =>
    in_array($a['category'], ['expense', 'cogs'], true)));
$opts = '';
foreach ($costExpense as $a) {
    $pick = (string) ($_POST['expenseAccountCode'] ?? ($newAcc !== '' ? $newAcc : '6600'));
    $sel = ($pick === (string) $a['account_code']) ? ' selected' : '';
    $opts .= '<option value="' . e((string) $a['account_code']) . '"' . $sel . '>'
           . e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) . '</option>';
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === $formAction) {
    $body = [
        'billNo' => trim((string) ($_POST['billNo'] ?? '')),
        'vendorInvoiceNo' => trim((string) ($_POST['vendorInvoiceNo'] ?? '')) ?: null,
        'vendorName' => (($_POST['vendorName'] ?? '') === '__custom__'
            ? trim((string) ($_POST['vendorNameCustom'] ?? ''))
            : trim((string) ($_POST['vendorName'] ?? ''))),
        'date' => (string) ($_POST['date'] ?? ''),
        'dueDate' => (string) ($_POST['dueDate'] ?? '') ?: null,
        'currency' => (string) ($_POST['currency'] ?? 'HKD'),
        'subject' => trim((string) ($_POST['subject'] ?? '')),
        'orderNumber' => trim((string) ($_POST['orderNumber'] ?? '')),
        'paymentTerms' => trim((string) ($_POST['paymentTerms'] ?? '')),
        'vendorAddress' => trim((string) ($_POST['vendorAddress'] ?? '')),
        'vendorNotes' => trim((string) ($_POST['vendorNotes'] ?? '')),
        'termsConditions' => trim((string) ($_POST['termsConditions'] ?? '')),
        'amount' => (float) ($_POST['amount'] ?? 0),
        'taxAmount' => (float) ($_POST['taxAmount'] ?? 0),
        'discountOriginal' => (float) ($_POST['discountOriginal'] ?? 0),
        'discountRate' => (float) ($_POST['discountRate'] ?? 0),
        // 明细行：有明细时金额由明细汇总，空行丢弃
        'lines' => array_values(array_filter(array_map(function ($i) {
            return [
                'itemCode'    => trim((string) ($_POST['lineItemCode'][$i] ?? '')),
                'description' => trim((string) ($_POST['lineDesc'][$i] ?? '')),
                'unit'        => trim((string) ($_POST['lineUnit'][$i] ?? '')),
                'quantity'    => trim((string) ($_POST['lineQty'][$i] ?? '')),
                'unitPrice'   => trim((string) ($_POST['linePrice'][$i] ?? '')),
                'discountRate' => trim((string) ($_POST['lineDisc'][$i] ?? '0')),
                'amount'      => trim((string) ($_POST['lineAmount'][$i] ?? '')),
                'taxRate'     => trim((string) ($_POST['lineTax'][$i] ?? '')),
                'taxAmount'   => trim((string) ($_POST['lineTaxAmt'][$i] ?? '')),
                'notes'       => trim((string) ($_POST['lineNote'][$i] ?? '')),
            ];
        }, array_keys((array) ($_POST['lineDesc'] ?? []))), fn($l) => $l['description'] !== '')),
        'expenseAccountCode' => (string) ($_POST['expenseAccountCode'] ?? '6600'),
        'reviewedBy' => trim((string) ($_POST['reviewedBy'] ?? '')) ?: null,
        'requiredDocuments' => ['invoice'],
        'documents' => [['type' => 'invoice', 'ref' => 'upload']],
        'actor' => (string) ($user['username'] ?? 'system'),
    ];
    $res = $isEdit ? api_post('/bills/' . $editId . '/update', $body)
                   : api_post('/bills', $body);
    if ($res['ok']) {
        unset($_SESSION['ai_prefill']);            // 预填用完了，清掉避免下次误填
        $bid = (int) $res['data']['billId'];
        // 表单里带的附件：落盘并登记到这张账单
        if (!empty($_FILES['attach']['name'][0])) {
            $actor2 = (string) ($user['username'] ?? 'system');
            foreach ((array) $_FILES['attach']['name'] as $i => $orig) {
                $tmp = (string) ($_FILES['attach']['tmp_name'][$i] ?? '');
                if ($tmp === '' || (int) ($_FILES['attach']['error'][$i] ?? 1) !== UPLOAD_ERR_OK) { continue; }
                if ((int) ($_FILES['attach']['size'][$i] ?? 0) > 20 * 1024 * 1024) { continue; }
                $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', basename((string) $orig));
                $dest = UPLOAD_DIR . '/' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
                if (!@move_uploaded_file($tmp, $dest)) { continue; }
                @chmod($dest, 0640);
                api_post('/bill-files', [
                    'billId' => $bid,
                    'fileName' => (string) $orig,
                    'fileType' => strtolower(pathinfo($safe, PATHINFO_EXTENSION)) ?: 'other',
                    'fileSize' => (int) filesize($dest),
                    'sha256' => (string) hash_file('sha256', $dest),
                    'storagePath' => $dest,
                    'actor' => $actor2,
                ]);
            }
        }
        $autoPost = ($_POST['action_flag'] ?? '') === 'post' && !$isEdit;
        if ($autoPost) {
            $pr = api_post('/bills/' . $bid . '/post', ['actor' => (string) ($user['username'] ?? 'system')]);
            $msg = $pr['ok'] ? '账单已保存并过账（' . (string) ($pr['data']['entryNo'] ?? '') . '）'
                             : '账单已保存为草稿，过账失败：' . (string) $pr['error'];
            header('Location: ?p=bill-view&id=' . $bid . '&msg=' . urlencode($msg));
            exit;
        }
        header('Location: ?p=bill-view&id=' . $bid . '&msg=' . urlencode('账单已保存为草稿，附件已挂上，校验通过即可过账'));
        exit;
    }
    $errMsg = (string) $res['error'];
}
?>
<div class="banner REVIEW" style="background:var(--c-primary-soft);border-color:var(--c-primary-border);color:var(--c-primary)">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title">这是「支出」单据</div>
    <div class="banner-reason">
      供应商开给你的发票记在这里：借 成本／费用 ＋ 进项税额，贷 应付账款。
      你自己开给客户的发票请用「新建销售发票」（那是收入）。
    </div>
  </div>
</div>

<?php if ($msg): ?>
  <div class="banner PASS" style="margin-bottom:12px"><span class="banner-icon">✓</span>
    <div class="banner-body"><div class="banner-title">操作成功</div>
    <div class="banner-reason"><?= $msg ?></div></div></div>
<?php endif; ?>
<?php if ($errMsg): ?><?= errbox($errMsg) ?><?php endif; ?>

<?php if ($fromAi): ?>
  <div class="banner REVIEW" style="margin-bottom:12px">
    <span class="banner-icon">i</span>
    <div class="banner-body">
      <div class="banner-title">以下字段由发票识别自动填入，请逐项核对后再保存</div>
      <div class="banner-reason">
        供应商、金额、日期、税额都可能有识别误差；保存前请与原件比对。
        <?php if (!empty($prefill['ocr']['method'])): ?>
          识别方式：<?= e((string) $prefill['ocr']['method']) ?>
          （<?= e((string) ($prefill['ocr']['confidence'] ?? '')) ?>）
        <?php endif; ?>
      </div>
    </div>
  </div>

  <?php if ($vendorKnown === false): ?>
    <div class="banner FAIL" style="margin-bottom:12px">
      <span class="banner-icon">!</span>
      <div class="banner-body">
        <div class="banner-title">供应商「<?= e((string) ($prefill['supplierName'] ?? '')) ?>」尚未建档</div>
        <div class="banner-reason">
          可以先直接保存采购发票（名称会随单据保留），也可以现在就把它建成正式供应商，
          以后开票、对账、账龄都能按供应商归集。
        </div>
        <form method="post" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <?= csrf_field() ?>
          <input type="hidden" name="action" value="create_vendor_from_ai">
          <input type="text" name="newVendorName" value="<?= e((string) ($prefill['supplierName'] ?? '')) ?>"
                 style="min-width:260px" required>
          <input type="text" name="newVendorCurrency" value="<?= e((string) ($prefill['currency'] ?? 'HKD')) ?>"
                 style="width:80px" title="默认币种">
          <input type="text" name="newVendorEmail" placeholder="邮箱（可空）" style="width:180px">
          <button class="btn primary sm">建立供应商并继续</button>
        </form>


      </div>
    </div>
  <?php elseif ($vendorKnown === true && $vendorMatch): ?>
    <div class="banner PASS" style="margin-bottom:12px">
      <span class="banner-icon">✓</span>
      <div class="banner-body">
        <div class="banner-title">已匹配到档案供应商：<?= e((string) $vendorMatch['vendor_name']) ?></div>
        <div class="banner-reason">编号 <?= e((string) $vendorMatch['vendor_code']) ?> · 币种 <?= e((string) $vendorMatch['default_currency']) ?></div>
      </div>
    </div>
  <?php endif; ?>
<?php endif; ?>

<form method="post" enctype="multipart/form-data" id="billForm">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="<?= e($formAction) ?>">

  <?php ob_start(); ?>
  <div class="zform">
    <div class="zcol">
      <div class="zsec-h">往来与摘要</div>
      <div class="field"><label class="f">供应商名称 *</label>
        <?php
        $curVendor = (string) ($_POST['vendorName'] ?? (($prefill['supplierName'] ?? '') ?: ($newParty ?: '')));
        $vOpts = '<option value="">— 选择供应商 —</option>';
        $vSeen = [];
        foreach ($vendorList as $vv) {
            $vn = (string) $vv['vendor_name'];
            $vSeen[$vn] = true;
            $vOpts .= '<option value="' . e($vn) . '"' . ($curVendor === $vn ? ' selected' : '') . '>'
                    . e($vn . ($vv['vendor_code'] ? '（' . $vv['vendor_code'] . '）' : '')) . '</option>';
        }
        if ($curVendor !== '' && !isset($vSeen[$curVendor])) {
            $vOpts .= '<option value="' . e($curVendor) . '" selected>' . e($curVendor) . '（未建档）</option>';
        }
        $isCustomVendor = ($curVendor !== '' && !isset($vSeen[$curVendor]));
        if ($role !== 'auditor'):
            $vOpts .= '<option value="__custom__"' . ($isCustomVendor ? ' selected' : '') . '>+ 新供应商（手写名称）</option>';
        endif;
        ?>
        <select name="vendorName" id="vendName" required data-allow-create="1"><?= $vOpts ?></select>
        <input type="text" name="vendorNameCustom" id="vendNameCustom"
               value="<?= e($isCustomVendor ? $curVendor : '') ?>" placeholder="输入供应商名称"
               style="margin-top:6px;<?= $isCustomVendor ? '' : 'display:none' ?>">
      </div>
      <div class="field"><label class="f">地址</label>
        <textarea name="vendorAddress" rows="3" placeholder="供应商地址"><?= e((string) ($_POST['vendorAddress'] ?? '')) ?></textarea>
      </div>
      <div class="field"><label class="f">费用 / 成本科目 *</label>
        <select name="expenseAccountCode" required data-allow-create="1" id="expAcc"><?= $opts ?></select>
        <div class="hint">借方科目；进项税额自动记入 1160</div>
        <div style="display:flex;gap:6px;align-items:center;margin-top:6px">
          <button type="button" class="btn sm" id="accSuggestBtn">根据摘要建议</button>
          <span class="hint" id="accSuggestMsg"></span>
        </div>
        <div id="accSuggestList" style="margin-top:4px"></div>
      </div>
      <div class="field"><label class="f">主题</label>
        <input type="text" name="subject" value="<?= e((string) ($_POST['subject'] ?? '')) ?>" placeholder="例：年度审计费">
      </div>
    </div>

    <div class="zcol zcol-2">
      <div class="zsec-h">单据信息</div>
      <div class="z2">
        <?= doc_no_field('账单编号', next_doc_no((string) ($_POST['date'] ?? date('Y-m-d')), 'bill'), 'billNo') ?>
        <div class="field"><label class="f">供应商发票号</label>
          <input type="text" name="vendorInvoiceNo" value="<?= $v('vendorInvoiceNo') ?>" placeholder="对方开具的凭证号">
        </div>
        <div class="field"><label class="f">账单日期 *</label>
          <input type="date" name="date" id="billDate" value="<?= $v('date', (string) (($prefill['invoiceDate'] ?? '') ?: date('Y-m-d'))) ?>" required>
        </div>
        <div class="field"><label class="f">到期日</label>
          <input type="date" name="dueDate" id="dueDate" value="<?= $v('dueDate', (string) ($prefill['dueDate'] ?? '')) ?>">
        </div>
        <div class="field"><label class="f">付款条件</label>
          <select name="paymentTerms" id="payTerms">
            <?php foreach (['due_on_receipt' => '收到即付', 'net_15' => 'Net 15', 'net_30' => 'Net 30',
                            'net_45' => 'Net 45', 'net_60' => 'Net 60', 'custom' => '自定义'] as $k => $lab): ?>
              <option value="<?= e($k) ?>"<?= (($_POST['paymentTerms'] ?? 'net_30') === $k) ? ' selected' : '' ?>><?= e($lab) ?></option>
            <?php endforeach; ?>
          </select>
        </div>
        <div class="field"><label class="f">订单号</label>
          <input type="text" name="orderNumber" value="<?= e((string) ($_POST['orderNumber'] ?? '')) ?>" placeholder="选填">
        </div>
        <div class="field"><label class="f">币种</label>
          <select name="currency"><?= currency_options($_POST['currency'] ?? ($prefill['currency'] ?? 'HKD')) ?></select>
        </div>
        <div class="field"><label class="f">复核人</label>
          <input type="text" name="reviewedBy" value="<?= $v('reviewedBy', 'supervisor') ?>">
        </div>
      </div>
    </div>
  </div>
  <?php echo card('', ob_get_clean(), '', false); ?>

<?php ob_start(); ?>
<?php
$vLines = [];
foreach ((array) ($_POST['lineDesc'] ?? []) as $i => $dl) {
    if (trim((string) $dl) === '') { continue; }
    $vLines[] = [
        'code'   => (string) ($_POST['lineItemCode'][$i] ?? ''),
        'desc'   => (string) $dl,
        'unit'   => (string) ($_POST['lineUnit'][$i] ?? ''),
        'qty'    => (string) ($_POST['lineQty'][$i] ?? '1'),
        'price'  => (string) ($_POST['linePrice'][$i] ?? ''),
        'amount' => (string) ($_POST['lineAmount'][$i] ?? ''),
        'taxAmt' => (string) ($_POST['lineTaxAmt'][$i] ?? ''),
        'tax'    => (string) ($_POST['lineTax'][$i] ?? ''),
        'note'   => (string) ($_POST['lineNote'][$i] ?? ''),
    ];
}
if (!$vLines) { $vLines = [['code'=>'','desc'=>'','unit'=>'','qty'=>'1','price'=>'','amount'=>'','taxAmt'=>'','tax'=>'','note'=>'']]; }
?>
<div class="table-wrap"><table id="billLineTable" style="min-width:0">
  <thead><tr>
    <th style="width:38px" class="num">#</th>
    <th>项目 / 描述</th>
    <th style="width:84px" class="num">数量</th>
    <th style="width:124px" class="num">单价</th>
    <th style="width:84px" class="num">折扣 %</th>
    <th style="width:84px" class="num">税 %</th>
    <th style="width:130px" class="num">金额</th>
    <th style="width:40px"></th>
  </tr></thead>
  <tbody id="billLineBody">
  <?php foreach ($vLines as $i => $ln): ?>
    <tr>
      <td class="num hint bl-seq"><?= $i + 1 ?></td>
      <td><input type="text" name="lineDesc[]" value="<?= e($ln['desc']) ?>" placeholder="描述这个项目或服务" style="width:100%">
        <input type="hidden" name="lineItemCode[]" value="<?= e($ln['code']) ?>">
        <input type="hidden" name="lineUnit[]" value="<?= e($ln['unit']) ?>">
        <input type="hidden" name="lineNote[]" value="<?= e($ln['note']) ?>">
      </td>
      <td><input type="number" step="0.0001" min="0" name="lineQty[]" value="<?= e($ln['qty']) ?>" class="bl-qty" style="width:100%"></td>
      <td><input type="number" step="0.01" min="0" name="linePrice[]" value="<?= e($ln['price']) ?>" class="bl-price" style="width:100%"></td>
      <td><input type="number" step="0.01" min="0" max="100" name="lineDisc[]" value="<?= e($ln['disc'] ?? '0') ?>" class="bl-disc" style="width:100%"></td>
      <td><input type="number" step="0.01" min="0" max="100" name="lineTax[]" value="<?= e($ln['tax']) ?>" class="bl-tax" style="width:100%"></td>
      <td class="num bl-amt" style="font-variant-numeric:tabular-nums">0.00
        <input type="hidden" name="lineAmount[]" class="bl-amount" value="<?= e($ln['amount']) ?>">
        <input type="hidden" name="lineTaxAmt[]" class="bl-tax-amt" value="<?= e($ln['taxAmt']) ?>">
      </td>
      <td><button type="button" class="btn sm bl-del" title="删除本行">×</button></td>
    </tr>
  <?php endforeach; ?>
  </tbody>

</table></div>
<div class="toolbar" style="margin-top:10px">
  <button type="button" class="btn sm" id="billLineAdd">＋ 增加一行</button>
  <span class="grow"></span>
  <span class="hint">合价 = 数量 × 单价，自动计算不可改；要调整只能填折扣</span>
</div>
<?php echo card('明细清单', ob_get_clean()); ?>
<?php if ($role !== 'auditor'): ?>



  <div class="zfoot">
    <div class="zfoot-left">
      <?php ob_start(); ?>
      <input type="hidden" name="amount" id="amtTotalHidden" value="<?= $v('amountOriginal', $v('amount', '0')) ?>">
      <input type="hidden" name="taxAmount" id="taxTotalHidden" value="<?= $v('taxOriginal', $v('taxAmount', '0')) ?>">
      <input type="hidden" name="discountOriginal" id="discTotal" value="<?= $v('discountOriginal', '0') ?>">
      <div class="field"><label class="f">备注</label>
        <textarea name="vendorNotes" rows="3" placeholder="内部备注，供应商看不到"><?= e((string) ($_POST['vendorNotes'] ?? '')) ?></textarea>
      </div>
      <div class="field"><label class="f">条款与条件</label>
        <textarea name="termsConditions" rows="3" placeholder="付款方式、逾期条款等"><?= e((string) ($_POST['termsConditions'] ?? '')) ?></textarea>
      </div>
      <?php echo card('', ob_get_clean(), '', false); ?>
    </div>

    <div class="zfoot-right">
      <?php ob_start(); ?>
      <table class="totals">
        <tr><td>小计</td><td class="num" id="sumAmt">0.00</td></tr>
        <tr><td>折扣</td><td class="num" id="discShow">0.00</td></tr>
        <tr><td>税额</td><td class="num" id="taxTotal"><?= $v('taxOriginal', $v('taxAmount', '0')) ?></td></tr>
        <tr class="grand"><td>合计</td><td class="num" id="grossTotal">
          <?= e(number_format((float) ($_POST['amountOriginal'] ?? $v('amount', '0')) + (float) ($_POST['taxOriginal'] ?? 0), 2, '.', ',')) ?>
        </td></tr>
      </table>
      <div class="hint" style="margin-top:6px">整体折扣率
        <input type="number" step="0.01" min="0" max="100" id="discRate" name="discountRate"
               value="<?= $v('discountRate', '0') ?>" style="width:70px;display:inline-block"> %
      </div>
      <input type="hidden" id="amtTotal" value="<?= $v('amountOriginal', $v('amount', '0')) ?>">
      <?php echo card('', ob_get_clean(), '', false); ?>
    </div>
  </div>

  <?php ob_start(); ?>
  <label class="dropzone" for="billFiles">
    <input type="file" id="billFiles" name="attach[]" multiple
           accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.doc,.docx"
           style="position:absolute;width:1px;height:1px;opacity:0">
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5-5 5 5"/><path d="M12 5v12"/>
    </svg>
    <span class="dz-title">把供应商发票、账单扫描件拖到这里</span>
    <span class="hint">或点击选择文件 · 单个不超过 20MB · 保存后自动挂到这张账单</span>
  </label>
  <div id="dzList" class="dz-list"></div>
  <?php echo card('附件', ob_get_clean(), '', false); ?>

  <div class="pc-box" id="aiPrecheck"></div>

  <div class="toolbar" style="justify-content:flex-end">
    <span class="hint" style="margin-right:auto">保存后可在详情页补附件，校验通过再过账</span>
    <a class="btn" href="<?= $isEdit ? '?p=bill-view&id=' . $editId : '?p=bills' ?>">取消</a>
    <?php if ($isEdit): ?>
      <button class="btn primary" name="action_flag" value="draft"><?= e('保存修改') ?></button>
    <?php else: ?>
      <button class="btn" name="action_flag" value="post" data-shortcut-post>保存并过账</button>
      <button class="btn primary" name="action_flag" value="draft" data-shortcut-save>保存草稿</button>
    <?php endif; ?>
  </div>
</form>

<script src="assets/precheck.js?v=<?= @filemtime(__DIR__ . '/../assets/precheck.js') ?>"></script>
<script>
(function () {
  var f = document.getElementById('billForm');
  if (!f || !window.LeduPrecheck) return;
  function v(name) { var el = f.elements[name]; return el ? el.value : ''; }
  function gather() {
    var vendor = v('vendorName');
    if (vendor === '__custom__') { vendor = v('vendorNameCustom'); }
    var body = document.getElementById('billLineBody');
    var lines = [];
    if (body) {
      body.querySelectorAll('tr').forEach(function (tr) {
        var g = function (sel) { var e = tr.querySelector(sel); return e ? e.value : ''; };
        var desc = g('input[name="lineDesc[]"]');
        if (!desc) return;
        lines.push({description: desc, quantity: g('input[name="lineQty[]"]'),
                    unitPrice: g('input[name="linePrice[]"]'), discount: g('input[name="lineDisc[]"]'),
                    taxRate: g('input[name="lineTax[]"]'),
                    amount: g('input[name="lineAmount[]"]'),
                    taxAmount: g('input[name="lineTaxAmt[]"]'),
                    accountCode: v('expenseAccountCode')});
      });
    }
    return {vendorName: vendor, date: v('date'), currency: v('currency'),
            vendorInvoiceNo: v('vendorInvoiceNo'), subject: v('subject'),
            expenseAccountCode: v('expenseAccountCode'), vendorNotes: v('vendorNotes'), lines: lines};
  }
  window.LeduPrecheck.attach({
    el: '#aiPrecheck', form: f, workflow: 'bill', agentLabel: '会计', auto: true, collect: gather,
    ready: function (p) {
      return p.vendorName && p.lines.some(function (l) {
        return l.description && (parseFloat(l.amount) > 0 ||
          (parseFloat(l.quantity) * parseFloat(l.unitPrice)) > 0);
      });
    }
  });
})();
</script>

<script>
/* 付款条件 → 到期日 */
(function () {
  var terms = document.getElementById('payTerms'), dEl = document.getElementById('billDate'),
      dueEl = document.getElementById('dueDate');
  var DAYS = { due_on_receipt: 0, net_15: 15, net_30: 30, net_45: 45, net_60: 60 };
  function syncDue() {
    if (!terms || !dEl || !dueEl) return;
    var n = DAYS[terms.value];
    if (n === undefined || !dEl.value) return;
    var d = new Date(dEl.value + 'T00:00:00');
    d.setDate(d.getDate() + n);
    dueEl.value = d.toISOString().slice(0, 10);
  }
  if (terms) terms.addEventListener('change', syncDue);
  if (dEl) dEl.addEventListener('change', syncDue);
  if (dueEl && !dueEl.value) syncDue();
})();
</script>

<div id="accCreatePanel" class="card" style="display:none;margin-top:10px">
  <header class="card-head"><h2>＋ 新建费用 / 成本科目</h2></header>
  <div class="card-body">
    <form method="post">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="create_account_inline">
      <div class="grid">
        <div class="field"><label class="f">科目编码 *</label>
          <input type="text" name="newCode" id="newAccCode" pattern="[0-9]{3,6}" required
                 placeholder="如 6610"></div>
        <div class="field"><label class="f">科目名称 *</label>
          <input type="text" name="newName" id="newAccName" required placeholder="如 域名与网络费"></div>
        <div class="field"><label class="f">分类</label>
          <select name="newCategory">
            <option value="expense">费用</option>
            <option value="cogs">销售成本</option>
          </select></div>
      </div>
      <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
        <button type="button" class="btn" onclick="document.getElementById('accCreatePanel').style.display='none'">取消</button>
        <button class="btn primary">建立并返回填单</button>
        <span class="hint">新建后会自动选中该科目；变更写入审计日志</span>
      </div>
    </form>
  </div>
</div>
<script>
(function () {
  var sel = document.getElementById('expAcc');
  var panel = document.getElementById('accCreatePanel');
  if (!sel || !panel) return;
  sel.addEventListener('ssel:create', function (e) {
    var q = (e.detail && e.detail.query) || '';
    panel.style.display = '';
    var nameEl = document.getElementById('newAccName');
    var codeEl = document.getElementById('newAccCode');
    // 搜索词是纯数字就当作编码，否则当作名称
    if (/^\d{3,6}$/.test(q)) { codeEl.value = q; nameEl.focus(); }
    else { nameEl.value = q; codeEl.focus(); }
    panel.scrollIntoView({ block: 'center' });
  });
  <?php if ($newAcc !== ''): ?>
  // 刚建好的科目：提示一下
  var t = document.createElement('div');
  t.className = 'hint';
  t.style.marginTop = '6px';
  t.textContent = '已新建科目 <?= e($newAcc) ?> 并选中';
  sel.parentNode.parentNode.appendChild(t);
  <?php endif; ?>
})();
</script>
<?php endif; ?>

<?php if (!empty($partyErr)): ?>
  <div style="margin-top:12px"><?= errbox($partyErr) ?></div>
<?php endif; ?>
<?php if ($role !== 'auditor'): ?>
  <?= inline_party_create_panel('vendor') ?>
<?php endif; ?>

<script>
/* 供应商档案映射：选完自动填地址、币种、付款条件 */
window._vendors = <?= json_encode(array_map(function ($v) {
    return [
        'name' => (string) ($v['vendor_name'] ?? ''),
        'address' => trim((string) (($v['address'] ?? '') . ' ' . ($v['district'] ?? '') . ' ' . ($v['country'] ?? ''))),
        'currency' => (string) ($v['default_currency'] ?? 'HKD'),
        'termsDays' => (int) ($v['payment_terms_days'] ?? 0),
    ];
}, $vendorList)) ?>;
/* 供应商选「其他」→ 显示手写输入框；选了建档供应商 → 自动填地址/币种/付款天数 */
(function () {
  var sel = document.getElementById('vendName');
  var inp = document.getElementById('vendNameCustom');
  if (!sel || !inp) return;
  function toggle() {
    var custom = sel.value === '__custom__';
    inp.style.display = custom ? '' : 'none';
    inp.required = custom;
    sel.required = !custom;
    if (custom) inp.focus();
  }
  sel.addEventListener('change', toggle);
  toggle();

  sel.addEventListener('ssel:create', function (ev) {
    var panel = document.getElementById('party-create-panel');
    var q = (ev.detail && ev.detail.query) || '';
    if (panel && q) {
      var nm = panel.querySelector('[data-party-field="vendorName"]');
      if (nm) nm.value = q;
    }
  });

  var addrEl = document.querySelector('textarea[name="vendorAddress"]');
  var ccySel = document.querySelector('select[name="currency"]');
  var termsSel = document.getElementById('payTerms');
  var termsMap = { 0: 'due_on_receipt', 15: 'net_15', 30: 'net_30', 45: 'net_45', 60: 'net_60' };
  sel.addEventListener('change', function () {
    var v = sel.value;
    if (!v || v === '__custom__') return;
    var vend = null;
    for (var i = 0; i < (window._vendors || []).length; i++) {
      if (window._vendors[i].name === v) { vend = window._vendors[i]; break; }
    }
    if (!vend) return;
    if (addrEl && addrEl.value.trim() === '') addrEl.value = vend.address;
    if (ccySel && ccySel.value === 'HKD' && vend.currency) ccySel.value = vend.currency;
    if (termsSel) {
      var want = termsMap[vend.termsDays];
      if (want && termsSel.querySelector('option[value="' + want + '"]')) {
        termsSel.value = want;
        termsSel.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  });
})();
</script>

<script>
/* 采购明细：合价 = 数量 × 单价（只读），要调整只能填折扣 */
(function () {
  var body = document.getElementById('billLineBody');
  var addBtn = document.getElementById('billLineAdd');
  if (!body || !addBtn) return;
  function num(el) { var v = parseFloat(el.value); return isFinite(v) ? v : 0; }
  function fmt(n) { return (Math.round(n * 100) / 100).toFixed(2); }

  function sync(tr) {
    var qty = num(tr.querySelector('.bl-qty'));
    var price = num(tr.querySelector('.bl-price'));
    var rate = num(tr.querySelector('.bl-tax'));
    var discPct = Math.min(Math.max(num(tr.querySelector('.bl-disc')), 0), 100);
    var amt = qty * price * (1 - discPct / 100);
    var cell = tr.querySelector('.bl-amt');
    if (cell) {
      var text = cell.firstChild;
      if (text && text.nodeType === 3) text.nodeValue = fmt(amt) + '\n';
      else cell.insertBefore(document.createTextNode(fmt(amt) + '\n'), cell.firstChild);
    }
    var amountInput = tr.querySelector('.bl-amount'), taxInput = tr.querySelector('.bl-tax-amt');
    var tax = amt * rate / 100;
    if (amountInput) amountInput.value = fmt(amt);
    if (taxInput) taxInput.value = fmt(tax);
    return { amt: amt, tax: tax };
  }

  function renumber() {
    body.querySelectorAll('tr').forEach(function (tr, i) {
      var c = tr.querySelector('.bl-seq');
      if (c) c.textContent = i + 1;
    });
  }

  function recalcAll() {
    var lineSum = 0, lineTax = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      var v = sync(tr);
      lineSum += v.amt; lineTax += v.tax;
    });
    var sA = document.getElementById('sumAmt'), sT = document.getElementById('sumTax');
    if (sA) sA.textContent = fmt(lineSum);
    if (sT) sT.textContent = fmt(lineTax);

    var discEl = document.getElementById('discTotal');
    var rateEl = document.getElementById('discRate');
    var disc = discEl ? (parseFloat(discEl.value) || 0) : 0;
    if (disc > lineSum) { disc = lineSum; }
    if (rateEl && lineSum) {
      if (document.activeElement === rateEl) {
        disc = lineSum * (parseFloat(rateEl.value) || 0) / 100;
        if (discEl) discEl.value = fmt(disc);
      } else {
        rateEl.value = (disc / lineSum * 100).toFixed(4).replace(/\.?0+$/, '');
      }
    }
    var netAmt = lineSum - disc;
    var ratio = lineSum ? (netAmt / lineSum) : 0;
    var netTax = lineTax * ratio;

    var a = document.getElementById('amtTotal'), t = document.getElementById('taxTotal');
    if (a) a.value = fmt(netAmt);
    if (t) t.textContent = fmt(netTax);
    var subEl = document.getElementById('sumAmt'), discEl = document.getElementById('discShow'),
        grossEl = document.getElementById('grossTotal');
    if (subEl) subEl.textContent = fmt(lineSum);
    if (discEl) discEl.textContent = fmt(disc);
    if (grossEl) grossEl.textContent = fmt(netAmt + netTax);
    var hA = document.getElementById('amtTotalHidden'), hT = document.getElementById('taxTotalHidden');
    if (hA) hA.value = fmt(netAmt);
    if (hT) hT.value = fmt(netTax);
  }

  function bind(tr) {
    ['bl-qty', 'bl-price', 'bl-tax', 'bl-disc'].forEach(function (cls) {
      tr.querySelector('.' + cls).addEventListener('input', recalcAll);
    });
    tr.querySelector('input[name="lineDesc[]"]').addEventListener('input', recalcAll);
    tr.querySelector('.bl-del').addEventListener('click', function () {
      if (body.querySelectorAll('tr').length <= 1) {
        tr.querySelectorAll('input').forEach(function (i) { i.value = i.name === 'lineQty[]' ? '1' : ''; });
      } else { tr.remove(); }
      renumber(); recalcAll();
    });
  }

  body.querySelectorAll('tr').forEach(bind);
  addBtn.addEventListener('click', function () {
    var tr = body.querySelector('tr').cloneNode(true);
    tr.querySelectorAll('input').forEach(function (i) { i.value = i.name === 'lineQty[]' ? '1' : ''; });
    body.appendChild(tr); bind(tr); renumber();
    tr.querySelector('input[name="lineDesc[]"]').focus();
    recalcAll();
  });
  var d = document.getElementById('discTotal');
  if (d) d.addEventListener('input', recalcAll);
  var dr = document.getElementById('discRate');
  if (dr) dr.addEventListener('input', recalcAll);
  renumber(); recalcAll();
})();
</script>
<script>
/* 摘要 → 科目建议：只给候选，必须人工点击应用 */
(function () {
  var btn = document.getElementById('accSuggestBtn');
  var sel = document.getElementById('expAcc');
  var list = document.getElementById('accSuggestList');
  var msg = document.getElementById('accSuggestMsg');
  if (!btn || !sel || !list || !msg) return;
  var csrfEl = document.querySelector('input[name="_csrf"]');

  function gather() {
    var get = function (sel) { var el = document.querySelector(sel); return el ? el.value : ''; };
    var lines = [];
    document.querySelectorAll('input[name="lineDesc[]"]').forEach(function (el) {
      if (el.value.trim()) lines.push({ description: el.value.trim() });
    });
    return {
      subject: get('input[name="subject"]'),
      vendor: get('#vendName'),
      notes: get('textarea[name="vendorNotes"]'),
      lines: lines,
      csrf: csrfEl ? csrfEl.value : ''
    };
  }

  btn.addEventListener('click', function () {
    var body = gather();
    if (!body.subject.trim() && !body.lines.length) {
      msg.textContent = '请先填写主题或明细';
      return;
    }
    btn.disabled = true;
    msg.textContent = '正在分析…';
    list.innerHTML = '';
    fetch('suggest-account.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); }).then(function (res) {
      btn.disabled = false;
      if (!res.ok) { msg.textContent = res.error || '建议失败'; return; }
      var sugs = (res.data && res.data.suggestions) || [];
      if (!sugs.length) { msg.textContent = '未找到匹配科目，请手选'; return; }
      msg.textContent = '建议（' + (res.data.source === 'ai' ? 'AI' : '关键词') + '）：请确认后应用';
      list.innerHTML = '';
      sugs.forEach(function (s) {
        var row = document.createElement('div');
        row.style.marginTop = '4px';
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn sm';
        b.textContent = s.code + ' ' + s.name;
        b.addEventListener('click', function () {
          sel.value = s.code;
          sel.dispatchEvent(new Event('change'));
          list.innerHTML = '';
          var done = document.createElement('span');
          done.className = 'hint';
          done.textContent = '已应用 ' + s.code + '，可继续修改';
          list.appendChild(done);
        });
        var why = document.createElement('span');
        why.className = 'hint';
        why.style.marginLeft = '6px';
        why.textContent = s.reason || '';
        row.appendChild(b);
        row.appendChild(why);
        list.appendChild(row);
      });
    }).catch(function () {
      btn.disabled = false;
      msg.textContent = '网络错误，请重试';
    });
  });
})();
</script>

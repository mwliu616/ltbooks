<?php
/*
 * LtBooks — pages/invoice-new.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$custR = api_get('/customers?limit=0');
$customerList = $custR['ok'] ? ($custR['data']['customers'] ?? []) : [];
$partyErr = handle_inline_party_create('customer', 'invoice-new', $user ?? []);
$newParty = (string) ($_GET['newparty'] ?? '');
$role = isset($role) ? $role : 'accountant';  // 来自服务端会话
if ($role === 'auditor') { echo empty_state('审计角色不可录入'); return; }

$result = null;
$editId = (int) ($_GET['edit'] ?? 0);
$isEdit = $editId > 0;
$editInv = null;
if ($isEdit) {
    $er = api_get('/invoices/' . $editId);
    $editInv = $er['ok'] ? ($er['data'] ?? null) : null;
    if (!$editInv || ($editInv['status'] ?? '') !== 'draft') {
        echo errbox(t('只有草稿发票可以编辑'));
        return;
    }
}
$formAction = $isEdit ? 'update_invoice' : 'create_invoice';
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === $formAction) {
    $body = [
        'invoiceNo' => trim((string) ($_POST['invoiceNo'] ?? '')),
        'supplierName' => (($_POST['supplierName'] ?? '') === '__custom__'
            ? trim((string) ($_POST['supplierNameCustom'] ?? ''))
            : trim((string) ($_POST['supplierName'] ?? ''))),
        'invoiceDate' => (string) ($_POST['invoiceDate'] ?? ''),
        'revenueRecognitionDate' => (string) ($_POST['revenueRecognitionDate'] ?? '') ?: null,
        'currency' => (string) ($_POST['currency'] ?? 'HKD'),
        'subject' => trim((string) ($_POST['subject'] ?? '')),
        'orderNumber' => trim((string) ($_POST['orderNumber'] ?? '')),
        'paymentTerms' => trim((string) ($_POST['paymentTerms'] ?? '')),
        'salesperson' => trim((string) ($_POST['salesperson'] ?? '')),
        'billingAddress' => trim((string) ($_POST['billingAddress'] ?? '')),
        'shippingAddress' => trim((string) ($_POST['shippingAddress'] ?? '')),
        'customerNotes' => trim((string) ($_POST['customerNotes'] ?? '')),
        'termsConditions' => trim((string) ($_POST['termsConditions'] ?? '')),
        'dueDate' => (string) ($_POST['dueDate'] ?? '') ?: null,
        'amountOriginal' => (float) ($_POST['amountOriginal'] ?? 0),
        'taxOriginal' => (float) ($_POST['taxOriginal'] ?? 0),
        'discountOriginal' => (float) ($_POST['discountOriginal'] ?? 0),
        'discountRate' => (float) ($_POST['discountRate'] ?? 0),
        // 明细行：描述为空的行丢弃；金额与税额由后端按数量×单价重算
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
        'performanceObligationStatus' => (string) ($_POST['performanceObligationStatus'] ?? 'undetermined'),
        'recognitionPattern' => (string) ($_POST['recognitionPattern'] ?? 'point_in_time'),
        'hasUnconditionalRightToPayment' => ($_POST['unconditional'] ?? '') === 'true',
        'requiredDocuments' => array_values(array_filter((array) ($_POST['requiredDocuments'] ?? []))),
        'documents' => array_map(fn($t) => ['type' => $t, 'ref' => 'PHP-upload'], (array) ($_POST['requiredDocuments'] ?? [])),
        'reviewedBy' => trim((string) ($_POST['reviewedBy'] ?? '')) ?: null,
        'actor' => (string) ($user['username'] ?? 'system'),
    ];
    $res = $isEdit
        ? api_post('/invoices/' . $editId . '/update', $body)
        : api_post('/invoices', $body);
    $result = $res['ok'] ? $res['data'] : ['__error' => $res['error']];

    // —— 双按钮：新建态"保存并过账"自动跟过账 ——
    $autoPost = ($_POST['action_flag'] ?? '') === 'post' && !$isEdit && !isset($result['__error']);
    if ($autoPost) {
        $iid = (int) ($result['invoiceId'] ?? 0);
        if ($iid > 0) {
            $pr = api_post('/invoices/' . $iid . '/post',
                           ['actor' => (string) ($user['username'] ?? 'system')]);
            $msg = $pr['ok']
                ? '发票已保存并过账（entryNo=' . (string) ($pr['data']['entryNo'] ?? '') . '）'
                : '发票已保存为草稿，过账失败：' . (string) ($pr['error'] ?? '未知原因');
            header('Location: ?p=invoice-view&id=' . $iid . '&msg=' . urlencode($msg));
            exit;
        }
    }
}

$prefill = [];
if (isset($_GET['prefill']) && !empty($_SESSION['ai_prefill'])) {
    $prefill = $_SESSION['ai_prefill'];
    unset($_SESSION['ai_prefill']);
}
if ($isEdit && $_SERVER['REQUEST_METHOD'] !== 'POST') {
    // 把草稿映射回表单字段；金额由明细重算，避免带入旧的合计口径。
    $ymd = static fn ($v): string => $v ? substr((string) $v, 0, 10) : '';
    foreach ([
        'invoiceNo' => (string) $editInv['invoice_no'],
        'supplierName' => (string) $editInv['supplier_name'],
        'billingAddress' => (string) ($editInv['billing_address'] ?? ''),
        'shippingAddress' => (string) ($editInv['shipping_address'] ?? ''),
        'orderNumber' => (string) ($editInv['order_number'] ?? ''),
        'invoiceDate' => $ymd($editInv['invoice_date'] ?? ''),
        'dueDate' => $ymd($editInv['due_date'] ?? ''),
        'paymentTerms' => (string) ($editInv['payment_terms'] ?? '') ?: 'due_on_receipt',
        'salesperson' => (string) ($editInv['salesperson'] ?? ''),
        'currency' => (string) ($editInv['currency'] ?? 'HKD'),
        'subject' => (string) ($editInv['subject'] ?? ''),
        'customerNotes' => (string) ($editInv['customer_notes'] ?? ''),
        'termsConditions' => (string) ($editInv['terms_conditions'] ?? ''),
        'revenueRecognitionDate' => $ymd($editInv['revenue_recognition_date'] ?? ''),
        'performanceObligationStatus' => (string) ($editInv['performance_obligation_status'] ?? 'undetermined'),
        'recognitionPattern' => (string) ($editInv['recognition_pattern'] ?? 'point_in_time'),
        'discountRate' => (string) (float) ($editInv['discount_rate'] ?? 0),
    ] as $k => $val) {
        $_POST[$k] = $val;
    }
    $editLines = (array) ($editInv['lines'] ?? []);
    $_POST['lineDesc'] = array_map(static fn ($l): string => (string) $l['description'], $editLines);
    $_POST['lineQty'] = array_map(static fn ($l): string => (string) $l['quantity'], $editLines);
    $_POST['linePrice'] = array_map(static fn ($l): string => (string) $l['unit_price'], $editLines);
    $_POST['lineAmount'] = array_map(static fn ($l): string => (string) $l['amount'], $editLines);
    $_POST['lineTax'] = array_map(static fn ($l): string => $l['tax_rate'] !== null ? (string) $l['tax_rate'] : '', $editLines);
    $_POST['lineTaxAmt'] = array_map(static fn ($l): string => (string) ($l['tax_amount'] ?? ''), $editLines);
    $_POST['lineNote'] = array_map(static fn ($l): string => (string) ($l['notes'] ?? ''), $editLines);
    $_POST['lineUnit'] = array_map(static fn ($l): string => (string) ($l['unit'] ?? ''), $editLines);
    $_POST['lineItemCode'] = array_map(static fn ($l): string => (string) ($l['item_code'] ?? ''), $editLines);
    $_POST['lineDisc'] = array_map(static function ($l): string {
        $base = (float) ($l['quantity'] ?? 0) * (float) ($l['unit_price'] ?? 0);
        return $base > 0 ? (string) round((1 - (float) $l['amount'] / $base) * 100, 4) : '0';
    }, $editLines);
}
$v = function (string $k, string $d = '') use ($prefill) {
    $val = $_POST[$k] ?? ($prefill[$k] ?? $d);
    return e((string) $val);
};
$today = date('Y-m-d');
$cur = (string) ($_POST['currency'] ?? 'HKD');

if ($result !== null && isset($result['__error'])) {
    echo errbox((string) $result['__error']);
}

if ($result !== null && !isset($result['__error'])) {
    $st = 'PASS';
    foreach ($result['checks'] as $c) {
        if (($c['status'] ?? '') === 'FAIL') { $st = 'FAIL'; break; }
        if (($c['status'] ?? '') === 'REVIEW') { $st = 'REVIEW'; }
    }
    if (($result['agentCheck']['verdict'] ?? '') === 'FAIL') { $st = 'FAIL'; }
    // 横幅原因按严重度取：先阻断项，再需复核项，最后才是智能体的提示。
    $reasons = [];
    foreach ($result['checks'] as $c) {
        if (($c['status'] ?? '') === 'FAIL' && !empty($c['reason'])) { $reasons[] = $c['reason']; }
    }
    if (!$reasons) {
        foreach ($result['checks'] as $c) {
            if (($c['status'] ?? '') === 'REVIEW' && !empty($c['reason'])) { $reasons[] = $c['reason']; }
        }
    }
    if (!$reasons) {
        $reasons = array_merge($result['agentCheck']['blockedReasons'] ?? [],
                               $result['agentCheck']['reviewReasons'] ?? []);
    }
    echo banner($st, $reasons ? implode('；', $reasons) : null, $result['checks']);
    $newId = (int) ($result['invoiceId'] ?? 0);
    if ($newId > 0) {
        // 表单里带的附件：落盘并登记到这张发票
        if (!empty($_FILES['attach']['name'][0])) {
            $actor = (string) ($user['username'] ?? 'system');
            foreach ((array) $_FILES['attach']['name'] as $i => $orig) {
                $tmp = (string) ($_FILES['attach']['tmp_name'][$i] ?? '');
                if ($tmp === '' || (int) ($_FILES['attach']['error'][$i] ?? 1) !== UPLOAD_ERR_OK) { continue; }
                if ((int) ($_FILES['attach']['size'][$i] ?? 0) > 20 * 1024 * 1024) { continue; }
                $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', basename((string) $orig));
                $dest = UPLOAD_DIR . '/' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
                if (!@move_uploaded_file($tmp, $dest)) { continue; }
                @chmod($dest, 0640);
                api_post('/invoice-files', [
                    'invoiceId' => $newId,
                    'fileName' => (string) $orig,
                    'fileType' => strtolower(pathinfo($safe, PATHINFO_EXTENSION)) ?: 'other',
                    'fileSize' => (int) filesize($dest),
                    'sha256' => (string) hash_file('sha256', $dest),
                    'storagePath' => $dest,
                    'actor' => $actor,
                ]);
            }
        }
        $invNo = (string) ($result['invoiceNo'] ?? '');
        // 保存后当场问：过账还是先放着，不用跳去别的页面确认
        echo '<div class="toolbar" style="margin-top:10px">'
           . '<a class="btn" href="?p=invoice-view&id=' . $newId . '">查看发票详情</a>'
           . '<a class="btn" href="?p=invoice-new">继续新建</a>'
           . '</div>';

        // 弹窗让用户当场决定：过账 / 先放着
        // 只要有阻断项（FAIL）就不让点；校验提示（REVIEW）只提示，不拦
        $blocking = ($result['agentCheck']['verdict'] ?? '') === 'FAIL';
        foreach ($result['checks'] as $c) {
            if (($c['status'] ?? '') === 'FAIL') { $blocking = true; break; }
        }
        $canPost = !$blocking;
        $warn = [];
        foreach ($result['checks'] as $c) {
            if (($c['status'] ?? '') === 'REVIEW' && !empty($c['reason'])) { $warn[] = $c['reason']; }
        }
        $warn = array_merge($warn, $result['agentCheck']['reviewReasons'] ?? []);
        echo '<div id="postAsk" style="display:none;position:fixed;inset:0;z-index:9998;'
           . 'background:rgba(15,23,42,.45)"></div>';
        echo '<div id="postAskWin" style="display:none;position:fixed;top:50%;left:50%;'
           . 'transform:translate(-50%,-50%);width:min(460px,92vw);background:var(--c-surface);border-radius:12px;'
           . 'box-shadow:0 24px 70px rgba(0,0,0,.35);z-index:9999;padding:22px 24px">'
           . '<div style="font-size:var(--f-lg);margin-bottom:6px">发票已保存</div>'
           . '<div class="hint" style="margin-bottom:16px">' . e($invNo) . ' · 草稿</div>'
           . '<div style="font-size:var(--f-sm);color:var(--c-text-2);margin-bottom:18px">'
           . ($canPost
                ? '现在过账吗？过账后发票正式入账，应收账款即产生。'
                : '这张发票有阻断项，不能直接过账，请先处理后再过账。')
           . ($warn && $canPost
                ? '<div class="hint" style="margin-top:8px">提示：' . e(implode('；', array_slice($warn, 0, 3))) . '</div>'
                : '')
           . '</div>'
           . '<form method="post" action="?p=invoices" style="display:flex;flex-direction:column;gap:8px">'
           . csrf_field()
           . '<input type="hidden" name="action" value="post_invoice">'
           . '<input type="hidden" name="id" value="' . $newId . '">'
           . '<input type="hidden" name="back" value="invoice-view">'
           . '<button class="btn primary" name="do" value="post"' . ($canPost ? '' : ' disabled') . '>'
           . ($canPost ? '过账' : '过账（校验未通过，暂不可用）') . '</button>'
           . '</form>'
           . '<a class="btn" style="width:100%;justify-content:center;margin-top:8px" '
           . 'href="?p=invoice-view&id=' . $newId . '">不过账，先看看</a>'
           . '<a class="btn" style="width:100%;justify-content:center;margin-top:8px" '
           . 'href="?p=invoices">不过账，回到发票列表</a>'
           . '</div>';
        echo '<script>(function(){'
           . 'var m=document.getElementById("postAsk"),w=document.getElementById("postAskWin");'
           . 'if(!m||!w)return;m.style.display="";w.style.display="";'
           . 'document.addEventListener("keydown",function(e){if(e.key==="Escape"){m.style.display="none";w.style.display="none";}});'
           . '})();</script>';
    }
}
?>
<div class="banner <?= $isEdit ? 'REVIEW' : 'PASS' ?>" style="<?= $isEdit ? '' : 'background:var(--c-ok-soft);border-color:var(--c-ok-border);color:var(--c-ok)' ?>">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title"><?= e($isEdit ? '编辑发票草稿' : '这是「收入」单据') ?></div>
    <div class="banner-reason">
      <?= $isEdit
          ? e(str_replace('{no}', (string) $editInv['invoice_no'], t('发票编号 {no} 保持不变；保存后重新校验，过账前仍可继续修改。')))
          : '你开给客户的发票记在这里：借 应收／合同资产，贷 收入。
      供应商开给你的发票（支出）请用「新建采购发票」。' ?>
    </div>
  </div>
</div>


<form method="post" enctype="multipart/form-data">
  <?= csrf_field() ?>
<input type="hidden" name="action" value="<?= e($formAction) ?>">

<?php ob_start(); ?>
<div class="zform">
  <!-- 左：客户与地址 -->
  <div class="zcol">
    <div class="zsec-h">往来与摘要</div>
    <div class="field"><label class="f">客户名称 *</label>
      <?php
      $curCust = (string) ($_POST['supplierName'] ?? ($newParty !== '' ? $newParty : ''));
      $custOpts = '<option value="">— 选择客户 —</option>';
      $seen = [];
      foreach ($customerList as $cc) {
          $cn = (string) $cc['customer_name'];
          $seen[$cn] = true;
          $custOpts .= '<option value="' . e($cn) . '"' . ($curCust === $cn ? ' selected' : '') . '>'
                     . e($cn . ($cc['customer_code'] ? '（' . $cc['customer_code'] . '）' : '')) . '</option>';
      }
      if ($curCust !== '' && !isset($seen[$curCust])) {
          $custOpts .= '<option value="' . e($curCust) . '" selected>' . e($curCust) . '（未建档）</option>';
      }
      $isCustomName = ($curCust !== '' && !isset($seen[$curCust]));
      if ($role !== 'auditor'):
          $custOpts .= '<option value="__custom__"' . ($isCustomName ? ' selected' : '') . '>+ 新客户（手写名称）</option>';
      endif;
      ?>
      <select name="supplierName" id="custName" required data-allow-create="1"><?= $custOpts ?></select>
      <input type="text" name="supplierNameCustom" id="custNameCustom"
             value="<?= e($isCustomName ? $curCust : '') ?>" placeholder="输入客户名称"
             style="margin-top:6px;<?= $isCustomName ? '' : 'display:none' ?>">
    </div>
    <div class="field"><label class="f">地址</label>
      <textarea name="billingAddress" rows="3" placeholder="客户地址"><?= e((string) ($_POST['billingAddress'] ?? '')) ?></textarea>
    </div>
    <div class="field"><label class="f">主题</label>
      <input type="text" name="subject" value="<?= e((string) ($_POST['subject'] ?? '')) ?>" placeholder="例：2026 年度系统维护服务">
    </div>
  </div>

  <!-- 右：单据信息 -->
  <div class="zcol zcol-2">
    <div class="zsec-h">单据信息</div>
    <div class="z2">
      <?= doc_no_field('发票编号', next_doc_no((string) ($_POST['invoiceDate'] ?? date('Y-m-d')), 'invoice'), 'invoiceNo') ?>
      <div class="field"><label class="f">订单号</label>
        <input type="text" name="orderNumber" value="<?= e((string) ($_POST['orderNumber'] ?? '')) ?>" placeholder="选填">
      </div>
      <div class="field"><label class="f">发票日期 *</label>
        <input type="date" name="invoiceDate" id="invDate" value="<?= $v('invoiceDate', $today) ?>" required>
      </div>
      <div class="field"><label class="f">到期日 *</label>
        <input type="date" name="dueDate" id="dueDate" value="<?= e((string) ($_POST['dueDate'] ?? '')) ?>" required>
      </div>
      <div class="field"><label class="f">付款条件</label>
        <select name="paymentTerms" id="payTerms">
          <?php foreach (['due_on_receipt' => '收到即付', 'net_15' => 'Net 15', 'net_30' => 'Net 30',
                          'net_45' => 'Net 45', 'net_60' => 'Net 60', 'custom' => '自定义'] as $k => $lab): ?>
            <option value="<?= e($k) ?>"<?= (($_POST['paymentTerms'] ?? 'due_on_receipt') === $k) ? ' selected' : '' ?>><?= e($lab) ?></option>
          <?php endforeach; ?>
        </select>
      </div>
      <div class="field"><label class="f">销售员</label>
        <input type="text" name="salesperson" value="<?= e((string) ($_POST['salesperson'] ?? '')) ?>" placeholder="选填">
      </div>
      <div class="field"><label class="f">币种</label>
        <select name="currency"><?= currency_options($cur) ?></select>
      </div>
    </div>
  </div>
</div>
<?php echo card('', ob_get_clean(), '', false); ?>

<?php ob_start(); ?>
<?php
$vLines = [];
foreach ((array) ($_POST['lineDesc'] ?? []) as $i => $d) {
    if (trim((string) $d) === '') { continue; }
    $vLines[] = [
        'desc'  => (string) $d,
        'qty'   => (string) ($_POST['lineQty'][$i] ?? '1'),
        'price' => (string) ($_POST['linePrice'][$i] ?? ''),
        'disc'  => (string) ($_POST['lineDisc'][$i] ?? '0'),
        'tax'   => (string) ($_POST['lineTax'][$i] ?? ''),
        'unit'  => (string) ($_POST['lineUnit'][$i] ?? ''),
        'code'  => (string) ($_POST['lineItemCode'][$i] ?? ''),
        'note'  => (string) ($_POST['lineNote'][$i] ?? ''),
        'taxAmt'=> (string) ($_POST['lineTaxAmt'][$i] ?? ''),
        'amount'=> (string) ($_POST['lineAmount'][$i] ?? ''),
    ];
}
if (!$vLines) { $vLines = [['desc'=>'','qty'=>'1','price'=>'','disc'=>'0','tax'=>'','unit'=>'','code'=>'','note'=>'','taxAmt'=>'','amount'=>'']]; }
?>
<div class="table-wrap"><table id="lineTable" style="min-width:0">
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
  <tbody id="lineBody">
  <?php foreach ($vLines as $i => $ln): ?>
    <tr>
      <td class="num hint ln-seq"><?= $i + 1 ?></td>
      <td><input type="text" name="lineDesc[]" value="<?= e($ln['desc']) ?>" placeholder="描述这个项目或服务" style="width:100%">
        <input type="hidden" name="lineUnit[]" value="<?= e($ln['unit']) ?>">
        <input type="hidden" name="lineItemCode[]" value="<?= e($ln['code']) ?>">
        <input type="hidden" name="lineNote[]" value="<?= e($ln['note']) ?>">
      </td>
      <td><input type="number" step="0.0001" min="0" name="lineQty[]" value="<?= e($ln['qty']) ?>" class="ln-qty" style="width:100%"></td>
      <td><input type="number" step="0.01" min="0" name="linePrice[]" value="<?= e($ln['price']) ?>" class="ln-price" style="width:100%"></td>
      <td><input type="number" step="0.01" min="0" max="100" name="lineDisc[]" value="<?= e($ln['disc']) ?>" class="ln-disc" style="width:100%"></td>
      <td><input type="number" step="0.01" min="0" max="100" name="lineTax[]" value="<?= e($ln['tax']) ?>" class="ln-tax" style="width:100%"></td>
      <td class="num ln-amt" style="font-variant-numeric:tabular-nums">0.00
        <input type="hidden" name="lineAmount[]" class="ln-amount" value="<?= e($ln['amount']) ?>">
        <input type="hidden" name="lineTaxAmt[]" class="ln-tax-amt" value="<?= e($ln['taxAmt']) ?>">
      </td>
      <td><button type="button" class="btn sm ln-del" title="删除本行">×</button></td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
<div class="toolbar" style="margin-top:10px">
  <button type="button" class="btn sm" id="lineAdd"><?= e(t('＋ 添加一行')) ?></button>
  <span class="grow"></span>
  <span class="hint">金额 = 数量 × 单价 ×（1 − 折扣%）</span>
</div>
<?php echo card('项目明细', ob_get_clean()); ?>

<div class="zfoot">
  <div class="zfoot-left">
    <?php ob_start(); ?>
    <div class="field"><label class="f"><?= e(t('客户备注')) ?></label>
      <textarea name="customerNotes" rows="3" placeholder="<?= e(t('仅内部记录，不会显示在导出的发票上')) ?>"><?= e((string) ($_POST['customerNotes'] ?? '')) ?></textarea>
    </div>
    <div class="field"><label class="f"><?= e(t('条款与条件')) ?></label>
      <textarea name="termsConditions" rows="3" placeholder="<?= e(t('仅内部记录，不会显示在导出的发票上')) ?>"><?= e((string) ($_POST['termsConditions'] ?? '')) ?></textarea>
    </div>
    <?php echo card('', ob_get_clean(), '', false); ?>
  </div>

  <div class="zfoot-right">
    <?php ob_start(); ?>
    <input type="hidden" name="amountOriginal" id="amtTotalHidden" value="0">
    <input type="hidden" name="taxOriginal" id="taxTotalHidden" value="0">
    <input type="hidden" name="discountOriginal" id="discTotal" value="0">
    <table class="totals">
      <tr><td>小计</td><td class="num" id="sumAmt">0.00</td></tr>
      <tr><td>折扣</td><td class="num" id="discShow">0.00</td></tr>
      <tr><td>税额</td><td class="num" id="taxTotal">0.00</td></tr>
      <tr class="grand"><td>合计</td><td class="num" id="grossTotal">0.00</td></tr>
    </table>
    <div class="hint" style="margin-top:6px">整体折扣率
      <input type="number" step="0.01" min="0" max="100" id="discRate" name="discountRate" value="<?= $v('discountRate', '0') ?>"
             style="width:70px;display:inline-block"> %
    </div>
    <?php echo card('', ob_get_clean(), '', false); ?>
  </div>
</div>

<?php ob_start(); ?>
<div class="grid">
  <div class="field"><label class="f">收入确认日</label>
    <input type="date" name="revenueRecognitionDate" value="<?= $v('revenueRecognitionDate') ?>">
    <div class="hint">汇率绑定此日；不填按发票日期</div></div>
  <div class="field"><label class="f">履约义务</label>
    <select name="performanceObligationStatus">
      <?php foreach (['unfulfilled' => t('未履行'), 'partial' => t('部分履行'),
                      'fulfilled' => t('已履行'), 'undetermined' => t('未确定')] as $k => $lab): ?>
        <option value="<?= e($k) ?>"<?= ($_POST['performanceObligationStatus'] ?? '') === $k ? ' selected' : '' ?>><?= e($lab) ?></option>
      <?php endforeach; ?>
    </select></div>
  <div class="field"><label class="f">确认模式</label>
    <select name="recognitionPattern">
      <option value="point_in_time"><?= e(t('时点确认')) ?></option>
      <option value="over_time"<?= ($_POST['recognitionPattern'] ?? '') === 'over_time' ? ' selected' : '' ?>>时段确认</option>
    </select></div>
  <div class="field"><label class="f">收款权</label>
    <select name="unconditional">
      <option value="false">尚未无条件（可能入合同资产）</option>
      <option value="true"<?= ($_POST['unconditional'] ?? '') === 'true' ? ' selected' : '' ?>>已无条件（入应收）</option>
    </select></div>
  <div class="field"><label class="f">支持性文档</label>
    <select name="requiredDocuments[]" multiple size="3">
      <?php foreach (['invoice' => t('发票'), 'contract' => t('合同'), 'delivery_note' => t('交付单')] as $doc => $dl): ?>
        <option value="<?= e($doc) ?>" selected><?= e($dl) ?></option>
      <?php endforeach; ?>
    </select></div>
  <div class="field"><label class="f">复核人</label>
    <input type="text" name="reviewedBy" value="<?= $v('reviewedBy') ?>" placeholder="选填">
  </div>
</div>
<?php echo card('收入确认（HKFRS 15）', ob_get_clean(), '', false); ?>

<?php ob_start(); ?>
<label class="dropzone" for="invFiles">
  <input type="file" id="invFiles" name="attach[]" multiple
         accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.doc,.docx"
         style="position:absolute;width:1px;height:1px;opacity:0">
  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5-5 5 5"/><path d="M12 5v12"/>
  </svg>
  <span class="dz-title"><?= e(t('把合同、PO、送货单拖到这里')) ?></span>
  <span class="hint"><?= e(t('或点击选择文件 · 单个不超过 20MB · 保存后自动挂到这张发票')) ?></span>
</label>
<div id="dzList" class="dz-list"></div>
<script>
(function () {
  var input = document.getElementById('invFiles');
  var list = document.getElementById('dzList');
  if (!input || !list) return;
  function render() {
    list.innerHTML = '';
    Array.prototype.forEach.call(input.files || [], function (f) {
      var row = document.createElement('div');
      row.className = 'dz-item';
      row.innerHTML = '<span class="dz-name"></span><span class="hint">' +
        (f.size / 1024).toFixed(0) + ' KB</span>';
      row.querySelector('.dz-name').textContent = f.name;
      list.appendChild(row);
    });
  }
  input.addEventListener('change', render);
  var zone = input.closest('.dropzone');
  ['dragenter', 'dragover'].forEach(function (e) {
    zone.addEventListener(e, function (ev) { ev.preventDefault(); zone.classList.add('over'); });
  });
  ['dragleave', 'drop'].forEach(function (e) {
    zone.addEventListener(e, function (ev) { ev.preventDefault(); zone.classList.remove('over'); });
  });
  zone.addEventListener('drop', function (ev) {
    if (ev.dataTransfer && ev.dataTransfer.files.length) {
      input.files = ev.dataTransfer.files; render();
    }
  });
})();
</script>
<?php echo card(t('附件'), ob_get_clean(), '', false); ?>

<div class="toolbar" style="justify-content:flex-end">
  <a class="btn" href="<?= $isEdit ? '?p=invoice-view&id=' . $editId : '?p=invoices' ?>">取消</a>
  <?php if ($isEdit): ?>
    <button class="btn primary" type="submit" data-shortcut-save><?= e('保存修改') ?></button>
  <?php else: ?>
    <button class="btn" name="action_flag" value="post" data-shortcut-post>保存并过账</button>
    <button class="btn primary" name="action_flag" value="draft" data-shortcut-save>保存草稿</button>
  <?php endif; ?>
</div>
</form>

<script>
/* 客户档案映射：选完客户自动填地址、币种、付款条件 */
window._customers = <?= json_encode(array_map(function ($c) {
    return [
        'name' => (string) ($c['customer_name'] ?? ''),
        'address' => trim((string) (($c['address'] ?? '') . ' ' . ($c['district'] ?? '') . ' ' . ($c['country'] ?? ''))),
        'currency' => (string) ($c['default_currency'] ?? 'HKD'),
        'termsDays' => (int) ($c['payment_terms_days'] ?? 0),
    ];
}, $customerList)) ?>;
/* 客户选「其他」→ 显示手写输入框；选了建档客户 → 自动填地址/币种/付款天数 */
(function () {
  var sel = document.getElementById('custName');
  var inp = document.getElementById('custNameCustom');
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

  /* ssel:create — 搜索框搜不到，点了「＋ 新建」 */
  sel.addEventListener('ssel:create', function (ev) {
    var panel = document.getElementById('party-create-panel');
    var q = (ev.detail && ev.detail.query) || '';
    if (panel && q) {
      var nm = panel.querySelector('[data-party-field="customerName"]');
      if (nm) nm.value = q;
    }
  });

  /* 选了建档客户 → 自动带出默认地址、币种、付款条件 */
  var addrEl = document.querySelector('textarea[name="billingAddress"]');
  var ccySel = document.querySelector('select[name="currency"]');
  var termsSel = document.getElementById('payTerms');
  var termsMap = { 0: 'due_on_receipt', 15: 'net_15', 30: 'net_30', 45: 'net_45', 60: 'net_60' };
  sel.addEventListener('change', function () {
    var v = sel.value;
    if (!v || v === '__custom__') return;
    var cust = null;
    for (var i = 0; i < (window._customers || []).length; i++) {
      if (window._customers[i].name === v) { cust = window._customers[i]; break; }
    }
    if (!cust) return;
    if (addrEl && addrEl.value.trim() === '') addrEl.value = cust.address;
    if (ccySel && ccySel.value === 'HKD' && cust.currency) ccySel.value = cust.currency;
    if (termsSel) {
      var want = termsMap[cust.termsDays];
      if (want && termsSel.querySelector('option[value="' + want + '"]')) {
        termsSel.value = want;
        termsSel.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  });
})();
</script>



<?php if (!empty($partyErr)): ?>
  <div style="margin-top:12px"><?= errbox($partyErr) ?></div>
<?php endif; ?>
<?php if ($role !== 'auditor'): ?>
  <?= inline_party_create_panel('customer') ?>
<?php endif; ?>

<script>
/* 明细清单：合价 = 数量 × 单价 ×（1 − 行折扣%），税额按行税率；整单折扣作用于小计 */
(function () {
  var body = document.getElementById('lineBody');
  var addBtn = document.getElementById('lineAdd');
  if (!body || !addBtn) return;

  function num(el) { var v = el ? parseFloat(el.value) : 0; return isFinite(v) ? v : 0; }
  function fmt(n) { return (Math.round(n * 100) / 100).toFixed(2); }
  function $(id) { return document.getElementById(id); }

  function sync(tr) {
    var qty = num(tr.querySelector('.ln-qty'));
    var price = num(tr.querySelector('.ln-price'));
    var disc = Math.min(Math.max(num(tr.querySelector('.ln-disc')), 0), 100);
    var rate = num(tr.querySelector('.ln-tax'));
    var amt = qty * price * (1 - disc / 100);
    var cell = tr.querySelector('.ln-amt');
    if (cell) {
      var text = cell.firstChild;
      if (text && text.nodeType === 3) text.nodeValue = fmt(amt) + '\n';
      else cell.insertBefore(document.createTextNode(fmt(amt) + '\n'), cell.firstChild);
    }
    var amountInput = tr.querySelector('.ln-amount'), taxInput = tr.querySelector('.ln-tax-amt');
    var tax = amt * rate / 100;
    if (amountInput) amountInput.value = fmt(amt);
    if (taxInput) taxInput.value = fmt(tax);
    return { amt: amt, tax: tax };
  }

  function renumber() {
    body.querySelectorAll('tr').forEach(function (tr, i) {
      var c = tr.querySelector('.ln-seq');
      if (c) c.textContent = i + 1;
    });
  }

  function recalcAll() {
    var sub = 0, taxSum = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      var v = sync(tr);
      sub += v.amt; taxSum += v.tax;
    });

    var rateEl = $('discRate');
    var discRate = Math.min(Math.max(num(rateEl), 0), 100);
    var discAmt = sub * discRate / 100;
    var net = sub - discAmt;
    var taxNet = sub ? taxSum * (net / sub) : 0;
    var gross = net + taxNet;

    if ($('sumAmt')) $('sumAmt').textContent = fmt(sub);
    if ($('discShow')) $('discShow').textContent = fmt(discAmt);
    if ($('taxTotal')) $('taxTotal').textContent = fmt(taxNet);
    if ($('grossTotal')) $('grossTotal').textContent = fmt(gross);
    if ($('amtTotalHidden')) $('amtTotalHidden').value = fmt(net);
    if ($('taxTotalHidden')) $('taxTotalHidden').value = fmt(taxNet);
    if ($('discTotal')) $('discTotal').value = fmt(discAmt);
  }

  function bind(tr) {
    ['ln-qty', 'ln-price', 'ln-tax', 'ln-disc'].forEach(function (cls) {
      var el = tr.querySelector('.' + cls);
      if (el) el.addEventListener('input', recalcAll);
    });
    var d = tr.querySelector('input[name="lineDesc[]"]');
    if (d) d.addEventListener('input', recalcAll);
    var del = tr.querySelector('.ln-del');
    if (del) del.addEventListener('click', function () {
      if (body.querySelectorAll('tr').length <= 1) {
        tr.querySelectorAll('input').forEach(function (i) {
          i.value = (i.name === 'lineQty[]') ? '1' : ((i.name === 'lineDisc[]') ? '0' : '');
        });
      } else { tr.remove(); }
      renumber(); recalcAll();
    });
  }

  body.querySelectorAll('tr').forEach(bind);
  addBtn.addEventListener('click', function () {
    var tr = body.querySelector('tr').cloneNode(true);
    tr.querySelectorAll('input').forEach(function (i) {
      i.value = (i.name === 'lineQty[]') ? '1' : ((i.name === 'lineDisc[]') ? '0' : '');
    });
    body.appendChild(tr); bind(tr); renumber();
    tr.querySelector('input[name="lineDesc[]"]').focus();
    recalcAll();
  });
  var dr = $('discRate');
  if (dr) dr.addEventListener('input', recalcAll);

  // 付款条件 → 到期日
  var terms = $('payTerms'), dEl = $('invDate'), dueEl = $('dueDate');
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

  renumber(); recalcAll();
})();
</script>

<?php
/*
 * LtBooks — pages/customers.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'save_customer') {
    $r = api_post('/customers', [
        'customerId' => (int) ($_POST['customerId'] ?? 0) ?: null,
        'customerCode' => trim((string) ($_POST['customerCode'] ?? '')),
        'customerName' => trim((string) ($_POST['customerName'] ?? '')),
        'customerType' => ($_POST['customerType'] ?? 'company') === 'individual' ? 'individual' : 'company',
        'defaultCurrency' => (string) ($_POST['defaultCurrency'] ?? 'HKD'),
        'paymentTermsDays' => (int) ($_POST['paymentTermsDays'] ?? 30),
        'isRelatedParty' => !empty($_POST['isRelatedParty']),
        'email' => trim((string) ($_POST['email'] ?? '')),
        // 详细资料（都可空，填了才存）
        'contactName'  => trim((string) ($_POST['contactName'] ?? '')) ?: null,
        'contactTitle' => trim((string) ($_POST['contactTitle'] ?? '')) ?: null,
        'phone'        => trim((string) ($_POST['phone'] ?? '')) ?: null,
        'mobile'       => trim((string) ($_POST['mobile'] ?? '')) ?: null,
        'fax'          => trim((string) ($_POST['fax'] ?? '')) ?: null,
        'address'      => trim((string) ($_POST['address'] ?? '')) ?: null,
        'district'     => trim((string) ($_POST['district'] ?? '')) ?: null,
        'country'      => trim((string) ($_POST['country'] ?? '')) ?: null,
        'website'      => trim((string) ($_POST['website'] ?? '')) ?: null,
        'taxId'        => trim((string) ($_POST['taxId'] ?? '')) ?: null,
        'notes'        => trim((string) ($_POST['notes'] ?? '')) ?: null,
        'actor' => $displayName ?? 'system',
    ]);
    if ($r['ok']) {
        header('Location: ?p=customers&msg=' . urlencode('客户已保存'));
        exit;
    }
    $errMsg = (string) $r['error'];
}
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'delete_customer') {
    $r = api_request('DELETE', '/customers/' . (int) ($_POST['customerId'] ?? 0)
        . '?actor=' . urlencode((string) ($displayName ?? 'system')));
    if ($r['ok']) {
        header('Location: ?p=customers&msg=' . urlencode('客户已删除'));
        exit;
    }
    $errMsg = (string) $r['error'];
}
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'extract_party') {
    $payload = ['text' => trim((string) ($_POST['partyText'] ?? ''))];
    if (!empty($_FILES['partyFile']['tmp_name']) && ($_FILES['partyFile']['error'] ?? 1) === UPLOAD_ERR_OK) {
        if (($_FILES['partyFile']['size'] ?? 0) > 20 * 1024 * 1024) {
            $errMsg = '文件超过 20MB';
        } else {
            $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', basename((string) $_FILES['partyFile']['name']));
            $dest = UPLOAD_DIR . '/party-' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
            if (move_uploaded_file($_FILES['partyFile']['tmp_name'], $dest)) {
                @chmod($dest, 0640);
                $payload = ['path' => $dest];
            } else {
                $errMsg = '文件落盘失败';
            }
        }
    }
    if ($errMsg === null && empty($payload['text']) && empty($payload['path'])) {
        $errMsg = '请上传名片 / 注册证书，或粘贴客户资料文本';
    }
    if ($errMsg === null) {
        $rr = api_post('/ai/extract-party', $payload);
        if ($rr['ok']) {
            $_SESSION['party_prefill'] = $rr['data'];
            $back = (int) ($_POST['editId'] ?? 0) > 0
                ? '?p=customers&edit=' . (int) $_POST['editId'] . '&ai=1'
                : '?p=customers&new=1&ai=1';
            header('Location: ' . $back);
            exit;
        }
        $errMsg = (string) $rr['error'];
    }
}
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

// ?edit=<id> 时把表单切成编辑模式并预填该客户
$editId = (int) ($_GET['edit'] ?? 0);
$E = null;
if ($editId > 0) {
    $er = api_get('/customers/' . $editId);
    if ($er['ok']) { $E = $er['data']; }
}
// AI 识别结果只用于回填空字段，已有资料不会被覆盖
$P = !empty($_SESSION['party_prefill']) ? $_SESSION['party_prefill'] : null;
unset($_SESSION['party_prefill']);
if ($P) {
    $PI = [
        'customer_type' => ($P['customerType'] ?? 'company') === 'individual' ? 'individual' : 'company',
        'customer_name' => $P['customerName'] ?? '',
        'contact_name' => $P['contactName'] ?? '',
        'contact_title' => $P['contactTitle'] ?? '',
        'phone' => $P['phone'] ?? '',
        'mobile' => $P['mobile'] ?? '',
        'fax' => $P['fax'] ?? '',
        'email' => $P['email'] ?? '',
        'website' => $P['website'] ?? '',
        'tax_id' => $P['taxId'] ?? '',
        'address' => $P['address'] ?? '',
        'district' => $P['district'] ?? '',
        'country' => $P['country'] ?? '',
        'default_currency' => $P['currency'] ?? '',
        'payment_terms_days' => $P['paymentTermsDays'] ?? 30,
        'notes' => $P['notes'] ?? '',
    ];
    $E = $E ?: [];
    foreach ($PI as $k => $v) {
        if (!isset($E[$k]) || $E[$k] === '' || $E[$k] === null) { $E[$k] = $v; }
    }
}
$formMode = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $editId > 0 || $errMsg !== null || $P !== null);
if (!$formMode):
[$page, $per] = pager_state('ledu_customers_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kwPage = trim((string) ($_GET['q'] ?? ''));
$r = api_get('/customers?limit=' . $limit . '&offset=' . $offset
           . ($kwPage !== '' ? '&q=' . urlencode($kwPage) : ''));
$rows = $r['ok'] ? ($r['data']['customers'] ?? []) : [];
$totalRows = (int) ($r['data']['total'] ?? count($rows));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }
ob_start();
if (!$rows) { echo empty_state('暂无客户'); } else { ?>
<div class="table-wrap"><table>
<thead><tr><th>编码</th><th>名称</th><th>类型</th><th>联系人</th><th>电话</th><th>邮箱</th>
<th>地区</th><th>币种</th><th class="num">账期</th><th>状态</th><th style="width:90px">操作</th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<tr><td class="mono"><a href="?p=party-view&type=customer&id=<?= (int) $x['customer_id'] ?>"><?= e((string) $x['customer_code']) ?></a></td>
<td><a href="?p=party-view&type=customer&id=<?= (int) $x['customer_id'] ?>"><?= e((string) $x['customer_name']) ?></a>
  <?php if (!empty($x['is_related_party'])): ?><span class="badge review">关联方</span><?php endif; ?></td>
<td><?php if (($x['customer_type'] ?? 'company') === 'individual'): ?><span class="badge">个人</span><?php else: ?><span class="badge">公司</span><?php endif; ?></td>
<td><?= e((string) ($x['contact_name'] ?: '—')) ?>
  <?php if (!empty($x['contact_title'])): ?><div class="hint"><?= e((string) $x['contact_title']) ?></div><?php endif; ?></td>
<td class="hint" style="white-space:nowrap"><?= e((string) ($x['phone'] ?: ($x['mobile'] ?: '—'))) ?></td>
<td class="hint"><?= e((string) ($x['email'] ?? '—')) ?></td>
<td class="hint"><?= e((string) ($x['district'] ?: ($x['country'] ?: '—'))) ?></td>
<td><?= e((string) $x['default_currency']) ?></td>
<td class="num"><?= (int) $x['payment_terms_days'] ?> <?= e(t('天')) ?></td>
<td><?= status_pill((string) $x['status']) ?></td>
<td><?php if ($role !== 'auditor'): ?>
  <form method="post" style="display:inline">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="delete_customer">
    <input type="hidden" name="customerId" value="<?= (int) $x['customer_id'] ?>">
    <button type="submit" class="btn sm ghost"
            data-confirm="确定删除该客户？"
            data-confirm-note="仅未被单据引用的客户可删除；删除后不可恢复。"
            data-confirm-ok="删除">删除</button>
  </form>
<?php endif; ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php }
// 列表版式：筛选与搜索单独一行，分页放在卡片底部
$listBar = '<form method="get" class="list-bar">'
    . '<input type="hidden" name="p" value="customers">'
    . '<select name="st" onchange="this.form.submit()">'
    . '<option value="">' . e(t('全部客户')) . '</option>'
    . '<option value="active"' . (($_GET['st'] ?? '') === 'active' ? ' selected' : '') . '>启用</option>'
    . '<option value="inactive"' . (($_GET['st'] ?? '') === 'inactive' ? ' selected' : '') . '>停用</option>'
    . '</select>'
    . '<input type="text" name="q" value="' . e($kwPage) . '" placeholder="搜索编码 / 名称 / 联系人 / 电话" style="width:280px">'
    . '<button class="btn sm">搜索</button>'
    . ($kwPage !== '' ? '<a class="btn sm" href="?p=customers">清除</a>' : '')
    . '</form>';
echo card('', $listBar . ob_get_clean(),
    pager_html($page, $per, $totalRows, ['p' => 'customers', 'q' => $kwPage ?: null]), false);
endif;

if ($formMode):
$ctype = ($E['customer_type'] ?? 'company') === 'individual' ? 'individual' : 'company';
// AI 识别：上传名片/证书或粘贴资料，结果回填到下面的表单（只填空字段）
ob_start(); ?>
<form method="post" enctype="multipart/form-data" id="aiExtractForm">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="extract_party">
  <?php if ($editId > 0): ?><input type="hidden" name="editId" value="<?= (int) $editId ?>"><?php endif; ?>
  <div class="grid form-grid">
    <div class="field"><label class="f">上传名片 / 注册证书 / 客户资料</label>
      <input type="file" name="partyFile" accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.csv">
      <div class="hint">PDF、图片或文本；扫描件请保持清晰</div></div>
    <div class="field span-full"><label class="f">或粘贴资料文本</label>
      <textarea name="partyText" rows="3" placeholder="公司名称、联系人、电话、地址、邮箱、商业登记号…"></textarea></div>
  </div>
  <div class="toolbar form-actions" style="margin-top:10px;margin-bottom:0">
    <button class="btn primary" id="aiExtractBtn">AI 识别并回填</button>
    <span class="hint">识别结果只填入空字段，保存前请逐项核对</span>
  </div>
</form>
<div class="pc-box" id="aiExtractProgress" data-state="loading" hidden>
  <div class="pc-head">
    <div class="pc-title">AI 识别 <span class="pc-agent">客户资料</span><span class="pc-badge pc-loading-badge">识别中</span></div>
  </div>
  <div class="pc-loading">
    <div class="pc-bar"><span></span></div>
    <div class="pc-phase">正在上传资料…</div>
    <div class="pc-elapsed">已耗时 00:00</div>
  </div>
</div>
<script>
(function () {
  var form = document.getElementById('aiExtractForm');
  if (!form) { return; }
  var box = document.getElementById('aiExtractProgress');
  var btn = document.getElementById('aiExtractBtn');
  var phase = box ? box.querySelector('.pc-phase') : null;
  var elapsed = box ? box.querySelector('.pc-elapsed') : null;
  var wrap = box ? box.querySelector('.pc-loading') : null;
  var timer = null, startedAt = 0;

  function fmtTime(s) {
    s = Math.max(0, Math.floor(s));
    var m = Math.floor(s / 60), ss = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (ss < 10 ? '0' : '') + ss;
  }
  // 后端同步识别，前端拿不到真实阶段；按耗时切换文案，让用户知道还在跑。
  function phaseFor(s) {
    if (s < 2) { return '正在上传资料…'; }
    if (s < 6) { return '正在读取文件并识别文字…'; }
    if (s < 15) { return 'AI 正在提取客户资料…'; }
    if (s < 35) { return '模型返回较慢，仍在识别中…'; }
    return '已超过 35 秒，仍在运行，请稍候…';
  }

  form.addEventListener('submit', function () {
    var fileEl = form.querySelector('input[type="file"]');
    var textEl = form.querySelector('textarea[name="partyText"]');
    var hasFile = !!(fileEl && fileEl.files && fileEl.files.length);
    var hasText = !!(textEl && textEl.value.trim() !== '');
    if (!hasFile && !hasText) { return; }   // 无内容时交给后端给出提示，不显示进度
    if (box) {
      box.hidden = false;
      startedAt = Date.now();
      var tick = function () {
        var s = (Date.now() - startedAt) / 1000;
        if (phase) { phase.textContent = phaseFor(s); }
        if (elapsed) { elapsed.textContent = '已耗时 ' + fmtTime(s); }
        if (wrap) { wrap.classList.toggle('pc-slow', s >= 20); }
      };
      tick();
      timer = setInterval(tick, 1000);
      if (box.scrollIntoView) { box.scrollIntoView({ block: 'nearest' }); }
    }
    if (btn) {
      btn.disabled = true;
      btn.textContent = '识别中…';
    }
  });

  // 从浏览器缓存返回时复位，避免按钮一直停在「识别中」。
  window.addEventListener('pageshow', function () {
    if (timer) { clearInterval(timer); timer = null; }
    if (box) { box.hidden = true; }
    if (btn) { btn.disabled = false; btn.textContent = 'AI 识别并回填'; }
  });
})();
</script>
<?php
$aiBody = ob_get_clean();
if ($P) {
    $conf = (string) ($P['confidence'] ?? 'low');
    $warn = $P['warnings'] ?? [];
    $aiBody = '<div class="banner REVIEW" style="margin-bottom:10px"><span class="banner-icon">i</span>'
        . '<div class="banner-body"><div class="banner-title">识别完成，已回填空字段（置信度 ' . e($conf) . '）</div>'
        . ($warn ? '<div class="banner-reason">' . e(implode('；', $warn)) . '</div>' : '')
        . '</div></div>' . $aiBody;
}
echo card('AI 识别客户资料', $aiBody);
ob_start(); ?>

<form method="post" id="edit">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="save_customer">
  <?php if ($editId > 0): ?><input type="hidden" name="customerId" value="<?= (int) $editId ?>"><?php endif; ?>
  <div class="form-section-title">基本信息</div>
  <div class="grid form-grid">
    <div class="field"><label class="f">客户类型</label>
      <select name="customerType" id="customerType">
        <option value="company"<?= $ctype === 'company' ? ' selected' : '' ?>>公司</option>
        <option value="individual"<?= $ctype === 'individual' ? ' selected' : '' ?>>个人</option>
      </select></div>
    <div class="field"><label class="f">客户编码</label><input type="text" name="customerCode" placeholder="留空自动生成，如 C-0001" value="<?= e((string) ($E['customer_code'] ?? '')) ?>"><div class="hint">新公司或个人客户保存时自动递增编号</div></div>
    <div class="field span-full"><label class="f" id="customerNameLabel"><?= $ctype === 'individual' ? '姓名 *' : '公司名称 *' ?></label><input type="text" name="customerName" id="customerNameInput" required placeholder="<?= $ctype === 'individual' ? '例：陈大文' : '例：ABC Trading Limited / 香港贸易有限公司' ?>" value="<?= e((string) ($E['customer_name'] ?? '')) ?>"></div>
    <div class="field"><label class="f">默认币种</label>
      <select name="defaultCurrency"><?= currency_options($E['default_currency'] ?? null) ?></select></div>
    <div class="field"><label class="f">账期（天）</label><input type="number" name="paymentTermsDays" value="<?= (int) ($E['payment_terms_days'] ?? 30) ?>" min="0"></div>
    <div class="field"><label class="f">关联方</label>
      <select name="isRelatedParty"><option value="">否</option><option value="1"<?= !empty($E['is_related_party']) ? ' selected' : '' ?>>是</option></select></div>
    <div class="field"><label class="f">税务登记号</label><input type="text" name="taxId" placeholder="<?= e(t('BR / 税号')) ?>" value="<?= e((string) ($E['tax_id'] ?? '')) ?>"></div>
  </div>

  <div id="contactSectionTitle" class="form-section-title"><?= $ctype === 'individual' ? '联系方式' : '联系人' ?></div>
  <div class="grid form-grid">
    <div class="field company-only"<?= $ctype === 'individual' ? ' style="display:none"' : '' ?>><label class="f">联系人姓名</label><input type="text" name="contactName" placeholder="例：陈大文" value="<?= e((string) ($E['contact_name'] ?? '')) ?>"></div>
    <div class="field company-only"<?= $ctype === 'individual' ? ' style="display:none"' : '' ?>><label class="f">职位</label><input type="text" name="contactTitle" placeholder="例：财务经理" value="<?= e((string) ($E['contact_title'] ?? '')) ?>"></div>
    <div class="field"><label class="f">电话</label><input type="text" name="phone" placeholder="+852 1234 5678" value="<?= e((string) ($E['phone'] ?? '')) ?>"></div>
    <div class="field"><label class="f">手机</label><input type="text" name="mobile" placeholder="+852 9876 5432" value="<?= e((string) ($E['mobile'] ?? '')) ?>"></div>
    <div class="field"><label class="f">传真</label><input type="text" name="fax" value="<?= e((string) ($E['fax'] ?? '')) ?>"></div>
    <div class="field"><label class="f">邮箱</label><input type="text" name="email" placeholder="name@company.com" value="<?= e((string) ($E['email'] ?? '')) ?>"></div>
  </div>

  <div class="form-section-title">地址</div>
  <div class="grid form-grid">
    <div class="field span-full"><label class="f">详细地址</label><input type="text" name="address" placeholder="例：香港中环皇后大道中 1 号 20 楼" value="<?= e((string) ($E['address'] ?? '')) ?>"></div>
    <div class="field"><label class="f">地区 / 城市</label><input type="text" name="district" placeholder="例：中环" value="<?= e((string) ($E['district'] ?? '')) ?>"></div>
    <div class="field"><label class="f">国家 / 地区</label><input type="text" name="country" placeholder="例：香港" value="<?= e((string) ($E['country'] ?? '香港')) ?>"></div>
    <div class="field"><label class="f">网站</label><input type="text" name="website" placeholder="https://" value="<?= e((string) ($E['website'] ?? '')) ?>"></div>
  </div>

  <div class="field" style="margin-top:14px"><label class="f">备注</label>
    <input type="text" name="notes" placeholder="其他需要记录的信息" value="<?= e((string) ($E['notes'] ?? '')) ?>"></div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0"><a class="btn" href="?p=customers"><?= e(t('取消')) ?></a><button class="btn primary"><?= e($editId > 0 ? t('保存修改') : t('新建客户')) ?></button></div>
</form>
<script>
(function () {
  var sel = document.getElementById('customerType');
  if (!sel) { return; }
  var nameLabel = document.getElementById('customerNameLabel');
  var nameInput = document.getElementById('customerNameInput');
  var contactTitle = document.getElementById('contactSectionTitle');
  // 个人客户没有“联系人/职位”这一层，姓名直接写在名称字段里。
  function sync() {
    var individual = sel.value === 'individual';
    nameLabel.textContent = individual ? '姓名 *' : '公司名称 *';
    nameInput.placeholder = individual ? '例：陈大文' : '例：ABC Trading Limited / 香港贸易有限公司';
    contactTitle.textContent = individual ? '联系方式' : '联系人';
    Array.prototype.forEach.call(document.querySelectorAll('.company-only'), function (el) {
      el.style.display = individual ? 'none' : '';
    });
  }
  sel.addEventListener('change', sync);
  sync();
})();
</script>
<?php echo str_replace('<section class="card">', '<section class="card" id="new">',
    card($editId > 0 ? t('编辑客户') : t('客户信息'), ob_get_clean(),
        '<a class="btn sm" href="?p=customers">' . e(t('返回列表')) . '</a>'));
endif; ?>

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
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

// ?edit=<id> 时把表单切成编辑模式并预填该客户
$editId = (int) ($_GET['edit'] ?? 0);
$E = null;
if ($editId > 0) {
    $er = api_get('/customers/' . $editId);
    if ($er['ok']) { $E = $er['data']; }
}
$formMode = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $editId > 0 || $errMsg !== null);
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
<th>地区</th><th>币种</th><th class="num">账期</th><th>状态</th></tr></thead>
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
<td><?= status_pill((string) $x['status']) ?></td></tr>
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
ob_start(); ?>

<form method="post" id="edit">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="save_customer">
  <?php if ($E): ?><input type="hidden" name="customerId" value="<?= (int) $editId ?>"><?php endif; ?>
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
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0"><a class="btn" href="?p=customers"><?= e(t('取消')) ?></a><button class="btn primary"><?= e($E ? t('保存修改') : t('新建客户')) ?></button></div>
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
    card($E ? t('编辑客户') : t('客户信息'), ob_get_clean(),
        '<a class="btn sm" href="?p=customers">' . e(t('返回列表')) . '</a>'));
endif; ?>

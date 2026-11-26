<?php
/*
 * LtBooks — pages/vendors.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'save_vendor') {
    $r = api_post('/vendors', [
        'vendorId' => (int) ($_POST['vendorId'] ?? 0) ?: null,
        'vendorCode' => trim((string) ($_POST['vendorCode'] ?? '')),
        'vendorName' => trim((string) ($_POST['vendorName'] ?? '')),
        'defaultCurrency' => (string) ($_POST['defaultCurrency'] ?? 'HKD'),
        'paymentTermsDays' => (int) ($_POST['paymentTermsDays'] ?? 30),
        'isRelatedParty' => !empty($_POST['isRelatedParty']),
        'email' => trim((string) ($_POST['email'] ?? '')),
        // 与客户一致：都可空，填了才存
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
        // 付款用的银行资料，可空
        'bankName'        => trim((string) ($_POST['bankName'] ?? '')) ?: null,
        'bankAccountName' => trim((string) ($_POST['bankAccountName'] ?? '')) ?: null,
        'bankAccountNo'   => trim((string) ($_POST['bankAccountNo'] ?? '')) ?: null,
        'bankSwift'       => trim((string) ($_POST['bankSwift'] ?? '')) ?: null,
        'bankAddress'     => trim((string) ($_POST['bankAddress'] ?? '')) ?: null,
        'notes'        => trim((string) ($_POST['notes'] ?? '')) ?: null,
        'actor' => $displayName ?? 'system',
    ]);
    if ($r['ok']) {
        header('Location: ?p=vendors&msg=' . urlencode('供应商已保存'));
        exit;
    }
    $errMsg = (string) $r['error'];
}
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'delete_vendor') {
    $r = api_request('DELETE', '/vendors/' . (int) ($_POST['vendorId'] ?? 0)
        . '?actor=' . urlencode((string) ($displayName ?? 'system')));
    if ($r['ok']) {
        header('Location: ?p=vendors&msg=' . urlencode('供应商已删除'));
        exit;
    }
    $errMsg = (string) $r['error'];
}
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

// ?edit=<id> 时把表单切成编辑模式并预填该供应商
$editId = (int) ($_GET['edit'] ?? 0);
$E = null;
if ($editId > 0) {
    $er = api_get('/vendors/' . $editId);
    if ($er['ok']) { $E = $er['data']; }
}
$formMode = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $editId > 0 || $errMsg !== null);
if (!$formMode):
[$page, $per] = pager_state('ledu_vendors_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kwPage = trim((string) ($_GET['q'] ?? ''));
$r = api_get('/vendors?limit=' . $limit . '&offset=' . $offset
           . ($kwPage !== '' ? '&q=' . urlencode($kwPage) : ''));
$rows = $r['ok'] ? ($r['data']['vendors'] ?? []) : [];
$totalRows = (int) ($r['data']['total'] ?? count($rows));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }
ob_start();
if (!$rows) { echo empty_state('暂无供应商'); } else { ?>
<div class="table-wrap"><table>
<thead><tr><th>编码</th><th>名称</th><th>联系人</th><th>电话</th><th>邮箱</th>
<th>地区</th><th>币种</th><th class="num"><?= e(t('账期')) ?></th><th>状态</th><th style="width:90px">操作</th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<tr><td class="mono"><a href="?p=party-view&type=vendor&id=<?= (int) $x['vendor_id'] ?>"><?= e((string) $x['vendor_code']) ?></a></td>
<td><a href="?p=party-view&type=vendor&id=<?= (int) $x['vendor_id'] ?>"><?= e((string) $x['vendor_name']) ?></a>
  <?php if (!empty($x['is_related_party'])): ?><span class="badge review"><?= e(t('关联方')) ?></span><?php endif; ?></td>
<td><?= e((string) ($x['contact_name'] ?: '—')) ?>
  <?php if (!empty($x['contact_title'])): ?><div class="hint"><?= e((string) $x['contact_title']) ?></div><?php endif; ?></td>
<td class="hint" style="white-space:nowrap"><?= e((string) (($x['phone'] ?? '') ?: (($x['mobile'] ?? '') ?: '—'))) ?></td>
<td class="hint"><?= e((string) ($x['email'] ?? '—')) ?></td>
<td class="hint"><?= e((string) (($x['district'] ?? '') ?: (($x['country'] ?? '') ?: '—'))) ?></td>
<td><?= e((string) $x['default_currency']) ?></td>
<td class="num"><?= (int) $x['payment_terms_days'] ?> <?= e(t('天')) ?></td>
<td><?= status_pill((string) $x['status']) ?></td>
<td><?php if ($role !== 'auditor'): ?>
  <form method="post" style="display:inline">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="delete_vendor">
    <input type="hidden" name="vendorId" value="<?= (int) $x['vendor_id'] ?>">
    <button type="submit" class="btn sm ghost"
            data-confirm="确定删除该供应商？"
            data-confirm-note="仅未被单据引用的供应商可删除；删除后不可恢复。"
            data-confirm-ok="删除">删除</button>
  </form>
<?php endif; ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php }
$listBar = '<form method="get" class="list-bar">'
    . '<input type="hidden" name="p" value="vendors">'
    . '<input type="text" name="q" value="' . e($kwPage) . '" placeholder="搜索编码 / 名称 / 联系人 / 电话" style="width:280px">'
    . '<button class="btn sm">搜索</button>'
    . ($kwPage !== '' ? '<a class="btn sm" href="?p=vendors">清除</a>' : '')
    . '</form>';
echo card('', $listBar . ob_get_clean(),
    pager_html($page, $per, $totalRows, ['p' => 'vendors', 'q' => $kwPage ?: null]), false);
endif;

if ($formMode):
ob_start(); ?>
<form method="post" id="edit">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="save_vendor">
  <?php if ($E): ?><input type="hidden" name="vendorId" value="<?= (int) $editId ?>"><?php endif; ?>
  <div class="form-section-title"><?= e(t('基本信息')) ?></div>
  <div class="grid form-grid">
    <div class="field"><label class="f"><?= e(t('供应商编码')) ?></label><input type="text" name="vendorCode" placeholder="<?= e(t('留空自动生成，如 V-0001')) ?>" value="<?= e((string) ($E['vendor_code'] ?? '')) ?>"><div class="hint"><?= e(t('保存时自动递增编号')) ?></div></div>
    <div class="field span-full"><label class="f"><?= e(t('公司名称 *')) ?></label>
      <input type="text" name="vendorName" required placeholder="<?= e(t('例：ABC Trading Limited / 香港贸易有限公司')) ?>" value="<?= e((string) ($E['vendor_name'] ?? '')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('默认币种')) ?></label>
      <select name="defaultCurrency"><?= currency_options($E['default_currency'] ?? null) ?></select></div>
    <div class="field"><label class="f"><?= e(t('账期（天）')) ?></label><input type="number" name="paymentTermsDays" value="<?= (int) ($E['payment_terms_days'] ?? 30) ?>" min="0"></div>
    <div class="field"><label class="f"><?= e(t('关联方')) ?></label>
      <select name="isRelatedParty"><option value=""><?= e(t('否')) ?></option><option value="1"<?= !empty($E['is_related_party']) ? ' selected' : '' ?>><?= e(t('是')) ?></option></select></div>
    <div class="field"><label class="f"><?= e(t('税务登记号')) ?></label><input type="text" name="taxId" value="<?= e((string) ($E['tax_id'] ?? '')) ?>" placeholder="<?= e(t('BR / 税号')) ?>"></div>
  </div>

  <div class="form-section-title"><?= e(t('联系人')) ?></div>
  <div class="grid form-grid">
    <div class="field"><label class="f"><?= e(t('联系人姓名')) ?></label><input type="text" name="contactName" value="<?= e((string) ($E['contact_name'] ?? '')) ?>" placeholder="<?= e(t('例：陈大文')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('职位')) ?></label><input type="text" name="contactTitle" value="<?= e((string) ($E['contact_title'] ?? '')) ?>" placeholder="<?= e(t('例：财务经理')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('电话')) ?></label><input type="text" name="phone" value="<?= e((string) ($E['phone'] ?? '')) ?>" placeholder="+852 1234 5678"></div>
    <div class="field"><label class="f"><?= e(t('手机')) ?></label><input type="text" name="mobile" value="<?= e((string) ($E['mobile'] ?? '')) ?>" placeholder="+852 9876 5432"></div>
    <div class="field"><label class="f"><?= e(t('传真')) ?></label><input type="text" name="fax" value="<?= e((string) ($E['fax'] ?? '')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('邮箱')) ?></label><input type="text" name="email" value="<?= e((string) ($E['email'] ?? '')) ?>" placeholder="name@company.com"></div>
  </div>

  <div class="form-section-title"><?= e(t('地址')) ?></div>
  <div class="grid form-grid">
    <div class="field span-full"><label class="f"><?= e(t('详细地址')) ?></label>
      <input type="text" name="address" value="<?= e((string) ($E['address'] ?? '')) ?>" placeholder="<?= e(t('例：香港中环皇后大道中 1 号 20 楼')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('地区 / 城市')) ?></label><input type="text" name="district" value="<?= e((string) ($E['district'] ?? '')) ?>" placeholder="<?= e(t('例：中环')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('国家 / 地区')) ?></label><input type="text" name="country" placeholder="<?= e(t('例：香港')) ?>" value="<?= e((string) ($E['country'] ?? '香港')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('网站')) ?></label><input type="text" name="website" value="<?= e((string) ($E['website'] ?? '')) ?>" placeholder="https://"></div>
  </div>

  <div class="form-section-title"><?= e(t('银行信息（付款用，可留空）')) ?></div>
  <div class="grid form-grid">
    <div class="field"><label class="f"><?= e(t('开户银行')) ?></label>
      <input type="text" name="bankName" value="<?= e((string) ($E['bank_name'] ?? '')) ?>" placeholder="<?= e(t('例：汇丰银行 香港总行')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('账户名称（户名）')) ?></label>
      <input type="text" name="bankAccountName" value="<?= e((string) ($E['bank_account_name'] ?? '')) ?>" placeholder="<?= e(t('例：ABC Trading Limited')) ?>"></div>
    <div class="field"><label class="f"><?= e(t('银行账号')) ?></label>
      <input type="text" name="bankAccountNo" value="<?= e((string) ($E['bank_account_no'] ?? '')) ?>" placeholder="123-456789-001" autocomplete="off"></div>
    <div class="field"><label class="f"><?= e(t('SWIFT / BIC')) ?></label>
      <input type="text" name="bankSwift" value="<?= e((string) ($E['bank_swift'] ?? '')) ?>" placeholder="HSBCHKHHHKH" autocomplete="off"></div>
    <div class="field span-full"><label class="f"><?= e(t('银行地址')) ?></label>
      <input type="text" name="bankAddress" value="<?= e((string) ($E['bank_address'] ?? '')) ?>" placeholder="<?= e(t('例：1 Queen\'s Road Central, Hong Kong')) ?>"></div>
  </div>

  <div class="field" style="margin-top:14px"><label class="f"><?= e(t('备注')) ?></label>
    <input type="text" name="notes" value="<?= e((string) ($E['notes'] ?? '')) ?>" placeholder="<?= e(t('其他需要记录的信息')) ?>"></div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0"><a class="btn" href="?p=vendors"><?= e(t('取消')) ?></a><button class="btn primary"><?= e($E ? t('保存修改') : t('新建供应商')) ?></button></div>
</form>
<?php echo str_replace('<section class="card">', '<section class="card" id="new">',
    card($E ? t('编辑供应商') : t('供应商信息'), ob_get_clean(),
        '<a class="btn sm" href="?p=vendors">' . e(t('返回列表')) . '</a>'));
endif; ?>

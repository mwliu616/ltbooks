<?php
/*
 * LtBooks — pages/party-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 客户 / 供应商详情：基本信息、联系人、地址、往来单据与未结金额。
 *
 * 一个页面服务两种往来单位：字段完全一样，分成两个文件只会让两边慢慢不一致。
 */
$type = (string) ($_GET['type'] ?? 'customer');
$id   = (int) ($_GET['id'] ?? 0);
$back = (string) ($_GET['back'] ?? '');
if (!in_array($type, ['customer', 'vendor'], true) || $id <= 0) {
    echo errbox('没有指定要查看的往来单位');
    return;
}
$isCust = $type === 'customer';
$r = api_get(($isCust ? '/customers/' : '/vendors/') . $id);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'] ?? [];
$backHref = $back !== '' ? $back : ($isCust ? '?p=customers' : '?p=vendors');
$name = (string) ($d[$isCust ? 'customer_name' : 'vendor_name'] ?? '');
$code = (string) ($d[$isCust ? 'customer_code' : 'vendor_code'] ?? '');
$ccy  = (string) ($d['default_currency'] ?? 'HKD');

$kv = function (string $label, $value, string $fmt = 'text') {
    if ($value === null || $value === '' || $value === 0 && $fmt === 'skipzero') { $value = '—'; }
    if ($fmt === 'money') { $value = number_format((float) $value, 2); }
    return '<div class="kvg-item"><div class="kvg-k">' . e(t($label)) . '</div>'
         . '<div class="kvg-v">' . e((string) $value) . '</div></div>';
};
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e($name) ?></h1>
    <div class="page-sub mono"><?= e($code) ?><?= !empty($d['is_related_party']) ? ' · ' . e(t('关联方')) : '' ?></div>
  </div>
  <div class="page-actions">
    <a class="btn" href="<?= e($backHref) ?>"><?= e(t('返回列表')) ?></a>
    <?php if (($role ?? '') !== 'auditor'): ?>
      <a class="btn primary"
         href="<?= e(($isCust ? '?p=customers&edit=' : '?p=vendors&edit=') . (int) $id) ?>#edit"><?= e(t('编辑资料')) ?></a>
    <?php endif; ?>
  </div>
</div>

<?= help_html('party-view') ?>

<div class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('基本信息')) ?></h2></div>
  <div class="card-body">
    <div class="kvg">
      <?= $isCust ? $kv('客户类型', ($d['customer_type'] ?? 'company') === 'individual' ? t('个人') : t('公司')) : '' ?>
      <?= $kv($isCust ? '客户编码' : '供应商编码', $code) ?>
      <?= $kv('默认币种', $ccy) ?>
      <?= $kv('账期（天）', (int) ($d['payment_terms_days'] ?? 0)) ?>
      <?= $kv('关联方', !empty($d['is_related_party']) ? t('是') : t('否')) ?>
      <?= $kv('税务登记号', $d['tax_id'] ?? '') ?>
      <?= $kv('状态', status_label((string) ($d['status'] ?? ''))) ?>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('联系方式')) ?></h2></div>
  <div class="card-body">
    <div class="kvg">
      <?= $kv('联系人', $d['contact_name'] ?? '') ?>
      <?= $kv('职位', $d['contact_title'] ?? '') ?>
      <?= $kv('电话', $d['phone'] ?? '') ?>
      <?= $kv('手机', $d['mobile'] ?? '') ?>
      <?= $kv('传真', $d['fax'] ?? '') ?>
      <?= $kv('邮箱', $d['email'] ?? '') ?>
      <?= $kv('网站', $d['website'] ?? '') ?>
      <?= $kv('地区 / 城市', $d['district'] ?? '') ?>
      <?= $kv('国家 / 地区', $d['country'] ?? '') ?>
    </div>
    <?php if (!empty($d['address'])): ?>
      <div class="kvg" style="margin-top:14px">
        <div class="kvg-item kvg-wide"><div class="kvg-k"><?= e(t('详细地址')) ?></div>
          <div class="kvg-v"><?= e((string) $d['address']) ?></div></div>
      </div>
    <?php endif; ?>
    <?php if (!empty($d['notes'])): ?>
      <div class="kvg" style="margin-top:14px">
        <div class="kvg-item kvg-wide"><div class="kvg-k"><?= e(t('备注')) ?></div>
          <div class="kvg-v"><?= e((string) $d['notes']) ?></div></div>
      </div>
    <?php endif; ?>
  </div>
</div>

<div class="card">
  <div class="card-head">
    <h2 class="card-title"><?= e($isCust ? t('开给这个客户的发票') : t('这个供应商的账单')) ?></h2>
    <div class="hint"><?= e(t('未结金额')) ?>：<b class="mono"><?= money($d['outstanding'] ?? 0, $ccy) ?></b></div>
  </div>
  <?php $docs = (array) ($d['documents'] ?? []); ?>
  <?php if (!$docs): ?>
    <div class="card-body"><?= empty_state($isCust ? '还没有开过发票' : '还没有账单') ?></div>
  <?php else: ?>
  <div class="table-wrap"><table>
    <thead><tr><th><?= e(t('单号')) ?></th><th><?= e(t('日期')) ?></th>
      <th><?= e(t('币种')) ?></th><th class="num"><?= e(t('合计')) ?></th>
      <th class="num"><?= e(t('未结')) ?></th><th><?= e(t('状态')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($docs as $x): ?>
      <tr>
        <td class="mono"><a href="?p=<?= $isCust ? 'invoice-view' : 'bill-view' ?>&id=<?= (int) $x['id'] ?>">
          <?= e((string) $x['no']) ?></a></td>
        <td class="hint"><?= e((string) $x['date']) ?></td>
        <td><?= e((string) $x['currency']) ?></td>
        <td class="num"><?= money($x['gross_original'], (string) $x['currency']) ?></td>
        <td class="num"><?= money($x['outstanding'], (string) $x['currency']) ?></td>
        <td><?= status_pill((string) $x['status']) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
  <?php endif; ?>
</div>

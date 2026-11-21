<?php
/*
 * LtBooks — pages/company.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'save_company') {
    $r = api_post('/company', [
        'name' => trim((string) ($_POST['name'] ?? '')),
        'legalName' => trim((string) ($_POST['legalName'] ?? '')),
        'legalNameZh' => trim((string) ($_POST['legalNameZh'] ?? '')),
        'brNumber' => trim((string) ($_POST['brNumber'] ?? '')),
        'addressLine1' => trim((string) ($_POST['addressLine1'] ?? '')),
        'addressLine2' => trim((string) ($_POST['addressLine2'] ?? '')),
        'district' => trim((string) ($_POST['district'] ?? '')),
        'region' => trim((string) ($_POST['region'] ?? '')),
        'phone' => trim((string) ($_POST['phone'] ?? '')),
        'email' => trim((string) ($_POST['email'] ?? '')),
        'website' => trim((string) ($_POST['website'] ?? '')),
        'fiscalYearEnd' => trim((string) ($_POST['fiscalYearEnd'] ?? '')),
        'reportingFramework' => trim((string) ($_POST['reportingFramework'] ?? '')),
        'bank' => [
            'accountHolder' => trim((string) ($_POST['accountHolder'] ?? '')),
            'bankName' => trim((string) ($_POST['bankName'] ?? '')),
            'bankCode' => trim((string) ($_POST['bankCode'] ?? '')),
            'swiftCode' => trim((string) ($_POST['swiftCode'] ?? '')),
            'bankAddress' => trim((string) ($_POST['bankAddress'] ?? '')),
            'accountNumber' => trim((string) ($_POST['accountNumber'] ?? '')),
        ],
    ]);
    $msg = $r['ok'] ? '公司档案已更新' : null;
    $errMsg = $r['ok'] ? null : (string) $r['error'];
}

// Logo 上传：文件落盘后交给后端生成多档尺寸
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'upload_logo') {
    if (empty($_FILES['logo']['tmp_name']) || ($_FILES['logo']['error'] ?? 1) !== UPLOAD_ERR_OK) {
        $errMsg = '未选择文件';
    } elseif (($_FILES['logo']['size'] ?? 0) > 5 * 1024 * 1024) {
        $errMsg = 'Logo 文件不能超过 5MB';
    } else {
        $ext = strtolower(pathinfo((string) $_FILES['logo']['name'], PATHINFO_EXTENSION));
        if (!in_array($ext, ['png', 'jpg', 'jpeg', 'gif', 'webp'], true)) {
            $errMsg = '只支持 PNG / JPG / GIF / WebP';
        } else {
            $dest = UPLOAD_DIR . '/logo-' . date('Ymd') . '-' . bin2hex(random_bytes(5)) . '.' . $ext;
            if (!move_uploaded_file($_FILES['logo']['tmp_name'], $dest)) {
                $errMsg = '文件落盘失败';
            } else {
                @chmod($dest, 0640);
                $res = api_post('/company/logo', [
                    'storagePath' => $dest, 'fileName' => (string) $_FILES['logo']['name'],
                    'sha256' => hash_file('sha256', $dest), 'actor' => $user['username'] ?? 'system',
                ]);
                if ($res['ok']) { $msg = 'Logo 已更新，全站与 PDF 同步生效'; }
                else { @unlink($dest); $errMsg = (string) $res['error']; }
            }
        }
    }
}
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'reset_logo') {
    $res = api_request('DELETE', '/company/logo');
    if ($res['ok']) { $msg = '已恢复内置 Logo'; } else { $errMsg = (string) $res['error']; }
}

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

$r = api_get('/company');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$c = $r['data'];
$b = $c['bank'] ?? [];
// 中文名称是香港注册的法定标识，任何界面语言都显示繁体，不做简繁转换
$nvR = api_get('/company/name-variants');
$nv  = $nvR['ok'] ? $nvR['data'] : [];
$zhName = (string) ($nv['zhHk'] ?? ($c['legalNameZh'] ?? ''));

$fullAddr = implode(', ', array_filter([
    $c['addressLine1'], $c['addressLine2'], $c['district'], $c['region'],
]));
ob_start(); ?>
<dl class="dl">
  <dt><?= e(t('公司名称')) ?></dt><dd><b><?= e((string) $c['name']) ?></b></dd>
  <dt><?= e(t('中文名称')) ?></dt><dd><?= e($zhName ?: '—') ?></dd>
  <dt><?= e(t('法定名称')) ?></dt><dd><?= e((string) ($c['legalName'] ?: '—')) ?></dd>
  <dt><?= e(t('商业登记')) ?></dt><dd><?= e((string) ($c['brNumber'] ?: '—')) ?></dd>
  <dt><?= e(t('注册地址')) ?></dt><dd><?= e($fullAddr ?: '—') ?></dd>
  <dt><?= e(t('功能货币')) ?></dt><dd><?= e((string) $c['functionalCurrency']) ?></dd>
</dl>
<?php
// 抬头纸：三种语言各一个按钮，点哪个生成哪个，不依赖当前设置
$lhBtn = export_menu(export_lang_items('/company/letterhead/pdf'), t('生成抬头纸'), 'btn btn-file');
echo card('公司档案', ob_get_clean(), $lhBtn);
?>

<?php ob_start(); ?>
<?php if (!$b): ?>
  <?= empty_state('尚未设置主收款账户') ?>
<?php else: ?>
<dl class="dl">
  <dt><?= e(t('收款人')) ?></dt><dd><?= e((string) ($b['account_holder'] ?: '—')) ?></dd>
  <dt><?= e(t('开户银行')) ?></dt><dd><?= e((string) ($b['bank_name'] ?: '—')) ?></dd>
  <dt><?= e(t('银行代码')) ?></dt><dd><?= e((string) ($b['bank_code'] ?: '—')) ?></dd>
  <dt>SWIFT</dt><dd><?= e((string) ($b['swift_code'] ?: '—')) ?></dd>
  <dt><?= e(t('账户号码')) ?></dt><dd><?= e((string) ($b['account_number'] ?: $b['account_number_masked'] ?: '—')) ?></dd>
  <dt><?= e(t('账户币种')) ?></dt><dd><?= e((string) ($b['currency'] ?: '—')) ?></dd>
  <dt><?= e(t('银行地址')) ?></dt><dd><?= e((string) ($b['bank_address'] ?: '—')) ?></dd>
</dl>
<div class="hint" style="margin-top:12px"><?= e(t('此账户信息会打印在销售发票的「收款账户」区块。')) ?></div>
<?php endif; ?>
<?php echo card('主收款账户', ob_get_clean(), '', true); ?>

<?php ob_start(); ?>
<div class="logo-row">
  <div class="logo-preview">
    <img src="<?= e(company_logo(192)) ?>?v=<?= (int) @filemtime(__DIR__ . '/../' . company_logo(192)) ?>" alt="Logo">
  </div>
  <div class="logo-form">
    <div class="hint">
      <?= e(t('当前 Logo')) ?>：<?= file_exists(__DIR__ . '/../assets/logo-custom-192.png') ? e(t('自定义')) : e(t('内置')) ?>
    </div>
    <?php if ($role !== 'auditor'): ?>
    <form method="post" enctype="multipart/form-data" class="logo-upload">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="upload_logo">
      <label class="logo-file">
        <input type="file" name="logo" accept=".png,.jpg,.jpeg,.gif,.webp" required>
        <span class="btn sm">选择文件</span>
        <span class="logo-fname">未选择</span>
      </label>
      <button class="btn primary sm">上传并替换</button>
    </form>
    <div class="hint" style="margin-top:6px">PNG / JPG / GIF / WebP，≤ 5MB；建议正方形、透明背景</div>
    <?php if (file_exists(__DIR__ . '/../assets/logo-custom-192.png')): ?>
    <form method="post" style="margin-top:8px">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="reset_logo">
      <button class="btn sm ghost">恢复内置 Logo</button>
    </form>
    <?php endif; ?>
    <?php endif; ?>
  </div>
</div>
<?php echo card('公司 Logo', ob_get_clean()); ?>

<?php if ($role === 'admin'): ?>
<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="save_company">
  <div class="grid form-grid">
    <div class="field"><label class="f">公司名称</label><input type="text" name="name" value="<?= e((string) $c['name']) ?>" required></div>
    <div class="field"><label class="f">法定名称</label><input type="text" name="legalName" value="<?= e((string) ($c['legalName'] ?? '')) ?>"></div>
    <div class="field"><label class="f">中文名称</label><input type="text" name="legalNameZh" value="<?= e($zhName) ?>"
         placeholder="例如：示例贸易有限公司"></div>
    <div class="field"><label class="f">商业登记证号码</label><input type="text" name="brNumber" value="<?= e((string) ($c['brNumber'] ?? '')) ?>"></div>
    <div class="field"><label class="f">地址行 1</label><input type="text" name="addressLine1" value="<?= e((string) ($c['addressLine1'] ?? '')) ?>"></div>
    <div class="field"><label class="f">地址行 2</label><input type="text" name="addressLine2" value="<?= e((string) ($c['addressLine2'] ?? '')) ?>"></div>
    <div class="field"><label class="f">地区</label><input type="text" name="district" value="<?= e((string) ($c['district'] ?? '')) ?>"></div>
    <div class="field"><label class="f">行政区</label><input type="text" name="region" value="<?= e((string) ($c['region'] ?? '')) ?>"></div>
    <div class="field"><label class="f">电话</label><input type="text" name="phone" value="<?= e((string) ($c['phone'] ?? '')) ?>"></div>
    <div class="field"><label class="f">邮箱</label><input type="text" name="email" value="<?= e((string) ($c['email'] ?? '')) ?>"></div>
    <div class="field"><label class="f">网站</label><input type="text" name="website" value="<?= e((string) ($c['website'] ?? '')) ?>"></div>
    <div class="field">
      <label class="f"><?= e(t('财务年度年结日')) ?></label>
      <?php
      // 年结日 = 某个月的月末。12 个月全部可选（自动算月末，闰年 2 月给 29）
      $fy = (string) ($c['fiscalYearEnd'] ?? '12-31');
      $fyMonth = (int) substr($fy, 0, 2);
      $__monthNames = [1 => '1 月', 2 => '2 月', 3 => '3 月', 4 => '4 月', 5 => '5 月', 6 => '6 月',
                       7 => '7 月', 8 => '8 月', 9 => '9 月', 10 => '10 月', 11 => '11 月', 12 => '12 月'];
      ?>
      <select name="fiscalYearEnd" id="fyEnd">
        <?php for ($m = 1; $m <= 12; $m++):
          $lastDay = (int) date('t', strtotime(sprintf('2026-%02d-01', $m)));
          $val = sprintf('%02d-%02d', $m, $lastDay); ?>
          <option value="<?= e($val) ?>" <?= $fyMonth === $m ? 'selected' : '' ?>>
            <?= e($__monthNames[$m] . $lastDay . ' 日' . ($m === 12 ? '（日历年）' : '（非日历年）')) ?>
          </option>
        <?php endfor; ?>
      </select>
      <span class="hint" id="fyHint">
        <?= e(t('年结日是某个月的月末，12 个月都可选；改完报表的「本年度」口径随之变化')) ?>
      </span>
    </div>
    <div class="field">
      <label class="f"><?= e(t('报告框架')) ?></label>
      <select name="reportingFramework">
        <?php $fw = (string) ($c['reportingFramework'] ?? 'full_hkfrs'); ?>
        <option value="full_hkfrs" <?= $fw === 'full_hkfrs' ? 'selected' : '' ?>>
          <?= e(t('HKFRS 完整准则')) ?></option>
        <option value="sme_hkfrs" <?= $fw === 'sme_hkfrs' ? 'selected' : '' ?>>
          <?= e(t('HKFRS for Private Entities（中小企）')) ?></option>
      </select>
      <span class="hint"><?= e(t('决定资产负债表、损益表的呈现口径与附注要求')) ?></span>
    </div>
  </div>
  <div class="form-section-title"><?= e(t('主收款账户')) ?></div>
  <div class="grid form-grid" style="margin-top:8px">
    <div class="field"><label class="f">收款人</label><input type="text" name="accountHolder" value="<?= e((string) ($b['account_holder'] ?? '')) ?>"></div>
    <div class="field"><label class="f">开户银行</label><input type="text" name="bankName" value="<?= e((string) ($b['bank_name'] ?? '')) ?>"></div>
    <div class="field"><label class="f">银行代码</label><input type="text" name="bankCode" value="<?= e((string) ($b['bank_code'] ?? '')) ?>"></div>
    <div class="field"><label class="f">SWIFT</label><input type="text" name="swiftCode" value="<?= e((string) ($b['swift_code'] ?? '')) ?>"></div>
    <div class="field"><label class="f">账户号码</label><input type="text" name="accountNumber" value="<?= e((string) ($b['account_number'] ?? '')) ?>"></div>
    <div class="field span-full"><label class="f">银行地址</label><input type="text" name="bankAddress" value="<?= e((string) ($b['bank_address'] ?? '')) ?>"></div>
  </div>
  <div class="toolbar form-actions">
    <button class="btn primary">保存公司档案</button>
    <span class="hint">变更会写入审计日志；账户信息将用于发票打印，务必与开户文件一致</span>
  </div>
</form>


<?php echo card('编辑公司档案', ob_get_clean()); ?>
<?php endif; ?>

<script>
/* 年结日改动时，实时显示对应的财务年度起止 */
(function () {
  var sel = document.getElementById('fyEnd');
  var hint = document.getElementById('fyHint');
  if (!sel || !hint) return;
  var base = hint.textContent;
  function refresh() {
    var m = parseInt(sel.value.slice(0, 2), 10);
    var today = new Date();
    var y = today.getFullYear();
    // 本年度结束：今年的年结日；若已过，则是明年的
    var endYear = y;
    var endMonthIdx = m - 1;
    var endsThisYear = new Date(y, endMonthIdx + 1, 0);
    if (endsThisYear < today) endYear = y + 1;
    var end = new Date(endYear, endMonthIdx + 1, 0);
    var start = new Date(endYear - 1, endMonthIdx + 1, 1);
    var f = function (d) {
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    };
    hint.textContent = base + ' · 本年度 ' + f(start) + ' 至 ' + f(end);
  }
  sel.addEventListener('change', refresh);
  refresh();
})();
</script>

<?php
/*
 * LtBooks — pages/banks.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'create_account') {
    $ccy = strtoupper(trim((string) ($_POST['currency'] ?? 'HKD')));
    if ($ccy === '__NEW__') {
        $ccy = strtoupper(trim((string) ($_POST['newCurrency'] ?? '')));
    }
    $r = api_post('/bank-accounts', [
        'name' => trim((string) ($_POST['name'] ?? '')),
        'currency' => $ccy,
        'accountCode' => trim((string) ($_POST['accountCode'] ?? '')),
        'accountHolder' => trim((string) ($_POST['accountHolder'] ?? '')),
        'bankName' => trim((string) ($_POST['bankName'] ?? '')),
        'bankCode' => trim((string) ($_POST['bankCode'] ?? '')),
        'swiftCode' => trim((string) ($_POST['swiftCode'] ?? '')),
        'accountNumber' => trim((string) ($_POST['accountNumber'] ?? '')),
        'openingBalance' => (float) ($_POST['openingBalance'] ?? 0),
        'isCreditCard' => !empty($_POST['isCreditCard']),
        'actor' => $displayName ?? 'system',
    ]);
    if ($r['ok']) {
        $msg = '账户已建立：科目 ' . $r['data']['accountCode'] . ' · ' . $r['data']['currency']
             . '（期初折合 HKD ' . number_format((float) $r['data']['openingBalanceFunctional'], 2) . '）';
        header('Location: ?p=banks&msg=' . urlencode($msg));
        exit;
    } else {
        $errMsg = (string) $r['error'];
    }
}

$r = api_get('/bank-accounts');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$groups = $r['data']['groups'] ?? [];
$subs = $r['data']['subaccounts'] ?? [];
$glNames = [];
foreach ($r['data']['accounts'] ?? [] as $ba) {
    $glNames[(int) $ba['account_id']] = (string) ($ba['account_name'] ?? '');
}
$formMode = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $errMsg !== null);

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">账户已建立</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

if (!$formMode):
foreach ($groups as $g) {
    ob_start(); ?>
    <div class="table-wrap"><table>
    <thead><tr><th>账户</th><th>开户行 / SWIFT</th><th>账号</th><th>科目</th>
    <th class="num">原币余额</th><th class="num">折 HKD</th>
    <th class="num">上次重估汇率</th><th></th></tr></thead>
    <tbody>
    <?php foreach ($g['accounts'] as $a): ?>
      <tr>
        <td><?= e($a['name']) ?>
          <?php if (!empty($a['is_primary_receiving'])): ?><span class="badge pass">收款</span><?php endif; ?></td>
        <td class="hint"><?= e((string) ($a['bank_name'] ?? '—')) ?><br>
          <?= e((string) ($a['bank_code'] ?? '')) ?> · <?= e((string) ($a['swift_code'] ?? '')) ?></td>
        <td style="font-family:var(--mono);font-size:var(--f-2xs)">
          <?= e((string) ($a['account_number'] ?? $a['account_number_masked'] ?? '—')) ?></td>
        <td><?= e($a['account_code']) ?>
          <?php if (!empty($glNames[(int) $a['account_id']])): ?><br>
            <span class="hint" style="font-size:var(--f-2xs)"><?= e($glNames[(int) $a['account_id']]) ?></span><?php endif; ?></td>
        <td class="num"><?= money($a['current_balance'], (string) $a['currency']) ?></td>
        <td class="num"><?= $a['currency'] === 'HKD' ? '—' : money($a['current_balance_functional'], 'HKD') ?></td>
        <td class="num"><?= $a['last_reval_rate'] === null ? '—' : e((string) $a['last_reval_rate']) ?></td>
        <td><a class="btn sm" href="?p=reconcile&account=<?= (int) $a['account_id'] ?>">对账</a></td>
      </tr>
    <?php endforeach; ?>
    </tbody></table></div>
    <?php echo card($g['currency'] . ' 账户', ob_get_clean());
}
echo '<div class="hint" style="padding:10px 14px">' . e($r['data']['note'] ?? '') . '</div>';
endif;

if ($formMode) {
ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="create_account">
  <div class="grid">
    <div class="field"><label class="f">账户名称 *</label>
      <input type="text" name="name" required placeholder="例如：汇丰银行 — 储蓄账户"></div>
    <div class="field"><label class="f">币种（默认港币）</label>
      <select name="currency" id="ccySel" onchange="document.getElementById('newCcyWrap').style.display=(this.value==='__new__')?'':'none'">
        <?php foreach (currencies() as $c): ?>
          <option value="<?= e($c) ?>"<?= $c === base_currency() ? ' selected' : '' ?>><?= e($c) ?><?= $c === base_currency() ? '（功能货币）' : '' ?></option>
        <?php endforeach; ?>
        <option value="__new__">其他币种…</option>
      </select>
      <div class="hint">新建其他币种账户前，须先在「汇率维护」录入该币种汇率</div>
    </div>
    <div class="field" id="newCcyWrap" style="display:none"><label class="f">新币种代码</label>
      <input type="text" name="newCurrency" maxlength="3" placeholder="GBP" style="text-transform:uppercase"></div>
    <div class="field"><label class="f">会计科目（112x）</label>
      <select name="accountCode" onchange="pickCcy(this)">
        <option value="">自动：为该币种新建或复用空闲科目</option>
        <?php foreach ($subs as $s): ?>
          <option value="<?= e($s['accountCode']) ?>" data-ccy="<?= e($s['currency'] ?? '') ?>"<?= !empty($s['used']) ? ' disabled' : '' ?>><?= e($s['accountCode'] . ' · ' . $s['name']) ?><?= !empty($s['used']) ? '（已使用）' : '' ?></option>
        <?php endforeach; ?>
      </select>
      <script>
      function pickCcy(el) {
        var c = el.options[el.selectedIndex].getAttribute('data-ccy');
        if (!c) return;
        var s = document.getElementById('ccySel'), hit = false;
        for (var i = 0; i < s.options.length; i++) {
          if (s.options[i].value === c) { s.selectedIndex = i; hit = true; break; }
        }
        if (!hit) {
          s.value = '__new__';
          document.querySelector('input[name=newCurrency]').value = c;
        }
        s.dispatchEvent(new Event('change'));
      }
      </script>
      <div class="hint">可人工指定银行子科目；留空则按币种自动匹配（USD→1122 等），没有空闲科目时自动新建</div>
    </div>
    <div class="field"><label class="f">开户行</label><input type="text" name="bankName"></div>
    <div class="field"><label class="f">银行代码</label><input type="text" name="bankCode" placeholder="004"></div>
    <div class="field"><label class="f">SWIFT</label><input type="text" name="swiftCode" placeholder="HSBCHKHHHKH"></div>
    <div class="field"><label class="f">账号</label><input type="text" name="accountNumber"></div>
    <div class="field"><label class="f">期初余额</label>
      <input type="number" step="0.01" name="openingBalance" value="0">
      <div class="hint">非港币将按最新汇率折合，并生成期初分录</div>
    </div>
  </div>
  <div class="banner INFO" style="margin-top:12px">
    <span class="banner-icon">i</span>
    <div class="banner-body">
      <div class="banner-title">账户一经建立不可删除</div>
      <div class="banner-reason">
        银行账户关联着流水、对账单与会计分录，删除会破坏账目可追溯性。
        系统不提供删除功能；如不再使用，请将其余额结清后停用。
      </div>
    </div>
  </div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <a class="btn" href="?p=banks">取消</a>
    <button class="btn primary">建立账户</button>
    <label style="display:flex;gap:6px;align-items:center;font-size:var(--f-xs)">
      <input type="checkbox" name="isCreditCard" value="1"> 信用卡账户
    </label>
    <span class="hint">未指定科目时，系统会按币种自动匹配或建立 112x 科目</span>
  </div>
</form>
<?php echo card('新增银行账户', ob_get_clean(),
    '<a class="btn sm" href="?p=banks">返回列表</a>');
}

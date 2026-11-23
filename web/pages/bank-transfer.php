<?php
/*
 * LtBooks — pages/bank-transfer.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 转账（同币种）与外币兑换（跨币种）。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$err = null;
$op = (string) ($_POST['op'] ?? 'transfer');
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor') {
    if ($op === 'exchange') {
        $r = api_post('/fx/exchanges', [
            'fromAccountId' => (int) ($_POST['fromAccountId'] ?? 0),
            'toAccountId' => (int) ($_POST['toAccountId'] ?? 0),
            'fromAmount' => (float) ($_POST['fromAmount'] ?? 0),
            'toAmount' => (float) ($_POST['toAmount'] ?? 0),
            'dealRate' => (float) ($_POST['dealRate'] ?? 0),
            'feeAmount' => (float) ($_POST['feeAmount'] ?? 0),
            'date' => (string) ($_POST['date'] ?? date('Y-m-d')),
            'note' => (string) ($_POST['note'] ?? ''),
            'actor' => $actor,
        ]);
        if ($r['ok']) {
            header('Location: ?p=bank-transfer&msg=' . urlencode(
                '已兑换 ' . (string) ($r['data']['exchangeNo'] ?? '') . '，汇兑差额 ' .
                number_format((float) ($r['data']['fxDiff'] ?? 0), 2) . ' HKD'));
            exit;
        }
        $err = (string) $r['error'];
    } elseif ($op === 'claim' || $op === 'void') {
        $xid = (int) ($_POST['exchangeId'] ?? 0);
        $r = api_post('/fx/exchanges/' . $xid . '/' . $op, ['actor' => $actor]);
        if ($r['ok']) {
            header('Location: ?p=bank-transfer&msg=' . urlencode($op === 'claim' ? '已认领对账单流水' : '兑换单已作废'));
            exit;
        }
        $err = (string) $r['error'];
    } else {
        $r = api_post('/bank/transfer', [
            'fromId' => (int) ($_POST['fromId'] ?? 0),
            'toId' => (int) ($_POST['toId'] ?? 0),
            'amount' => (float) ($_POST['amount'] ?? 0),
            'date' => (string) ($_POST['date'] ?? date('Y-m-d')),
            'actor' => $actor,
        ]);
        if ($r['ok']) {
            header('Location: ?p=bank-transfer&msg=' . urlencode(
                '已转账 ' . number_format((float) ($r['data']['amount'] ?? 0), 2) . ' · 凭证 ' . (string) ($r['data']['entryNo'] ?? '')));
            exit;
        }
        $err = (string) $r['error'];
    }
}
$accR = api_get('/bank-accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$exR = api_get('/fx/exchanges');
$exchanges = $exR['ok'] ? ($exR['data']['exchanges'] ?? []) : [];
$msg = (string) ($_GET['msg'] ?? '');
?>
<div class="page-head">
  <div>
    <h1 class="page-title">转账</h1>
    <div class="page-sub">同币种账户之间调拨；跨币种用下方「外币兑换」，按银行实际成交价入账</div>
  </div>
</div>

<?= help_html('bank-transfer') ?>

<?php if ($msg !== ''): ?>
  <div class="banner PASS" style="margin-bottom:12px"><span class="banner-icon">✓</span>
    <div class="banner-body"><div class="banner-title">成功</div><div class="banner-reason"><?= e($msg) ?></div></div></div>
<?php endif; ?>
<?php if ($err): ?><?= errbox($err) ?><?php endif; ?>

<section class="card">
  <div class="card-body">
    <h3 style="margin-top:0">同币种转账</h3>
    <form method="post">
      <?= csrf_field() ?>
      <input type="hidden" name="op" value="transfer">
      <div class="grid">
        <div class="field"><label class="f">从</label>
          <select name="fromId" required>
            <?php foreach ($accounts as $a): ?>
              <option value="<?= (int) $a['account_id'] ?>"><?= e((string) $a['name'] . '（' . $a['currency'] . '）') ?></option>
            <?php endforeach; ?>
          </select></div>
        <div class="field"><label class="f">到</label>
          <select name="toId" required>
            <?php foreach ($accounts as $a): ?>
              <option value="<?= (int) $a['account_id'] ?>"><?= e((string) $a['name'] . '（' . $a['currency'] . '）') ?></option>
            <?php endforeach; ?>
          </select></div>
        <div class="field"><label class="f">金额 *</label>
          <input type="number" name="amount" step="0.01" min="0.01" required></div>
        <div class="field"><label class="f">日期</label>
          <input type="date" name="date" value="<?= e(date('Y-m-d')) ?>"></div>
      </div>
      <div class="toolbar form-actions" style="margin-top:14px;margin-bottom:0">
        <?php if ($role === 'auditor'): ?>
          <span class="hint">审计角色只读</span>
        <?php else: ?>
          <button class="btn primary"
            data-confirm="确认转账？" data-confirm-note="会生成一张两行的凭证：借「到」账户，贷「从」账户。"
            data-confirm-ok="确认转账">确认转账</button>
        <?php endif; ?>
      </div>
    </form>
  </div>
</section>

<section class="card" style="margin-top:14px">
  <div class="card-body">
    <h3 style="margin-top:0">外币兑换</h3>
    <div class="hint" style="margin-bottom:10px">
      按汇丰实际成交金额填写：例如卖出 1,000.00 HKD、买入 127.04 USD，成交汇率自动算出 0.12704。
      点差形成的差额自动记入 4410 已实现汇兑损益；手续费另记 6400 银行手续费。
    </div>
    <form method="post" id="fxForm">
      <?= csrf_field() ?>
      <input type="hidden" name="op" value="exchange">
      <div class="grid">
        <div class="field"><label class="f">卖出账户 *</label>
          <select name="fromAccountId" id="fxFromAcc" required>
            <?php foreach ($accounts as $a): ?>
              <option value="<?= (int) $a['account_id'] ?>" data-ccy="<?= e($a['currency']) ?>"><?= e((string) $a['name'] . '（' . $a['currency'] . '）') ?></option>
            <?php endforeach; ?>
          </select></div>
        <div class="field"><label class="f">买入账户 *</label>
          <select name="toAccountId" id="fxToAcc" required>
            <?php foreach ($accounts as $a): ?>
              <option value="<?= (int) $a['account_id'] ?>" data-ccy="<?= e($a['currency']) ?>"><?= e((string) $a['name'] . '（' . $a['currency'] . '）') ?></option>
            <?php endforeach; ?>
          </select></div>
        <div class="field"><label class="f">卖出金额 *</label>
          <input type="number" name="fromAmount" id="fxFrom" step="0.01" min="0.01" required></div>
        <div class="field"><label class="f">买入金额 *</label>
          <input type="number" name="toAmount" id="fxTo" step="0.01" min="0.01" required></div>
        <div class="field"><label class="f">成交汇率（1 卖出币 = ? 买入币）</label>
          <input type="number" name="dealRate" id="fxRate" step="0.0000000001" min="0"></div>
        <div class="field"><label class="f">手续费（卖出币）</label>
          <input type="number" name="feeAmount" step="0.01" min="0" value="0"></div>
        <div class="field"><label class="f">日期</label>
          <input type="date" name="date" value="<?= e(date('Y-m-d')) ?>"></div>
        <div class="field"><label class="f">备注</label>
          <input type="text" name="note" maxlength="200" placeholder="如 HSBC 兑换水单号"></div>
      </div>
      <div class="toolbar form-actions" style="margin-top:14px;margin-bottom:0">
        <?php if ($role === 'auditor'): ?>
          <span class="hint">审计角色只读</span>
        <?php else: ?>
          <button class="btn primary"
            data-confirm="确认生成外币兑换？" data-confirm-note="会按成交金额生成兑换凭证与两条银行流水；导入 HSBC 对账单后可认领替换。"
            data-confirm-ok="确认兑换">确认兑换</button>
        <?php endif; ?>
      </div>
    </form>
  </div>
</section>

<section class="card" style="margin-top:14px">
  <div class="card-body">
    <h3 style="margin-top:0">兑换记录</h3>
    <?php if (!$exchanges): ?>
      <div class="hint">暂无兑换记录。</div>
    <?php else: ?>
      <table class="table">
        <thead><tr>
          <th>编号</th><th>日期</th><th>卖出</th><th>买入</th><th>成交汇率</th>
          <th class="num">汇兑差额</th><th>状态</th><th>操作</th>
        </tr></thead>
        <tbody>
        <?php foreach ($exchanges as $x): ?>
          <tr>
            <td><?= e((string) $x['exchangeNo']) ?></td>
            <td><?= e((string) $x['date']) ?></td>
            <td><?= e(number_format((float) $x['fromAmount'], 2) . ' ' . $x['fromCurrency']) ?><br>
              <span class="hint"><?= e((string) $x['fromName']) ?></span></td>
            <td><?= e(number_format((float) $x['toAmount'], 2) . ' ' . $x['toCurrency']) ?><br>
              <span class="hint"><?= e((string) $x['toName']) ?></span></td>
            <td><?= e((string) $x['dealRate']) ?></td>
            <td class="num"><?= e(number_format((float) $x['fxDiff'], 2)) ?></td>
            <td><?= $x['status'] === 'void' ? '已作废' : '已过账' ?></td>
            <td>
              <?php if ($role !== 'auditor' && $x['status'] === 'posted'): ?>
                <form method="post" style="display:inline">
                  <?= csrf_field() ?>
                  <input type="hidden" name="op" value="claim">
                  <input type="hidden" name="exchangeId" value="<?= (int) $x['exchangeId'] ?>">
                  <button class="btn small" data-confirm="认领对账单流水？"
                    data-confirm-note="会用导入的 HSBC 流水替换系统占位流水，金额需一致（容差 0.05）。"
                    data-confirm-ok="认领">认领流水</button>
                </form>
                <form method="post" style="display:inline">
                  <?= csrf_field() ?>
                  <input type="hidden" name="op" value="void">
                  <input type="hidden" name="exchangeId" value="<?= (int) $x['exchangeId'] ?>">
                  <button class="btn small" data-confirm="作废该兑换单？"
                    data-confirm-note="会冲销凭证、解除流水认领，且不可恢复。"
                    data-confirm-ok="确认作废">作废</button>
                </form>
              <?php endif; ?>
            </td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    <?php endif; ?>
  </div>
</section>

<script>
(function () {
  var from = document.getElementById('fxFrom'), to = document.getElementById('fxTo'),
      rate = document.getElementById('fxRate');
  function calcTo() {
    var f = parseFloat(from.value), r = parseFloat(rate.value);
    if (f > 0 && r > 0) { to.value = (f * r).toFixed(2); }
  }
  function calcRate() {
    var f = parseFloat(from.value), t = parseFloat(to.value);
    if (f > 0 && t > 0) { rate.value = (t / f).toFixed(10).replace(/0+$/, '').replace(/\.$/, ''); }
  }
  from.addEventListener('input', calcTo);
  rate.addEventListener('input', calcTo);
  to.addEventListener('input', calcRate);
  var fa = document.getElementById('fxFromAcc'), ta = document.getElementById('fxToAcc');
  function checkCcy() {
    if (fa.value === ta.value) {
      for (var i = 0; i < ta.options.length; i++) {
        if (ta.options[i].value !== fa.value) { ta.selectedIndex = i; break; }
      }
    }
  }
  fa.addEventListener('change', checkCcy);
  ta.addEventListener('change', checkCcy);
})();
</script>

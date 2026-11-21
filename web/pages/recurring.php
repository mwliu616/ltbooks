<?php
/*
 * LtBooks — pages/recurring.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 循环交易：固定单据按规则到期建单；发票、账单入口共用本页。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$pageSlug = (string) ($pageSlug ?? 'recurring');
$side = (string) ($side ?? ($_GET['kind'] ?? 'invoice'));
$side = $side === 'bill' ? 'bill' : 'invoice';
$self = '?p=' . $pageSlug . ($pageSlug === 'recurring' ? '&kind=' . $side : '');
$errMsg = null;
$editId = (int) ($_GET['edit'] ?? 0);

$FREQ = ['monthly' => '每月', 'quarterly' => '每季', 'yearly' => '每年'];
$KIND = $side === 'invoice' ? ['invoice' => '销售发票'] : ['bill' => '账单', 'expense' => '费用'];
$SIDE_LABEL = ['invoice' => '经常性发票', 'bill' => '经常性账单及费用'];

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor') {
    $action = (string) ($_POST['action'] ?? '');
    $id = (int) ($_POST['id'] ?? 0);

    if (in_array($action, ['recurring_create', 'recurring_update'], true)) {
        $isUpdate = $action === 'recurring_update' && $id > 0;
        $res = api_post($isUpdate ? '/recurring/' . $id . '/update' : '/recurring', [
            'name' => trim((string) ($_POST['name'] ?? '')),
            'docKind' => (string) ($_POST['docKind'] ?? $side),
            'partyName' => trim((string) ($_POST['partyName'] ?? '')),
            'currency' => (string) ($_POST['currency'] ?? 'HKD'),
            'amountOriginal' => (float) ($_POST['amountOriginal'] ?? 0),
            'taxOriginal' => (float) ($_POST['taxOriginal'] ?? 0),
            'description' => (string) ($_POST['description'] ?? ''),
            'expenseAccountCode' => (string) ($_POST['expenseAccountCode'] ?? '6200'),
            'revenueAccountCode' => (string) ($_POST['revenueAccountCode'] ?? '') ?: null,
            'frequency' => (string) ($_POST['frequency'] ?? 'monthly'),
            'startDate' => (string) ($_POST['startDate'] ?? date('Y-m-d')),
            'endDate' => (string) ($_POST['endDate'] ?? '') ?: null,
            'autoPost' => !empty($_POST['autoPost']),
            'actor' => $actor,
        ]);
        if ($res['ok']) {
            header('Location: ' . $self . '&msg=' . urlencode(t($isUpdate ? '循环规则已更新' : '循环规则已建立')));
            exit;
        }
        $errMsg = (string) $res['error'];
        $editId = $isUpdate ? $id : 0;
    } elseif ($action === 'recurring_run') {
        $res = api_post('/recurring/' . $id . '/run', ['actor' => $actor, 'role' => $role]);
        if ($res['ok']) {
            $d = $res['data'];
            $msg = t('已按规则建单') . ' ' . (string) ($d['docNo'] ?? '')
                 . ' · ' . t('下次执行') . ' ' . (string) ($d['nextRun'] ?? '');
            $post = (array) ($d['postResult'] ?? []);
            if ($post && empty($post['ok'])) { $msg .= ' · ' . t('自动记账未完成') . '：' . (string) ($post['error'] ?? ''); }
            header('Location: ' . $self . '&msg=' . urlencode($msg));
            exit;
        }
        $errMsg = (string) $res['error'];
    } elseif ($action === 'recurring_status') {
        $res = api_post('/recurring/' . $id . '/status',
            ['status' => (string) ($_POST['status'] ?? 'paused'), 'actor' => $actor]);
        if ($res['ok']) {
            header('Location: ' . $self . '&msg=' . urlencode(t('规则状态已更新')));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}

[$page, $per] = pager_state('ledu_rec_per', 25);
$r = api_get('/recurring');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rules = array_values(array_filter($r['data']['rules'] ?? [], static function ($x) use ($side): bool {
    $kind = (string) ($x['doc_kind'] ?? '');
    return $side === 'invoice' ? $kind === 'invoice' : in_array($kind, ['bill', 'expense'], true);
}));
$editRule = null;
if ($editId > 0) {
    foreach ($rules as $x) {
        if ((int) $x['rule_id'] === $editId) { $editRule = $x; break; }
    }
    if (!$editRule) { echo errbox('规则不存在或不属于当前列表'); return; }
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        foreach ([
            'name' => 'name', 'docKind' => 'doc_kind', 'partyName' => 'party_name',
            'currency' => 'currency', 'amountOriginal' => 'amount_original',
            'taxOriginal' => 'tax_original', 'description' => 'description',
            'expenseAccountCode' => 'expense_account_code',
            'revenueAccountCode' => 'revenue_account_code', 'frequency' => 'frequency',
            'startDate' => 'start_date', 'endDate' => 'end_date',
        ] as $field => $key) { $_POST[$field] = (string) ($editRule[$key] ?? ''); }
        $_POST['autoPost'] = !empty($editRule['auto_post']) ? '1' : '';
    }
}
$formError = $errMsg !== null
    && in_array((string) ($_POST['action'] ?? ''), ['recurring_create', 'recurring_update'], true);
$showNew = (string) ($_GET['new'] ?? '') === '1' || $editRule !== null || $formError;
if ($role === 'auditor') { $showNew = false; }
$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$costAccounts = array_values(array_filter($accounts,
    fn($a) => in_array($a['category'], ['expense', 'cogs'], true)));
$isEdit = $editRule !== null;
$formAction = $isEdit ? 'recurring_update' : 'recurring_create';
$selectedKind = (string) ($_POST['docKind'] ?? ($side === 'bill' ? 'bill' : 'invoice'));
$pagerParams = ['p' => $pageSlug];
if ($pageSlug === 'recurring') { $pagerParams['kind'] = $side; }
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e($showNew ? ($isEdit ? '编辑循环规则' : '新建循环规则') : $SIDE_LABEL[$side]) ?></h1>
    <div class="page-sub">固定单据按规则到期建单；执行一次即生成一张草稿</div>
  </div>
  <div class="page-actions">
    <?php if ($showNew): ?>
      <a class="btn" href="<?= e($self) ?>">返回列表</a>
    <?php elseif ($role !== 'auditor'): ?>
      <a class="btn primary" href="<?= e($self . '&new=1') ?>">＋ 新建规则</a>
    <?php endif; ?>
  </div>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>
<?= help_html($pageSlug ?? 'recurring') ?>

<?php if ($showNew): ?>
<section class="card">
  <div class="card-head">
    <h2><?= e($isEdit ? '编辑循环规则' : '新建循环规则') ?></h2>
    <a class="btn sm" href="<?= e($self) ?>">返回列表</a>
  </div>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="<?= e($formAction) ?>">
    <?php if ($isEdit): ?><input type="hidden" name="id" value="<?= (int) $editId ?>"><?php endif; ?>
    <div class="grid form-grid-4">
      <div class="field span-2">
        <label class="f" for="rName">规则名称</label>
        <input type="text" id="rName" name="name" required maxlength="200"
               value="<?= e((string) ($_POST['name'] ?? '')) ?>" placeholder="例：办公室租金（月付）">
      </div>
      <div class="field">
        <label class="f" for="rKind">单据类型</label>
        <select id="rKind" name="docKind" <?= $isEdit ? 'disabled' : '' ?>>
          <?php foreach ($KIND as $k => $lab): ?>
            <option value="<?= e($k) ?>" <?= $k === $selectedKind ? 'selected' : '' ?>><?= e($lab) ?></option>
          <?php endforeach; ?>
        </select>
        <?php if ($isEdit): ?><input type="hidden" name="docKind" value="<?= e($selectedKind) ?>"><?php endif; ?>
      </div>
      <div class="field">
        <label class="f" for="rFreq">频率</label>
        <select id="rFreq" name="frequency">
          <?php foreach ($FREQ as $k => $lab): ?>
            <option value="<?= e($k) ?>" <?= (string) ($_POST['frequency'] ?? 'monthly') === $k ? 'selected' : '' ?>><?= e($lab) ?></option>
          <?php endforeach; ?>
        </select>
      </div>
      <div class="field">
        <label class="f" for="rParty">往来单位 / 类别</label>
        <input type="text" id="rParty" name="partyName" required maxlength="200"
               value="<?= e((string) ($_POST['partyName'] ?? '')) ?>" placeholder="例：Kowloon Property Ltd">
      </div>
      <div class="field">
        <label class="f" for="rAmt">金额（不含税）</label>
        <input type="number" step="0.01" min="0" id="rAmt" name="amountOriginal" required
               value="<?= e((string) ($_POST['amountOriginal'] ?? '')) ?>">
      </div>
      <div class="field">
        <label class="f" for="rTax">税额</label>
        <input type="number" step="0.01" min="0" id="rTax" name="taxOriginal"
               value="<?= e((string) ($_POST['taxOriginal'] ?? '0')) ?>">
      </div>
      <div class="field">
        <label class="f" for="rCcy">币种</label>
        <select id="rCcy" name="currency"><?= currency_options((string) ($_POST['currency'] ?? null)) ?></select>
      </div>
      <div class="field">
        <label class="f" for="rStart"><?= $isEdit && (int) $editRule['runs_count'] > 0 ? '开始日期（保留下次执行日）' : '首次执行日' ?></label>
        <input type="date" id="rStart" name="startDate" required
               value="<?= e((string) ($_POST['startDate'] ?? date('Y-m-d'))) ?>">
      </div>
      <div class="field">
        <label class="f" for="rEnd">结束日（可空）</label>
        <input type="date" id="rEnd" name="endDate" value="<?= e((string) ($_POST['endDate'] ?? '')) ?>">
      </div>
      <div class="field span-2">
        <label class="f" for="rAcc">费用科目（采购 / 费用类）</label>
        <select id="rAcc" name="expenseAccountCode">
          <?php foreach ($costAccounts as $a): ?>
            <option value="<?= e((string) $a['account_code']) ?>"
              <?= (string) ($_POST['expenseAccountCode'] ?? '6200') === (string) $a['account_code'] ? 'selected' : '' ?>>
              <?= e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) ?>
            </option>
          <?php endforeach; ?>
        </select>
      </div>
      <div class="field span-2">
        <label class="f" for="rDesc">摘要（写进单据描述）</label>
        <input type="text" id="rDesc" name="description" maxlength="400"
               value="<?= e((string) ($_POST['description'] ?? '')) ?>" placeholder="例：2026 年 11 月办公室租金">
      </div>
      <div class="field span-2" id="autoPostField">
        <label class="f">自动记账</label>
        <label class="check-line">
          <input type="checkbox" name="autoPost" value="1" <?= !empty($_POST['autoPost']) ? 'checked' : '' ?>>
          建单后自动走复核与记账（费用规则仅生成草稿）
        </label>
      </div>
    </div>
    <div class="card-actions">
      <a class="btn" href="<?= e($self) ?>">取消</a>
      <button class="btn primary" type="submit"><?= e($isEdit ? '保存修改' : '保存规则') ?></button>
    </div>
  </form>
</section>
<script>
(function () {
  var kind = document.getElementById('rKind'), box = document.querySelector('input[name="autoPost"]');
  if (!kind || !box) return;
  function sync() { if (kind.value === 'expense') { box.checked = false; box.disabled = true; } else { box.disabled = false; } }
  kind.addEventListener('change', sync); sync();
})();
</script>
<?php endif; ?>

<?php if (!$showNew): ?>
<section class="card">
  <div class="card-head">
    <h2>规则列表</h2>
    <span class="hint">「执行一次」按下次执行日建单，并把下次执行日往后推一期</span>
  </div>
  <?php
    $totalRows = count($rules);
    if ($per > 0) { $rules = array_slice($rules, ($page - 1) * $per, $per); }
  ?>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>规则名称</th><th style="width:100px">类型</th><th>往来单位</th>
        <th style="width:80px">频率</th><th class="num" style="width:130px">金额</th>
        <th style="width:110px">下次执行</th><th style="width:110px">上次执行</th>
        <th class="num" style="width:70px">已执行</th><th style="width:90px">状态</th><th style="width:280px"></th>
      </tr></thead>
      <tbody>
      <?php if (!$rules): ?><tr><td colspan="10" class="table-empty">还没有循环规则</td></tr><?php endif; ?>
      <?php foreach ($rules as $x): ?>
        <?php
          $st = (string) $x['status'];
          $stCls = $st === 'active' ? 'ok' : ($st === 'paused' ? 'warn' : 'draft');
          $stLab = $st === 'active' ? '生效' : ($st === 'paused' ? '已暂停' : '已结束');
        ?>
        <tr>
          <td><div><?= e((string) $x['name']) ?></div>
            <?php if (!empty($x['description'])): ?><div class="hint truncate" style="max-width:280px"><?= e((string) $x['description']) ?></div><?php endif; ?>
          </td>
          <td><span class="tag tag-info"><?= e(['invoice' => '销售发票', 'bill' => '账单', 'expense' => '费用'][(string) $x['doc_kind']] ?? (string) $x['doc_kind']) ?></span></td>
          <td class="truncate" style="max-width:200px"><?= e((string) $x['party_name']) ?></td>
          <td class="hint"><?= e($FREQ[(string) $x['frequency']] ?? (string) $x['frequency']) ?></td>
          <td class="num"><?= money($x['amount_original'], (string) $x['currency']) ?></td>
          <td class="mono hint"><?= e((string) $x['next_run']) ?></td>
          <td class="mono hint"><?= e((string) ($x['last_run'] ?? '—')) ?></td>
          <td class="num"><?= num((int) $x['runs_count']) ?></td>
          <td><span class="tag tag-<?= e($stCls) ?>"><?= e($stLab) ?></span></td>
          <td style="text-align:right;white-space:nowrap">
            <?php if ($role === 'auditor'): ?><span class="hint">只读</span><?php else: ?>
              <a class="btn sm" href="<?= e($self . '&edit=' . (int) $x['rule_id']) ?>">编辑</a>
              <?php if ($st === 'active'): ?>
                <form method="post" class="inline-form">
                  <?= csrf_field() ?><input type="hidden" name="action" value="recurring_run">
                  <input type="hidden" name="id" value="<?= (int) $x['rule_id'] ?>">
                  <button class="btn sm primary" data-confirm="<?= e(t('确认按这条规则建单？')) ?>"
                    data-confirm-note="<?= e(t('会在「下次执行日」生成一张草稿单据，下次执行日往后推一期。')) ?>"
                    data-confirm-ok="<?= e(t('确认建单')) ?>">执行一次</button>
                </form>
              <?php endif; ?>
              <form method="post" class="inline-form">
                <?= csrf_field() ?><input type="hidden" name="action" value="recurring_status">
                <input type="hidden" name="id" value="<?= (int) $x['rule_id'] ?>">
                <input type="hidden" name="status" value="<?= $st === 'active' ? 'paused' : 'active' ?>">
                <button class="btn sm"><?= $st === 'active' ? '暂停' : '启用' ?></button>
              </form>
            <?php endif; ?>
          </td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
  </div>
  <?= pager_html($page, $per, $totalRows, $pagerParams, 'recurring') ?>
</section>
<?php endif; ?>

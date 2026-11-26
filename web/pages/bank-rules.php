<?php
/*
 * LtBooks — pages/bank-rules.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 银行规则：按摘要里的关键词自动指定对方科目。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$msg = null; $err = null; $ruleCreateError = false;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor') {
    $act = (string) ($_POST['action'] ?? '');
    if ($act === 'rule_create') {
        $r = api_post('/bank-rules', [
            'name' => trim((string) ($_POST['name'] ?? '')),
            'matchField' => (string) ($_POST['matchField'] ?? 'any'),
            'matchText' => trim((string) ($_POST['matchText'] ?? '')),
            'txnKind' => (string) ($_POST['txnKind'] ?? 'any'),
            'counterAccount' => (string) ($_POST['counterAccount'] ?? ''),
            'autoPost' => !empty($_POST['autoPost']),
            'actor' => $actor,
        ]);
        if ($r['ok']) { header('Location: ?p=bank-rules&msg=' . urlencode('规则已建立')); exit; }
        $err = (string) $r['error'];
        $ruleCreateError = true;
    } elseif ($act === 'rule_delete') {
        $r = api_post('/bank-rules/' . (int) ($_POST['id'] ?? 0) . '/delete', ['actor' => $actor]);
        if ($r['ok']) { header('Location: ?p=bank-rules&msg=' . urlencode('规则已删除')); exit; }
        $err = (string) $r['error'];
    } elseif ($act === 'rule_apply') {
        $r = api_post('/bank-rules/apply', ['actor' => $actor]);
        if ($r['ok']) {
            $n = (int) ($r['data']['total'] ?? 0);
            header('Location: ?p=bank-rules&msg=' . urlencode("已套用，命中 {$n} 笔未匹配流水")); exit;
        }
        $err = (string) $r['error'];
    }
}
[$page, $per] = pager_state('ledu_bank_rules_per', 25);
$limit = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$rl = api_get('/bank-rules?limit=' . $limit . '&offset=' . $offset);
$rules = $rl['ok'] ? ($rl['data']['rules'] ?? []) : [];
$totalRows = (int) ($rl['data']['total'] ?? count($rules));
$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
// 对方科目先列费用/成本，再列收入与资产负债——银行流水多数是费用
$__order = ['expense' => 0, 'cogs' => 1, 'revenue' => 2, 'asset' => 3, 'liability' => 4, 'equity' => 5];
$expense = array_values(array_filter($accounts, fn($a) => isset($__order[$a['category']])));
usort($expense, fn($a, $b) => [$__order[$a['category']], $a['account_code']]
                           <=> [$__order[$b['category']], $b['account_code']]);
$formMode = $role !== 'auditor'
    && ((string) ($_GET['new'] ?? '') === '1' || $ruleCreateError);
$msg = (string) ($_GET['msg'] ?? '');
?>
<div class="page-head">
  <div>
    <h1 class="page-title">银行规则</h1>
    <div class="page-sub">按摘要关键词自动指定对方科目；套用只给建议，过账仍要你确认</div>
  </div>
  <?php if (!$formMode): ?>
  <div class="page-actions">
    <form method="post" class="inline-form">
      <?= csrf_field() ?><input type="hidden" name="action" value="rule_apply">
      <button class="btn">套用到未匹配流水</button>
    </form>
    <?php if ($role !== 'auditor'): ?>
      <a class="btn primary" href="?p=bank-rules&new=1">＋ <?= e(t('新建规则')) ?></a>
    <?php endif; ?>
  </div>
  <?php endif; ?>
</div>

<?= help_html('bank-rules') ?>

<?php if ($msg !== ''): ?>
  <div class="banner PASS" style="margin-bottom:12px"><span class="banner-icon">✓</span>
    <div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason"><?= e($msg) ?></div></div></div>
<?php endif; ?>
<?php if ($err): ?><?= errbox($err) ?><?php endif; ?>

<?php if (!$formMode): ?>
<?php ob_start(); ?>
<?php if (!$rules): ?>
  <?= empty_state('还没有规则。常见做法：摘要含「MONTHLY SERVICE FEE」→ 银行手续费；含「SAAS」→ IT 服务费。') ?>
<?php else: ?>
<div class="table-wrap"><table>
  <thead><tr><th>规则名称</th><th>匹配</th><th>方向</th><th>对方科目</th>
    <th class="num">命中</th><th>状态</th><th style="width:80px"></th></tr></thead>
  <tbody>
  <?php foreach ($rules as $r): ?>
    <tr>
      <td><?= e((string) $r['name']) ?></td>
      <td class="mono hint"><?= e((string) $r['match_text']) ?></td>
      <td><?= e(['any' => '不限', 'in' => '收入', 'out' => '支出'][(string) $r['txn_kind']] ?? (string) $r['txn_kind']) ?></td>
      <td class="mono"><?= e((string) $r['counter_account']) ?></td>
      <td class="num"><?= (int) $r['hits'] ?></td>
      <td><span class="tag tag-<?= $r['status'] === 'active' ? 'ok' : 'info' ?>"><?= e((string) $r['status']) ?></span></td>
      <td>
        <?php if ($role !== 'auditor'): ?>
        <form method="post" class="inline-form">
          <?= csrf_field() ?><input type="hidden" name="action" value="rule_delete">
          <input type="hidden" name="id" value="<?= (int) $r['rule_id'] ?>">
          <button class="btn sm danger" data-confirm="删除这条规则？" data-confirm-ok="删除">删除</button>
        </form>
        <?php endif; ?>
      </td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
<?php endif; ?>
<?php echo card('规则列表', ob_get_clean(),
    pager_html($page, $per, $totalRows, ['p' => 'bank-rules']), false); ?>
<?php endif; ?>

<?php if ($formMode): ?>
<?php ob_start(); ?>
  <form method="post">
    <?= csrf_field() ?><input type="hidden" name="action" value="rule_create">
    <div class="grid form-grid">
      <div class="field"><label class="f">规则名称 *</label>
        <input type="text" name="name" required placeholder="如：银行月费"></div>
      <div class="field"><label class="f">摘要包含 *</label>
        <input type="text" name="matchText" required placeholder="如：MONTHLY SERVICE FEE"></div>
      <div class="field"><label class="f">方向</label>
        <select name="txnKind">
          <option value="any">不限</option><option value="out">支出</option><option value="in">收入</option>
        </select></div>
      <div class="field"><label class="f">对方科目 *</label>
        <select name="counterAccount" required>
          <?php foreach ($expense as $a): ?>
            <option value="<?= e((string) $a['account_code']) ?>">
              <?= e($a['account_code'] . ' · ' . acc_name((string) $a['account_code'], (string) $a['account_name'])) ?>
            </option>
          <?php endforeach; ?>
        </select></div>
    </div>
    <div class="toolbar form-actions">
      <a class="btn" href="?p=bank-rules">取消</a>
      <button class="btn primary">保存规则</button>
      <span class="hint">套用后给的是建议清单，不会自动记账</span>
    </div>
  </form>
<?php echo card('新建规则', ob_get_clean(),
    '<a class="btn sm" href="?p=bank-rules">返回列表</a>'); ?>
<?php endif; ?>

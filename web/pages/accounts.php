<?php
/*
 * LtBooks — pages/accounts.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'toggle_account') {
    $code = (string) ($_POST['code'] ?? '');
    $active = ($_POST['active'] ?? '') === '1';
    $r = api_post('/accounts/' . rawurlencode($code) . '/active',
                  ['active' => $active, 'actor' => $displayName ?? 'system']);
    $msg = $r['ok'] ? ($code . ($active ? ' 已启用' : ' 已停用')) : null;
    $errMsg = $r['ok'] ? null : (string) $r['error'];
}

// 新增科目
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'create_account') {
    $r = api_post('/accounts', [
        'code'          => trim((string) ($_POST['code'] ?? '')),
        'name'          => trim((string) ($_POST['name'] ?? '')),
        'category'      => (string) ($_POST['category'] ?? 'asset'),
        'normalBalance' => (string) ($_POST['normalBalance'] ?? 'debit'),
        'parent'        => trim((string) ($_POST['parent'] ?? '')),
        'actor'         => $user['username'] ?? 'system',
    ]);
    $r['ok'] ? $msg = '科目 ' . e((string) ($_POST['code'] ?? '')) . ' 已新增' : $errMsg = (string) $r['error'];
}
// 删除科目
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'delete_account') {
    $r = api_request('DELETE', '/accounts/' . rawurlencode((string) ($_POST['code'] ?? '')));
    $r['ok'] ? $msg = '科目 ' . e((string) ($_POST['code'] ?? '')) . ' 已删除' : $errMsg = (string) $r['error'];
}

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

$r = api_get('/accounts/tree');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$all = $r['data']['accounts'];

$catName = ['asset' => '资产', 'liability' => '负债', 'equity' => '权益',
            'revenue' => '收入', 'cogs' => '销售成本', 'expense' => '费用'];

// 构建父子关系
$byCode = [];
foreach ($all as $a) { $byCode[$a['account_code']] = $a; }
$children = [];
$roots = [];
foreach ($all as $a) {
    $pc = $a['parent_account_code'];
    if ($pc !== null && isset($byCode[$pc])) { $children[$pc][] = $a['account_code']; }
    else { $roots[] = $a['account_code']; }
}
sort($roots);
$catOrder = array_flip(array_keys($catName));

$activeCount = count(array_filter($all, fn($a) => $a['is_active']));
// 默认只看启用科目；勾选后连同停用科目一起显示
$totalAll = count($all);
$inactiveCount = $totalAll - count(array_filter($all, fn($a) => $a['is_active']));
$showInactive = !empty($_GET['show_inactive']);
if (!$showInactive) {
    $all = array_values(array_filter($all, fn($a) => $a['is_active']));
    $byCode = []; foreach ($all as $a) { $byCode[$a['account_code']] = $a; }
    $children = []; $roots = [];
    foreach ($all as $a) {
        $pc = $a['parent_account_code'];
        if ($pc !== null && isset($byCode[$pc])) { $children[$pc][] = $a['account_code']; }
        else { $roots[] = $a['account_code']; }
    }
}

// 大类按资产→负债→权益→收入→销售成本→费用排列，类内按编码，保证类别标题只出现一次
usort($roots, function (string $x, string $y) use ($byCode, $catOrder): int {
    $cx = $catOrder[$byCode[$x]['category'] ?? ''] ?? 99;
    $cy = $catOrder[$byCode[$y]['category'] ?? ''] ?? 99;
    return $cx === $cy ? strcmp($x, $y) : $cx <=> $cy;
});
$catCount = [];
foreach ($all as $a) {
    $c = (string) ($a['category'] ?? '');
    $catCount[$c] = ($catCount[$c] ?? 0) + 1;
}

function render_node(string $code, array $byCode, array $children, int $depth, string $role, bool $isLast = false): string
{
    $a = $byCode[$code];
    $hasKids = !empty($children[$code]);
    $indent = 10 + $depth * 14;
    $icon = $hasKids ? '▾' : '·';
    $h = '<tr>';
    $h .= '<td style="padding-left:' . $indent . 'px;white-space:nowrap">'
        . '<span style="color:var(--c-text-3);font-size:var(--f-2xs);margin-right:6px">' . $icon . '</span>'
        . '<code>' . e($code) . '</code></td>';
    $h .= '<td>' . e(acc_name($code, (string) $a['account_name'])) . '</td>';
    $fs = trim((string) fs_line_label((string) $a['fs_line_item']));
    $h .= '<td class="hint">' . e($fs !== '' ? $fs : '—') . '</td>';
    $h .= '<td class="hint">' . e($a['normal_balance'] === 'debit' ? '借' : '贷') . '</td>';
    $h .= '<td class="num">' . (int) $a['txn_count'] . '</td>';
    $h .= '<td class="acc-actions">';
    if ($role === 'auditor') {
        $h .= $a['is_active'] ? badge('PASS') : '<span class="pill st-void">停用</span>';
    } else {
        $target = $a['is_active'] ? '0' : '1';
        $label = $a['is_active'] ? '停用' : '启用';
        $cls = $a['is_active'] ? 'btn sm ghost' : 'btn sm primary';
        $h .= '<form method="post" style="display:inline">' . csrf_field()
            . '<input type="hidden" name="action" value="toggle_account">'
            . '<input type="hidden" name="code" value="' . e($code) . '">'
            . '<input type="hidden" name="active" value="' . $target . '">'
            . '<button class="' . $cls . '">' . $label . '</button></form>';
        if ((int) $a['txn_count'] === 0 && !$hasKids) {
            $h .= '<form method="post" style="display:inline;margin-left:4px" '
                . 'onsubmit="return confirm(\'删除科目 ' . e($code) . '？此操作不可撤销。\')">' . csrf_field()
                . '<input type="hidden" name="action" value="delete_account">'
                . '<input type="hidden" name="code" value="' . e($code) . '">'
                . '<button class="btn sm danger">删除</button></form>';
        }
    }
    $h .= '</td></tr>';
    if ($hasKids) {
        foreach ($children[$code] as $c) {
            $h .= render_node($c, $byCode, $children, $depth + 1, $role);
        }
    }
    return $h;
}
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e(t('会计科目')) ?></h1>
    <div class="page-sub"><?= e(t('会计')) ?></div>
  </div>
  <?php if ($role === 'admin'): ?>
  <div class="page-actions">
    <button type="button" class="btn primary" data-acc-add>＋ <?= e(t('新建科目')) ?></button>
  </div>
  <?php endif; ?>
</div>
<?= help_html('accounts') ?>
<?php ob_start(); ?>
<div class="accbar">
  <div class="accstats">
    <span><i>科目总数</i><b><?= num($totalAll) ?></b></span>
    <span><i>启用中</i><b><?= num($activeCount) ?></b></span>
    <span><i>停用数</i><b><?= num($inactiveCount) ?></b></span>
  </div>
  <div class="accbar-actions">
    <a class="btn sm" href="?p=accounts&show_inactive=<?= $showInactive ? '0' : '1' ?>">
      <?= $showInactive ? '只看启用科目' : '显示停用科目（' . $inactiveCount . '）' ?>
    </a>
  </div>
</div>
<?php if ($role === 'admin'): ?>
<div class="accadd" id="accAdd" hidden>
  <form method="post" class="accform">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="create_account">
    <input type="text" name="code" placeholder="编码 6999" required pattern="[0-9]{3,6}">
    <input type="text" name="name" placeholder="科目名称" required>
    <select name="category">
      <?php foreach ($catName as $k => $v): ?><option value="<?= e($k) ?>"><?= e($v) ?></option><?php endforeach; ?>
    </select>
    <select name="normalBalance"><option value="debit">借</option><option value="credit">贷</option></select>
    <input type="text" name="parent" placeholder="上级科目（可空）">
    <button class="btn primary sm">保存</button>
  </form>
</div>
<script>(function(){var b=document.querySelector("[data-acc-add]"),p=document.getElementById("accAdd");if(!b||!p)return;b.addEventListener("click",function(){p.hidden=!p.hidden;if(!p.hidden){var i=p.querySelector("input[name=code]");if(i)i.focus();}});})();</script>
<?php endif; ?>
<div class="table-wrap acc-table"><table>
<thead><tr><th style="width:96px">编码</th><th>科目名称</th><th>报表项目</th>
<th style="width:44px">方向</th><th class="num" style="width:60px">分录数</th>
<th class="acc-actions-h" style="width:120px">操作</th></tr></thead>
<tbody>
<?php $lastCat = null; ?>
<?php foreach ($roots as $rc): ?>
  <?php $rootCat = $byCode[$rc]['category'] ?? ''; ?>
  <?php if ($rootCat !== $lastCat): ?>
  <tr class="acc-group"><td colspan="6">
    <?= e($catName[$rootCat] ?? $rootCat) ?><span class="acc-group-count">· <?= (int) ($catCount[$rootCat] ?? 0) ?></span>
  </td></tr>
  <?php $lastCat = $rootCat; endif; ?>
  <?= render_node($rc, $byCode, $children, 0, $role) ?>
<?php endforeach; ?>
</tbody></table></div>
<div class="acc-note">
  已发生分录的科目不允许停用；有启用中子科目的父科目须先停用子科目。
  停用只影响新分录的可选范围，不影响历史账。
</div>
<?php echo card('', ob_get_clean(), '', false); ?>

<style>
.accbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid var(--c-border)}
.accstats{display:flex;align-items:baseline;gap:16px;font-size:var(--f-xs);color:var(--c-text-3)}
.accstats i{font-style:normal;margin-right:4px}
.accstats b{font-family:var(--mono);font-size:var(--f-sm);font-weight:600;color:var(--c-text);margin-left:3px}
.accbar-actions{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.accbar .btn.sm{height:34px}
.accadd{padding:0 12px 10px;border-bottom:1px solid var(--c-border)}
.accform{display:grid;margin-top:8px;padding:8px 10px;background:var(--c-surface-alt);
  border:1px solid var(--c-border);border-radius:var(--r-md);
  grid-template-columns:repeat(6,minmax(0,1fr));gap:6px;align-items:center}
.accform input,.accform select{height:36px;font-size:var(--f-sm);padding:0 10px;margin:0;min-width:0}
.accform .btn{height:34px;font-size:var(--f-sm)}
.acc-table{max-height:68vh;overflow:auto}
.acc-table table{font-size:13px}
.acc-table thead th{height:38px;padding:0 12px;font-size:11.5px;white-space:nowrap}
.acc-table tbody td{height:40px;padding:0 12px}
.acc-table tbody tr.acc-group td{height:28px;background:var(--c-surface-alt);
  font-size:var(--f-xs);font-weight:600;color:var(--c-text);white-space:nowrap;
  border-top:1px solid var(--c-border);border-bottom:1px solid var(--c-border)}
.acc-table tbody tr.acc-group:first-child td{border-top:0}
.acc-group-count{margin-left:6px;font-weight:400;font-family:var(--mono);
  font-size:var(--f-2xs);color:var(--c-text-3)}
.acc-table th.acc-actions-h,.acc-table tbody td.acc-actions{text-align:right}
.acc-table tbody td.acc-actions{white-space:nowrap}
.acc-table td:first-child{padding-left:10px}
.acc-table td .btn.sm{height:28px;padding:0 10px;font-size:12px;line-height:26px}
.acc-note{padding:6px 12px;font-size:var(--f-2xs);color:var(--c-text-3);line-height:1.6}
@media (max-width:900px){.accform{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>

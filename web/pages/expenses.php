<?php
/*
 * LtBooks — pages/expenses.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
[$page, $per] = pager_state('ledu_expenses_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kwPage = trim((string) ($_GET['q'] ?? ''));
$r = api_get('/expenses?limit=' . $limit . '&offset=' . $offset
           . ($kwPage !== '' ? '&q=' . urlencode($kwPage) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rows = $r['data']['expenses'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? count($rows));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }
$role = isset($role) ? $role : 'accountant';
$bar = '<form method="get" class="list-bar">'
    . '<input type="hidden" name="p" value="expenses">'
    . '<input type="text" name="q" value="' . e($kwPage) . '" placeholder="搜索费用号 / 用途 / 项目 / 备注" style="width:300px">'
    . '<button class="btn sm">搜索</button>'
    . ($kwPage !== '' ? '<a class="btn sm" href="?p=expenses">清除</a>' : '')
    . '</form>';
ob_start();
echo $bar;
if (!$rows) { echo empty_state(t('暂无费用。没有正式发票的小额支出（打车、文具、餐费）用「新建费用」记。')); } else { ?>
<div class="table-wrap"><table>
<thead><tr><th>费用号</th><th>支出用途</th><th>项目</th><th>日期</th><th>币种</th>
<th class="num">原币</th><th class="num">折HKD</th><th>状态</th><th>操作</th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<tr><td><a href="?p=doc-view&type=expense&id=<?= (int) $x['expense_id'] ?>&back=<?= e(urlencode('?p=expenses')) ?>"><?= e($x['expense_no']) ?></a></td><td><?= e($x['category']) ?></td>
<td><?= e((string) ($x['project_name'] ?? '') ?: '—') ?></td>
<td class="nowrap"><?= e($x['date']) ?></td><td><?= e($x['currency']) ?></td>
<td class="num"><?= money($x['amount'], (string) $x['currency']) ?></td>
<td class="num"><?= $x['currency'] === 'HKD' ? '—' : money($x['amount_functional'], 'HKD') ?></td>
<td><?= status_pill((string) $x['status']) ?></td>
<td style="white-space:nowrap">
  <?php if ((string) $x['status'] === 'draft' && $role !== 'auditor'): ?>
    <?= draft_delete_form('expense', (int) $x['expense_id'], 'expenses') ?>
  <?php else: ?><span class="hint">—</span><?php endif; ?>
</td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php } echo card('', ob_get_clean(),
    pager_html($page, $per, $totalRows, ['p' => 'expenses', 'q' => $kwPage ?: null]), false); ?>

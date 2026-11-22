<?php
/*
 * LtBooks — pages/pending.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
[$page, $per] = pager_state('ledu_pending_per', 25);
$r = api_get('/pending-review');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rows = $r['data']['reviews'] ?? [];
$role = isset($role) ? $role : 'accountant';  // 来自服务端会话
if (!$rows) { echo card('', empty_state('没有待办')); return; }
ob_start(); ?>
<?php
  $pTotal = count($rows);
  if ($per > 0) { $rows = array_slice($rows, ($page - 1) * $per, $per); }
?>
<div class="table-wrap"><table>
<thead><tr><th></th><th>类别</th><th>级别</th><th>原因</th><th>来源</th><th>操作</th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<tr>
  <td><span style="display:inline-block;width:8px;height:8px;border-radius:4px;background:<?=
    $x['severity'] === 'blocker' ? 'var(--fail)' : ($x['severity'] === 'warning' ? 'var(--review)' : 'var(--accent)')
  ?>"></span></td>
  <td><code><?= e(t(['invoice' => '发票', 'bill' => '账单', 'payment' => '收付款',
                       'expense' => '费用', 'journal' => '分录'][(string) $x['kind']] ?? (string) $x['kind'])) ?></code></td>
  <td><?= badge($x['severity'] === 'blocker' ? 'FAIL' : 'REVIEW') ?></td>
  <td><?= e((string) $x['reason']) ?></td>
  <td class="hint"><?= e(t(['invoices' => '发票', 'bills' => '账单', 'payments' => '收付款',
                             'expenses' => '费用', 'journal_entries' => '分录'][(string) ($x['ref_table'] ?? '')] ?? (string) ($x['ref_table'] ?? '—'))) ?><?= $x['ref_id'] ? '#' . (int) $x['ref_id'] : '' ?></td>
  <td style="white-space:nowrap">
    <?php if ($role === 'auditor'): ?>
      <span class="hint">只读</span>
    <?php else: ?>
      <form method="post" style="display:inline">
  <?= csrf_field() ?>
        <input type="hidden" name="action" value="resolve_review">
        <input type="hidden" name="id" value="<?= (int) $x['review_id'] ?>">
        <input type="hidden" name="mode" value="resolve">
        <input type="hidden" name="resolution" value="已核对">
        <input type="hidden" name="actor" value="<?= e($role) ?>">
        <input type="hidden" name="back" value="pending">
        <button class="btn sm">确认</button>
      </form>
      <form method="post" style="display:inline">
  <?= csrf_field() ?>
        <input type="hidden" name="action" value="resolve_review">
        <input type="hidden" name="id" value="<?= (int) $x['review_id'] ?>">
        <input type="hidden" name="mode" value="dismiss">
        <input type="hidden" name="actor" value="<?= e($role) ?>">
        <input type="hidden" name="back" value="pending">
        <button class="btn sm">忽略</button>
      </form>
    <?php endif; ?>
  </td>
</tr>
<?php endforeach; ?>
</tbody></table></div>
<?= pager_html($page, $per, $pTotal, ['p' => 'pending'], 'pending') ?>
<?php echo card('', ob_get_clean(), '', false);

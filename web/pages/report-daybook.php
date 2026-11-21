<?php
/*
 * LtBooks — pages/report-daybook.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$from = (string) ($_GET['from'] ?? '');
$to = (string) ($_GET['to'] ?? '');
$qs = '/reports/daybook';
$pairs = [];
if ($from !== '') { $pairs[] = 'from=' . urlencode($from); }
if ($to !== '') { $pairs[] = 'to=' . urlencode($to); }
if ($pairs) { $qs .= '?' . implode('&', $pairs); }
$r = api_get($qs);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
?>
<form method="get" class="toolbar">
  <input type="hidden" name="p" value="report-daybook">
  <input type="date" name="from" value="<?= e($from) ?>">
  <input type="date" name="to" value="<?= e($to) ?>">
  <button class="btn">筛选</button>
</form>
<?php ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>日期</th><th>分录号</th><th>来源</th><th>摘要</th>
<th>状态</th><th class="num">借方合计</th></tr></thead>
<tbody>
<?php if (!$d['entries']): ?>
  <tr><td colspan="6"><?= empty_state('该区间没有分录') ?></td></tr>
<?php endif; ?>
<?php foreach ($d['entries'] as $x): ?>
  <tr><td><?= e((string) $x['entry_date']) ?></td>
  <td><a href="?p=journal-view&id=<?= (int) $x['entry_id'] ?>"><?= e((string) $x['entry_no']) ?></a></td>
  <td><?= e(source_label((string) $x['source_type'])) ?></td>
  <td><?= e((string) ($x['description'] ?: '—')) ?></td>
  <td><?= status_pill((string) $x['status']) ?></td>
  <td class="num"><?= money($x['total_debit']) ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php echo card('日记账明细', ob_get_clean(), '', false); ?>

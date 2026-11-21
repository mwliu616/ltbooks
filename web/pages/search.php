<?php
/*
 * LtBooks — pages/search.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$q = trim((string) ($_GET['q'] ?? ''));
if ($q === '') {
    echo card('搜索', empty_state('在顶部输入发票号、账单号、分录号或银行参考号'));
    return;
}
$r = api_get('/search?q=' . urlencode($q));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rows = $r['data']['results'] ?? [];

$labels = ['invoice' => '发票', 'bill' => '账单', 'entry' => '分录', 'bank' => '银行流水'];
ob_start();
if (!$rows) {
    echo empty_state('没有找到与「' . $q . '」匹配的记录');
} else { ?>
<div class="table-wrap"><table>
<thead><tr><th>类型</th><th>单号</th><th>内容</th><th>状态</th><th></th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
  <tr><td class="hint"><?= e($labels[$x['type']] ?? $x['type']) ?></td>
  <td><?= e((string) $x['title']) ?></td>
  <td><?= e((string) $x['sub']) ?></td>
  <td><?= $x['status'] !== '' ? status_pill((string) $x['status']) : '—' ?></td>
  <td><a class="btn sm" href="<?= e((string) $x['url']) ?>">打开</a></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php }
echo card('搜索结果：' . $q . '（' . count($rows) . ' 条）', ob_get_clean(), '', false);


<?php
/*
 * LtBooks — pages/journal.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
?>
<?php
// 列表只做查询与跳转：明细 / 附件 / 编辑 / 删除 / 冲销都在独立的 journal-view 页面，
// 唯一的例外是「凭证」导出菜单（PDF 直接在新标签打开）。
[$page, $per] = pager_state('ledu_journal_per', 25);
$limit  = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$kwPage = trim((string) ($_GET['q'] ?? ''));
$r = api_get('/journal?limit=' . $limit . '&offset=' . $offset
           . ($kwPage !== '' ? '&q=' . urlencode($kwPage) : ''));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$rows = $r['data']['entries'] ?? [];
$totalRows = (int) ($r['data']['total'] ?? count($rows));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }
$role = isset($role) ? $role : 'accountant';  // 来自服务端会话
$__ids = implode(',', array_map(fn($x) => (int) $x['entry_id'], $rows));

// 期间倒序、同期间内按分录号倒序：让表格按期间成段，分组标题只出现一次
usort($rows, function (array $a, array $b): int {
    $pa = (string) ($a['period'] ?? '');
    $pb = (string) ($b['period'] ?? '');
    return $pa === $pb ? (int) $b['entry_id'] <=> (int) $a['entry_id'] : strcmp($pb, $pa);
});
// 分组小计只统计当前页，避免误导为全期间合计
$periodAgg = [];
foreach ($rows as $x) {
    $p = (string) ($x['period'] ?? '') ?: '—';
    $periodAgg[$p]['n'] = ($periodAgg[$p]['n'] ?? 0) + 1;
    $periodAgg[$p]['d'] = ($periodAgg[$p]['d'] ?? 0) + (float) $x['total_debit'];
    $periodAgg[$p]['c'] = ($periodAgg[$p]['c'] ?? 0) + (float) $x['total_credit'];
}
$draftCnt = count(array_filter($rows, fn($x) => ($x['status'] ?? '') === 'draft'));

ob_start(); ?>
<div class="jrbar">
  <form method="get" class="jrsearch">
    <input type="hidden" name="p" value="journal">
    <input type="search" name="q" value="<?= e($kwPage) ?>"
           placeholder="<?= e(t('搜索分录号 / 摘要 / 来源')) ?>">
    <button class="btn sm"><?= e(t('搜索')) ?></button>
    <?php if ($kwPage !== ''): ?>
      <a class="btn sm" href="?p=journal"><?= e(t('清除')) ?></a>
    <?php endif; ?>
  </form>
  <div class="jrstats">
    <span><i><?= e(t('本页')) ?></i><b><?= count($rows) ?></b></span>
    <span><i><?= e(t('全部')) ?></i><b><?= num($totalRows) ?></b></span>
    <span><i><?= e(t('草稿')) ?></i><b><?= $draftCnt ?></b></span>
  </div>
  <div class="jrbar-actions">
    <?php if ($rows): ?>
      <?= voucher_menu(['ids' => $__ids], t('打印本页凭证') . ' (' . count($rows) . ')', 'btn sm') ?>
    <?php endif; ?>
    <?php if ($role !== 'auditor'): ?>
      <a class="btn sm primary" href="?p=journal-new">＋ <?= e(t('手工分录')) ?></a>
    <?php endif; ?>
  </div>
</div>
<?php if (!$rows): ?>
  <?= empty_state('尚无分录') ?>
<?php else: ?>
<div class="table-wrap jr-table"><table>
<thead><tr><th style="width:110px"><?= e(t('分录号')) ?></th><th style="width:100px"><?= e(t('日期')) ?></th>
<th style="width:90px"><?= e(t('来源')) ?></th><th><?= e(t('摘要')) ?></th>
<th class="num" style="width:120px"><?= e(t('借方')) ?></th><th class="num" style="width:120px"><?= e(t('贷方')) ?></th>
<th style="width:90px"><?= e(t('状态')) ?></th><th class="jr-actions-h" style="width:240px"><?= e(t('操作')) ?></th></tr></thead>
<tbody>
<?php $lastPeriod = null; ?>
<?php foreach ($rows as $x): ?>
  <?php $perKey = (string) ($x['period'] ?? '') ?: '—'; ?>
  <?php if ($perKey !== $lastPeriod): $agg = $periodAgg[$perKey]; ?>
  <tr class="jr-group"><td colspan="8">
    <?= e($perKey) ?><span class="jr-group-count"><?= (int) $agg['n'] ?> ·
      <?= e(t('借方合计')) ?> <?= money($agg['d']) ?> ·
      <?= e(t('贷方合计')) ?> <?= money($agg['c']) ?></span>
  </td></tr>
  <?php $lastPeriod = $perKey; endif; ?>
<tr>
  <td class="mono"><a href="?p=journal-view&amp;id=<?= (int) $x['entry_id'] ?>"><?= e($x['entry_no']) ?></a></td>
  <td class="nowrap"><?= e($x['entry_date']) ?></td>
  <td><?= e(source_label((string) $x['source_type'])) ?></td>
  <td><?= e((string) ($x['description'] ?: '—')) ?></td>
  <td class="num"><?= money($x['total_debit']) ?></td>
  <td class="num"><?= money($x['total_credit']) ?></td>
  <td><?= status_pill((string) $x['status']) ?></td>
  <td class="jr-actions">
    <a class="btn sm" href="?p=journal-view&amp;id=<?= (int) $x['entry_id'] ?>"><?= e(t('明细')) ?></a>
    <a class="btn sm" href="?p=journal-view&amp;id=<?= (int) $x['entry_id'] ?>#attach"><?= e(t('附件')) ?><?= (int) ($x['file_count'] ?? 0) > 0 ? ' (' . (int) $x['file_count'] . ')' : '' ?></a>
    <a class="btn sm" target="_blank" href="/pdf/voucher.php?id=<?= (int) $x['entry_id'] ?>&amp;lang=<?= e(lang()) ?>"><?= e(t('凭证')) ?></a>
    <?php if ($role !== 'auditor' && $x['status'] === 'draft'): ?>
      <a class="btn sm" href="?p=journal-new&amp;edit=<?= (int) $x['entry_id'] ?>"><?= e(t('编辑')) ?></a>
    <?php endif; ?>
  </td>
</tr>
<?php endforeach; ?>
</tbody></table></div>
<?php endif; ?>
<?php echo card('日记账', ob_get_clean(),
    pager_html($page, $per, $totalRows, ['p' => 'journal', 'q' => $kwPage ?: null]), false); ?>

<style>
.jrbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid var(--c-border)}
.jrsearch{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.jrsearch input[type=search]{height:34px;width:230px;font-size:13px;padding:0 10px;margin:0;
  border-color:var(--c-border)}
.jrsearch .btn,.jrbar .btn.sm{height:34px}
.jrstats{display:flex;align-items:baseline;gap:14px;font-size:var(--f-xs);color:var(--c-text-3);
  padding-left:14px;border-left:1px solid var(--c-border)}
.jrstats i{font-style:normal;margin-right:4px}
.jrstats b{font-family:var(--mono);font-size:var(--f-sm);font-weight:600;color:var(--c-text);margin-left:3px}
.jrbar-actions{margin-left:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.jrbar-actions .exp-list{left:auto;right:0}
.jr-table{max-height:68vh;overflow:auto}
.jr-table table{font-size:12.5px}
.jr-table thead th{height:30px;padding:0 10px;font-size:var(--f-2xs);white-space:nowrap}
.jr-table tbody td{height:34px;padding:0 10px}
.jr-table tbody td:nth-child(7){white-space:nowrap}
.jr-table .pill{white-space:nowrap}
.jr-table tbody tr.jr-group td{height:28px;background:var(--c-surface-alt);
  font-size:var(--f-xs);font-weight:600;color:var(--c-text);white-space:nowrap;
  border-top:1px solid var(--c-border);border-bottom:1px solid var(--c-border)}
.jr-table tbody tr.jr-group:first-child td{border-top:0}
.jr-group-count{margin-left:8px;font-weight:400;font-family:var(--mono);
  font-size:var(--f-2xs);color:var(--c-text-3)}
.jr-table th.jr-actions-h,.jr-table tbody td.jr-actions{text-align:right}
.jr-table tbody td.jr-actions{white-space:nowrap}
.jr-table tbody td.jr-actions .btn + .btn{margin-left:6px}
.jr-table td:first-child{padding-left:12px}
@media (max-width:760px){
  .jrsearch{width:100%}
  .jrsearch input[type=search]{flex:1;width:auto;min-width:0}
  .jrstats{width:100%;padding-left:0;border-left:0}
  .jrbar-actions{width:100%;margin-left:0;justify-content:flex-end}
}
</style>

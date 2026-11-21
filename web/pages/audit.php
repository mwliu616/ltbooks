<?php
/*
 * LtBooks — pages/audit.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
// 删除导出文件：只删磁盘文件，审计日志里的 export.create 记录保留
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'delete_export') {
    $res = api_request('DELETE', '/export/file/' . rawurlencode((string) ($_POST['file'] ?? '')));
    if ($res['ok']) {
        header('Location: ?p=audit&msg=' . urlencode('导出文件已删除'));
        exit;
    }
    $exportErr = (string) $res['error'];
}
$kw = trim((string) ($_GET['q'] ?? ''));
$entryId = (int) ($_GET['entry'] ?? 0);

// 每页条数：可切换 10 / 25 / 50 / 100 / 全部，也可自己填
$perAllowed = [10, 25, 50, 100];
$perCookie = (int) ($_COOKIE['ledu_audit_per'] ?? 25);
$per = (int) ($_GET['per'] ?? ($perCookie > 0 ? $perCookie : 25));
if ($per !== 0 && !in_array($per, $perAllowed, true)) {
    $per = max(5, min(500, $per));      // 自定义值夹在 5–500 之间
}
if (isset($_GET['per'])) {
    setcookie('ledu_audit_per', (string) $per, time() + 31536000, '/', '', true, true);
}
$page = max(1, (int) ($_GET['page'] ?? 1));
$limit = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;

$jr = api_get('/journal?limit=' . $limit . '&offset=' . $offset . ($kw !== '' ? '&q=' . urlencode($kw) : ''));
if (!$jr['ok']) { echo errbox((string) $jr['error']); return; }
$rows = $jr['data']['entries'] ?? [];
$totalRows = (int) ($jr['data']['total'] ?? count($rows));
$pageCount = $per === 0 ? 1 : max(1, (int) ceil($totalRows / max(1, $per)));
if ($page > $pageCount) { $page = $pageCount; }

$verify = api_get('/audit/verify');
$v = $verify['ok'] ? $verify['data'] : null;
?>
<div class="toolbar" style="margin-bottom:10px;gap:8px">
  <form method="get" style="display:flex;gap:8px">
    <input type="hidden" name="p" value="audit">
    <input type="text" name="q" value="<?= e($kw) ?>" placeholder="搜索分录号 / 摘要 / 来源" style="width:260px">
    <button class="btn">搜索</button>
  </form>
  <span class="grow"></span>
  <?php if ($v): ?>
    <span class="status-chip <?= $v['valid'] ? 'is-ok' : 'is-fail' ?>"
          title="<?= e((string) ($v['reason'] ?? '')) ?>">
      <b><?= $v['valid'] ? '✓' : '✕' ?></b>
      哈希链<?= $v['valid'] ? '完整' : '异常' ?>
      <span class="status-chip-num"><?= num((int) ($v['checked'] ?? 0)) ?> <?= e(t('条')) ?></span>
    </span>
  <?php endif; ?>
  <form method="post" style="display:flex;gap:8px;align-items:center">
  <?= csrf_field() ?>
    <input type="hidden" name="action" value="export_csv">
    <input type="hidden" name="kind" value="journal">
    <input type="hidden" name="purpose" value="<?= e(['zh_cn' => '审计复核导出', 'zh_hk' => '審計覆核匯出', 'en' => 'Audit review export'][lang()] ?? '审计复核导出') ?>">
    <input type="hidden" name="recipient" value="<?= e(['zh_cn' => '内部审计', 'zh_hk' => '內部審計', 'en' => 'Internal audit'][lang()] ?? '内部审计') ?>">
    <input type="hidden" name="back" value="audit">
    <button class="btn primary btn-file"><?= e(t('导出（带哈希）')) ?></button>
  </form>
</div>


<?php ob_start(); ?>
<?php if (!$rows): ?>
  <?= empty_state('没有匹配的分录') ?>
<?php else: ?>
<div class="table-wrap scroll-y scroll-y-audit"><table>
<thead><tr><th style="width:170px">分录号</th><th style="width:104px">日期</th>
<th style="width:86px">来源</th><th>摘要</th><th style="width:88px">状态</th>
<th style="width:160px">反向关系</th><th style="width:64px"></th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
  <?php
  $rel = [];
  if (!empty($x['reversal_of_entry_id'])) { $rel[] = t('冲销') . ' #' . (int) $x['reversal_of_entry_id']; }
  if (!empty($x['reversed_by_entry_id'])) { $rel[] = t('被') . ' #' . (int) $x['reversed_by_entry_id'] . ' ' . t('冲销'); }
  ?>
  <tr>
    <td><?= e($x['entry_no']) ?></td>
    <td><?= e($x['entry_date']) ?></td>
    <td><?= e(source_label((string) $x['source_type'])) ?></td>
    <td><?= e((string) ($x['description'] ?: '—')) ?></td>
    <td><?= status_pill((string) $x['status']) ?></td>
    <td class="hint"><?= e(implode(' ', $rel)) ?></td>
    <td><a class="btn sm" href="?p=audit&entry=<?= (int) $x['entry_id'] ?>&q=<?= urlencode($kw) ?>">下钻</a></td>
  </tr>
<?php endforeach; ?>
</tbody></table></div>
<?php endif; ?>
<?php
// 分页控件：两组各自不折行，窄屏时整组换行，按钮不会被挤断
$pager = '<div class="pager">';
$pager .= '<div class="pager-group">'
        . '<span class="hint" style="white-space:nowrap">' . e(str_replace('{n}', (string) num($totalRows), t('共 {n} 条'))) . '</span>'
        . '<span class="pager-sep"></span>';
foreach ([10, 25, 50, 100, 0] as $opt) {
    $label = $opt === 0 ? '全部' : (string) $opt;
    $pager .= '<a class="pager-btn' . ($per === $opt ? ' is-cur' : '') . '" href="?p=audit&per=' . $opt
            . ($kw !== '' ? '&q=' . urlencode($kw) : '') . '">' . $label . '</a>';
}
$pager .= '<form method="get" class="pager-custom">'
        . '<input type="hidden" name="p" value="audit">'
        . ($kw !== '' ? '<input type="hidden" name="q" value="' . e($kw) . '">' : '')
        . '<input type="number" name="per" min="5" max="500" value="' . ($per === 0 ? '' : (int) $per) . '" placeholder="自定义">'
        . '<button class="btn sm">应用</button></form>'
        . '</div>';

if ($per !== 0 && $pageCount > 1) {
    $mk = function (int $p_, string $txt) use ($kw, $per) {
        return '<a class="pager-btn" href="?p=audit&per=' . $per
             . ($kw !== '' ? '&q=' . urlencode($kw) : '') . '&page=' . $p_ . '">' . $txt . '</a>';
    };
    $pager .= '<div class="pager-group">'
            . '<span class="pager-sep"></span>'
            . ($page > 1 ? $mk($page - 1, t('‹ 上一页')) : '<span class="pager-btn is-off">‹ 上一页</span>');
    $from = max(1, $page - 2); $to = min($pageCount, $from + 4); $from = max(1, $to - 4);
    for ($i = $from; $i <= $to; $i++) {
        $pager .= $i === $page
            ? '<span class="pager-btn is-cur">' . $i . '</span>'
            : $mk($i, (string) $i);
    }
    $pager .= ($page < $pageCount ? $mk($page + 1, t('下一页 ›')) : '<span class="pager-btn is-off">下一页 ›</span>')
            . '<span class="hint" style="white-space:nowrap">' . e(str_replace(['{a}', '{b}'], [(string) $page, (string) $pageCount], t('第 {a} / {b} 页'))) . '</span>'
            . '</div>';
}
$pager .= '</div>';
echo card('分录（只读）', ob_get_clean(), $pager, false);
?>

<?php
if ($entryId) {
    $dr = api_get('/journal/' . $entryId);
    if ($dr['ok']) {
        $d = $dr['data'];
        ob_start(); ?>
        <div class="table-wrap"><table>
        <thead><tr><th>行</th><th>科目</th><th>说明</th><th class="num">借方</th>
        <th class="num">贷方</th><th class="num">原币</th><th class="num">汇率</th></tr></thead>
        <tbody>
        <?php foreach ($d['lines'] as $l): ?>
          <tr><td><?= (int) $l['line_no'] ?></td><td><?= e($l['account_code']) ?></td>
          <td><?= e((string) ($l['description'] ?: '—')) ?></td>
          <td class="num"><?= money($l['debit']) ?></td>
          <td class="num"><?= money($l['credit']) ?></td>
          <td class="num"><?= money($l['amount_original'], (string) $l['ccy']) ?></td>
          <td class="num"><?= e((string) $l['rate']) ?></td></tr>
        <?php endforeach; ?>
        </tbody></table></div>
        <div class="hint" style="padding:10px 14px">
          来源类型：<?= e((string) $d['entry']['source_type']) ?>
          · 源单 ID：<?= $d['entry']['source_id'] === null ? '—' : (int) $d['entry']['source_id'] ?>
          <?= $d['entry']['source_type'] === 'invoice' ? ' · 源文件路径与 SHA-256 见 invoice_files' : '' ?>
        </div>
        <?php echo card('分录 ' . $d['entry']['entry_no'] . ' → 明细行 → 源文件', ob_get_clean());
    }
}
?>

<?php if (!empty($exportErr)) { echo errbox($exportErr); } ?>
<?php
$ex = api_get('/export/list');
$exports = $ex['ok'] ? ($ex['data']['exports'] ?? []) : [];
// 只显示磁盘上还在的文件；已清理的不再列出（审计记录仍保留在审计日志里）
$exports = array_values(array_filter($exports, fn($x) => !empty($x['exists'])));
$hiddenExports = $ex['ok'] ? count($ex['data']['exports'] ?? []) - count($exports) : 0;
if ($exports):
ob_start(); ?>
<div class="table-wrap scroll-y scroll-y-export"><table>
<thead><tr><th>文件</th><th style="width:80px">类型</th><th style="width:110px">用途</th>
<th style="width:110px">接收方</th><th class="num" style="width:60px">行数</th>
<th style="width:110px">SHA-256</th><th style="width:90px">操作人</th>
<th style="width:150px">时间</th><th style="width:130px"></th></tr></thead>
<tbody>
<?php foreach ($exports as $x): ?>
  <tr>
    <td style="font-family:var(--mono);font-size:var(--f-2xs)"><?= e((string) $x['file']) ?></td>
    <td><?= e((string) ($x['kind'] ?? '—')) ?></td>
    <td><?= e((string) ($x['purpose'] ?? '—')) ?></td>
    <td><?= e((string) ($x['recipient'] ?? '—')) ?></td>
    <td class="num"><?= (int) ($x['rows'] ?? 0) ?></td>
    <td class="hint" style="font-family:var(--mono)"><?= e(substr((string) ($x['sha256'] ?? ''), 0, 12)) ?>…</td>
    <td><?= e((string) $x['actor']) ?></td>
    <td style="white-space:nowrap"><?= e(substr((string) $x['createdAt'], 0, 19)) ?></td>
    <td style="white-space:nowrap">
    <?php if (!empty($x['exists'])): ?>
      <a class="btn sm btn-file" href="/download.php?f=<?= rawurlencode((string) $x['file']) ?>">下载</a>
      <?php if ($role !== 'auditor'): ?>
      <form method="post" style="display:inline" onsubmit="return confirm('删除导出文件？审计记录会保留，文件不可恢复。')">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="delete_export">
        <input type="hidden" name="file" value="<?= e((string) $x['file']) ?>">
        <button class="btn sm ghost">删除</button>
      </form>
      <?php endif; ?>
    <?php else: ?>
      <span class="hint">文件已清理</span>
    <?php endif; ?>
    </td>
  </tr>
<?php endforeach; ?>
</tbody></table></div>
<div class="hint" style="padding:10px 14px">
  每次导出的文件与 SHA-256 均写入审计日志，可随时重新下载核对。
  <?php if ($hiddenExports > 0): ?>
    另有 <?= (int) $hiddenExports ?> 个已清理的文件不再列出（导出记录仍在审计日志中）。
  <?php endif; ?>
</div>
<?php echo card('最近导出（可重新下载）', ob_get_clean(), '', false);
endif;
?>

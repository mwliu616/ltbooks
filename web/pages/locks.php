<?php
/*
 * LtBooks — pages/locks.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $act = (string) ($_POST['action'] ?? '');
    if ($act === 'lock_period' || $act === 'unlock_period') {
        $r = api_post('/period-locks', [
            'period' => (string) ($_POST['period'] ?? ''),
            'status' => $act === 'lock_period' ? 'locked' : 'open',
            'note' => trim((string) ($_POST['note'] ?? '')),
            'actor' => $displayName ?? 'system',
        ]);
        $msg = $r['ok'] ? ('期间 ' . (string) ($_POST['period'] ?? '') . ($act === 'lock_period' ? ' 已锁定' : ' 已解锁')) : null;
        $errMsg = $r['ok'] ? null : (string) $r['error'];
    }
}
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

$r = api_get('/period-locks');
$rows = $r['ok'] ? ($r['data']['locks'] ?? []) : [];
ob_start();
if (!$rows) { echo empty_state('暂无锁定记录（默认全部开放）'); } else { ?>
<div class="table-wrap"><table>
<thead><tr><th>期间</th><th>状态</th><th>操作人</th><th>时间</th><th>备注</th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<tr><td><?= e((string) $x['period']) ?></td>
<td><?= status_pill($x['status'] === 'locked' ? 'posted' : 'draft') ?> <?= e((string) $x['status']) ?></td>
<td><?= e((string) ($x['locked_by'] ?? '—')) ?></td>
<td class="hint"><?= e((string) ($x['locked_at'] ?? '—')) ?></td>
<td class="hint"><?= e((string) ($x['note'] ?? '')) ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php } echo card('期间锁定', ob_get_clean(), '', false);

if ($role !== 'auditor'):
ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <div class="grid">
    <div class="field"><label class="f">期间（YYYY-MM）</label>
      <input type="text" name="period" value="<?= e(date('Y-m')) ?>" pattern="\d{4}-\d{2}" required></div>
    <div class="field"><label class="f">备注</label><input type="text" name="note"></div>
  </div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <button class="btn primary" name="action" value="lock_period">锁定期间</button>
    <button class="btn" name="action" value="unlock_period">解锁期间</button>
    <span class="hint">锁定后该期间不可再写入分录（数据库触发器强制）</span>
  </div>
</form>
<?php echo card('设置锁定', ob_get_clean());
endif; ?>

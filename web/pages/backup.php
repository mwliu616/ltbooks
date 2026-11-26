<?php
/**
 * LtBooks Ver 1.0 数据备份与恢复设置页。
 *
 * 仅管理员可创建、下载和恢复备份。所有写操作由全局 CSRF 守卫校验，
 * 后端再次校验管理员角色；恢复前强制生成当前账套的安全备份。
 *
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
declare(strict_types=1);

if (($role ?? 'accountant') !== 'admin') {
    http_response_code(403);
    echo errbox(t('只有管理员可以使用数据备份与恢复'));
    return;
}

$errMsg = null;
$backupNamePattern = '/^ltbooks-(?:[A-Za-z0-9][A-Za-z0-9_-]{0,31}-)?\d{8}T\d{6}Z-[0-9a-f]{8}\.tar\.gz$/';

/** 恢复成功后返回列表，避免刷新浏览器时重复提交危险操作。 */
$redirectBackup = static function (string $message): void {
    header('Location: ?p=backup&msg=' . rawurlencode($message));
    exit;
};

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = (string) ($_POST['action'] ?? '');
    $restoreDatabase = isset($_POST['restoreDatabase']);
    $restoreAttachments = isset($_POST['restoreAttachments']);

    if (in_array($action, ['restore_backup', 'restore_upload'], true)
        && (string) ($_POST['confirmRestore'] ?? '') !== '1') {
        $errMsg = t('请确认已了解恢复会覆盖当前数据');
    } elseif (in_array($action, ['restore_backup', 'restore_upload'], true)
        && !$restoreDatabase && !$restoreAttachments) {
        $errMsg = t('至少选择数据库或附件其中一项');
    } elseif ($action === 'create_backup') {
        $r = api_post('/backups/create', ['actor' => $displayName ?? 'system'], 600);
        if ($r['ok']) {
            $redirectBackup(str_replace('{name}', (string) ($r['data']['name'] ?? ''), t('备份已创建：{name}')));
        }
        $errMsg = (string) $r['error'];
    } elseif ($action === 'save_schedule') {
        $times = array_values(array_map('strval', (array) ($_POST['times'] ?? [])));
        $r = api_post('/backups/schedule', [
            'times' => $times,
            'actor' => $displayName ?? 'system',
        ], 30);
        if ($r['ok']) { $redirectBackup(t('自动备份时间已保存')); }
        $errMsg = (string) $r['error'];
    } elseif ($action === 'delete_backup') {
        $name = (string) ($_POST['name'] ?? '');
        if (!preg_match($backupNamePattern, $name)) {
            $errMsg = t('请选择有效的备份包');
        } else {
            $r = api_post('/backups/delete', [
                'name' => $name,
                'actor' => $displayName ?? 'system',
            ], 60);
            if ($r['ok']) {
                $redirectBackup(str_replace('{name}', $name, t('备份已删除：{name}')));
            }
            $errMsg = (string) $r['error'];
        }
    } elseif ($action === 'restore_backup') {
        $name = (string) ($_POST['name'] ?? '');
        if (!preg_match($backupNamePattern, $name)) {
            $errMsg = t('请选择有效的备份包');
        } else {
            $r = api_post('/backups/restore', [
                'name' => $name,
                'restoreDatabase' => $restoreDatabase,
                'restoreAttachments' => $restoreAttachments,
                'confirmRestore' => true,
                'actor' => $displayName ?? 'system',
            ], 600);
            if ($r['ok']) { $redirectBackup(t('恢复完成；恢复前安全备份已生成')); }
            $errMsg = (string) $r['error'];
        }
    } elseif ($action === 'restore_upload') {
        $file = $_FILES['archive'] ?? null;
        if (!is_array($file) || (int) ($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
            $errMsg = t('备份包上传失败；文件不能超过站点上传上限');
        } elseif (!preg_match('/\.tar\.gz$/i', (string) ($file['name'] ?? ''))) {
            $errMsg = t('备份包必须是 .tar.gz 文件');
        } else {
            $r = api_upload('/backups/restore-upload', 'archive', (string) $file['tmp_name'],
                (string) $file['name'], [
                    'restoreDatabase' => $restoreDatabase ? '1' : '0',
                    'restoreAttachments' => $restoreAttachments ? '1' : '0',
                    'confirmRestore' => '1',
                    'actor' => $displayName ?? 'system',
                ], 600);
            if ($r['ok']) { $redirectBackup(t('恢复完成；恢复前安全备份已生成')); }
            $errMsg = (string) $r['error'];
        }
    }
}

$listR = api_get('/backups');
$rows = $listR['ok'] ? (array) ($listR['data']['backups'] ?? []) : [];
$backupMeta = $listR['ok'] ? (array) ($listR['data']['settings'] ?? []) : [];
if (!$listR['ok'] && $errMsg === null) { $errMsg = (string) $listR['error']; }
$validRows = array_values(array_filter($rows, static fn (array $row): bool => empty($row['error'])));
$manualRows = array_values(array_filter($rows, static fn (array $row): bool => ($row['label'] ?? 'auto') !== 'auto'));
$autoRows = array_values(array_filter($rows, static fn (array $row): bool => ($row['label'] ?? 'auto') === 'auto'));
$schedule = array_values(array_filter(
    (array) ($backupMeta['schedule'] ?? []),
    static fn ($item): bool => is_string($item) && $item !== ''
));
$scheduleInputs = array_pad($schedule, 4, '');
$formatSize = static function ($bytes): string {
    $n = (float) $bytes;
    if ($n >= 1073741824) { return number_format($n / 1073741824, 2) . ' GB'; }
    if ($n >= 1048576) { return number_format($n / 1048576, 2) . ' MB'; }
    return number_format($n / 1024, 1) . ' KB';
};
$renderBackupList = static function (array $items, string $emptyText) use ($formatSize): string {
    ob_start();
    ?>
<div class="table-wrap"><table>
  <thead><tr><th style="width:180px"><?= e(t('创建时间（UTC）')) ?></th><th><?= e(t('备份包')) ?></th><th style="width:120px"><?= e(t('类型')) ?></th><th style="width:100px"><?= e(t('大小')) ?></th><th style="width:84px"><?= e(t('附件数')) ?></th><th style="width:140px"><?= e(t('操作')) ?></th></tr></thead>
  <tbody>
  <?php if (!$items): ?><tr><td colspan="6"><?= empty_state($emptyText) ?></td></tr><?php endif; ?>
  <?php foreach ($items as $row): ?>
    <tr>
      <td style="white-space:nowrap"><?= e((string) ($row['created_at'] ?? '—')) ?></td>
      <td><span class="backup-name"><?= e((string) $row['name']) ?></span>
        <?php if (!empty($row['error'])): ?><div class="hint" style="color:var(--c-danger)"><?= e((string) $row['error']) ?></div><?php endif; ?></td>
      <td><?php $bkRolling = !empty($row['rolling']); $bkType = ($row['type'] ?? '') === 'incremental'; ?><span class="tag <?= $bkType ? 'info' : ($bkRolling ? 'info' : 'ok') ?>"><?= e($bkType ? t('增量') : ($bkRolling ? t('自动滚动') : t('完整'))) ?></span><?php if ($bkRolling && (int) ($row['rolling_updates'] ?? 0) > 0): ?><div class="hint"><?= e(str_replace('{n}', (string) (int) $row['rolling_updates'], t('已合并 {n} 次'))) ?></div><?php endif; ?></td>
      <td><?= e($formatSize($row['size'] ?? 0)) ?></td>
      <td><?= e((string) ($row['attachment_count'] ?? '—')) ?></td>
      <td>
        <div class="backup-actions">
          <a class="btn sm" href="download.php?backup=<?= rawurlencode((string) $row['name']) ?>"><?= e(t('下载')) ?></a>
          <form method="post" data-confirm="<?= e(str_replace('{name}', (string) $row['name'], t('确定删除备份 {name}？此操作不可撤销。'))) ?>">
            <?= csrf_field() ?>
            <input type="hidden" name="action" value="delete_backup">
            <input type="hidden" name="name" value="<?= e((string) $row['name']) ?>">
            <button class="btn sm danger backup-del" type="submit"><?= e(t('删除')) ?></button>
          </form>
        </div>
      </td>
    </tr>
  <?php endforeach; ?>
  </tbody>
</table></div>
    <?php
    return (string) ob_get_clean();
};
?>
<style>
.backup-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; align-items:stretch; }
.backup-times { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:10px 0; }
.backup-times input { margin:0; width:100%; }
.backup-options { display:flex; gap:18px; flex-wrap:wrap; margin:12px 0; }
.backup-options label { display:flex; gap:7px; align-items:center; font-size:var(--f-sm); }
.backup-options input { width:auto; margin:0; }
.backup-confirm { display:flex; gap:8px; align-items:flex-start; padding:11px 12px; border:1px solid var(--c-warning); border-radius:var(--r-md); background:var(--c-surface-alt); }
.backup-confirm input { width:auto; margin-top:3px; }
.backup-name { font-family:var(--mono); font-size:var(--f-xs); word-break:break-all; }
.backup-actions { display:flex; gap:6px; align-items:center; }
.backup-actions form { margin:0; }
.backup-del { color:var(--c-danger); }
@media (max-width:1200px) { .backup-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:900px) { .backup-grid { grid-template-columns:1fr; } .backup-times { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>

<?php if ($errMsg !== null && $errMsg !== ''): ?><?= errbox($errMsg) ?><?php endif; ?>

<div class="banner INFO">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title">
      <?= $schedule
          ? e(str_replace('{times}', implode('、', $schedule), t('自动备份：每天 {times} 更新同一个备份文件（香港时间）')))
          : e(t('自动备份已关闭（未设置时间）')) ?>
    </div>
    <div class="banner-reason">
      <?= e(str_replace('{keep}', (string) (int) ($backupMeta['keep'] ?? 180), t('数据库与上传票据一并备份 · 每次合并进同一个文件 · 无基线时先建立完整备份 · 保留最近 {keep} 份 · 防并发锁已启用'))) ?>
    </div>
  </div>
</div>

<div class="backup-grid">
  <div>
    <?php ob_start(); ?>
    <p class="hint"><?= e(t('手动备份始终为完整备份：保存全部数据库、上传票据及其他附件，并成为后续自动备份合并的文件。每个文件均记录 SHA256 校验值。')) ?></p>
    <form method="post">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="create_backup">
      <button class="btn primary" type="submit"><?= e(t('立即创建完整备份')) ?></button>
    </form>
    <?php echo card(t('手动备份'), ob_get_clean()); ?>
  </div>
  <div>
    <?php ob_start(); ?>
    <form method="post">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="save_schedule">
      <div class="backup-times">
        <?php foreach ($scheduleInputs as $i => $val): ?>
          <div class="field">
            <label class="f"><?= e(t('时间')) ?> <?= $i + 1 ?></label>
            <input type="time" name="times[]" value="<?= e((string) $val) ?>">
          </div>
        <?php endforeach; ?>
      </div>
      <p class="hint"><?= e(t('香港时间，最多 4 个；留空表示不启用。保存后从下一个时间点开始执行，默认 09:00、17:00。')) ?></p>
      <button class="btn" type="submit"><?= e(t('保存自动备份时间')) ?></button>
    </form>
    <?php echo card(t('自动备份设置'), ob_get_clean()); ?>
  </div>
  <div>
    <?php ob_start(); ?>
    <p class="hint"><?= e(t('下载备份请妥善离线保存。本机备份不能替代异地或离线副本。')) ?></p>
    <div class="kv"><b><?= e(t('已有备份')) ?></b><span><?= count($rows) ?></span></div>
    <div class="kv"><b><?= e(t('最新备份附件数')) ?></b><span><?= e((string) ($rows[0]['attachment_count'] ?? '—')) ?></span></div>
    <?php echo card(t('备份概况'), ob_get_clean()); ?>
  </div>
</div>

<?php echo card(t('手动备份列表'), $renderBackupList($manualRows, t('尚无手动备份')), '', false); ?>
<?php echo card(t('自动备份列表'), $renderBackupList($autoRows, t('尚无自动备份')), '', false); ?>

<div class="backup-grid">
  <div>
    <?php ob_start(); ?>
    <?php if ($validRows): ?>
    <form method="post" data-confirm="<?= e(t('恢复会覆盖当前数据。系统会先创建安全备份，确定继续吗？')) ?>">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="restore_backup">
      <div class="field"><label class="f"><?= e(t('选择已有备份')) ?></label>
        <select name="name" required>
          <?php foreach ($validRows as $row): ?><option value="<?= e((string) $row['name']) ?>"><?= e((string) $row['created_at'] . ' · ' . $row['name']) ?></option><?php endforeach; ?>
        </select></div>
      <div class="backup-options">
        <label><input type="checkbox" name="restoreDatabase" value="1" checked><?= e(t('恢复数据库')) ?></label>
        <label><input type="checkbox" name="restoreAttachments" value="1" checked><?= e(t('恢复上传票据与附件')) ?></label>
      </div>
      <label class="backup-confirm"><input type="checkbox" name="confirmRestore" value="1" required>
        <span><?= e(t('我了解数据库将被覆盖；同名附件会被替换，备份后新增的附件不会删除。')) ?></span></label>
      <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0"><button class="btn danger" type="submit"><?= e(t('恢复所选备份')) ?></button></div>
    </form>
    <?php else: ?><?= empty_state(t('没有可用于恢复的备份')) ?><?php endif; ?>
    <?php echo card(t('从已有备份恢复'), ob_get_clean()); ?>
  </div>
  <div>
    <?php ob_start(); ?>
    <form method="post" enctype="multipart/form-data" data-confirm="<?= e(t('上传包会先校验全部文件，再覆盖当前数据。确定继续吗？')) ?>">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="restore_upload">
      <div class="field"><label class="f"><?= e(t('上传 Lt-AI-Books .tar.gz 备份包')) ?></label>
        <input type="file" name="archive" accept=".tar.gz,application/gzip" required>
        <span class="hint"><?= e(t('最大 512MB；恢复前自动创建安全备份，校验失败不会改动当前数据。')) ?></span></div>
      <div class="backup-options">
        <label><input type="checkbox" name="restoreDatabase" value="1" checked><?= e(t('恢复数据库')) ?></label>
        <label><input type="checkbox" name="restoreAttachments" value="1" checked><?= e(t('恢复上传票据与附件')) ?></label>
      </div>
      <label class="backup-confirm"><input type="checkbox" name="confirmRestore" value="1" required>
        <span><?= e(t('我了解数据库将被覆盖；同名附件会被替换，备份后新增的附件不会删除。')) ?></span></label>
      <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0"><button class="btn danger" type="submit"><?= e(t('上传并恢复')) ?></button></div>
    </form>
    <?php echo card(t('上传备份包恢复'), ob_get_clean()); ?>
  </div>
</div>

<?php
/*
 * LtBooks — pages/account.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$user = current_user();
if (!$user) { echo errbox('会话失效'); return; }
$msg = null; $errMsg = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $action = (string) ($_POST['action'] ?? '');
    if ($action === 'change_password') {
        $r = api_post('/auth/change-password', [
            'oldPassword' => (string) ($_POST['oldPassword'] ?? ''),
            'newPassword' => (string) ($_POST['newPassword'] ?? ''),
        ]);
        $msg = $r['ok'] ? '口令已更新，下次登录请使用新口令。' : null;
        $errMsg = $r['ok'] ? null : (string) $r['error'];
    } elseif ($action === 'set_two_tier' && ($user['role'] ?? '') === 'admin') {
        $r = api_post('/entity/two-tier', [
            'status' => (string) ($_POST['twoTierStatus'] ?? 'undetermined'),
            'basis' => trim((string) ($_POST['basis'] ?? '')),
        ]);
        $msg = $r['ok'] ? ('两级制资格已设为 ' . (string) ($_POST['twoTierStatus'] ?? '')) : null;
        $errMsg = $r['ok'] ? null : (string) $r['error'];
    } elseif ($action === 'create_user' && ($user['role'] ?? '') === 'admin') {
        $r = api_post('/admin/users', [
            'username' => trim((string) ($_POST['username'] ?? '')),
            'displayName' => trim((string) ($_POST['displayName'] ?? '')),
            'password' => (string) ($_POST['password'] ?? ''),
            'role' => (string) ($_POST['role'] ?? 'accountant'),
        ]);
        $msg = $r['ok'] ? ('用户已创建：' . (string) ($_POST['username'] ?? '')) : null;
        $errMsg = $r['ok'] ? null : (string) $r['error'];
    } elseif ($action === 'update_user' && ($user['role'] ?? '') === 'admin') {
        $r = api_request('PATCH', '/admin/users/' . (int) ($_POST['user_id'] ?? 0), [
            'displayName' => trim((string) ($_POST['displayName'] ?? '')),
            'role' => (string) ($_POST['role'] ?? ''),
            'status' => (string) ($_POST['status'] ?? 'active'),
        ]);
        $msg = $r['ok'] ? '用户已更新' : null;
        $errMsg = $r['ok'] ? null : (string) $r['error'];
    } elseif ($action === 'delete_user' && ($user['role'] ?? '') === 'admin') {
        $r = api_request('DELETE', '/admin/users/' . (int) ($_POST['user_id'] ?? 0));
        $msg = $r['ok'] ? '用户已删除' : null;
        $errMsg = $r['ok'] ? null : (string) $r['error'];
    }
}
if ($msg) {
    echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body">'
       . '<div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>';
}
if ($errMsg) { echo errbox($errMsg); }
?>
<?php ob_start(); ?>
<div class="kv"><b>用户名</b><span><?= e((string) $user['username']) ?></span></div>
<div class="kv"><b>显示名</b><span><?= e((string) $user['displayName']) ?></span></div>
<div class="kv"><b>角色</b><span><?= e(t(['admin' => '管理员', 'accountant' => '会计', 'auditor' => '审计只读',
                          'cashier' => '出纳'][(string) $user['role']] ?? (string) $user['role'])) ?></span></div>
<?php echo card('当前账号', ob_get_clean()); ?>

<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="change_password">
  <div class="grid form-grid">
    <div class="field"><label class="f">原口令</label>
      <input type="password" name="oldPassword" autocomplete="current-password" required></div>
    <div class="field"><label class="f">新口令（至少 10 位）</label>
      <input type="password" name="newPassword" autocomplete="new-password" minlength="10" required></div>
  </div>
  <div class="toolbar form-actions">
    <button class="btn primary">修改口令</button>
  </div>
</form>
<?php echo card('修改口令', ob_get_clean()); ?>

<?php ob_start(); $__m = ui_mode(); ?>
<div class="hint" style="margin-bottom:12px">
  <?= e(t('两种模式只是入口与界面密度不同：权限、复核、审计、守门人完全一样，没有任何智能体能记账，五件危险动作照旧弹窗确认。')) ?>
</div>
<div class="grid form-grid mode-grid">
  <a class="mode-card<?= $__m === 'ai' ? ' on' : '' ?>" href="?p=switch-mode&m=ai">
    <div class="mc-t">AI 模式
      <?php if ($__m === 'ai'): ?><span class="tag tag-info"><?= e(t('当前')) ?></span><?php endif; ?>
    </div>
    <div class="hint" style="margin-top:4px"><?= e(t('进来就是指令台；左侧功能条默认收起')) ?></div>
  </a>
  <a class="mode-card<?= $__m === 'manual' ? ' on' : '' ?>" href="?p=switch-mode&m=manual">
    <div class="mc-t">人工模式
      <?php if ($__m === 'manual'): ?><span class="tag tag-ok"><?= e(t('当前')) ?></span><?php endif; ?>
    </div>
    <div class="hint" style="margin-top:4px"><?= e(t('进来是「今天」；单据报表自己点')) ?></div>
  </a>
</div>
<div class="hint" style="margin-top:10px">
  <?= e(t('当前：')) ?><span class="tag tag-<?= $__m === 'ai' ? 'info' : 'ok' ?>"><?= e($__m === 'ai' ? t('AI 模式') : t('人工模式')) ?></span>
  · <?= e(t('也可以在顶栏随时切换。')) ?>
</div>
<?php echo card('使用模式', ob_get_clean()); ?>

<?php if (($user['role'] ?? '') === 'admin'):
    $ov = api_get('/overview');
    $ent = $ov['ok'] ? ($ov['data']['entity'] ?? []) : [];
    ob_start(); ?>
    <div class="kv"><b>实体</b><span><?= e((string) ($ent['code'] ?? '')) ?> · <?= e((string) ($ent['name'] ?? '')) ?></span></div>
    <div class="kv"><b>功能货币</b><span><?= e((string) ($ent['functionalCurrency'] ?? '')) ?></span></div>
    <div class="kv"><b>两级制资格</b><span><?= e((string) ($ent['twoTierStatus'] ?? '')) ?></span></div>
    <form method="post" style="margin-top:10px">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="set_two_tier">
      <div class="grid form-grid">
        <div class="field"><label class="f">两级制资格</label>
          <select name="twoTierStatus">
            <?php foreach (['undetermined' => t('未确定'), 'nominated' => t('已提名'),
                            'not_nominated' => t('未提名')] as $k => $lab): ?>
              <option value="<?= e($k) ?>"<?= ($ent['twoTierStatus'] ?? '') === $k ? ' selected' : '' ?>><?= e($lab) ?></option>
            <?php endforeach; ?>
          </select></div>
        <div class="field span-full"><label class="f">认定依据</label>
          <input type="text" name="basis" placeholder="例如：税局两级制提名确认函编号与日期"></div>
      </div>
      <div class="toolbar form-actions">
        <button class="btn primary">更新资格</button>
        <span class="hint">资格未确定时，利得税计算一律拒绝，不自行假定</span>
      </div>
    </form>
    <?php echo card('实体税务资格', ob_get_clean());

    $ur = api_get('/admin/users');
    $users = $ur['ok'] ? ($ur['data']['users'] ?? []) : [];
    $editId = (int) ($_GET['edit'] ?? 0);
    $editing = null;
    foreach ($users as $x) { if ((int) $x['user_id'] === $editId) { $editing = $x; break; } }
    ob_start(); ?>
    <div class="table-wrap"><table>
    <thead><tr><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>最近登录</th><th>操作</th></tr></thead>
    <tbody>
    <?php foreach ($users as $x): ?>
      <tr><td><?= e((string) $x['username']) ?></td>
          <td><?= e((string) $x['display_name']) ?></td>
          <td><?= e(t(['admin' => '管理员', 'accountant' => '会计', 'auditor' => '审计只读',
                          'cashier' => '出纳'][(string) $x['role']] ?? (string) $x['role'])) ?></td>
          <td><?= status_pill((string) $x['status']) ?></td>
          <td class="hint"><?= e((string) ($x['last_login_at'] ?? '—')) ?></td>
          <td><div style="display:flex;gap:6px">
            <a class="btn sm" href="?p=account&amp;edit=<?= (int) $x['user_id'] ?>">编辑</a>
            <?php if ((string) $x['username'] === 'admin'): ?>
              <button class="btn sm danger" disabled title="内置 admin 账号不能删除">删除</button>
            <?php else: ?>
              <form method="post" style="display:inline"
                    onsubmit="return confirm('确定删除该用户？删除后不可恢复。')">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="delete_user">
                <input type="hidden" name="user_id" value="<?= (int) $x['user_id'] ?>">
                <button class="btn sm danger">删除</button>
              </form>
            <?php endif; ?>
          </div></td></tr>
    <?php endforeach; ?>
    </tbody></table></div>
    <?php echo card('用户列表', ob_get_clean());

    if ($editing):
        ob_start(); ?>
        <form method="post">
          <?= csrf_field() ?>
          <input type="hidden" name="action" value="update_user">
          <input type="hidden" name="user_id" value="<?= (int) $editing['user_id'] ?>">
          <div class="grid form-grid">
            <div class="field"><label class="f">用户名</label>
              <input type="text" value="<?= e((string) $editing['username']) ?>" disabled></div>
            <div class="field"><label class="f">显示名</label>
              <input type="text" name="displayName" value="<?= e((string) $editing['display_name']) ?>"></div>
            <div class="field"><label class="f">角色</label>
              <?php if ((string) $editing['username'] === 'admin'): ?>
                <input type="hidden" name="role" value="admin">
              <?php endif; ?>
              <select name="role"<?= (string) $editing['username'] === 'admin' ? ' disabled' : '' ?>>
                <?php foreach (['accountant' => '会计', 'auditor' => '审计只读', 'admin' => '管理员'] as $__rv => $__rl): ?>
                  <option value="<?= e($__rv) ?>"<?= (string) $editing['role'] === $__rv ? ' selected' : '' ?>><?= e(t($__rl)) ?></option>
                <?php endforeach; ?>
              </select></div>
            <div class="field"><label class="f">状态</label>
              <?php if ((string) $editing['username'] === 'admin'): ?>
                <input type="hidden" name="status" value="active">
              <?php endif; ?>
              <select name="status"<?= (string) $editing['username'] === 'admin' ? ' disabled' : '' ?>>
                <option value="active"<?= (string) $editing['status'] === 'active' ? ' selected' : '' ?>>启用</option>
                <option value="disabled"<?= (string) $editing['status'] === 'disabled' ? ' selected' : '' ?>>停用</option>
              </select></div>
          </div>
          <?php if ((string) $editing['username'] === 'admin'): ?>
            <div class="hint">内置 admin 账号的角色和状态不可修改。</div>
          <?php endif; ?>
          <div class="toolbar form-actions">
            <a class="btn" href="?p=account">取消</a>
            <button class="btn primary">保存修改</button>
          </div>
        </form>
        <?php echo card('编辑用户：' . (string) $editing['username'], ob_get_clean());
    endif;

    ob_start(); ?>
    <form method="post">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="create_user">
      <div class="grid form-grid">
        <div class="field"><label class="f">用户名</label><input type="text" name="username" required></div>
        <div class="field"><label class="f">显示名</label><input type="text" name="displayName"></div>
        <div class="field"><label class="f">初始口令（至少 10 位）</label>
          <input type="password" name="password" minlength="10" required></div>
        <div class="field"><label class="f">角色</label>
          <select name="role">
            <?php foreach (['accountant' => '会计', 'auditor' => '审计只读', 'admin' => '管理员'] as $__rv => $__rl): ?>
              <option value="<?= e($__rv) ?>"><?= e(t($__rl)) ?></option>
            <?php endforeach; ?>
          </select></div>
      </div>
      <div class="toolbar form-actions">
        <button class="btn primary">新建用户</button>
      </div>
    </form>
    <?php echo card('新建用户', ob_get_clean());
endif; ?>

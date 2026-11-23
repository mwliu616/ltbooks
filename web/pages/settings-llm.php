<?php
/*
 * LtBooks — pages/settings-llm.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 系统设置 · 大模型：可以配置多个服务商（地址、模型、密钥、温度），
 * 选一个当前生效；AI 问答、客户资料识别、智能体都用当前服务商。
 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$msg = null; $errMsg = null; $test = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $act = (string) ($_POST['action'] ?? '');
    $pid = (int) ($_POST['providerId'] ?? 0);
    if ($act === 'save_llm_provider') {
        $r = api_post('/settings/llm/providers', [
            'providerId' => $pid,
            'name' => trim((string) ($_POST['name'] ?? '')),
            'base' => trim((string) ($_POST['base'] ?? '')),
            'model' => trim((string) ($_POST['model'] ?? '')),
            'apiKey' => trim((string) ($_POST['apiKey'] ?? '')),
            'temperature' => (string) ($_POST['temperature'] ?? '0.2'),
            'actor' => $actor,
        ]);
        if ($r['ok']) {
            $msg = $pid ? '服务商已更新' : '服务商已添加';
        } else {
            $errMsg = (string) $r['error'];
        }
    } elseif ($act === 'activate_llm_provider') {
        $r = api_post('/settings/llm/providers/' . $pid . '/activate', ['actor' => $actor]);
        if ($r['ok']) { $msg = '已切换当前服务商'; } else { $errMsg = (string) $r['error']; }
    } elseif ($act === 'delete_llm_provider') {
        $r = api_post('/settings/llm/providers/' . $pid . '/delete', ['actor' => $actor]);
        if ($r['ok']) { $msg = '服务商已删除'; } else { $errMsg = (string) $r['error']; }
    } elseif ($act === 'test_llm_provider') {
        $r = api_post('/settings/llm/providers/' . $pid . '/test', []);
        if ($r['ok'] && !empty($r['data']['ok'])) {
            $test = '连接正常，模型回复：' . (string) ($r['data']['reply'] ?? '');
        } else {
            $test = '连接失败：' . (string) ($r['data']['error'] ?? $r['error'] ?? '未知错误');
        }
    }
}

$r = api_get('/settings/llm/providers');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'] ?? [];
$providers = (array) ($d['providers'] ?? []);
$models = (array) ($d['models'] ?? []);
$cur = (array) ($d['current'] ?? []);

$editId = (int) ($_GET['edit'] ?? 0);
$editing = null;
foreach ($providers as $p) {
    if ((int) $p['providerId'] === $editId) { $editing = $p; break; }
}
$fName = $editing ? (string) $editing['name'] : '';
$fBase = $editing ? (string) $editing['base'] : (string) ($cur['base'] ?? 'https://api.deepseek.com');
$fModel = $editing ? (string) $editing['model'] : (string) ($cur['model'] ?? 'deepseek-chat');
$fTemp = $editing ? (string) $editing['temperature'] : '0.2';

if ($msg) {
    echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body">'
        . '<div class="banner-title">' . e($msg) . '</div></div></div>';
}
if ($errMsg) { echo errbox($errMsg); }
if ($test !== null) {
    $ok = strpos($test, '连接正常') === 0;
    echo '<div class="banner ' . ($ok ? 'PASS' : 'FAIL') . '"><span class="banner-icon">'
        . ($ok ? '✓' : '!') . '</span><div class="banner-body"><div class="banner-reason">'
        . e($test) . '</div></div></div>';
}
?>
<div class="banner REVIEW" style="margin-bottom:var(--s-4)">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title"><?= e(t('当前生效')) ?>：<?= e((string) ($cur['providerName'] ?: t('未命名服务商'))) ?>
      · <?= e((string) ($cur['model'] ?? '')) ?></div>
    <div class="banner-reason"><?= e(t('AI 问答、客户资料识别与智能体都使用当前服务商；切换后立即生效，不需要重启服务')) ?></div>
  </div>
</div>

<?php if ($role !== 'auditor'): ?>
<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e($editing ? t('编辑服务商') : t('添加服务商')) ?></h2>
    <?php if ($editing): ?>
      <div class="hint"><a href="?p=settings-llm"><?= e(t('取消编辑')) ?></a></div>
    <?php endif; ?>
  </div>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="save_llm_provider">
    <input type="hidden" name="providerId" value="<?= (int) ($editing['providerId'] ?? 0) ?>">
    <div class="grid form-grid">
      <div class="field">
        <label class="f" for="llmName"><?= e(t('服务商名称')) ?></label>
        <input type="text" id="llmName" name="name" required maxlength="80"
               value="<?= e($fName) ?>" placeholder="<?= e(t('如 DeepSeek、OpenAI、通义千问')) ?>">
      </div>
      <div class="field">
        <label class="f" for="llmModel"><?= e(t('模型')) ?></label>
        <input type="text" id="llmModel" name="model" required list="llmModels"
               value="<?= e($fModel) ?>">
        <datalist id="llmModels">
          <?php foreach ($models as $m): ?>
            <option value="<?= e((string) $m['id']) ?>"><?= e((string) $m['label']) ?></option>
          <?php endforeach; ?>
        </datalist>
      </div>
      <div class="field span-full">
        <label class="f" for="llmBase"><?= e(t('服务地址（Base URL）')) ?></label>
        <input type="text" id="llmBase" name="base" required
               value="<?= e($fBase) ?>" placeholder="https://api.deepseek.com">
        <div class="hint"><?= e(t('OpenAI 兼容接口；末尾不要带 /chat/completions')) ?></div>
      </div>
      <div class="field">
        <label class="f" for="llmTemp"><?= e(t('温度')) ?></label>
        <input type="number" id="llmTemp" name="temperature" step="0.1" min="0" max="2"
               value="<?= e($fTemp) ?>">
        <div class="hint"><?= e(t('取数类任务建议 0–0.3')) ?></div>
      </div>
      <div class="field">
        <label class="f" for="llmKey"><?= e(t('API Key')) ?></label>
        <input type="password" id="llmKey" name="apiKey" autocomplete="new-password"
               placeholder="<?= e($editing && !empty($editing['keySet']) ? t('已设置（留空则保持不变）') . ' ' . (string) $editing['keyMask'] : 'sk-...') ?>">
        <div class="hint"><?= e(t('密钥只存在服务器数据库里，界面只回显掩码；留空表示不修改')) ?></div>
      </div>
    </div>
    <div class="toolbar form-actions">
      <button class="btn primary" type="submit"><?= e($editing ? t('保存修改') : t('添加服务商')) ?></button>
    </div>
  </form>
</section>
<?php endif; ?>

<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('服务商列表')) ?></h2>
    <div class="hint"><?= e(t('可配置多个，选一个作为当前生效')) ?></div></div>
  <div class="card-body pad0"><div class="table-wrap"><table>
    <thead><tr>
      <th><?= e(t('名称')) ?></th><th><?= e(t('服务地址')) ?></th><th><?= e(t('模型')) ?></th>
      <th><?= e(t('温度')) ?></th><th><?= e(t('API Key')) ?></th><th><?= e(t('状态')) ?></th>
      <th><?= e(t('操作')) ?></th>
    </tr></thead>
    <tbody>
    <?php if (!$providers): ?>
      <tr><td colspan="7" class="hint"><?= e(t('还没有服务商。用上面的表单添加第一个，添加后自动设为当前。')) ?></td></tr>
    <?php endif; ?>
    <?php foreach ($providers as $p): ?>
      <tr>
        <td><?= e((string) $p['name']) ?></td>
        <td class="mono hint"><?= e((string) $p['base']) ?></td>
        <td class="mono"><?= e((string) $p['model']) ?></td>
        <td><?= e((string) $p['temperature']) ?></td>
        <td class="mono hint"><?= e($p['keySet'] ? (string) $p['keyMask'] : t('未设置')) ?></td>
        <td>
          <?php if (!empty($p['active'])): ?>
            <span class="badge pass"><?= e(t('当前')) ?></span>
          <?php else: ?>
            <span class="hint">—</span>
          <?php endif; ?>
        </td>
        <td>
          <?php if ($role !== 'auditor'): ?>
            <a class="btn small" href="?p=settings-llm&amp;edit=<?= (int) $p['providerId'] ?>"><?= e(t('编辑')) ?></a>
            <?php if (empty($p['active'])): ?>
              <form method="post" style="display:inline">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="activate_llm_provider">
                <input type="hidden" name="providerId" value="<?= (int) $p['providerId'] ?>">
                <button class="btn small" type="submit"><?= e(t('设为当前')) ?></button>
              </form>
            <?php endif; ?>
            <form method="post" style="display:inline">
              <?= csrf_field() ?>
              <input type="hidden" name="action" value="test_llm_provider">
              <input type="hidden" name="providerId" value="<?= (int) $p['providerId'] ?>">
              <button class="btn small" type="submit"><?= e(t('测试')) ?></button>
            </form>
            <form method="post" style="display:inline"
                  data-confirm="<?= e(t('确定删除该服务商？')) ?>">
              <?= csrf_field() ?>
              <input type="hidden" name="action" value="delete_llm_provider">
              <input type="hidden" name="providerId" value="<?= (int) $p['providerId'] ?>">
              <button class="btn small" type="submit"><?= e(t('删除')) ?></button>
            </form>
          <?php else: ?>
            <span class="hint">—</span>
          <?php endif; ?>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div></div>
</section>

<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('可用模型')) ?></h2></div>
  <div class="card-body pad0"><div class="table-wrap"><table>
    <thead><tr><th><?= e(t('模型')) ?></th><th><?= e(t('说明')) ?></th><th><?= e(t('状态')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($models as $m): ?>
      <tr>
        <td class="mono"><?= e((string) $m['id']) ?></td>
        <td class="hint"><?= e((string) ($m['note'] ?? '')) ?></td>
        <td>
          <?php if ((string) $m['id'] === (string) ($cur['model'] ?? '')): ?>
            <span class="badge pass"><?= e(t('当前')) ?></span>
          <?php else: ?>
            <span class="hint">—</span>
          <?php endif; ?>
        </td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div></div>
</section>

<?php
/*
 * LtBooks — pages/settings-llm.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 系统设置 · 大模型：服务地址、模型、密钥、温度，以及「测试连接」。
 *
 * 为什么放在这里：原来只能改 .env 再重启服务，换个模型要动服务器。
 * 现在界面上改，保存即生效（环境变量仍优先，界面上会说明）。
 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$msg = null; $errMsg = null; $test = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $act = (string) ($_POST['action'] ?? '');
    if ($act === 'save_llm') {
        $r = api_post('/settings/llm', [
            'base' => trim((string) ($_POST['base'] ?? '')),
            'model' => trim((string) ($_POST['model'] ?? '')),
            'apiKey' => trim((string) ($_POST['apiKey'] ?? '')),
            'temperature' => (string) ($_POST['temperature'] ?? '0.2'),
            'actor' => $actor,
        ]);
        if ($r['ok']) { $msg = '大模型配置已保存'; } else { $errMsg = (string) $r['error']; }
    } elseif ($act === 'test_llm') {
        $r = api_post('/settings/llm/test', []);
        if ($r['ok'] && !empty($r['data']['ok'])) {
            $test = '连接正常，模型回复：' . (string) ($r['data']['reply'] ?? '');
        } else {
            $test = '连接失败：' . (string) ($r['data']['error'] ?? $r['error'] ?? '未知错误');
        }
    }
}

$r = api_get('/settings/llm');
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'] ?? [];
$models = (array) ($d['models'] ?? []);

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
<?php if (!empty($d['fromEnv'])): ?>
  <div class="banner REVIEW" style="margin-bottom:var(--s-4)">
    <span class="banner-icon">i</span>
    <div class="banner-body">
      <div class="banner-title"><?= e(t('地址与密钥来自环境变量，模型名以界面选择为准')) ?></div>
      <div class="banner-reason"><?= e((string) ($d['envHint'] ?? '')) ?></div>
    </div>
  </div>
<?php endif; ?>

<?php if ($role !== 'auditor'): ?>
<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('大模型 API 配置')) ?></h2>
    <div class="hint"><?= e(t('保存后立即生效，不需要重启服务')) ?></div></div>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="save_llm">
    <div class="grid form-grid">
      <div class="field span-full">
        <label class="f" for="llmBase"><?= e(t('服务地址（Base URL）')) ?></label>
        <input type="text" id="llmBase" name="base" required
               value="<?= e((string) ($d['base'] ?? '')) ?>" placeholder="https://api.deepseek.com">
        <div class="hint"><?= e(t('OpenAI 兼容接口；末尾不要带 /chat/completions')) ?></div>
      </div>
      <div class="field">
        <label class="f" for="llmModel"><?= e(t('模型')) ?></label>
        <input type="text" id="llmModel" name="model" required list="llmModels"
               value="<?= e((string) ($d['model'] ?? '')) ?>">
        <datalist id="llmModels">
          <?php foreach ($models as $m): ?>
            <option value="<?= e((string) $m['id']) ?>"><?= e((string) $m['label']) ?></option>
          <?php endforeach; ?>
        </datalist>
      </div>
      <div class="field">
        <label class="f" for="llmTemp"><?= e(t('温度')) ?></label>
        <input type="number" id="llmTemp" name="temperature" step="0.1" min="0" max="2"
               value="<?= e((string) ($d['temperature'] ?? 0.2)) ?>">
        <div class="hint"><?= e(t('取数类任务建议 0–0.3')) ?></div>
      </div>
      <div class="field span-full">
        <label class="f" for="llmKey"><?= e(t('API Key')) ?></label>
        <input type="password" id="llmKey" name="apiKey" autocomplete="new-password"
               placeholder="<?= e(!empty($d['keySet']) ? t('已设置（留空则保持不变）') . ' ' . (string) ($d['keyMask'] ?? '') : 'sk-...') ?>">
        <div class="hint">
          <?= e(t('密钥只存在服务器数据库里，界面只回显掩码；留空表示不修改')) ?>
          <?php if (!empty($d['keyFromEnv'])): ?>
            · <?= e(t('当前生效的是环境变量里的密钥')) ?>
          <?php endif; ?>
        </div>
      </div>
    </div>
    <div class="toolbar form-actions">
      <button class="btn primary" type="submit"><?= e(t('保存配置')) ?></button>
    </div>
  </form>
  <form method="post" class="card-body card-actions">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="test_llm">
    <button class="btn" type="submit"><?= e(t('测试连接')) ?></button>
    <span class="hint"><?= e(t('发一条最小请求，确认地址与密钥可用')) ?></span>
  </form>
</section>
<?php endif; ?>

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
          <?php if ((string) $m['id'] === (string) ($d['model'] ?? '')): ?>
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

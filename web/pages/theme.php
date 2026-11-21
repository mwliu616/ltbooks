<?php
/*
 * LtBooks — pages/theme.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 外观：八套明暗配色，预览后一键应用并记住。 */
$role = isset($role) ? $role : 'accountant';
$presets = theme_presets();
$cur = theme_current();
$currentPreset = $presets[$cur];
$swatches = [
    '--c-bg' => t('页面背景'),
    '--c-surface' => t('卡片表面'),
    '--c-primary' => t('主要操作'),
    '--c-accent' => t('辅助强调'),
    '--c-ok' => t('成功状态'),
];
?>
<section class="theme-overview" aria-labelledby="theme-overview-title">
  <div class="theme-overview-copy">
    <div class="theme-kicker"><?= e(t('工作台外观')) ?></div>
    <h2 id="theme-overview-title"><?= e(t('让财务数据清晰，也让双眼舒适')) ?></h2>
    <p><?= e(t('从明亮的报表工作台到低光环境的深色界面，选择适合你当前任务的配色。')) ?></p>
  </div>
  <div class="theme-current">
    <span class="theme-current-label"><?= e(t('当前主题')) ?></span>
    <div class="theme-current-name">
      <span class="theme-current-marker" aria-hidden="true"></span>
      <strong><?= e(t($currentPreset['name'])) ?></strong>
    </div>
    <span class="theme-current-meta">
      <?= e($currentPreset['mode'] === 'dark' ? t('深色模式') : t('浅色模式')) ?> · <?= e(t('已在此浏览器保存')) ?>
    </span>
  </div>
</section>

<div class="theme-section-head">
  <div>
    <h2><?= e(t('选择配色方案')) ?></h2>
    <p><?= e(t('所有主题只改变界面颜色，不影响功能布局、公司数据与报表内容。')) ?></p>
  </div>
  <span class="theme-count"><?= e(sprintf(t('%d 套主题'), count($presets))) ?></span>
</div>

<div class="theme-grid">
  <?php foreach ($presets as $k => $p): ?>
    <article class="theme-card<?= $k === $cur ? ' is-cur' : '' ?><?= $p['mode'] === 'dark' ? ' is-dark' : '' ?>"
      style="<?php foreach ($p['vars'] as $vk => $vv): ?><?= e($vk) ?>:<?= e($vv) ?>;<?php endforeach; ?>"
      <?= $k === $cur ? 'aria-current="true"' : '' ?>>
      <div class="theme-preview" aria-hidden="true">
        <div class="tp-bar">
          <span class="tp-dots"><i></i><i></i><i></i></span>
          <span class="tp-address"></span>
          <span class="tp-avatar"></span>
        </div>
        <div class="tp-body">
          <div class="tp-side">
            <span class="tp-side-logo"></span>
            <i class="active"></i><i></i><i></i><i></i>
          </div>
          <div class="tp-main">
            <div class="tp-heading"><span></span><b></b></div>
            <div class="tp-kpis">
              <div class="tp-kpi"><span></span><b></b><i></i></div>
              <div class="tp-kpi"><span></span><b></b><i></i></div>
              <div class="tp-kpi"><span></span><b></b><i></i></div>
            </div>
            <div class="tp-table">
              <div class="tp-row tp-row-head"><span></span><b></b><i></i></div>
              <div class="tp-row"><span></span><b></b><i></i></div>
              <div class="tp-row"><span></span><b></b><i></i></div>
            </div>
            <div class="tp-foot"><span class="tp-status"></span><span class="tp-btn"></span></div>
          </div>
        </div>
      </div>

      <div class="theme-meta">
        <div class="theme-heading">
          <h3 class="theme-name"><?= e(t($p['name'])) ?></h3>
          <span class="theme-mode<?= $p['mode'] === 'dark' ? ' is-dark' : '' ?>">
            <?= e($p['mode'] === 'dark' ? t('深色') : t('浅色')) ?>
          </span>
        </div>
        <div class="theme-note"><?= e(t($p['note'])) ?></div>
        <div class="theme-palette" role="group" aria-label="<?= e(t('核心色彩样本')) ?>">
          <span class="theme-palette-label"><?= e(t('核心色')) ?></span>
          <div class="theme-swatches">
            <?php foreach ($swatches as $vk => $label): ?>
              <span class="theme-swatch" style="--theme-swatch:<?= e($p['vars'][$vk]) ?>"
                role="img" aria-label="<?= e($label . '：' . $p['vars'][$vk]) ?>"
                title="<?= e($label . '：' . $p['vars'][$vk]) ?>"></span>
            <?php endforeach; ?>
          </div>
        </div>
      </div>

      <div class="theme-actions">
        <?php if ($k === $cur): ?>
          <span class="theme-applied"><span class="theme-applied-dot" aria-hidden="true"></span><?= e(t('正在使用')) ?></span>
        <?php else: ?>
          <a class="btn primary sm theme-apply" href="?theme=<?= e($k) ?>&amp;p=theme"
            aria-label="<?= e(sprintf(t('应用主题：%s'), t($p['name']))) ?>"><?= e(t('应用主题')) ?></a>
        <?php endif; ?>
      </div>
    </article>
  <?php endforeach; ?>
</div>

<section class="theme-guide" aria-labelledby="theme-guide-title">
  <div class="theme-guide-head">
    <h2 id="theme-guide-title"><?= e(t('按工作场景选择')) ?></h2>
    <p><?= e(t('没有绝对最好的配色，适合当前光线与阅读时长更重要。')) ?></p>
  </div>
  <div class="theme-guide-grid">
    <section class="theme-guide-item">
      <h3><?= e(t('明亮办公环境')) ?></h3>
      <p><?= e(t('科技蓝适合日常操作与对外展示；冰川青更清爽，雾蓝低对比更柔和。')) ?></p>
    </section>
    <section class="theme-guide-item">
      <h3><?= e(t('长时间阅读与复核')) ?></h3>
      <p><?= e(t('暖纸灰、赤陶暖棕和墨绿沉静能降低纯白底带来的视觉刺激。')) ?></p>
    </section>
    <section class="theme-guide-item">
      <h3><?= e(t('低光与夜间工作')) ?></h3>
      <p><?= e(t('石墨夜色偏中性，午夜靛蓝偏冷色；两者都提高了正文与状态色亮度。')) ?></p>
    </section>
  </div>
</section>
<p class="theme-footnote"><?= e(t('主题选择会保存一年，仅影响当前浏览器；你可以随时切换，选择会立即生效。')) ?></p>

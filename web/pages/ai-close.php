<?php
/*
 * LtBooks — pages/ai-close.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * AI 模式 · 月结概览（design/ai-finance/analysis.html 的落地）
 * 只读展示六步进度与费用构成；执行动作仍走 AI 对话里的 run_period_close 工具。
 */
$period = (string) ($_GET['period'] ?? date('Y-m'));
if (!preg_match('/^\d{4}-\d{2}$/', $period)) { $period = date('Y-m'); }
$r = api_get('/period-close?period=' . urlencode($period));
$steps = $r['ok'] ? ($r['data']['steps'] ?? []) : [];
$done = 0;
foreach ($steps as $s) { if (($s['status'] ?? '') === 'done') { $done++; } }
$total = max(1, count($steps));

$pl = api_get('/reports/pnl?from=' . $period . '-01&to=' . $period . '-31');
$exp = [];
if ($pl['ok']) {
    foreach (($pl['data']['operatingExpenses']['items'] ?? []) as $it) {
        $amt = abs((float) ($it['amount'] ?? 0));
        if ($amt > 0.005) { $exp[] = ['name' => acc_name((string) ($it['accountCode'] ?? ''), (string) ($it['accountName'] ?? '')), 'amt' => $amt]; }
    }
}
usort($exp, fn($a, $b) => $b['amt'] <=> $a['amt']);
$maxExp = 0.0;
foreach ($exp as $e) { $maxExp = max($maxExp, $e['amt']); }
$sumExp = array_sum(array_column($exp, 'amt'));
?>
<div class="aic">
  <header class="aic-head">
    <div>
      <h1><?= e($period) ?> · <?= e(t('月结')) ?></h1>
      <p class="hint"><?= e(t('六步收尾：可自动的三步已跑，其余由人确认。锁账后该期间不再接受写入。')) ?></p>
    </div>
    <a class="btn" href="?p=command"><?= e(t('回到对话')) ?></a>
  </header>

  <?= help_html('ai-close') ?>

  <section class="aic-card">
    <div class="aic-card-head">
      <h2><?= e(t('六步进度')) ?></h2>
      <span class="tag tag-warn"><?= (int) $done ?> / <?= (int) $total ?> <?= e(t('完成')) ?></span>
    </div>
    <div class="aic-steps">
      <?php foreach ($steps as $s): ?>
        <div class="aic-step">
          <span class="aic-dot <?= ($s['status'] ?? '') === 'done' ? 'done' : 'todo' ?>"></span>
          <div>
            <div class="aic-step-t"><?= e((string) ($s['name'] ?? '')) ?></div>
            <div class="aic-step-d"><?= e((string) ($s['detail'] ?? '')) ?></div>
          </div>
        </div>
      <?php endforeach; ?>
    </div>
  </section>

  <section class="aic-card">
    <div class="aic-card-head">
      <h2><?= e(t('本月费用构成')) ?></h2>
      <span class="tag">HKD</span>
    </div>
    <?php if (!$exp): ?>
      <p class="hint"><?= e(t('本月没有经营费用。')) ?></p>
    <?php else: ?>
    <div class="aic-bars">
      <?php foreach (array_slice($exp, 0, 8) as $i => $e): ?>
        <div class="aic-bar-row">
          <span class="aic-bar-k"><?= e($e['name']) ?></span>
          <span class="aic-bar"><i class="<?= $i === 0 ? 'hot' : '' ?>"
            style="width:<?= $maxExp > 0 ? max(2, round($e['amt'] / $maxExp * 100)) : 0 ?>%"></i></span>
          <span class="num aic-bar-v"><?= money($e['amt'], 'HKD') ?></span>
        </div>
      <?php endforeach; ?>
    </div>
    <p class="hint" style="margin-top:14px">
      <?= e(t('经营费用合计')) ?> <?= money($sumExp, 'HKD') ?>
    </p>
    <?php endif; ?>
  </section>
</div>

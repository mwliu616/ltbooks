<?php
/*
 * LtBooks — pages/today.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 经营概览（仪表盘）——整体重构版
 *
 *  信息架构（自上而下）
 *    1. 经营概览   ← 本期净利 + 现金/应收/应付 + 需要关注的信号
 *    2. 趋势       ← 收入、成本、费用、净利，3/6/12/24/36 个月
 *    3. 待办 / 回款 ← 逾期未收、待复核；现金覆盖、DSO、逾期占比、净营运资金
 *    4. 结构       ← 成本费用构成、逾期 Top 5、Top 客户
 *    5. 流水       ← 最近记账
 *
 *  数据口径
 *    · 先问图表接口「账簿数据截至哪一天」，再据此倒推财务年度；
 *      账簿停更时不再拿今天的空年度算盈亏，首页不会出现 0.00 的假数字。
 *    · 所有金额为 HKD 本位；净值 = 收入 − 销售成本 − 费用。
 *
 *  样式
 *    全部走 .db-* 命名空间，避免与旧主题的 .metric/.card 互相覆盖。
 */
require_once __DIR__ . '/../lib/chart.php';

$role = isset($role) ? $role : 'accountant';

$ov    = api_get('/overview')['data'] ?? [];
$bb    = api_get('/reports/bank-balances')['data'] ?? [];
$ent   = api_get('/company')['data'] ?? [];
$todo  = api_get('/workbench/todo')['data'] ?? [];
$items = $todo['items'] ?? [];
$tsum  = $todo['summary'] ?? [];

/* ---------- 期间：URL → Cookie → 12 个月 ---------- */
$ALLOWED = [3, 6, 12, 24, 36];
$span = isset($_GET['months']) ? (int) $_GET['months'] : (int) ($_COOKIE['ledu_dash_months'] ?? 12);
if (!in_array($span, $ALLOWED, true)) { $span = 12; }
if (isset($_GET['months']) && !headers_sent()) {
    setcookie('ledu_dash_months', (string) $span, ['expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax']);
}
$ch    = api_get('/reports/dashboard-charts?months=' . $span)['data'] ?? [];
$trend = $ch['trend'] ?? [];

$dataThrough = trim((string) ($ch['dataThrough'] ?? ''));
$today   = new DateTimeImmutable('today');
$asOf    = $dataThrough !== '' ? new DateTimeImmutable($dataThrough) : $today;
$asOfYmd = $asOf->format('Y-m-d');

/* ---------- 财务年度：跟着「有数据的最后一天」走 ---------- */
$fye = (string) ($ent['fiscalYearEnd'] ?? '04-30');
[$fyeM, $fyeD] = array_map('intval', explode('-', $fye) + [0, 0]);
$fyEnd = new DateTimeImmutable(sprintf('%d-%02d-%02d', (int) $asOf->format('Y'), $fyeM ?: 12, $fyeD ?: 31));
if ($asOf > $fyEnd) { $fyEnd = $fyEnd->modify('+1 year'); }
$fyStart  = $fyEnd->modify('-1 year')->modify('+1 day');
$periodTo = $today < $fyEnd ? $today : $fyEnd;
$fyLabel  = sprintf('FY %d/%02d', (int) $fyStart->format('Y'),
                    ((int) $fyStart->format('Y') % 100) + 1);

$pl     = api_get('/reports/pnl?from=' . $fyStart->format('Y-m-d') . '&to=' . $periodTo->format('Y-m-d'))['data'] ?? [];
$rev    = (float) ($pl['revenue']['total'] ?? 0);
$np     = (float) ($pl['netProfit'] ?? 0);
$margin = $rev > 0 ? $np / $rev * 100 : null;

$curEnd = new DateTimeImmutable(sprintf('%d-%02d-%02d', (int) $today->format('Y'), $fyeM ?: 12, $fyeD ?: 31));
if ($today > $curEnd) { $curEnd = $curEnd->modify('+1 year'); }
$curStart   = $curEnd->modify('-1 year')->modify('+1 day');
$booksStale = $asOf < $curStart;
$lagMonths  = max(0, ((int) $today->format('Y') - (int) $asOf->format('Y')) * 12
                + ((int) $today->format('n') - (int) $asOf->format('n')));

/* ---------- 现金与账户 ---------- */
$accounts = [];
foreach (($bb['groups'] ?? []) as $gp) {
    foreach (($gp['accounts'] ?? []) as $a) { $accounts[] = $a; }
}
$cash     = (float) ($bb['hkdTotal'] ?? 0);
$cashName = (string) ($accounts[0]['name'] ?? '银行');

/* ---------- 应收应付 ---------- */
$ar = (float) ($ov['arFunctional'] ?? 0);
$ap = (float) ($ov['apFunctional'] ?? 0);
$glAr = (float) ($ov['arGlBalance'] ?? 0);
$glAp = (float) ($ov['apGlBalance'] ?? 0);

$arOver       = $ch['arOverdue'] ?? [];
$arOverN      = (int) ($arOver['count'] ?? 0);
$arOverAmt    = (float) ($arOver['amount'] ?? 0);
$arMaxDay     = (int) ($arOver['maxDays'] ?? 0);
$openAp       = $ch['openAp'] ?? [];
$apOpenN      = (int) ($openAp['count'] ?? 0);
$apNext       = (string) ($openAp['nextDue'] ?? '');
$apOverdue    = $apNext !== '' && $apNext < $today->format('Y-m-d');

/* ---------- 趋势合计与比率 ---------- */
$sumRev = $sumCogs = $sumExp = 0.0;
foreach ($trend as $t) {
    $sumRev  += (float) $t['revenue'];
    $sumCogs += (float) $t['cogs'];
    $sumExp  += (float) $t['expense'];
}
$sumNet  = $sumRev - $sumCogs - $sumExp;
$nMonths = max(1, count($trend));
$monthlyExpense = $sumExp / $nMonths;
$runway   = $monthlyExpense > 0 ? $cash / $monthlyExpense : null;
$dso      = $sumRev > 0 ? $ar / $sumRev * 365 : null;
$overRatio = $ar > 0 ? min(100, $arOverAmt / $ar * 100) : 0.0;
$nwc      = $ar - $ap;

/* ---------- 需要关注的信号 ---------- */
$signals = [];
if ($lagMonths >= 2) {
    $signals[] = ['danger', '账簿滞后', '账簿截至 ' . $asOfYmd . '，比今天滞后 ' . $lagMonths . ' 个月。'];
} elseif ($lagMonths === 1) {
    $signals[] = ['warn', '账簿待更新', '账簿截至 ' . $asOfYmd . '，上月凭证还未入账。'];
}
if ($arOverN > 0) {
    $signals[] = ['warn', '应收逾期', $arOverN . ' 笔、' . money($arOverAmt)
        . ' HKD 已逾期，最长 ' . $arMaxDay . ' 天。'];
}
if ($apOverdue) {
    $signals[] = ['warn', '应付已到期', $apOpenN . ' 张未结账单，最早 ' . $apNext . ' 已到期。'];
}
if (!$signals) {
    $signals[] = ['ok', '账务正常', '没有逾期应收或逾期应付。'];
}
$signals = array_slice($signals, 0, 3);
$topOverdue = (string) ($ch['overdueAr'][0]['party'] ?? '');
if ($overRatio >= 50 && $topOverdue !== '') {
    $insight = '应收 ' . number_format($overRatio, 0) . '% 已逾期，现金只够 '
        . ($runway !== null ? number_format($runway, 1) : '—') . ' 个月费用；优先催收 '
        . $topOverdue . '。';
} elseif ($runway !== null && $runway < 3) {
    $insight = '现金覆盖 ' . number_format($runway, 1)
        . ' 个月费用，低于 3 个月安全线，建议先催收逾期应收。';
} else {
    $insight = '现金覆盖与回款节奏处于可控区间。';
}

/* ---------- 待办分组 ---------- */
$overdueItems = array_values(array_filter($items, fn($x) => ($x['kind'] ?? '') === 'overdue_ar'));
$reviewItems  = array_values(array_filter($items, fn($x) => ($x['kind'] ?? '') === 'pending_review'));
$otherItems   = array_values(array_filter($items, fn($x) => !in_array($x['kind'] ?? '', ['overdue_ar', 'pending_review'], true)));
$groups = [];
if ($overdueItems) { $groups[] = ['red',   '逾期未收', count($overdueItems), array_slice($overdueItems, 0, 4), '?p=report-aging']; }
if ($reviewItems)  { $groups[] = ['amber', '待复核',   count($reviewItems),  array_slice($reviewItems, 0, 3),  '?p=pending']; }
if (!$groups && $otherItems) { $groups[] = ['', '待处理', count($otherItems), array_slice($otherItems, 0, 6), '?p=pending']; }

$daysOver = static function (?string $due) use ($today): int {
    if ($due === null || $due === '') { return 0; }
    try { $d = new DateTimeImmutable($due); } catch (Throwable $e) { return 0; }
    $n = (int) $d->diff($today)->format('%r%a');
    return $n > 0 ? $n : 0;
};

$recent = api_get('/journal?limit=6')['data']['entries'] ?? [];

$quick = [
    ['＋ 记收入', '?p=fast-new&kind=invoice', 'is-primary'],
    ['记支出', '?p=fast-new&kind=bill', ''],
    ['导入月结单', '?p=bank-import', ''],
    ['对账', '?p=reconcile', ''],
];
?>
<div class="db">
  <div class="db-head">
    <div>
      <div class="db-crumb">DASHBOARD</div>
      <h1>经营概览</h1>
      <p>
        <?= e($today->format(lang() === 'en' ? 'j M Y' : 'Y 年 n 月 j 日')) ?>
        · 账簿截至 <b><?= e($asOfYmd) ?></b>
        · <?= e($fyLabel) ?> <?= e($fyStart->format('Y-m-d')) ?> <?= e(t('至')) ?> <?= e($periodTo->format('Y-m-d')) ?>
        <?php if ($booksStale): ?><span class="db-badge">下一财年尚无凭证</span><?php endif; ?>
      </p>
    </div>
    <div class="db-actions">
      <?php foreach ($quick as [$label, $href, $cls]): ?>
        <a class="db-btn <?= e($cls) ?>" href="<?= e($href) ?>"><?= e($label) ?></a>
      <?php endforeach; ?>
    </div>
  </div>

  <?= help_html('today') ?>

  <!-- 1. 经营概览 -->
  <section class="db-card db-hero">
    <div class="db-hero-main">
      <div class="db-eyebrow"><?= e($fyLabel) ?> · <?= e($fyStart->format('Y-m-d')) ?> 至 <?= e($periodTo->format('Y-m-d')) ?> · 本期净利</div>
      <div class="db-hero-value <?= $np < 0 ? 'is-neg' : '' ?>">
        <?= money($np) ?><span>HKD</span>
      </div>
      <div class="db-hero-sub">
        收入 <?= money($rev) ?> HKD
        <?= $margin !== null ? ' · 净利率 ' . number_format($margin, 1) . '%' : '' ?>
        <?= $booksStale ? ' · 账簿截止年度' : ' · 年初至今' ?>
      </div>

      <div class="db-hero-kpis">
        <div class="db-mini">
          <span>现金及银行</span>
          <b><?= money($cash) ?></b>
          <i><?= e($cashName) ?></i>
        </div>
        <div class="db-mini">
          <span>应收未收</span>
          <b><?= money($ar) ?></b>
          <i><?= $arOverN ?> 笔逾期<?= $arMaxDay > 0 ? ' · 最长 ' . $arMaxDay . ' 天' : '' ?></i>
        </div>
        <div class="db-mini">
          <span>应付未付</span>
          <b><?= money($ap) ?></b>
          <i><?= $apOpenN ?> 张未结<?= $apNext !== '' ? ' · 最早 ' . e($apNext) : '' ?></i>
        </div>
      </div>
    </div>

    <aside class="db-hero-side">
      <div class="db-side-title">需要关注</div>
      <?php foreach ($signals as [$tone, $title, $desc]): ?>
        <div class="db-signal is-<?= e($tone) ?>">
          <span class="db-sig-dot"></span>
          <div>
            <b><?= e($title) ?></b>
            <p><?= e($desc) ?></p>
          </div>
        </div>
      <?php endforeach; ?>
      <a class="db-side-link" href="?p=pending">去处理这 <?= count($items) ?> 条 →</a>
    </aside>
  </section>

  <div class="db-grid" style="margin-top:16px">
    <!-- 2. 趋势 -->
    <section class="db-card db-span-12">
      <div class="db-card-head">
        <div>
          <h2>收入、成本与净利</h2>
          <p>近 <?= $span ?> 个月<?= !empty($ch['window']['from']) ? ' · ' . e($ch['window']['from']) . ' 至 ' . e($ch['window']['to']) : '' ?></p>
        </div>
        <div class="db-seg">
          <?php foreach ([3 => '3M', 6 => '6M', 12 => '12M', 24 => '24M', 36 => '36M'] as $mv => $mlab): ?>
            <a class="<?= $mv === $span ? 'is-on' : '' ?>" href="?p=today&months=<?= $mv ?>"><?= e($mlab) ?></a>
          <?php endforeach; ?>
        </div>
      </div>
      <div class="db-card-body">
        <?php if ($trend): ?>
          <div class="db-summary">
            <div><span>收入</span><b><?= money($sumRev) ?></b></div>
            <div><span>销售成本</span><b><?= money($sumCogs) ?></b></div>
            <div><span>费用</span><b><?= money($sumExp) ?></b></div>
            <div><span>净利</span><b class="<?= $sumNet < 0 ? 'is-neg' : 'is-pos' ?>"><?= money($sumNet) ?></b></div>
          </div>
          <div class="db-chart">
            <?= bar_chart(
                array_map(fn($t) => _period_label((string) $t['period']), $trend),
                [
                    ['label' => t('收入'), 'color' => 'var(--c-info)', 'values' => array_map(fn($t) => (float) $t['revenue'], $trend)],
                    ['label' => t('销售成本'), 'color' => 'var(--c-warn)', 'values' => array_map(fn($t) => (float) $t['cogs'], $trend)],
                    ['label' => t('经营费用'), 'color' => 'var(--c-text-3)', 'values' => array_map(fn($t) => (float) $t['expense'], $trend)],
                    ['label' => t('净利'), 'color' => 'var(--c-text)', 'type' => 'line',
                     'values' => array_map(fn($t) => (float) $t['profit'], $trend)],
                ], 250) ?>
          </div>
          <p class="db-note">数据截至 <?= e($asOfYmd) ?> · 按凭证日期归期 · 净值 = 收入 − 销售成本 − 费用</p>
        <?php else: ?>
          <div class="db-empty"><?= e(t('暂无已过账数据')) ?></div>
        <?php endif; ?>
      </div>
    </section>

    <!-- 3. 待办 -->
    <section class="db-card db-span-7">
      <div class="db-card-head">
        <div>
          <h2>等着你处理</h2>
          <p>共 <?= count($items) ?> 条 · 按紧急程度排序</p>
        </div>
        <a href="?p=pending">查看全部</a>
      </div>
      <?php if (!$groups): ?>
        <div class="db-empty">今天没有待办。</div>
      <?php else: ?>
        <div class="db-tasks">
          <?php foreach ($groups as [$tone, $gname, $gn, $rows, $more]): ?>
            <div class="db-group-head">
              <span class="db-dot <?= e($tone) ?>"></span>
              <b><?= e($gname) ?></b>
              <span><?= $gn ?></span>
              <a href="<?= e($more) ?>">全部</a>
            </div>
            <?php foreach ($rows as $it):
              $kind  = (string) ($it['kind'] ?? '');
              $party = trim((string) ($it['party'] ?? ''));
              $no    = trim((string) ($it['docNo'] ?? ''));
              if ($no !== '' && str_contains($no, '#')) {
                  $no = '#' . substr($no, strpos($no, '#') + 1);
              }
              $date = (string) ($it['dueDate'] ?? $it['date'] ?? '');
              $days = $daysOver($date);
              $amt  = $it['amount'] ?? null;
              if ($kind === 'pending_review') {
                  $title = '发票待复核';
                  $sub   = trim(($no !== '' ? '单据 ' . $no . ' · ' : '') . $party, ' ·');
              } else {
                  $title = $party !== '' ? $party : ($no !== '' ? $no : '待处理单据');
                  $sub   = trim(($no !== '' ? $no : '') . ($date !== '' ? ' · 到期 ' . $date : ''), ' ·');
              }
            ?>
              <a class="db-task" href="<?= e((string) ($it['href'] ?? '?p=pending')) ?>">
                <div class="db-task-main">
                  <b><?= e($title) ?></b>
                  <span><?= e($sub) ?></span>
                </div>
                <div class="db-task-side">
                  <?php if ($amt !== null): ?>
                    <b><?= money($amt) ?></b>
                    <span class="<?= $days > 0 ? 'is-red' : '' ?>"><?= $days > 0 ? ('逾期 ' . $days . ' 天') : ($kind === 'pending_review' ? '待复核' : '') ?></span>
                  <?php elseif ($kind === 'pending_review'): ?>
                    <span class="db-pill is-amber">待复核</span>
                  <?php else: ?>
                    <span>—</span>
                  <?php endif; ?>
                </div>
              </a>
            <?php endforeach; ?>
          <?php endforeach; ?>
        </div>
      <?php endif; ?>
    </section>

    <!-- 3b. 资金与回款 -->
    <section class="db-card db-span-5 db-metrics-card">
      <div class="db-card-head">
        <div>
          <h2>资金与回款</h2>
          <p>按近 <?= $span ?> 个月与当前余额计算</p>
        </div>
      </div>
      <div class="db-card-body">
        <div class="db-metric <?= $runway !== null && $runway < 1.5 ? 'is-red' : ($runway !== null && $runway < 3 ? 'is-amber' : 'is-green') ?>">
          <div class="db-metric-top">
            <span>现金可覆盖</span>
            <b><?= $runway !== null ? number_format($runway, 1) : '—' ?><small>个月费用</small></b>
          </div>
          <div class="db-track"><i style="width:<?= $runway !== null ? min(100, $runway / 6 * 100) : 0 ?>%"></i></div>
          <div class="db-metric-hint">现金 <?= money($cash) ?> ÷ 月均费用 <?= money($monthlyExpense) ?></div>
        </div>

        <div class="db-metric <?= $dso !== null && $dso > 90 ? 'is-red' : ($dso !== null && $dso > 60 ? 'is-amber' : 'is-green') ?>">
          <div class="db-metric-top">
            <span>应收周转天数</span>
            <b><?= $dso !== null ? number_format($dso, 0) : '—' ?><small>天</small></b>
          </div>
          <div class="db-track"><i style="width:<?= $dso !== null ? min(100, $dso / 120 * 100) : 0 ?>%"></i></div>
          <div class="db-metric-hint">应收 <?= money($ar) ?> ÷ 近 <?= $span ?> 个月收入 × 365</div>
        </div>

        <div class="db-metric <?= $overRatio > 50 ? 'is-red' : ($overRatio > 0 ? 'is-amber' : 'is-green') ?>">
          <div class="db-metric-top">
            <span>逾期应收占比</span>
            <b><?= number_format($overRatio, 0) ?><small>%</small></b>
          </div>
          <div class="db-track"><i style="width:<?= min(100, $overRatio) ?>%"></i></div>
          <div class="db-metric-hint"><?= money($arOverAmt) ?> HKD 已逾期 · <?= $arOverN ?> 笔</div>
        </div>

        <div class="db-metric">
          <div class="db-metric-top">
            <span>净营运资金</span>
            <b class="<?= $nwc < 0 ? 'is-neg' : '' ?>"><?= money($nwc) ?><small>HKD</small></b>
          </div>
          <div class="db-metric-hint">应收 <?= money($ar) ?> − 应付 <?= money($ap) ?></div>
        </div>

        <div class="db-insight"><?= e($insight) ?></div>
      </div>
    </section>

    <!-- 4. 结构 -->
    <section class="db-card db-span-4">
      <div class="db-card-head">
        <div>
          <h2>成本与费用构成</h2>
          <p>近 <?= $span ?> 个月 · 不含期初结转</p>
        </div>
      </div>
      <div class="db-card-body">
        <?php
        $palette = ['var(--c-info)', 'var(--c-accent-bright)', 'var(--c-warn)', 'var(--c-text-3)', '#38BDF8',
                    '#A78BFA', '#FB7185', '#4ADE80', '#FBBF24', '#94A3B8'];
        $exp = [];
        foreach (($ch['expenseBreakdown'] ?? []) as $i => $x) {
            $exp[] = ['label' => fs_line_label((string) $x['key']), 'value' => (float) $x['amount'],
                      'color' => $palette[$i % count($palette)]];
        }
        $expTotal = array_sum(array_map(fn($x) => $x['value'], $exp));
        echo $exp ? donut_chart($exp, '合计', number_format($expTotal, 0)) : '<div class="db-empty">暂无成本费用数据</div>';
        ?>
      </div>
    </section>

    <section class="db-card db-span-4">
      <div class="db-card-head">
        <div>
          <h2>逾期 Top 5 客户</h2>
          <p>按未收金额 · 最长 <?= $arMaxDay ?> 天</p>
        </div>
      </div>
      <div class="db-card-body">
        <?php
        $overRows = [];
        foreach (($ch['overdueAr'] ?? []) as $r) {
            $overRows[] = ['label' => (string) $r['party'], 'value' => (float) $r['amount'], 'color' => 'var(--c-danger)'];
        }
        echo $overRows ? hbar_chart($overRows) : '<div class="db-empty">没有逾期应收</div>';
        ?>
      </div>
    </section>

    <section class="db-card db-span-4">
      <div class="db-card-head">
        <div>
          <h2>逾期客户排行</h2>
          <p>按开票金额</p>
        </div>
      </div>
      <div class="db-card-body">
        <?php
        $topRows = [];
        foreach (($ch['topCustomers'] ?? []) as $i => $r) {
            $topRows[] = ['label' => (string) $r['party'], 'value' => (float) $r['amount'],
                          'color' => $palette[$i % count($palette)]];
        }
        echo $topRows ? hbar_chart($topRows) : '<div class="db-empty">暂无客户数据</div>';
        ?>
      </div>
    </section>

    <!-- 5. 流水 -->
    <section class="db-card db-span-12">
      <div class="db-card-head">
        <div>
          <h2>最近记账</h2>
          <p>所有凭证，包括单据生成与手工录入</p>
        </div>
        <a href="?p=journal">全部凭证</a>
      </div>
      <?php if (!$recent): ?>
        <div class="db-empty">还没有记账。</div>
      <?php else: ?>
        <div class="db-recent">
          <?php foreach ($recent as $en):
            $eid   = (int) ($en['entryId'] ?? $en['entry_id'] ?? 0);
            $edate = (string) ($en['entryDate'] ?? $en['entry_date'] ?? '');
            $eno   = (string) ($en['entryNo'] ?? $en['entry_no'] ?? '');
            $desc  = (string) ($en['description'] ?? '');
          ?>
            <a class="db-task" href="?p=journal<?= $eid > 0 ? '&entry=' . $eid : '' ?>">
              <div class="db-task-main">
                <b><?= e($desc !== '' ? $desc : $eno) ?></b>
                <span><?= e($edate) ?><?= $eno !== '' ? ' · ' . e($eno) : '' ?></span>
              </div>
              <div class="db-task-side">
                <b><?= money($en['totalDebit'] ?? $en['total_debit'] ?? 0) ?></b>
                <span>HKD</span>
              </div>
            </a>
          <?php endforeach; ?>
        </div>
      <?php endif; ?>
    </section>
  </div>
</div>

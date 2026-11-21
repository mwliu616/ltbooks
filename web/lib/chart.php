<?php
/*
 * LtBooks — lib/chart.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 仪表盘图表（纯内联 SVG，无第三方依赖，离线可用）。
 *
 * 设计原则：
 *  - 颜色取语义令牌，收入蓝 / 成本琥珀 / 费用红，与界面一致；
 *  - 每根柱、每个扇区都带 <title>，悬停即显示精确金额；
 *  - 数值标签直接标在图上，不依赖图例猜读。
 */

function _fmt_short(float $v): string
{
    $a = abs($v);
    if ($a >= 1e6) return number_format($v / 1e6, 1) . 'M';
    if ($a >= 1e3) return number_format($v / 1e3, 0) . 'k';
    return number_format($v, 0);
}

function _fmt_full(float $v): string
{
    return number_format($v, 2);
}

/** 「2026-10」→ 本地化短标签。 */
function _period_label(string $p): string
{
    $m = (int) substr($p, 5, 2);
    if (function_exists('lang') && lang() === 'en') {
        return ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][$m - 1] ?? $p;
    }
    return $m . '月';
}

/**
 * 组合图：柱（收入/成本/费用）+ 折线（净利）。
 */
function bar_chart(array $labels, array $series, int $h = 210): string
{
    $n = count($labels);
    if ($n === 0) return '<div class="chart-empty">' . e(t('暂无已过账数据')) . '</div>';

    $w = 1180; $padL = 58; $padR = 18; $padB = 28; $padT = 18;
    // 值域要覆盖所有系列（含折线），并且保留负值：
    // 亏损月份必须画到零线以下，否则折线会被截断、看起来像没数据。
    $vmax = 0.0; $vmin = 0.0;
    foreach ($series as $s) {
        foreach ($s['values'] as $v) {
            $f = (float) $v;
            $vmax = max($vmax, $f);
            $vmin = min($vmin, $f);
        }
    }
    if ($vmax - $vmin <= 0) { $vmax = 1.0; $vmin = 0.0; }
    // 有负数时把轴做成对称的：刻度才会落在 0 / ±10k / ±20k 这种整值上，
    // 否则零点会落在 16 这种奇怪的位置
    if ($vmin < 0) {
        $m = max($vmax, -$vmin);
        $vmax = $m; $vmin = -$m;
    }
    $span = $vmax - $vmin;
    $max = $vmax;                       // 兼容旧变量名

    $plotW = $w - $padL - $padR;
    $plotH = $h - $padB - $padT;
    $groupW = $plotW / max(1, $n);
    $bars = array_values(array_filter($series, fn($s) => ($s['type'] ?? 'bar') === 'bar'));
    $barW = max(7.0, min(46.0, ($groupW * 0.58) / max(1, count($bars))));

    // 月份太多时柱子会细成一条线，改用面积图读趋势
    $dense = $n > 14;

    $svg = '<svg viewBox="0 0 ' . $w . ' ' . $h . '" preserveAspectRatio="xMidYMid meet" '
         . 'style="width:100%;height:auto;display:block" role="img">';
    $svg .= '<defs>';
    foreach ($series as $i => $s) {
        $svg .= '<linearGradient id="g' . $i . '" x1="0" y1="0" x2="0" y2="1">'
              . '<stop offset="0%" stop-color="' . e($s['color']) . '" stop-opacity="1"/>'
              . '<stop offset="100%" stop-color="' . e($s['color']) . '" stop-opacity=".72"/>'
              . '</linearGradient>';
    }
    $svg .= '</defs>';

    // 网格 + 刻度
    for ($i = 0; $i <= 4; $i++) {
        $y = $padT + $plotH * $i / 4;
        $val = $vmax - $span * $i / 4;
        $svg .= sprintf('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="var(--c-border)" stroke-width="1"%s/>',
                        $padL, $y, $w - $padR, $y, $i === 4 ? ' stroke-opacity="1"' : '');
        $svg .= sprintf('<text x="%d" y="%.1f" font-size="12" fill="var(--c-text-3)" text-anchor="end">%s</text>',
                        $padL - 8, $y + 4, _fmt_short($val));
    }

    if ($dense) {
        // ---- 面积 + 多线 ----
        $xOf = fn($i) => $padL + ($n === 1 ? $plotW / 2 : $plotW * $i / ($n - 1));
        $yOf = fn($v) => $padT + $plotH - $plotH * ((float) $v - $vmin) / $span;
        $yZero = $yOf(0);

        foreach ($series as $k => $ser) {
            $vals = array_map(fn($v) => (float) $v, $ser['values']);
            $pts = [];
            foreach ($vals as $i => $v) { $pts[] = [$xOf($i), $yOf($v)]; }
            $line = '';
            foreach ($pts as $i => $pt) { $line .= ($i === 0 ? 'M' : 'L') . sprintf('%.1f,%.1f ', $pt[0], $pt[1]); }
            $isArea = ($ser['type'] ?? 'bar') === 'bar';
            if ($isArea) {
                $area = $line . sprintf('L%.1f,%.1f L%.1f,%.1f Z',
                        $pts[count($pts) - 1][0], $yZero, $pts[0][0], $yZero);
                $svg .= sprintf('<path d="%s" fill="url(#g%d)" opacity=".85"/>', trim($area), $k);
            }
            $svg .= sprintf('<path d="%s" fill="none" stroke="%s" stroke-width="%s" '
                          . 'stroke-linejoin="round" stroke-linecap="round"><title>%s</title></path>',
                            trim($line), e($ser['color']),
                            $isArea ? '1.2' : '2.2', e((string) $ser['label']));
            // 末点标记，便于识别最新月份
            $last = $pts[count($pts) - 1];
            $svg .= sprintf('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s" stroke="var(--c-surface)" stroke-width="1.5">'
                          . '<title>%s：%s</title></circle>',
                            $last[0], $last[1], e($ser['color']),
                            e((string) $ser['label']), _fmt_full($vals[count($vals) - 1]));
        }

        // 仅保留四个时间刻度，避免拥挤
        $step = max(1, (int) ceil($n / 4));
        foreach ($labels as $i => $lab) {
            if ($i % $step !== 0 && $i !== $n - 1) continue;
            $svg .= sprintf('<text x="%.1f" y="%d" font-size="12" fill="var(--c-text-2)" text-anchor="middle">%s</text>',
                            $xOf($i), $h - 8, e((string) $lab));
        }
    } else {
        // ---- 柱 + 折线 ----
        foreach ($labels as $i => $lab) {
            $gx = $padL + $groupW * $i;
            $si = 0;
            $total = count($bars);
            foreach ($series as $k => $s2) {
                if (($s2['type'] ?? 'bar') !== 'bar') continue;
                $v = (float) ($s2['values'][$i] ?? 0);
                $yZero = $padT + $plotH - $plotH * (0 - $vmin) / $span;
                $yVal = $padT + $plotH - $plotH * ($v - $vmin) / $span;
                $bh = abs($yVal - $yZero);
                $x = $gx + ($groupW - $barW * $total) / 2 + $barW * $si;
                $y = min($yVal, $yZero);
                if ($bh > 0.8) {
                    $svg .= sprintf(
                        '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="url(#g%d)" rx="3">'
                      . '<title>%s：%s %s</title></rect>',
                        $x, $y, $barW - 2, $bh, $k, e((string) $s2['label']),
                        e((string) $lab), _fmt_full($v));
                }
                $si++;
            }
            $svg .= sprintf('<text x="%.1f" y="%d" font-size="12" fill="var(--c-text-2)" text-anchor="middle">%s</text>',
                            $gx + $groupW / 2, $h - 8, e((string) $lab));
        }

        foreach ($series as $k => $s2) {
            if (($s2['type'] ?? 'bar') !== 'line') continue;
            $vals = array_map(fn($v) => (float) $v, $s2['values']);
            $pts = [];
            foreach ($vals as $i => $v) {
                $pts[] = [$padL + $groupW * $i + $groupW / 2,
                          $padT + $plotH - $plotH * ($v - $vmin) / $span, $v];
            }
            $d = '';
            foreach ($pts as $i => $pt) { $d .= ($i === 0 ? 'M' : 'L') . sprintf('%.1f,%.1f ', $pt[0], $pt[1]); }
            $svg .= sprintf('<path d="%s" fill="none" stroke="%s" stroke-width="2.2" '
                          . 'stroke-linejoin="round" stroke-linecap="round"/>', trim($d), e($s2['color']));
            foreach ($pts as $pt) {
                $svg .= sprintf('<circle cx="%.1f" cy="%.1f" r="4" fill="var(--c-surface)" stroke="%s" stroke-width="2.2">'
                              . '<title>%s：%s</title></circle>',
                                $pt[0], $pt[1], e($s2['color']), e((string) $s2['label']), _fmt_full($pt[2]));
            }
        }
    }
    $svg .= '</svg>';

    $legend = '<div class="chart-legend">';
    foreach ($series as $s) {
        $shape = ($s['type'] ?? 'bar') === 'line' ? 'line' : 'bar';
        $legend .= '<span class="lg"><i class="lg-' . $shape . '" style="background:' . e($s['color']) . '"></i>'
                 . e((string) $s['label']) . '</span>';
    }
    $legend .= '</div>';
    return $svg . $legend;
}

/** 环形图：费用构成 / 现金分布。 */
function donut_chart(array $items, string $centerLabel = '', string $centerValue = '', int $size = 190): string
{
    $items = array_values(array_filter($items, fn($i) => (float) $i['value'] > 0));
    if (!$items) return '<div class="chart-empty">' . e(t('暂无数据')) . '</div>';
    $total = array_sum(array_map(fn($i) => (float) $i['value'], $items));
    $cx = $size / 2; $cy = $size / 2; $r = $size / 2 - 6; $ir = $r * 0.62;

    $svg = '<svg viewBox="0 0 ' . $size . ' ' . $size . '" style="width:' . $size . 'px;height:' . $size . 'px" role="img">';
    $a0 = -M_PI / 2;
    foreach ($items as $i) {
        $frac = (float) $i['value'] / $total;
        $a1 = $a0 + $frac * 2 * M_PI;
        $large = ($a1 - $a0) > M_PI ? 1 : 0;
        $x0 = $cx + $r * cos($a0); $y0 = $cy + $r * sin($a0);
        $x1 = $cx + $r * cos($a1); $y1 = $cy + $r * sin($a1);
        $xi1 = $cx + $ir * cos($a1); $yi1 = $cy + $ir * sin($a1);
        $xi0 = $cx + $ir * cos($a0); $yi0 = $cy + $ir * sin($a0);
        $svg .= sprintf(
            '<path d="M%.2f,%.2f A%.2f,%.2f 0 %d 1 %.2f,%.2f L%.2f,%.2f A%.2f,%.2f 0 %d 0 %.2f,%.2f Z" fill="%s">'
          . '<title>%s：%s（%s%%）</title></path>',
            $x0, $y0, $r, $r, $large, $x1, $y1, $xi1, $yi1, $ir, $ir, $large, $xi0, $yi0,
            e($i['color']), e((string) $i['label']), _fmt_full((float) $i['value']),
            number_format($frac * 100, 1));
        $a0 = $a1;
    }
    if ($centerValue !== '') {
        $svg .= sprintf('<text x="%.1f" y="%.1f" font-size="13" fill="var(--c-text-3)" text-anchor="middle">%s</text>',
                        $cx, $cy - 6, e($centerLabel));
        $svg .= sprintf('<text x="%.1f" y="%.1f" font-size="16" font-weight="400" fill="var(--c-text)" '
                      . 'text-anchor="middle">%s</text>', $cx, $cy + 14, e($centerValue));
    }
    $svg .= '</svg>';

    $legend = '<div class="donut-legend">';
    foreach ($items as $i) {
        $pct = (float) $i['value'] / $total * 100;
        $legend .= '<div class="dl"><i style="background:' . e($i['color']) . '"></i>'
                 . '<span class="dl-l">' . e((string) $i['label']) . '</span>'
                 . '<span class="dl-v">' . number_format($pct, 1) . '%</span></div>';
    }
    return '<div class="donut-wrap">' . $svg . $legend . '</div>';
}

/**
 * 水平条形：Top 客户 / 账龄。
 * $items: [['label'=>, 'value'=>, 'note'=>]]，value 用于排序与长度。
 */
function hbar_chart(array $items, string $ccy = 'HKD'): string
{
    if (!$items) return '<div class="chart-empty">' . e(t('暂无数据')) . '</div>';
    $max = 0.0;
    foreach ($items as $i) $max = max($max, abs((float) $i['value']));
    if ($max <= 0) $max = 1;

    $out = '<div class="hbars">';
    foreach ($items as $it) {
        $v = (float) $it['value'];
        $pct = max(1.5, abs($v) / $max * 100);
        $note = (string) ($it['note'] ?? '');
        $out .= '<div class="hbar">'
              . '<div class="hbar-top"><span class="hbar-l">' . e((string) $it['label']) . '</span>'
              . '<span class="hbar-v">' . number_format($v, 2) . ' ' . e((string) ($it['ccy'] ?? $ccy)) . '</span></div>'
              . '<div class="hbar-track"><div class="hbar-fill" style="width:' . $pct . '%;'
              . 'background:' . e((string) ($it['color'] ?? 'var(--c-primary)')) . '"></div></div>'
              . ($note !== '' ? '<div class="hbar-note">' . e($note) . '</div>' : '')
              . '</div>';
    }
    return $out . '</div>';
}

/** 迷你折线（指标卡内）。 */
function sparkline(array $values, string $color = '#1E40AF'): string
{
    $n = count($values);
    if ($n < 3) return '';
    $max = max($values); $min = min($values);
    $span = ($max - $min) ?: 1;
    $w = 120; $h = 28;
    $pts = [];
    foreach ($values as $i => $v) {
        $pts[] = sprintf('%.1f,%.1f', $w * $i / ($n - 1), $h - ($h - 4) * (($v - $min) / $span) - 2);
    }
    $d = 'M' . implode(' L', $pts);
    return '<svg viewBox="0 0 ' . $w . ' ' . $h . '" style="width:' . $w . 'px;height:' . $h . 'px" '
         . 'aria-hidden="true"><path d="' . $d . '" fill="none" stroke="' . e($color) . '" '
         . 'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>';
}

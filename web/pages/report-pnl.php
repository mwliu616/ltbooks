<?php
/*
 * LtBooks — pages/report-pnl.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$__rp = $GLOBALS['RP'] ?? report_period();
// 期间由 report_period() 给出：本财务年度没有分录时会自动落到有数据的年度
$__fye = (string) ((api_get('/company')['data']['fiscalYearEnd'] ?? '12-31'));
$from = (string) ($_GET['from'] ?? $__rp['from']);
$to = (string) ($_GET['to'] ?? $__rp['to']);
$qs = '/reports/pnl';
$p = [];
if ($from !== '') { $p[] = 'from=' . urlencode($from); }
if ($to !== '') { $p[] = 'to=' . urlencode($to); }
if ($p) { $qs .= '?' . implode('&', $p); }
$r = api_get($qs);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];

// 对比口径：
//   compare=fy  上一财务年度（按年结日整年，例：2026-05-01~2027-04-30 对 2025-05-01~2026-04-30）
//   compare=1   上年同期（同起止日各往回推一年，默认）
//   compare=0   不对比
$__cmp = (string) ($_GET['compare'] ?? 'fy');
$showCompare = $__cmp !== '0';
$prevFrom = $prevTo = '';
$pvs = [];
if ($showCompare && $from !== '' && $to !== '') {
    try {
        if ($__cmp === 'fy') {
            // 找出 $to 所在财务年度的年结日，再往前推一年
            [$fm, $fd] = array_map('intval', explode('-', $__fye) + [0, 0]);
            $fm = $fm ?: 12; $fd = $fd ?: 31;
            $toD = new DateTimeImmutable($to);
            $fyEnd = new DateTimeImmutable(sprintf('%d-%02d-%02d', (int) $toD->format('Y'), $fm, $fd));
            if ($fyEnd < $toD) { $fyEnd = $fyEnd->modify('+1 year'); }
            $prevToD = $fyEnd->modify('-1 year');
            $prevFromD = $prevToD->modify('-1 year')->modify('+1 day');
            $prevFrom = $prevFromD->format('Y-m-d');
            $prevTo = $prevToD->format('Y-m-d');
        } else {
            $prevFrom = (new DateTimeImmutable($from))->modify('-1 year')->format('Y-m-d');
            $prevTo = (new DateTimeImmutable($to))->modify('-1 year')->format('Y-m-d');
        }
        $pr = api_get('/reports/pnl?from=' . urlencode($prevFrom) . '&to=' . urlencode($prevTo));
        if ($pr['ok']) {
            $pvs = $pr['data'];
            foreach (['revenue','costOfSales','otherIncome','otherGains','operatingExpenses',
                      'financeCosts','taxExpense'] as $k) {
                $pvs[$k]['_byCode'] = [];
                foreach (($pvs[$k]['items'] ?? []) as $it) {
                    $pvs[$k]['_byCode'][(string) $it['accountCode']] = (float) $it['amount'];
                }
            }
        } else { $showCompare = false; }
    } catch (Throwable $e) { $showCompare = false; }
}
$hasPrev = $showCompare && $pvs;
?>
<?php
/** 一行三段：本期 / 上年同期 / 变动（金额为 HKD，负方向用括号） */
function pl_amount(float $v, bool $negative = false): string
{
    if (abs($v) < 0.005) { return '—'; }
    return $negative ? '(' . money(abs($v)) . ')' : money($v);
}

function pl_delta(float $cur, float $prev): string
{
    $d = $cur - $prev;
    if (abs($d) < 0.005) { return '<span style="color:var(--c-text-3)">—</span>'; }
    $cls = $d > 0 ? 'var(--c-ok)' : 'var(--c-danger)';
    $sign = $d > 0 ? '+' : '−';
    return '<span style="color:' . $cls . ';font-variant-numeric:tabular-nums">'
        . $sign . money(abs($d)) . '</span>';
}

function pl_section(string $label, array $sec, bool $negative = false, ?array $prev = null): string
{
    $prevItems = $prev['_byCode'] ?? [];
    $h = '<tr class="total"><td colspan="' . ($prev === null ? 3 : 4) . '">' . e($label) . '</td></tr>';
    if (!$sec['items']) {
        $h .= '<tr><td style="padding-left:24px;color:var(--c-text-3)">（无）</td><td class="num">—</td>'
            . ($prev === null ? '<td></td>' : '<td class="num">' . pl_amount((float) ($prev['total'] ?? 0), $negative)
               . '</td><td class="num">' . pl_delta(0, (float) ($prev['total'] ?? 0)) . '</td>')
            . '</tr>';
    }
    foreach ($sec['items'] as $i) {
        $code = (string) $i['accountCode'];
        $cur = (float) $i['amount'];
        $pv = (float) ($prevItems[$code] ?? 0);
        $h .= '<tr><td style="padding-left:24px">' . e((string) acc_name($code, $i['accountName'] ?? ''))
            . ' <span class="hint" style="display:inline">· ' . e($code) . '</span></td>'
            . '<td class="num">' . pl_amount($cur, $negative) . '</td>';
        if ($prev !== null) {
            $h .= '<td class="num">' . pl_amount($pv, $negative) . '</td>'
                . '<td class="num">' . pl_delta($cur, $pv) . '</td>';
        } else {
            $h .= '<td></td>';
        }
        $h .= '</tr>';
    }
    $v = (float) $sec['total'];
    $pvTotal = (float) ($prev['total'] ?? 0);
    $h .= '<tr><td style="font-weight:400">' . e($label) . '合计</td>'
        . '<td class="num" style="font-weight:400">' . pl_amount($v, $negative) . '</td>';
    if ($prev !== null) {
        $h .= '<td class="num">' . pl_amount($pvTotal, $negative) . '</td>'
            . '<td class="num">' . pl_delta($v, $pvTotal) . '</td>';
    } else {
        $h .= '<td></td>';
    }
    return $h . '</tr>';
}

ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr>
  <th>项目</th>
  <th class="num" style="width:150px">本期<?= $hasPrev ? '<div class="hint" style="font-weight:400">' . e($from) . ' ~ ' . e($to) . '</div>' : '' ?></th>
  <?php if ($hasPrev): ?>
    <th class="num" style="width:150px"><?= $__cmp === 'fy' ? e(t('上一财务年度')) : e(t('上年同期')) ?><div class="hint" style="font-weight:400"><?= e($prevFrom) ?> ~ <?= e($prevTo) ?></div></th>
    <th class="num" style="width:140px">变动</th>
  <?php else: ?>
    <th style="width:40px"></th>
  <?php endif; ?>
</tr></thead>
<tbody>
  <?= pl_section('收入', $d['revenue'], false, $hasPrev ? $pvs['revenue'] : null) ?>
  <?= pl_section('销售成本', $d['costOfSales'], true, $hasPrev ? $pvs['costOfSales'] : null) ?>
  <tr class="total"><td><b>毛利</b></td><td class="num"><b><?= money($d['grossProfit']) ?></b></td>
    <?php if ($hasPrev): ?>
      <td class="num"><?= money((float) $pvs['grossProfit']) ?></td>
      <td class="num"><?= pl_delta((float) $d['grossProfit'], (float) $pvs['grossProfit']) ?></td>
    <?php else: ?><td></td><?php endif; ?>
  </tr>
  <?= pl_section('其他收入', $d['otherIncome'], false, $hasPrev ? $pvs['otherIncome'] : null) ?>
  <?= pl_section('其他收益／（亏损）', $d['otherGains'], false, $hasPrev ? $pvs['otherGains'] : null) ?>
  <?= pl_section('经营费用', $d['operatingExpenses'], true, $hasPrev ? $pvs['operatingExpenses'] : null) ?>
  <tr class="total"><td><b>除税前溢利</b></td><td class="num"><b><?= money($d['profitBeforeTax']) ?></b></td>
    <?php if ($hasPrev): ?>
      <td class="num"><?= money((float) $pvs['profitBeforeTax']) ?></td>
      <td class="num"><?= pl_delta((float) $d['profitBeforeTax'], (float) $pvs['profitBeforeTax']) ?></td>
    <?php else: ?><td></td><?php endif; ?>
  </tr>
  <?= pl_section('财务费用', $d['financeCosts'], true, $hasPrev ? $pvs['financeCosts'] : null) ?>
  <?= pl_section('税项', $d['taxExpense'], true, $hasPrev ? $pvs['taxExpense'] : null) ?>
  <tr class="total" style="font-size:var(--f-md)"><td>本期溢利</td>
    <td class="num"><?= money($d['netProfit']) ?></td>
    <?php if ($hasPrev): ?>
      <td class="num"><?= money((float) $pvs['netProfit']) ?></td>
      <td class="num"><?= pl_delta((float) $d['netProfit'], (float) $pvs['netProfit']) ?></td>
    <?php else: ?><td></td><?php endif; ?>
  </tr>
</tbody></table></div>
<div class="hint" style="padding:10px 14px"><?= e((string) $d['note']) ?></div>
<?php
$__sum = abs((float) ($d['revenue']['total'] ?? 0)) + abs((float) ($d['operatingExpenses']['total'] ?? 0))
       + abs((float) ($d['costOfSales']['total'] ?? 0));
$__sumPrev = 0.0;
if ($hasPrev) {
    foreach (['revenue', 'operatingExpenses', 'costOfSales'] as $k) {
        $__sumPrev += abs((float) ($pvs[$k]['total'] ?? 0));
    }
}
if ($__sum < 0.005) {
    echo '<div class="hint" style="padding:0 4px 10px">';
    if ($__sumPrev >= 0.005) {
        echo e(t('本期还没有已过账的损益分录；右列是上一财务年度的审计数字，可直接对照。'));
    } else {
        echo e(t('这个区间没有已过账的损益分录，换一个期间再看看。'));
    }
    echo '</div>';
}
$__card = ob_get_clean();
echo card('损益及其他全面收益表', $__card, '', false); ?>

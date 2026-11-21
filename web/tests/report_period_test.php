<?php
/**
 * 报表期间单元测试
 * ---------------------------------------------------------------------------
 * 覆盖「本财务年度没有分录时，自动回落到账簿最后一笔所在的财务年度」这一逻辑，
 * 以及各预设期间不受影响、上一期间随回落一起重算。
 *
 * 运行：env -u LD_LIBRARY_PATH php tests/report_period_test.php
 * 退出码 0 = 全部通过，1 = 有失败项。
 */
declare(strict_types=1);

// lib/ui.php 里的 report_period() 依赖 api_get()，这里给出最小桩
function api_get(string $path): array
{
    $GLOBALS['__api_calls'][] = $path;
    if (str_starts_with($path, '/journal')) {
        return ['ok' => true, 'data' => ['entries' => $GLOBALS['__api_entries']]];
    }
    return ['ok' => false, 'error' => 'not stubbed: ' . $path];
}

require_once __DIR__ . '/../lib/ui.php';

$GLOBALS['__api_calls'] = [];
$GLOBALS['__api_entries'] = [];
$passes = 0;
$fails = 0;

function check(string $label, mixed $expected, mixed $actual): void
{
    global $passes, $fails;
    if ($expected === $actual) {
        $passes++;
        echo "  ok   {$label}\n";
        return;
    }
    $fails++;
    echo "  FAIL {$label}\n";
    echo '       期望：' . var_export($expected, true) . "\n";
    echo '       实际：' . var_export($actual, true) . "\n";
}

/**
 * 用固定「今天」跑一次 report_period()。
 * @param string|null $lastEntry 账簿最后一笔分录日期；null 表示账簿为空
 */
function period_for(string $today, string $fye, ?string $lastEntry, array $get = []): array
{
    $_GET = $get;
    $_COOKIE = [];
    $_SESSION = ['company_fye' => $fye];
    $GLOBALS['__api_calls'] = [];
    $GLOBALS['__api_entries'] = $lastEntry === null ? [] : [['entry_date' => $lastEntry]];

    return report_period(new DateTimeImmutable($today));
}

echo "report_period：本财务年度为空时回落到有数据的年度\n";

// 1. 今天 2026-11-18、年结 04-30，本财年 2026-05-01 起；账簿停 2026-03-31
$p = period_for('2026-11-18', '04-30', '2026-03-31');
check('本期起', '2025-05-01', $p['from']);
check('本期止', '2026-04-30', $p['to']);
check('上期起', '2024-05-01', $p['prevFrom']);
check('上期止', '2025-04-30', $p['prevTo']);
check('预设仍记为本财务年度', 'fiscal_year', $p['preset']);
check('只查一次账簿', ['/journal?limit=1'], $GLOBALS['__api_calls']);

// 2. 最后一笔分录恰好在财年末日，仍应完整覆盖该财年
$p = period_for('2026-11-18', '04-30', '2026-04-30');
check('财年末日：本期起', '2025-05-01', $p['from']);
check('财年末日：本期止', '2026-04-30', $p['to']);

// 3. 本财年已有分录，不回退，止日仍为今天
$p = period_for('2026-11-18', '04-30', '2026-06-15');
check('本财年有数：本期起', '2026-05-01', $p['from']);
check('本财年有数：本期止', '2026-11-18', $p['to']);
check('本财年有数：上期起', '2025-05-01', $p['prevFrom']);
check('本财年有数：上期止', '2026-04-30', $p['prevTo']);

// 4. 账簿为空：保留本财年，不擅自跳年
$p = period_for('2026-11-18', '04-30', null);
check('空账簿：本期起', '2026-05-01', $p['from']);
check('空账簿：本期止', '2026-11-18', $p['to']);

// 5. 年结日为 12-31 时同样按年结日推
$p = period_for('2026-11-18', '12-31', '2025-06-30');
check('年结 12-31：本期起', '2025-01-01', $p['from']);
check('年结 12-31：本期止', '2025-12-31', $p['to']);
check('年结 12-31：上期起', '2024-01-01', $p['prevFrom']);
check('年结 12-31：上期止', '2024-12-31', $p['prevTo']);

echo "\nreport_period：其他预设不受回落逻辑影响\n";

// 6. 自定义区间按传入值使用，且不应触发账簿查询
$p = period_for('2026-11-18', '04-30', '2025-06-30', [
    'preset' => 'custom', 'from' => '2026-01-01', 'to' => '2026-03-31',
]);
check('自定义：本期起', '2026-01-01', $p['from']);
check('自定义：本期止', '2026-03-31', $p['to']);
check('自定义：不查账簿', [], $GLOBALS['__api_calls']);

// 7. 本月预设保持自然月
$p = period_for('2026-11-18', '04-30', '2025-06-30', ['preset' => 'this_month']);
check('本月：起', '2026-11-01', $p['from']);
check('本月：止', '2026-11-30', $p['to']);
check('本月：不查账簿', [], $GLOBALS['__api_calls']);

// 8. 上一财务年度仍相对「今天」推，不随数据年度变化
$p = period_for('2026-11-18', '04-30', '2025-06-30', ['preset' => 'prev_fiscal']);
check('上一财年：起', '2025-05-01', $p['from']);
check('上一财年：止', '2026-04-30', $p['to']);

echo "\n结果：{$passes} 通过，{$fails} 失败\n";
exit($fails === 0 ? 0 : 1);

<?php
/*
 * LtBooks — lib/i18n.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 全站语言层：简中 / 繁中 / 英文。
 *
 * 策略：页面仍以简体中文撰写，输出时按当前语言做「文本节点翻译」。
 *  - 只翻译标签之间的文本与 placeholder/title/aria-label 属性，不碰 class/id 等
 *  - 科目名称不走词典：数据库已有 name_zh_cn / name_zh_hk / name_en，从源头取
 *  - 词典未命中的文本原样保留（宁可留着中文，也不输出半截英文）
 */
declare(strict_types=1);

const LANGS = ['zh_cn', 'zh_hk', 'en'];

/** 当前语言。会话记忆，默认简体中文（用户可切换）。 */
function lang(): string
{
    // 不能做静态缓存：切换语言的请求里，页面处理（含 API 调用）可能在
    // set_lang() 之前就读过一次 lang()，缓存住旧值会让整页停在旧语言。
    $l = (string) ($_SESSION['lang'] ?? 'zh_cn');
    return in_array($l, LANGS, true) ? $l : 'zh_cn';
}

/** 设置语言。 */
function set_lang(string $l): void
{
    if (in_array($l, LANGS, true)) {
        $_SESSION['lang'] = $l;
    }
}

/** 语言元数据。 */
function lang_meta(): array
{
    return [
        'zh_cn' => ['label' => '简', 'name' => '简体中文', 'html' => 'zh-CN'],
        'zh_hk' => ['label' => '繁', 'name' => '繁體中文', 'html' => 'zh-HK'],
        'en'    => ['label' => 'EN', 'name' => 'English',  'html' => 'en'],
    ];
}

/** 词典（按语言缓存）。键做空白归一化，便于匹配换行缩进过的文本。 */
function lang_dict(string $l): array
{
    static $cache = [];
    if (isset($cache[$l])) return $cache[$l];
    $file = __DIR__ . '/lang/' . $l . '.php';
    if (!is_file($file)) return $cache[$l] = [];
    $raw = (array) require $file;
    // 繁中再叠一层「简体原文 → 港式繁體」的自动映射，
    // 覆盖手工字典里还没收录的文案；手写条目优先级更高（后面的覆盖前面的）。
    if ($l === 'zh_hk') {
        $auto = __DIR__ . '/zh_hk_auto.php';
        if (is_file($auto)) { $raw = array_merge((array) require $auto, $raw); }
    }
    $norm = [];
    foreach ($raw as $k => $v) {
        $norm[preg_replace('/\s+/u', ' ', trim((string) $k))] = $v;
    }
    return $cache[$l] = $norm;
}

function zh_hk_chars(): array
{
    static $m = null;
    if ($m === null) {
        $f = __DIR__ . '/zh_hk_chars.php';
        $m = is_file($f) ? (array) require $f : [];
    }
    return $m;
}


/** 简体中文的会计术语表（大陆财务用词）。 */
function zh_cn_terms(): array
{
    static $terms = null;
    if ($terms === null) {
        $f = __DIR__ . '/lang/zh_cn_terms.php';
        $terms = is_file($f) ? (array) require $f : [];
    }
    return $terms;
}

/** 单条翻译。未命中返回原文。
 *
 * 用在「数字 + 中文」拼出来的句子里（如 "26 张未结清"）：
 * 整段文本命不中词典，拼出来就会半截中文，所以拆开翻译。
 */
function t(string $cn): string
{
    $key = preg_replace('/\s+/u', ' ', trim($cn));
    $l = lang();
    if ($l === 'zh_cn') {
        $terms = zh_cn_terms();
        return $terms ? strtr($key, $terms) : $key;
    }
    $d = lang_dict($l);
    $out = $d[$key] ?? ($d[$cn] ?? $key);
    // 动态拼装的句子未必能整句命中词典；繁中统一再做逐字兜底，
    // 同时修正旧词条里残留的简体字，避免同一句话简繁混杂。
    if ($l === 'zh_hk') {
        $chars = zh_hk_chars();
        if ($chars) { $out = strtr($out, $chars); }
    }
    return $out;
}

/**
 * 简体中文的术语替换：只改会计用词，不做整句翻译。
 *
 * 与其它语言共用同一套「保护 script/style → 处理文本节点 → 处理可翻译属性」流程，
 * 区别是这里做 strtr 词替换，而不是整句查表。
 */
function zh_cn_localize_html(string $html): string
{
    $terms = zh_cn_terms();
    if (!$terms) return $html;

    $stash = [];
    $html = preg_replace_callback('#<(script|style)\b[^>]*>.*?</\1>#is', function ($m) use (&$stash) {
        $k = "\x01BLK" . count($stash) . "\x01";
        $stash[$k] = $m[0];
        return $k;
    }, $html);

    $html = preg_replace_callback('/>([^<>]+)</u', function ($m) use ($terms) {
        $raw = $m[1];
        if (!preg_match('/\p{Han}/u', $raw)) return $m[0];
        return '>' . strtr($raw, $terms) . '<';
    }, $html);

    $attrRe = '/\b(placeholder|title|aria-label|alt|data-fill)="([^"]*[\x{4e00}-\x{9fff}][^"]*)"/u';
    $html = preg_replace_callback($attrRe, function ($m) use ($terms) {
        $val = html_entity_decode($m[2], ENT_QUOTES, 'UTF-8');
        return $m[1] . '="' . htmlspecialchars(strtr($val, $terms), ENT_QUOTES, 'UTF-8') . '"';
    }, $html);

    if ($stash) {
        $html = strtr($html, $stash);
    }
    return $html;
}


/**
 * 翻译一段 HTML 的文本节点与可翻译属性。
 */
function localize_html(string $html, array $accountNames = []): string
{
    $l = lang();
    if ($l === 'zh_cn') {
        return zh_cn_localize_html($html);
    }

    $dict = lang_dict($l);
    if (!$dict) return $html;
    $patterns = lang_patterns($l);

    // 脚本与样式块原样保护：里面的中文串不能翻译，否则会破坏 JS/CSS
    $stash = [];
    $html = preg_replace_callback('#<(script|style)\b[^>]*>.*?</\1>#is', function ($m) use (&$stash) {
        $k = "\x01BLK" . count($stash) . "\x01";
        $stash[$k] = $m[0];
        return $k;
    }, $html);

    // 1) 文本节点
    $html = preg_replace_callback('/>([^<>]+)</u', function ($m) use ($dict, $patterns, $accountNames, $l) {
        $raw = $m[1];
        $txt = trim($raw);
        if ($txt === '' || !preg_match('/\p{Han}/u', $txt)) return $m[0];

        $fix = function (string $v) use ($l): string {
            if ($l !== 'zh_hk') { return $v; }
            $chars = zh_hk_chars();
            return $chars ? strtr($v, $chars) : $v;
        };

        // 「 · 贷方合计 」这类：分隔符在文本节点里，单独摘出来再翻译
        $lead = '';
        $core = $txt;
        if (preg_match('/^([·—–\-]\s*)(\S.*)$/u', $txt, $lm)) {
            $lead = $lm[1]; $core = $lm[2];
        }
        $trail = preg_match('/\s$/u', $raw) ? ' ' : '';

        $key = preg_replace('/\s+/u', ' ', $core);
        if ($lead === '' && isset($dict[$key])) {
            return '>' . $fix($dict[$key]) . '<';
        }
        if ($lead !== '' && isset($dict[$key])) {
            return '>' . $lead . $fix($dict[$key]) . $trail . '<';
        }
        // 复合文本：标题后缀、副标题分隔等
        $compound = localize_compound($txt, $dict, $accountNames);
        if ($compound !== null) {
            return '>' . $fix($compound) . '<';
        }
        if (isset($dict[$txt])) {
            $pos = strpos($raw, $txt);
            return '>' . substr_replace($raw, $fix($dict[$txt]), $pos, strlen($txt)) . '<';
        }
        foreach ($patterns as $p) {
            $flat = preg_replace('/\s+/u', ' ', $txt);
            $out = preg_replace($p[0], $p[1], $flat);
            if ($out !== null && $out !== $flat) {
                return '>' . $fix($out) . '<';
            }
        }
        if ($l === 'zh_hk') {
            $chars = zh_hk_chars();
            if ($chars) {
                $conv = strtr($txt, $chars);
                if ($conv !== $txt) {
                    $pos = strpos($raw, $txt);
                    return '>' . substr_replace($raw, $conv, $pos, strlen($txt)) . '<';
                }
            }
        }
        return $m[0];
    }, $html);

    // 2) 可翻译属性
    $attrRe = '/\b(placeholder|title|aria-label|alt|data-fill)="([^"]*[\x{4e00}-\x{9fff}][^"]*)"/u';
    $html = preg_replace_callback($attrRe, function ($m) use ($dict, $patterns, $l) {
        $val = html_entity_decode($m[2], ENT_QUOTES, 'UTF-8');
        $out = $dict[$val] ?? null;
        if ($out === null) {
            $flat = preg_replace('/\s+/u', ' ', $val);
            foreach ($patterns as $p) {
                $try = preg_replace($p[0], $p[1], $flat);
                if ($try !== null && $try !== $flat) { $out = $try; break; }
            }
        }
        // 繁中：词典里若残留简体（历史自动词条），属性文案也要逐字转繁
        if ($out !== null && $l === 'zh_hk') {
            $chars = zh_hk_chars();
            if ($chars) { $out = strtr($out, $chars); }
        }
        // 繁中：词典没收录的属性文案也要逐字转繁，否则 placeholder 会残留简体
        if ($out === null && $l === 'zh_hk') {
            $chars = zh_hk_chars();
            if ($chars) {
                $conv = strtr($val, $chars);
                if ($conv !== $val) { $out = $conv; }
            }
        }
        if ($out === null) return $m[0];
        return $m[1] . '="' . htmlspecialchars($out, ENT_QUOTES, 'UTF-8') . '"';
    }, $html);

    // 还原被保护的块
    if ($stash) {
        $html = strtr($html, $stash);
    }
    return $html;
}

/**
 * 复合文本翻译：处理「页面名 — 产品名」「页面名 · 公司 · 币种 · 准则」等拼接。
 * 返回 null 表示不适用。
 */
/** 英文界面的动态整句规则：数字 + 中文拼出来的句子，按模式整句替换。 */
function lang_patterns(string $l): array
{
    if ($l !== 'en') return [];
    return [
        ['/^([\d,\.]+) HKD 已逾期 · (\d+) 笔$/u', 'HKD $1 overdue · $2 items'],
        ['/^(\d+) 张未结 · 最早 (\d{4}-\d{2}-\d{2})$/u', '$1 open · oldest $2'],
        ['/^(\d+) 张未结$/u', '$1 open'],
        ['/^(\d+) 张未结账单，最早 (\d{4}-\d{2}-\d{2}) 已到期。$/u', '$1 open bills; the oldest fell due on $2.'],
        ['/^(\d+) 笔、([\d,\.]+) HKD 已逾期，最长 (\d+) 天。$/u', '$1 items, HKD $2 overdue, up to $3 days.'],
        ['/^(\d+) 笔逾期 · 最长 (\d+) 天$/u', '$1 overdue · up to $2 days'],
        ['/^(\d+) 笔逾期$/u', '$1 overdue'],
        ['/^逾期 (\d+) 天$/u', 'Overdue $1 days'],
        ['/^AR ([\d,\.]+) ÷ 近 12 个月收入 × 365$/u', 'AR $1 ÷ last 12 months revenue × 365'],
        ['/^AR ([\d,\.]+) − 应付 ([\d,\.]+)$/u', 'AR $1 − payables $2'],
        ['/^AR (\d+)% 已逾期，现金只够 ([\d\.]+) 个月费用；优先催收 (.+)。$/u',
         '$1% of receivables are overdue; cash covers $2 months of expenses; collect from $3 first.'],
        ['/^Cash ([\d,\.]+) ÷ 月均费用 ([\d,\.]+)$/u', 'Cash $1 ÷ average monthly expenses $2'],
        ['/^FY ([\d\/]+) · (\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2}) · 本期净利$/u',
         'FY $1 · $2 to $3 · net profit'],
        ['/^收入 ([\d,\.\-]+) HKD · 净利率 ([\d\.]+)% · 账簿截止年度$/u',
         'Revenue HKD $1 · net margin $2% · year to books close'],
        ['/^收入 ([\d,\.\-]+) HKD · 账簿截止年度$/u', 'Revenue HKD $1 · year to books close'],
        ['/^未匹配流水 (\d+) 笔，全部匹配$/u', 'Unmatched bank lines: $1 · all matched'],
        ['/^本月已抓取 (\d+) 条 ECB 汇率$/u', 'Fetched $1 ECB rates this month'],
        ['/^去处理这 (\d+) 条 →$/u', 'Handle these $1 items →'],
        ['/^共 (\d+) 条 · 按紧急程度排序$/u', '$1 items · sorted by urgency'],
        ['/^(\d+) \/ (\d+) 完成$/u', '$1 / $2 complete'],
        ['/^链完整，共校验 (\d+) 条$/u', 'Chain intact; $1 records verified'],
        ['/^基期止：(\d{4}-\d{2})（用上面的期间选择器调整）$/u',
         'Base period ends: $1 (adjust with the period selector above)'],
        ['/^账簿截至 (\d{4}-\d{2}-\d{2})，比今天滞后 (\d+) 个月。$/u',
         'Books end $1, $2 months behind today.'],
        ['/^数据截至 (\d{4}-\d{2}-\d{2}) · 按凭证日期归期 · 净值 = 收入 − 销售成本 − 费用$/u',
         'Data to $1 · dated by voucher · net = revenue − cost of sales − expenses'],
        ['/^近 12 个月 · (\d{4}-\d{2}) 至 (\d{4}-\d{2})$/u', 'Last 12 months · $1 to $2'],
        ['/^(.+) · 到期 (\d{4}-\d{2}-\d{2})$/u', '$1 · due $2'],
        ['/^(.+) · 账簿截至$/u', '$1 · books as of'],
        ['/^系统建议：(\d+)$/u', 'Suggested: $1'],
        ['/^单据 #(\d+) · 履约义务状态不明确，禁止自动判断$/u',
         'Document #$1 · performance obligation unclear; automatic judgment is blocked'],
        ['/^借方 ([\d,\.]+) HKD · 贷方 ([\d,\.]+) HKD · 差 ([\d,\.]+) HKD$/u',
         'Debit $1 HKD · credit $2 HKD · difference $3 HKD'],
        ['/^Convert at the system rate · 按最近汇率 ([\d\.]+) ≈ HKD ([\d,\.]+)$/u',
         'Convert at the system rate · latest rate $1 ≈ HKD $2'],
        ['/^发件人 (.+) · 密码存在数据库 app_settings 表（仅管理员可改），接口只回「是否已设置」，不回传明文$/u',
         'Sender $1 · The password is stored in the app_settings table (administrators only); the API only reports whether it is set and never returns the password.'],
        ['/^外发服务器\s+(\S+)\s*（(SSL|STARTTLS|NONE)，需要认证）$/u',
         'Outgoing server $1 ($2, authentication required)'],
        ['/^按未收金额 · 最长 (\d+) 天$/u', 'By outstanding amount · up to $1 days'],
        ['/^· 应评税利润为负，属税务亏损，可无限期结转抵销未来年度利润$/u',
         '· Assessable profits are negative (a tax loss), which carries forward indefinitely against future profits'],
        ['/^(\d{4}-\d{2}) 薪酬及强积金$/u', '$1 Payroll and MPF'],
        ['/^(\d{4}-\d{2}) 固定资产折旧$/u', '$1 Depreciation of fixed assets'],
        ['/^(\d{4})\/(\d{2}) 年度利得税计提$/u', 'Profit tax accrual for $1/$2'],
        ['/^(\d{4}) 年度审计费计提$/u', 'Audit fee accrual for $1'],
        ['/^董事贷款利息计提$/u', 'Director loan interest accrual'],
        ['/^期初余额：银行、股本及保留盈利$/u', 'Opening balances: bank, share capital and retained earnings'],
        ['/^逾期 Top 5 客户$/u', 'Top 5 overdue customers'],
        ['/^把发票内容粘贴到这里[\s\S]*$/u',
         'Paste the invoice text here, e.g. ACME TRADING LIMITED Invoice No.: INV-2026-8899 Invoice date: 2026-11-05 Subtotal 50000.00 Tax 6500.00 Total 56500.00'],
        ['/^应收 ([\d,\.]+) ÷ 近 12 个月收入 × 365$/u', 'Receivables $1 ÷ last 12 months revenue × 365'],
        ['/^应收 ([\d,\.]+) − 应付 ([\d,\.]+)$/u', 'Receivables $1 − payables $2'],
        ['/^应收 (\d+)% 已逾期，现金只够 ([\d\.]+) 个月费用；优先催收 (.+)。$/u',
         '$1% of receivables are overdue; cash covers $2 months of expenses; collect from $3 first.'],
        ['/^现金 ([\d,\.]+) ÷ 月均费用 ([\d,\.]+)$/u', 'Cash $1 ÷ average monthly expenses $2'],
    ];
}

function localize_segments(string $txt, array $dict): ?string
{
    $clean = trim($txt);
    $suffix = '';
    // 「摘要 *」「分录日期 *」：把结尾的星号摘掉再翻
    if (preg_match('/^(.*?)(\s*\*+)$/u', $clean, $m)) {
        $clean = trim($m[1]); $suffix = $m[2];
    }
    if (isset($dict[$clean])) { return $dict[$clean] . $suffix; }

    // 动态模式：金额、财务年度选项、报表合计
    if (preg_match('/^账面应收\s*([\d,\.]+)\s*HKD$/u', $clean, $m)) { return 'Ledger receivable ' . $m[1] . ' HKD' . $suffix; }
    if (preg_match('/^账面应付\s*([\d,\.]+)\s*HKD$/u', $clean, $m)) { return 'Ledger payable ' . $m[1] . ' HKD' . $suffix; }
    if (preg_match('/^全面收益\s*(-?[\d,\.]+)$/u', $clean, $m)) { return 'Total comprehensive income ' . $m[1] . $suffix; }
    if (preg_match('/^含本期损益\s*(-?[\d,\.]+)$/u', $clean, $m)) { return 'incl. profit for the period ' . $m[1] . $suffix; }
    if (preg_match('/^借方合计\s*([\d,\.]+)$/u', $clean, $m)) { return 'Total debit ' . $m[1] . $suffix; }
    if (preg_match('/^贷方合计\s*([\d,\.]+)$/u', $clean, $m)) { return 'Total credit ' . $m[1] . $suffix; }
    if (preg_match('/^差额\s*(-?[\d,\.]+)$/u', $clean, $m)) { return 'Difference ' . $m[1] . $suffix; }
    if (preg_match('/^(\d{1,2}) 月(\d{1,2}) 日（(非?日历年)）$/u', $clean, $m)) {
        $mo = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"];
        $cal = $m[3] === '日历年' ? 'calendar year' : 'non-calendar year';
        return ($mo[(int) $m[1]] ?? $m[1]) . ' ' . (int) $m[2] . ' (' . $cal . ')' . $suffix;
    }

    foreach ([' · ', ' — ', '：', '，', '；', '。', '、'] as $sep) {
        if (strpos($clean, $sep) === false) { continue; }
        $parts = explode($sep, $clean);
        $out = [];
        $ok = true;
        foreach ($parts as $part) {
            if (trim($part) === '') { $out[] = $part; continue; }
            // 已经是目标语言的片段（无中文）原样保留，不要求字典里有
            if (!preg_match('/\p{Han}/u', $part)) { $out[] = $part; continue; }
            $one = localize_segments($part, $dict);
            if ($one === null) { $ok = false; break; }
            $out[] = $one;
        }
        if ($ok) { return implode($sep, $out) . $suffix; }
    }
    return null;
}


function localize_compound(string $txt, array $dict, array $accountNames = []): ?string
{
    // 通用兜底：把「A · B — C」这类拼接文本按分隔符拆开，逐段翻译后拼回。
    // 这样「汇丰银行 — HKD 往来账户 · 按总账余额」也能翻，不必为每种组合加词条。
    $translated = localize_segments($txt, $dict);
    if ($translated !== null) { return $translated; }

    // 裸科目名（总账等页面只显示名称）：按数据库三语字段反查
    if ($accountNames) {
        static $rev = null;
        if ($rev === null) { $rev = []; foreach ($accountNames as $code => $nm) { $rev[(string) $nm] = $code; } }
        if (isset($rev[$txt])) { return $txt; }   // 已是目标语言则原样
    }
    // 「1000 · 资产」科目行：名称取自数据库的三语字段
    if (preg_match('/^(\d{3,6})\s+·\s+(.+)$/u', $txt, $m)) {
        $code = $m[1];
        $name = $accountNames[$code] ?? null;
        if ($name !== null && $name !== '') {
            return $code . ' · ' . $name;
        }
    }

    // 「自动核销 0 · 待复核 41 · 未匹配 19」
    if (preg_match('/^自动核销\s*(\d+)\s*·\s*待复核\s*(\d+)\s*·\s*未匹配\s*(\d+)$/u', $txt, $m)) {
        return "Auto-settled {$m[1]} · Pending review {$m[2]} · Unmatched {$m[3]}";
    }
    // 「Equity (含本期损益 373,501.11)」——全角/半角括号都要认
    if (preg_match('/^(.+?)\s*[（(]含本期损益\s*(-?[\d,\.]+)[）)]$/u', $txt, $m)) {
        $head = $dict[$m[1]] ?? $m[1];
        return $head . ' (incl. profit for the period ' . $m[2] . ')';
    }
    // 「全面收益 -19,520.25」等带金额的报表合计
    if (preg_match('/^全面收益\s*(-?[\d,\.]+)$/u', $txt, $m)) {
        return 'Total comprehensive income ' . $m[1];
    }
    if (preg_match('/^Equity\s*\(含本期损益\s*(-?[\d,\.]+)\)$/u', $txt, $m)) {
        return 'Equity (incl. profit for the period ' . $m[1] . ')';
    }

    // 「账面应收 17,381.17 HKD」这类带金额的说明
    if (preg_match('/^账面应收\s*([\d,\.]+)\s*HKD$/u', $txt, $m)) {
        return 'Ledger receivable ' . $m[1] . ' HKD';
    }
    if (preg_match('/^账面应付\s*([\d,\.]+)\s*HKD$/u', $txt, $m)) {
        return 'Ledger payable ' . $m[1] . ' HKD';
    }

    // 「4 月30 日（非日历年）」财务年度选项
    if (preg_match('/^(\d{1,2}) 月(\d{1,2}) 日（(非?日历年)）$/u', $txt, $m)) {
        $mo = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"];
        $cal = $m[3] === '日历年' ? 'calendar year' : 'non-calendar year';
        return ($mo[(int) $m[1]] ?? $m[1]) . ' ' . (int) $m[2] . ' (' . $cal . ')';
    }

    // 银行账户显示名：「汇丰银行 — HKD 往来账户」→「HSBC — HKD Current Account」
    if (mb_strpos($txt, '银行') !== false || mb_strpos($txt, '账户') !== false) {
        $bankWords = [
            '汇丰银行' => 'HSBC', '恒生银行' => 'Hang Seng Bank', '中国银行' => 'Bank of China',
            '渣打银行' => 'Standard Chartered', '东亚银行' => 'Bank of East Asia',
            '外币账户' => 'Foreign Currency Account', '加元账户' => 'CAD Account',
            '美元账户' => 'USD Account', '往来账户' => 'Current Account',
            '储蓄账户' => 'Savings Account', '储蓄' => 'Savings',
            '定期存款' => 'Time Deposit', '账户' => 'Account',
        ];
        $out = $txt;
        foreach ($bankWords as $cn => $en) { $out = str_replace($cn, $en, $out); }
        if ($out !== $txt && !preg_match('/\p{Han}/u', $out)) { return $out; }
    }
    // 「跨币种匹配需要 HKD→USD 在 2025-04-22 的汇率，未取得；不得静默核销」
    if (preg_match('/^跨币种匹配需要\s*(\w+)\s*[→\->]+\s*(\w+)\s*在\s*(\d{4}-\d{2}-\d{2})\s*的汇率[，,]\s*未取得[；;]\s*不得静默核销$/u', $txt, $m)) {
        return "Cross-currency match needs the {$m[1]}→{$m[2]} rate on {$m[3]}, which is unavailable; the item must not be settled silently";
    }
    // 「正数为汇兑收益，负数为汇兑损失 · 合计 320.00」
    if (preg_match('/^正数为汇兑收益[，,]\s*负数为汇兑损失\s*·\s*合计\s*([\d,\.\-]+)$/u', $txt, $m)) {
        return "Positive is a gain, negative a loss · Total {$m[1]}";
    }
    // 「一、财务状况表」「五、财务报表附注」等中文序号标题
    if (preg_match('/^[一二三四五六七八九十]+[、.]\s*(.+)$/u', $txt, $m)) {
        $idx = mb_substr($txt, 0, 1);
        $num = ['一' => 'I', '二' => 'II', '三' => 'III', '四' => 'IV',
                '五' => 'V', '六' => 'VI', '七' => 'VII', '八' => 'VIII',
                '九' => 'IX', '十' => 'X'][$idx] ?? '';
        $head = $dict[$m[1]] ?? null;
        if ($head === null) {
            foreach ($dict as $k => $v) { if (mb_strpos($m[1], $k) !== false) { $head = str_replace($k, $v, $m[1]); break; } }
        }
        if ($head !== null && !preg_match('/\p{Han}/u', $head)) {
            return ($num !== '' ? $num . '. ' : '') . $head;
        }
    }
    // 「两级制税率资格：undetermined」
    if (preg_match('/^两级制税率资格[：:]\s*(\S+)$/u', $txt, $m)) {
        return 'Two-tiered rates eligibility: ' . $m[1];
    }
    // 「功能货币为 XXX，列报货币相同。」
    if (preg_match('/^功能货币为\s*(\w+)[，,]\s*列报货币相同[。.]?$/u', $txt, $m)) {
        return "The functional currency is {$m[1]}, which is also the presentation currency.";
    }
    // 「净变动 -12,000.00」
    if (preg_match('/^净变动\s*([\-\d,\.]+)$/u', $txt, $m)) { return "Net change {$m[1]}"; }
    // 「… (于 2026-11-07 结算)」/「… (2026-01-01 至 2026-11-07)」
    if (preg_match('/^(.+?)\s*[（(]于\s*(\d{4}-\d{2}-\d{2})\s*结算[）)]$/u', $txt, $m)) {
        $head = $dict[$m[1]] ?? localize_compound($m[1], $dict, $accountNames) ?? $m[1];
        return $head . ' (as at ' . $m[2] . ')';
    }
    if (preg_match('/^(.+?)\s*[（(](\d{4}-\d{2}-\d{2})\s*至\s*(\d{4}-\d{2}-\d{2})[）)]$/u', $txt, $m)) {
        $head = $dict[$m[1]] ?? localize_compound($m[1], $dict, $accountNames) ?? $m[1];
        return $head . ' (' . $m[2] . ' to ' . $m[3] . ')';
    }
    // 「勾稽：资产 X － 权益及负债 Y ＝ Z」
    if (preg_match('/^勾稽[：:]\s*资产\s*([\d,\.]+)\s*[－-]\s*权益及负债\s*([\d,\.]+)\s*[＝=]\s*([\-\d,\.]+)$/u', $txt, $m)) {
        return "Reconciliation: assets {$m[1]} − equity and liabilities {$m[2]} = {$m[3]}";
    }
    // 「课税年度 2026/27 · 基期止 2026-11」
    if (preg_match('/^课税年度\s*(\S+)\s*·\s*基期止\s*(\S+)$/u', $txt, $m)) {
        return "Year of assessment {$m[1]} · basis period ended {$m[2]}";
    }

    // 「付款 LEDU20261219007」「收款 RCT-2026...」等系统生成的摘要前缀
    if (preg_match('/^(付款|收款|转账|冲销)\s+(\S.*)$/u', $txt, $m)) {
        $map = ['付款' => 'Payment', '收款' => 'Receipt',
                '转账' => 'Transfer', '冲销' => 'Reversal'];
        return $map[$m[1]] . ' ' . $m[2];
    }
    // 「银行账户期初余额 XXX」「期末重估 xxx #2 USD @ 7.89（2026-11-30）」
    if (preg_match('/^银行账户期初余额\s+(\S.*)$/u', $txt, $m)) {
        return 'Opening balance of bank account ' . $m[1];
    }
    if (preg_match('/^期末重估\s+(\S+)\s+#(\d+)\s+(\w+)\s+@\s+([\d.]+)[（(](\S+)[）)]$/u', $txt, $m)) {
        return 'FX revaluation ' . $m[1] . ' #' . $m[2] . ' ' . $m[3]
             . ' @ ' . $m[4] . ' (' . $m[5] . ')';
    }
    // 「银行流水入账：银行手续费 BANK CHARGES」
    if (preg_match('/^银行流水入账[：:]\s*(.+)$/u', $txt, $m)) {
        return 'Statement line posting: ' . $m[1];
    }
    // 「找不到 XXX→HKD 在 2027-01-31 的汇率（回退窗口 5 天）」
    if (preg_match('/^找不到\s*(\w+)\s*→\s*(\w+)\s*在\s*(\S+)\s*的汇率[（(]回退窗口\s*(\d+)\s*天[）)]$/u', $txt, $m)) {
        return "No {$m[1]}→{$m[2]} rate found for {$m[3]} (fallback window {$m[4]} days)";
    }
    // 「采购发票 BILL-001 — Gamma Logistics Ltd」
    if (preg_match('/^(采购发票|销售发票|费用|收入合同|收款|付款)\s+(\S+)\s+—\s+(.+)$/u', $txt, $m)) {
        $map = ['采购发票' => 'Bill', '销售发票' => 'Invoice', '费用' => 'Expense',
                '收入合同' => 'Contract', '收款' => 'Receipt', '付款' => 'Payment'];
        return $map[$m[1]] . ' ' . $m[2] . ' — ' . $m[3];
    }
    // 「供应商号 SUP-9988」「客户号 C-001」等：前缀译，编号保留
    if (preg_match('/^(供应商号|客户号|员工号)\s+(\S.*)$/u', $txt, $m)) {
        $map = ['供应商号' => 'Supplier No.', '客户号' => 'Customer No.', '员工号' => 'Employee No.'];
        return $map[$m[1]] . ' ' . $m[2];
    }
    // 「Details (CSV：日期,金额,参考号,对手方；...)」
    if (preg_match('/^(?:明细|Details)\s*[（(]CSV[：:]\s*日期[，,]\s*金额[，,]\s*参考号[，,]\s*对手方[；;](.+)[）)]$/u', $txt, $m)) {
        $tail = str_replace(
            ['金额正为收入、负为支出', '金额正为收入', '负为支出'],
            ['positive = inflow, negative = outflow', 'positive = inflow', 'negative = outflow'],
            $m[1]);
        return 'Details (CSV: date, amount, reference, counterparty;' . $tail . ')';
    }
    // 「（重分类至 XXX）」
    if (preg_match('/^[（(]重分类至\s*(.+?)[）)]$/u', $txt, $m)) {
        return '(reclassified to ' . $m[1] . ')';
    }
    // 「链完整，共校验 157 条」——必须先于通用前缀规则，否则尾部「条」会残留
    if (preg_match('/^链完整[，,]\s*共校验\s*(\d+)\s*条$/u', $txt, $m)) {
        return "Chain intact, verified {$m[1]} records";
    }
    // 「Chain intact, verified 157 条」
    if (preg_match('/^Chain intact, verified\s*(\d+)\s*条$/u', $txt, $m)) {
        return "Chain intact, verified {$m[1]} records";
    }

    // 「合同 3 份 · 截至 2026-11-07」
    if (preg_match('/^合同\s*(\d+)\s*份\s*·\s*截至\s*(\S+)$/u', $txt, $m)) {
        return ($m[1] === '1' ? '1 contract' : "{$m[1]} contracts") . ' · as at ' . $m[2];
    }
    // 「N 张 · 合计 X」
    if (preg_match('/^(\d+)\s*张\s*·\s*合计\s*(.+)$/u', $txt, $m)) {
        return $m[1] . ' items · total ' . $m[2];
    }
    // 「发件人 NAME <addr> · 密码仅存于…」→ 整行本地化
    if (preg_match('/^发件人\s+(.+?)(?:\s*·\s*密码仅存于服务端配置文件.*)?$/u', $txt, $m)) {
        $sender = $m[1];
        if (mb_strpos($txt, '密码仅存于') !== false) {
            return 'From ' . $sender . ' · The password lives only in the server-side config file; it is never written to the database nor returned by any API.';
        }
        return 'From ' . $sender;
    }
    // 「HKFRFS 15 收入确认 XXX 截至 DATE」
    if (preg_match('/^(?:HKFRS\s*15\s*)?收入确认\s+(.+?)\s+截至\s+(\d{4}-\d{2}-\d{2})$/u', $txt, $m)) {
        return "HKFRS 15 revenue recognition {$m[1]} as at {$m[2]}";
    }
    // 「冲销 XXX：actor」/「被 #N 冲销」
    if (preg_match('/^冲销\s+(.+)$/u', $txt, $m)) {
        return 'Reverse ' . $m[1];
    }
    if (preg_match('/^被\s+(#\d+)\s+冲销$/u', $txt, $m)) {
        return 'Reversed by ' . $m[1];
    }
    // 「发票 XXX 确认」
    if (preg_match('/^发票\s+(\S+)\s+确认$/u', $txt, $m)) {
        return "Invoice {$m[1]} recognised";
    }
    // 「全面收益 256,051.11」「期初 0.00」「待复核（6）」：前缀命中词典则只译前缀
    if (preg_match('/^(.{2,12}?)\s+([-\d(].*)$/u', $txt, $m) && !preg_match('/\p{Han}/u', $m[2]) && isset($dict[$m[1]])) {
        return $dict[$m[1]] . ' ' . $m[2];
    }
    if (preg_match('/^(.{2,12}?)（([^）]*)）$/u', $txt, $m) && !preg_match('/\p{Han}/u', $m[2]) && isset($dict[$m[1]])) {
        return $dict[$m[1]] . ' (' . $m[2] . ')';
    }
    // 「X — LtBooks」：只翻译页面名，产品名保持统一。
    if (preg_match('/^(.+?)\s+—\s+LtBooks$/u', $txt, $m)) {
        $head = $dict[trim($m[1])] ?? null;
        if ($head !== null) return $head . ' — LtBooks';
    }
    // 「会计 · accountant」面包屑：首段翻译，用户名保留
    if (preg_match('/^(.+?)\s+·\s+(?!LEDU)(.+)$/u', $txt, $m) && isset($dict[trim($m[1])])) {
        return $dict[trim($m[1])] . ' · ' . $m[2];
    }
    // 「X · LEDU TECH CO., LIMITED · HKD · HKFRS」
    if (preg_match('/^(.+?)\s+·\s+LEDU TECH CO\., LIMITED\s+·/u', $txt, $m)) {
        $head = $dict[trim($m[1])] ?? null;
        if ($head !== null) {
            return preg_replace('/^.+?\s+·\s+/u', $head . ' · ', $txt, 1);
        }
    }
    return null;
}

/** 语言属性，用于 <html lang="...">。 */
function lang_html(): string
{
    return lang_meta()[lang()]['html'];
}

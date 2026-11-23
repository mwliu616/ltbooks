<?php
/*
 * LtBooks — lib/ui.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 视图辅助：格式化、徽章、表格。所有输出统一转义。 */
declare(strict_types=1);

function e(mixed $v): string
{
    return htmlspecialchars((string) $v, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function money(mixed $v, ?string $ccy = null): string
{
    if ($v === null || $v === '') {
        return '—';
    }
    $n = is_numeric($v) ? (float) $v : null;
    if ($n === null || !is_finite($n)) {
        return '—';
    }
    $s = number_format($n, 2, '.', ',');
    return $ccy !== null ? $s . ' ' . e($ccy) : $s;
}

function num(mixed $v): string
{
    if ($v === null || $v === '') {
        return '—';
    }
    return is_numeric($v) ? number_format((float) $v, 0, '.', ',') : '—';
}

function badge(string $status): string
{
    $map = [
        'PASS'   => ['pass', '通过'],
        'REVIEW' => ['review', '待复核'],
        'FAIL'   => ['fail', '未通过'],
    ];
    [$cls, $label] = $map[$status] ?? ['review', $status];
    return '<span class="badge ' . $cls . '">' . e(t($label)) . '</span>';
}

/**
 * 单据状态的唯一翻译表。所有列表、详情、下拉筛选都从这里取，
 * 避免同一个 posted 在 A 页叫「已记账」、B 页叫「已过账」。
 */
function status_label(string $code): string
{
    static $T = [
        'draft'        => ['草稿', '草稿', 'Draft'],
        'posted'       => ['已记账', '已記帳', 'Posted'],
        'void'         => ['已作废', '已作廢', 'Void'],
        'reversed'     => ['已冲销', '已沖銷', 'Reversed'],
        'open'         => ['未结', '未結', 'Open'],
        'closed'       => ['已结', '已結', 'Closed'],
        'active'       => ['启用', '啟用', 'Active'],
        'inactive'     => ['停用', '停用', 'Inactive'],
        'matched'      => ['已匹配', '已匹配', 'Matched'],
        'unmatched'    => ['未匹配', '未匹配', 'Unmatched'],
        'pending'      => ['待复核', '待覆核', 'For review'],
        'approved'     => ['已批准', '已批准', 'Approved'],
        'rejected'     => ['已退回', '已退回', 'Rejected'],
        'locked'       => ['已锁定', '已鎖定', 'Locked'],
        'sent'         => ['已发出', '已發出', 'Sent'],
        'accepted'     => ['已接受', '已接受', 'Accepted'],
        'expired'      => ['已过期', '已過期', 'Expired'],
        'converted'    => ['已转换', '已轉換', 'Converted'],
        'fulfilled'    => ['已履行', '已履行', 'Fulfilled'],
        'partial'      => ['部分履行', '部分履行', 'Partially fulfilled'],
        'unfulfilled'  => ['未履行', '未履行', 'Not fulfilled'],
        'undetermined' => ['未确定', '未確定', 'Undetermined'],
        'overdue'      => ['逾期', '逾期', 'Overdue'],
        'paid'         => ['已付款', '已付款', 'Paid'],
        'unpaid'       => ['未付款', '未付款', 'Unpaid'],
        'partial_paid' => ['部分付款', '部分付款', 'Partially paid'],
        'ordered'      => ['已下单', '已下單', 'Ordered'],
        'cancelled'    => ['已取消', '已取消', 'Cancelled'],
        'done'         => ['已完成', '已完成', 'Done'],
        'not_started'  => ['未开始', '未開始', 'Not started'],
        'running'      => ['执行中', '執行中', 'Running'],
        'auto'         => ['自动', '自動', 'Auto'],
        'manual'       => ['人工', '人工', 'Manual'],
        'dismissed'    => ['已忽略', '已忽略', 'Dismissed'],
        'resolved'     => ['已处理', '已處理', 'Resolved'],
        'rejected_review' => ['已退回', '已退回', 'Rejected'],
    ];
    $l = function_exists('lang') ? lang() : 'zh_cn';
    $i = ['zh_cn' => 0, 'zh_hk' => 1, 'en' => 2][$l] ?? 0;
    $key = strtolower(trim($code));
    if (isset($T[$key])) { return $T[$key][$i]; }
    // 未知状态码：中文界面不要把英文码直接摆出来
    return $l === 'en' ? $code : $code;
}

/** 状态药丸：颜色按状态族，文字走 status_label()。 */
function status_pill(string $s): string
{
    $cls = match ($s) {
        'posted'   => 'st-posted',
        'draft'    => 'st-draft',
        'void'     => 'st-void',
        'reversed' => 'st-rev',
        'matched'  => 'st-posted',
        'pending'  => 'st-draft',
        'unmatched' => 'st-void',
        default    => 'st-draft',
    };
    return '<span class="pill ' . $cls . '">' . e(status_label($s)) . '</span>';
}

/** 渲染校验横幅（PASS / REVIEW / FAIL）。 */
function banner(string $status, ?string $reason = null, array $checks = []): string
{
    if ($status === '') {
        return '';
    }
    $title = match ($status) {
        'PASS'   => '校验通过，可提交过账确认',
        'REVIEW' => '部分项目需人工确认',
        default  => '校验未通过，不可过账',
    };
    $icon = match ($status) {
        'PASS'   => '✓',
        'REVIEW' => '!',
        default  => '✕',
    };
    $h  = '<div class="banner ' . e($status) . '">';
    $h .= '<span class="banner-icon">' . $icon . '</span><div class="banner-body">';
    $h .= '<div class="banner-title">' . e($title) . '</div>';
    if ($reason !== null && $reason !== '') {
        $h .= '<div class="banner-reason">' . e($reason) . '</div>';
    }
    if ($checks) {
        $h .= '<details class="banner-details"><summary>查看明细（' . count($checks) . ' 项）</summary><ul>';
        foreach ($checks as $c) {
            $h .= '<li><b>' . e($c['step'] ?? '') . '</b> '
                . badge((string) ($c['status'] ?? 'REVIEW')) . ' '
                . e($c['reason'] ?? '') . '</li>';
        }
        $h .= '</ul></details>';
    }
    return $h . '</div></div>';
}

function card(string $title, string $body, string $right = '', bool $pad = true): string
{
    // 列表页的分页统一放在卡片底部：从工具条里抽出来，附在表体之后。
    $pager = '';
    $pos = strpos($right, '<div class="pager">');
    if ($pos !== false) {
        $pager = substr($right, $pos);
        $right = substr($right, 0, $pos);
    }
    $h  = '<section class="card">';
    if ($title !== '' || trim($right) !== '') {
        $h .= '<header class="card-head"><h2>' . e($title) . '</h2><div class="card-head-side">' . $right . '</div></header>';
    }
    $h .= '<div class="card-body' . ($pad ? '' : ' pad0') . '">' . $body . '</div>'
        . $pager . '</section>';
    return $h;
}

function empty_state(string $text): string
{
    return '<div class="empty">' . e($text) . '</div>';
}

function errbox(string $msg, string $title = '未能完成'): string
{
    return '<div class="errbox"><b>' . e($title) . '</b><div>' . e($msg) . '</div></div>';
}

function draft_delete_form(string $kind, int $id, string $back, string $label = '删除'): string
{
    $allowed = ['quote', 'invoice', 'bill', 'expense', 'credit_note', 'order',
                'payment_received', 'payment_made', 'journal'];
    if ($id <= 0 || !in_array($kind, $allowed, true)) {
        return '';
    }
    return '<form method="post" class="inline-form">'
        . csrf_field()
        . '<input type="hidden" name="action" value="delete_draft">'
        . '<input type="hidden" name="kind" value="' . e($kind) . '">'
        . '<input type="hidden" name="id" value="' . e((string) $id) . '">'
        . '<input type="hidden" name="back" value="' . e($back) . '">'
        . '<button type="submit" class="btn sm"'
        . ' data-confirm="确定删除这张草稿单据？"'
        . ' data-confirm-note="删除后无法恢复；审计日志会保留本次操作。"'
        . ' data-confirm-ok="删除">' . e($label) . '</button></form>';
}


/** 可用币种：以银行账户与汇率为准，避免页面写死。单次请求内缓存。 */
function currencies(): array
{
    static $list = null;
    if ($list !== null) {
        return $list;
    }
    $r = api_get('/currencies');
    $list = ($r['ok'] && !empty($r['data']['currencies'])) ? $r['data']['currencies'] : ['HKD'];
    return $list;
}

/** 渲染币种下拉选项。 */
function currency_options(?string $selected = null): string
{
    $list = currencies();
    // 未指定时默认选中功能货币（港币），不依赖「排在第一位」这种隐式约定
    if ($selected === null) {
        $selected = base_currency();
    }
    $out = '';
    foreach ($list as $c) {
        $sel = strtoupper((string) $selected) === strtoupper($c) ? ' selected' : '';
        $out .= '<option value="' . e($c) . '"' . $sel . '>' . e($c) . '</option>';
    }
    return $out;
}

/** 功能货币（本系统为 HKD）。 */
function base_currency(): string
{
    static $base = null;
    if ($base === null) {
        $r = api_get('/currencies');
        $base = ($r['ok'] && !empty($r['data']['base'])) ? $r['data']['base'] : 'HKD';
    }
    return $base;
}


/** 兼容旧调用：报表语言即全站语言。 */
/**
 * 导出 PDF 的语言。
 *
 * PDF 默认英文；用户在页面上另行选择简/繁时才切换，与界面语言互不影响。
 * 选择写入 Cookie（一年），下次进入沿用 —— 与仪表板「显示区间」的行为保持一致。
 */
function report_lang(): string
{
    $allowed = ['en', 'zh_cn', 'zh_hk'];
    if (isset($_GET['pdf_lang'])) {
        $l = (string) $_GET['pdf_lang'];
        $l = in_array($l, $allowed, true) ? $l : 'en';
        // 页面在输出缓冲中渲染，此处 setcookie 仍然有效
        if (!headers_sent()) {
            setcookie('ledu_pdf_lang', $l, [
                'expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax',
            ]);
        }
        return $l;
    }
    $l = (string) ($_COOKIE['ledu_pdf_lang'] ?? 'en');
    return in_array($l, $allowed, true) ? $l : 'en';
}


/** PDF 语言选择器：英文（默认）/ 简体 / 繁体。 */
function pdf_lang_switcher(array $extra = [], bool $showLabel = true): string
{
    $cur = report_lang();
    $ui = lang();
    $labels = $ui === 'en'
        ? ['en' => 'EN', 'zh_cn' => 'SC', 'zh_hk' => 'TC']
        : ['en' => 'EN', 'zh_cn' => '简', 'zh_hk' => '繁'];
    $titles = [
        'zh_cn' => ['en' => 'English', 'zh_cn' => '简体中文', 'zh_hk' => '繁体中文'],
        'zh_hk' => ['en' => 'English', 'zh_cn' => '簡體中文', 'zh_hk' => '繁體中文'],
        'en'    => ['en' => 'English', 'zh_cn' => 'Simplified Chinese', 'zh_hk' => 'Traditional Chinese'],
    ][$ui] ?? ['en' => 'English', 'zh_cn' => '简体中文', 'zh_hk' => '繁體中文'];
    $out = '<span class="pdf-lang" role="group" aria-label="PDF language">'
         . ($showLabel ? '<span class="pdf-lang-lbl">PDF</span>' : '');
    foreach ($labels as $k => $lab) {
        $q = array_merge($extra, ['pdf_lang' => $k]);
        $cls = $k === $cur ? 'pdf-lang-item active' : 'pdf-lang-item';
        $out .= '<a class="' . $cls . '" href="?' . http_build_query($q) . '"'
              . ' title="' . e($titles[$k]) . '" hreflang="' . $k . '">' . $lab . '</a>';
    }
    return $out . '</span>';
}

/** 全站语言切换器（顶栏）。保留当前查询参数。 */
function lang_switcher(): string
{
    $cur = lang();
    $meta = lang_meta();
    // 标签与语言名跟着界面语言走：英文界面用 SC / TC / EN，
    // 简中界面不出现繁体字，繁中界面不出现简体字。
    $labels = $cur === 'en'
        ? ['zh_cn' => 'SC', 'zh_hk' => 'TC', 'en' => 'EN']
        : ['zh_cn' => '简', 'zh_hk' => '繁', 'en' => 'EN'];
    $names = [
        'zh_cn' => ['zh_cn' => '简体中文', 'zh_hk' => '繁体中文', 'en' => 'English'],
        'zh_hk' => ['zh_cn' => '簡體中文', 'zh_hk' => '繁體中文', 'en' => 'English'],
        'en'    => ['zh_cn' => 'Simplified Chinese', 'zh_hk' => 'Traditional Chinese', 'en' => 'English'],
    ];
    $items = [];
    foreach ($meta as $code => $m) {
        $items[] = [$code, $labels[$code] ?? $m['label'], $names[$cur][$code] ?? $m['name']];
    }
    $q = $_GET;
    $out = '<div class="tabs" role="group" aria-label="报表语言">';
    foreach ($items as [$code, $label, $name]) {
        $q['lang'] = $code;
        $href = '?' . http_build_query($q);
        $cls = $cur === $code ? 'tab active' : 'tab';
        $out .= '<a class="' . $cls . '" href="' . e($href) . '" hreflang="' . e($code)
              . '" title="' . e($name) . '">' . e($label) . '</a>';
    }
    return $out . '</div>';
}


/** 预览下一个文件编号（LEDU + 年月日 + 当日第几份）。 */
/**
 * 预览下一个单据编号。
 *
 * 格式：公司缩写-功能缩写-YYYYMMDD-当日份数，例 LEDU-INV-20261108-001
 * $kind 取 invoice / bill / expense / receipt / payment / journal / contract
 */
function next_doc_no(string $date, string $kind = 'invoice'): string
{
    $r = api_get('/numbering/peek?date=' . urlencode($date) . '&kind=' . urlencode($kind));
    return ($r['ok'] && !empty($r['data']['number'])) ? $r['data']['number'] : '';
}

/** 只读编号展示（自动编号，不给改）。 */
function doc_no_field(string $label, string $number, string $name = ''): string
{
    // 不传 name：只读展示；传 name：可自定义，附「恢复自动」按钮
    if ($name === '') {
        return '<div class="field"><label class="f">' . e(t($label)) . '</label>'
             . '<input type="text" value="' . e($number) . '" readonly'
             . ' style="font-family:var(--mono);background:var(--c-surface-alt)">'
             . '<div class="hint">' . e(t('公司缩写-功能缩写-日期-份数，保存时按当日顺序占用')) . '</div></div>';
    }
    $cur = (string) ($_POST[$name] ?? '');
    $val = $cur !== '' ? $cur : $number;
    $id  = 'docno-' . $name;
    return '<div class="field span-full"><label class="f">' . e(t($label)) . '</label>'
         . '<div style="display:flex;gap:6px">'
         . '<input type="text" name="' . e($name) . '" id="' . e($id) . '"'
         . ' value="' . e($val) . '" data-auto="' . e($number) . '"'
         . ' style="font-family:var(--mono);font-size:12.5px;flex:1;min-width:0" autocomplete="off">'
         . '<button type="button" class="btn sm" title="恢复自动编号"'
         . ' onclick="var el=document.getElementById(\'' . e($id) . '\');'
         . 'el.value=el.dataset.auto;">自动</button>'
         . '</div>'
         . '<div class="hint">默认按 公司缩写-功能缩写-日期-份数 生成，可改成自己的编号</div></div>';
}


/**
 * 版权行。公司为法定实体，与产品名分开表述。
 */
function copyright_line(string $sep = ' · '): string
{
    $year = date('Y');
    $l = function_exists('lang') ? lang() : 'zh_cn';
    // 本系统以 MIT 许可证开源发布：版权归 LEDU TECH CO., LIMITED，同时授予 MIT 权利
    $rights = [
        'zh_cn' => '依 MIT 许可证发布',
        'zh_hk' => '依 MIT 許可證發布',
        'en'    => 'Released under the MIT License',
    ][$l] ?? 'Released under the MIT License';
    return '© ' . $year . ' LEDU TECH CO., LIMITED' . $sep . $rights;
}

/** 带链接的版权区块（页脚用）。 */
function copyright_footer(): string
{
    $l = function_exists('lang') ? lang() : 'zh_cn';
    $more = [
        'zh_cn' => '查看许可证',
        'zh_hk' => '查看許可證',
        'en'    => 'View license',
    ][$l] ?? 'View license';
    return '<div class="copyright">' . e(copyright_line()) . ' · '
         . '<a href="?p=license">' . e($more) . '</a></div>';
}

/** 版权区块（页脚用）。 */
function copyright_block(): string
{
    return '<div class="copyright">' . e(copyright_line()) . '</div>';
}


/** 三语科目名映射（按语言取），单次请求内缓存。 */
function account_names_for_lang(): array
{
    static $cache = null;
    if ($cache !== null) return $cache;
    $r = api_get('/accounts/names');
    $all = $r['ok'] ? ($r['data']['names'] ?? []) : [];
    $l = lang();
    $out = [];
    foreach ($all as $code => $names) {
        $out[$code] = $names[$l] ?: ($names['zh_cn'] ?? '');
    }
    return $cache = $out;
}


/** 取当前语言的科目名；无映射时回退原文。 */
function acc_name(string $code, string $fallback = ''): string
{
    if ($code === '') return $fallback;
    $m = account_names_for_lang();
    return $m[$code] ?? $fallback;
}


/** 科目类别代码（asset/cogs/...）→ 当前语言名称。 */
function cat_name(string $c): string
{
    $m = ['asset' => '资产', 'liability' => '负债', 'equity' => '权益',
          'revenue' => '收入', 'cogs' => '销售成本', 'expense' => '费用'];
    return t($m[$c] ?? $c);
}


/** 分录来源代码（invoice/bill/...）→ 当前语言名称。 */
function source_label(string $code): string
{
    $m = ['invoice' => '发票', 'bill' => '账单', 'manual' => '手工录入',
          'payment_received' => '收款', 'payment_made' => '付款',
          'opening' => '期初', 'expense' => '费用', 'transfer' => '转账'];
    return isset($m[$code]) ? t($m[$code]) : $code;
}


/**
 * 直接输出文件给浏览器并终止。
 *
 * 页面处理程序是在 index.php 的输出缓冲里执行的（此时页头 HTML 已生成），
 * 若不清空缓冲，下载会变成「HTML + 文件内容」。这里先丢弃缓冲再发文件。
 */
function send_file(string $path, string $downloadName): void
{
    if (!is_file($path)) {
        while (ob_get_level() > 0) { ob_end_clean(); }
        http_response_code(404);
        exit('文件不存在');
    }
    while (ob_get_level() > 0) { ob_end_clean(); }
    header('Content-Type: application/octet-stream');
    header('Content-Disposition: attachment; filename="' . basename($downloadName) . '"');
    header('Content-Length: ' . filesize($path));
    header('X-Content-Type-Options: nosniff');
    readfile($path);
    exit;
}


/**
 * 报表项目代码的中文/英文显示名。
 *
 * fs_line_item 是数据库字段名，直接显示给用户是泄露内部术语，
 * 这里统一转成可读的报表行名称。
 */
function fs_line_label(string $code): string
{
    $m = [
        'CASH' => '库存现金', 'CASH_EQUIVALENTS' => '银行存款', 'TRADE_RECEIVABLES' => '应收账款',
        'OTHER_RECEIVABLES' => '其他应收款', 'PREPAYMENTS' => '预付款项',
        'CONTRACT_ASSETS' => '合同资产', 'TAX_ASSETS' => '税务资产',
        'CURRENT_ASSETS' => '流动资产', 'NON_CURRENT_ASSETS' => '非流动资产', 'ASSETS' => '资产',
        'TRADE_PAYABLES' => '应付账款', 'OTHER_PAYABLES' => '其他应付款',
        'ACCRUALS' => '应计费用', 'CONTRACT_LIABILITIES' => '合同负债',
        'TAX_LIABILITIES' => '税务负债', 'SHORT_TERM_BORROWINGS' => '短期借款',
        'LEASE_LIABILITIES_CURRENT' => '租赁负债（流动）', 'CURRENT_LIABILITIES' => '流动负债',
        'NON_CURRENT_LIABILITIES' => '非流动负债', 'LIABILITIES' => '负债',
        'SHARE_CAPITAL' => '股本', 'SHARE_PREMIUM' => '股份溢价',
        'RETAINED_EARNINGS' => '保留溢利', 'CURRENT_YEAR_PL' => '本期损益',
        'DIVIDENDS_DECLARED' => '已宣派股息', 'REVALUATION_RESERVE' => '重估储备',
        'FX_TRANSLATION_RESERVE' => '汇兑折算储备', 'EQUITY' => '权益',
        'REVENUE' => '收入', 'OTHER_INCOME' => '其他收入', 'COST_OF_SALES' => '销售成本',
        'STAFF_COSTS' => '员工成本', 'OCCUPANCY' => '租金及差饷',
        'PROFESSIONAL_FEES' => '专业费用', 'BANK_CHARGES' => '银行手续费',
        'ENTERTAINMENT' => '业务招待', 'TRAVEL' => '差旅费',
        'OPERATING_EXPENSES' => '经营费用', 'ADMIN_EXPENSES' => '行政费用',
        'DEPRECIATION' => '折旧', 'AMORTISATION' => '摊销',
        'FINANCE_COSTS' => '财务费用', 'TAX_EXPENSE' => '所得税费用',
        'FX_GAIN_LOSS' => '汇兑损益', 'CREDIT_CARD' => '信用卡欠款',
    ];
    if ($code === '') return '';
    $name = $m[$code] ?? $code;
    // 英文界面走词典
    return function_exists('t') ? t($name) : $name;
}


/**
 * 公司 Logo 的网页地址。
 *
 * 用户在公司信息页上传过自定义 Logo 时用自定义版，否则回退到内置 Logo。
 * 传入尺寸档位：192 / 64。
 */
function company_logo(int $size = 192): string
{
    $custom = __DIR__ . '/../assets/logo-custom-' . $size . '.png';
    if (is_file($custom)) {
        return 'assets/logo-custom-' . $size . '.png';
    }
    return $size >= 100 ? 'assets/logo-192.png' : 'assets/logo-64.png';
}


/**
 * 科目下拉「搜不到就建」：处理新建请求。
 *
 * 在页面最前面调用；成功后跳回本页并带上 ?newacc=编码，
 * 由页面把该科目设为选中项。变更写入审计日志。
 */
function handle_inline_account_create(array $allowedCats, string $backPage, array $user): ?string
{
    if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !csrf_ok()
        || ($_POST['action'] ?? '') !== 'create_account_inline') {
        return null;
    }
    $code = trim((string) ($_POST['newCode'] ?? ''));
    $name = trim((string) ($_POST['newName'] ?? ''));
    $cat  = (string) ($_POST['newCategory'] ?? ($allowedCats[0] ?? 'expense'));
    if (!preg_match('/^[0-9]{3,6}$/', $code)) {
        return '科目编码须为 3–6 位数字';
    }
    if ($name === '') {
        return '请填写科目名称';
    }
    if (!in_array($cat, $allowedCats, true)) {
        return '科目分类不合法';
    }
    $normal = in_array($cat, ['equity', 'revenue', 'liability'], true) ? 'credit' : 'debit';
    $res = api_post('/accounts', [
        'code' => $code, 'name' => $name, 'category' => $cat,
        'normalBalance' => $normal, 'actor' => (string) ($user['username'] ?? 'system'),
    ]);
    if (!$res['ok']) {
        return (string) $res['error'];
    }
    header('Location: ?p=' . urlencode($backPage) . '&newacc=' . urlencode($code));
    exit;
}


/**
 * 科目下拉「搜不到就建」：渲染新建面板。
 *
 * 页面里任何带 data-allow-create 的 <select> 触发 ssel:create 后，
 * 这个面板会展开并把搜索词填进去。
 */
function inline_account_create_panel(array $cats, string $newAcc = ''): string
{
    $label = '科目';
    $catLabel = ['asset' => '资产', 'liability' => '负债', 'equity' => '权益',
                 'revenue' => '收入', 'cogs' => '销售成本', 'expense' => '费用'];
    $opts = '';
    foreach ($cats as $c) {
        $opts .= '<option value="' . e($c) . '">' . e($catLabel[$c] ?? $c) . '</option>';
    }
    $catsJson = json_encode(array_values($cats), JSON_UNESCAPED_UNICODE);
    $h = '<div id="accCreatePanel" class="card" style="display:none;margin-top:14px">'
       . '<header class="card-head"><h2>＋ 新建会计科目</h2></header><div class="card-body">'
       . '<form method="post">' . csrf_field()
       . '<input type="hidden" name="action" value="create_account_inline">'
       . '<div class="grid">'
       . '<div class="field"><label class="f">科目编码 *</label>'
       . '<input type="text" name="newCode" id="newAccCode" pattern="[0-9]{3,6}" required placeholder="如 6610"></div>'
       . '<div class="field"><label class="f">科目名称 *</label>'
       . '<input type="text" name="newName" id="newAccName" required placeholder="如 域名与网络费"></div>'
       . '<div class="field"><label class="f">分类</label>'
       . '<select name="newCategory" id="newAccCat">' . $opts . '</select></div>'
       . '</div>'
       . '<div class="toolbar" style="margin-top:12px;margin-bottom:0">'
       . '<button class="btn primary">建立' . $label . '并返回</button>'
       . '<button type="button" class="btn" onclick="document.getElementById(\'accCreatePanel\').style.display=\'none\'">取消</button>'
       . '<span class="hint">新建后会自动选中该科目；变更写入审计日志</span>'
       . '</div></form></div></div>';
    $h .= '<script>(function(){'
        . 'var panel=document.getElementById("accCreatePanel");if(!panel)return;'
        . 'var cats=' . $catsJson . ';'
        . 'document.addEventListener("ssel:create",function(ev){'
        . '  var q=(ev.detail&&ev.detail.query)||"";'
        . '  panel.style.display="";'
        . '  var codeEl=document.getElementById("newAccCode");'
        . '  var nameEl=document.getElementById("newAccName");'
        . '  var catEl=document.getElementById("newAccCat");'
        . '  if(/^[0-9]{3,6}$/.test(q)){codeEl.value=q;nameEl.focus();}else{nameEl.value=q;codeEl.focus();}'
        . '  if(catEl&&q&&/费|租|薪|佣金|差旅|广告/.test(q)&&cats.indexOf("expense")>-1)catEl.value="expense";'
        . '  panel.scrollIntoView({block:"center"});'
        . '});';
    if ($newAcc !== '') {
        $h .= 'var sels=document.querySelectorAll("select[data-allow-create]");'
            . 'for(var i=0;i<sels.length;i++){var s=sels[i];'
            . 'var hit=Array.prototype.some.call(s.options,function(o){return o.value==="' . e($newAcc) . '";});'
            . 'if(hit&&!s.value){s.value="' . e($newAcc) . '";s.dispatchEvent(new Event("change",{bubbles:true}));}else if(hit&&s.value==="' . e($newAcc) . '"){s.dispatchEvent(new Event("change",{bubbles:true}));}}';
    }
    return $h . '})();</script>';
}


/**
 * 列表分页控件。
 *
 * 两组各自不折行：左组切换每页条数，右组翻页。
 * $params 为当前页面的筛选参数（不含 page / per），会带进每个链接。
 */
function pager_html(int $page, int $per, int $total, array $params = [], string $pageKey = '', string $prefix = ''): string
{
    $qs = function (array $extra) use ($params): string {
        $p = array_merge($params, $extra);
        return http_build_query(array_filter($p, fn($v) => $v !== null && $v !== ''));
    };
    $pageCount = $per === 0 ? 1 : max(1, (int) ceil($total / max(1, $per)));
    $h = '<div class="pager">';

    // 左组：条数
    $h .= '<div class="pager-group">'
        . '<span class="hint" style="white-space:nowrap">'
        . e(str_replace('{n}', (string) num($total), t('共 {n} 条'))) . '</span>'
        . '<span class="pager-sep"></span>';
    foreach ([10, 25, 50, 100, 0] as $opt) {
        $h .= '<a class="pager-btn' . ($per === $opt ? ' is-cur' : '') . '" href="?'
            . e($qs([$prefix . 'per' => $opt, $prefix . 'page' => null])) . '">' . ($opt === 0 ? e(t('全部')) : (string) $opt) . '</a>';
    }
    $h .= '</div>';

    // 右组：翻页
    if ($per !== 0 && $pageCount > 1) {
        $mk = fn(int $p_, string $txt) => '<a class="pager-btn" href="?'
            . e($qs([$prefix . 'per' => $per, $prefix . 'page' => $p_])) . '">' . $txt . '</a>';
        $h .= '<div class="pager-group"><span class="pager-sep"></span>'
            . ($page > 1 ? $mk($page - 1, '‹ ' . e(t('上一页'))) : '<span class="pager-btn is-off">‹ ' . e(t('上一页')) . '</span>');
        $from = max(1, $page - 2); $to = min($pageCount, $from + 4); $from = max(1, $to - 4);
        for ($i = $from; $i <= $to; $i++) {
            $h .= $i === $page ? '<span class="pager-btn is-cur">' . $i . '</span>' : $mk($i, (string) $i);
        }
        $h .= ($page < $pageCount ? $mk($page + 1, e(t('下一页')) . ' ›') : '<span class="pager-btn is-off">' . e(t('下一页')) . ' ›</span>')
            . '<span class="hint" style="white-space:nowrap">'
            . e(str_replace(['{a}', '{b}'], [(string) $page, (string) $pageCount], t('第 {a} / {b} 页')))
            . '</span></div>';
    }
    return $h . '</div>';
}


/**
 * 读分页参数：cookie 记忆 + 自定义值夹取。
 * 返回 [$page, $per]。
 */
function pager_state(string $cookieKey, int $default = 25, int $max = 500, string $prefix = ''): array
{
    $allowed = [10, 25, 50, 100];
    $pk = $prefix . 'per';
    $gk = $prefix . 'page';
    $per = (int) ($_GET[$pk] ?? ((int) ($_COOKIE[$cookieKey] ?? 0) ?: $default));
    if ($per !== 0 && !in_array($per, $allowed, true)) {
        $per = max(5, min($max, $per));
    }
    if (isset($_GET[$pk])) {
        setcookie($cookieKey, (string) $per, time() + 31536000, '/', '', true, true);
    }
    return [max(1, (int) ($_GET[$gk] ?? 1)), $per];
}


/**
 * 往来单位（客户 / 供应商）下拉「搜不到就建」：处理新建请求。
 */
function handle_inline_party_create(string $kind, string $backPage, array $user): ?string
{
    if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !csrf_ok()
        || ($_POST['action'] ?? '') !== 'create_party_inline') {
        return null;
    }
    /* 允许从前端动态传入 kind（如贷记单按类型切换客户/供应商） */
    $kind = (string) ($_POST['partyKind'] ?? $kind);
    $kind = $kind === 'vendor' ? 'vendor' : 'customer';
    $name = trim((string) ($_POST['newPartyName'] ?? ''));
    if ($name === '') {
        return ($kind === 'vendor' ? '供应商' : '客户') . '名称不能为空';
    }
    $base = $kind === 'vendor' ? '/vendors' : '/customers';
    $list = api_get($base);
    $n = $list['ok'] ? count($kind === 'vendor' ? ($list['data']['vendors'] ?? []) : ($list['data']['customers'] ?? [])) : 0;
    $prefix = $kind === 'vendor' ? 'V-' : 'C-';
    $res = api_post($base, [
        'vendorCode'   => $kind === 'vendor' ? $prefix . str_pad((string) ($n + 1), 4, '0', STR_PAD_LEFT) : null,
        'customerCode' => $kind === 'customer' ? $prefix . str_pad((string) ($n + 1), 4, '0', STR_PAD_LEFT) : null,
        'vendorName'   => $kind === 'vendor' ? $name : null,
        'customerName' => $kind === 'customer' ? $name : null,
        'defaultCurrency' => (string) ($_POST['newPartyCurrency'] ?? 'HKD'),
        'paymentTermsDays' => 30,
        'email' => trim((string) ($_POST['newPartyEmail'] ?? '')),
        'actor' => (string) ($user['username'] ?? 'system'),
    ]);
    if (!$res['ok']) {
        return (string) $res['error'];
    }
    $_SESSION['party_flash'] = ($kind === 'vendor' ? '供应商' : '客户') . '「' . $name . '」已建档';
    header('Location: ?p=' . urlencode($backPage) . '&newparty=' . urlencode($name));
    exit;
}


/** 往来单位下拉「搜不到就建」：渲染新建面板。 */
function inline_party_create_panel(string $kind, string $defaultCurrency = 'HKD'): string
{
    $kind = $kind === 'vendor' ? 'vendor' : 'customer';
    $label = $kind === 'vendor' ? '供应商' : '客户';
    $h = '<div id="partyCreatePanel" class="card" style="display:none;margin-top:14px">'
       . '<header class="card-head"><h2 id="partyCreateTitle">＋ 新建' . $label . '</h2></header><div class="card-body">'
       . '<form method="post">' . csrf_field()
       . '<input type="hidden" name="action" value="create_party_inline">'
       . '<input type="hidden" name="partyKind" id="partyCreateKind" value="' . $kind . '">'
       . '<div class="grid">'
       . '<div class="field"><label class="f">' . $label . '名称 *</label>'
       . '<input type="text" name="newPartyName" id="newPartyName" required></div>'
       . '<div class="field"><label class="f">默认币种</label>'
       . '<input type="text" name="newPartyCurrency" value="' . e($defaultCurrency) . '" style="width:100px"></div>'
       . '<div class="field"><label class="f">邮箱</label>'
       . '<input type="text" name="newPartyEmail" placeholder="可空"></div>'
       . '</div>'
       . '<div class="toolbar" style="margin-top:12px;margin-bottom:0">'
       . '<button class="btn primary">建立' . $label . '并返回</button>'
       . '<button type="button" class="btn" onclick="document.getElementById(\'partyCreatePanel\').style.display=\'none\'">取消</button>'
       . '<span class="hint">新建后会自动选中；变更写入审计日志</span>'
       . '</div></form></div></div>';
    $h .= '<script>(function(){'
        . 'var panel=document.getElementById("partyCreatePanel");if(!panel)return;'
        . 'document.addEventListener("ssel:create",function(ev){'
        . '  var q=(ev.detail&&ev.detail.query)||"";'
        . '  panel.style.display="";'
        . '  document.getElementById("newPartyName").value=q;'
        . '  panel.scrollIntoView({block:"center"});'
        . '  document.getElementById("newPartyName").focus();'
        . '});})();</script>';
    return $h;
}


/**
 * 详情页信息栅格：标签在上、值在下，等宽分列。
 * 用法：echo kv_grid([['客户', e($x)], ['日期', $d], ...]);
 * 某一项传 ['标签', '值', 'wide'] 可跨整行。
 */
function kv_grid(array $pairs): string
{
    $h = '<div class="kvg">';
    foreach ($pairs as $p) {
        if ($p === '---') { $h .= '<div class="kvg-sep"></div>'; continue; }
        $k = (string) ($p[0] ?? '');
        $v = (string) ($p[1] ?? '');
        $cls = 'kvg-item' . (($p[2] ?? '') === 'wide' ? ' kvg-wide' : '');
        $vcls = 'kvg-v' . (($p[2] ?? '') === 'mono' ? ' mono' : '');
        $h .= '<div class="' . $cls . '"><span class="kvg-k">' . e(t($k)) . '</span>'
            . '<span class="' . $vcls . '">' . ($v === '' ? '—' : $v) . '</span></div>';
    }
    return $h . '</div>';
}

/**
 * 使用模式。登录时选，之后随时可在顶栏切换。
 *
 * ai     —— 进来就是指令台：一句话说清要做什么，左侧功能条默认收起；
 * manual —— 进来是「今天」，左侧功能条全部展开，自己点。
 *
 * 两种模式只是入口与界面密度不同，权限、复核、审计、守门人完全一样：
 * 没有任何智能体能记账，五件危险动作照旧弹窗确认。
 */
function ui_mode(): string
{
    static $cached = null;
    if ($cached !== null) {
        return $cached;
    }
    $raw = $_SESSION['mode'] ?? ($_COOKIE['ledu_mode'] ?? 'ai');
    $cached = $raw === 'manual' ? 'manual' : 'ai';
    return $cached;
}

/** 该模式的首页。 */
function ui_mode_home(?string $mode = null): string
{
    // AI 模式：落地在指令台，一句话说清要做什么；
    // 人工模式：落地在「今天」，先看见账再自己点。
    return ($mode ?? ui_mode()) === 'ai' ? 'command' : 'today';
}


/**
 * 附件上传区（每类单据都可挂附件）。
 * 表单里放这个，提交时调 doc_files_save() 把文件挂到新建的单据上。
 */
function attach_dropzone(string $name = 'attach', string $title = '把单据拖到这里',
                          string $hint = '或点击选择文件 · 单个不超过 20MB'): string
{
    $id = $name . 'Input';
    return '<section class="card"><div class="card-body">'
        . '<label class="dropzone" for="' . e($id) . '">'
        . '<input type="file" id="' . e($id) . '" name="' . e($name) . '[]" multiple '
        . 'accept=".pdf,.png,.jpg,.jpeg,.xlsx,.csv,.doc,.docx" '
        . 'style="position:absolute;width:1px;height:1px;opacity:0">'
        . '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        . 'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        . '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5-5 5 5"/>'
        . '<path d="M12 5v12"/></svg>'
        . '<span class="dz-title">' . e($title) . '</span>'
        . '<span class="hint">' . e($hint) . '</span></label>'
        . '<div class="dz-list" id="' . e($id) . 'List"></div>'
        . '<script>(function(){var i=document.getElementById("' . e($id) . '"),'
        . 'l=document.getElementById("' . e($id) . 'List");if(!i||!l)return;'
        . 'function r(){l.innerHTML="";Array.prototype.forEach.call(i.files||[],function(f){'
        . 'var d=document.createElement("div");d.className="dz-item";'
        . 'var n=document.createElement("span");n.className="dz-name";n.textContent=f.name;'
        . 'var s=document.createElement("span");s.className="hint";'
        . 's.textContent=(f.size/1024).toFixed(0)+" KB";'
        . 'd.appendChild(n);d.appendChild(s);l.appendChild(d);});}'
        . 'i.addEventListener("change",r);var z=i.closest(".dropzone");'
        . '["dragenter","dragover"].forEach(function(e){z.addEventListener(e,function(ev){'
        . 'ev.preventDefault();z.classList.add("over");});});'
        . '["dragleave","drop"].forEach(function(e){z.addEventListener(e,function(ev){'
        . 'ev.preventDefault();z.classList.remove("over");});});'
        . 'z.addEventListener("drop",function(ev){if(ev.dataTransfer&&ev.dataTransfer.files.length){'
        . 'i.files=ev.dataTransfer.files;r();}});})();</script>'
        . '</div></section>';
}

/** 把表单里带的附件挂到刚建好的单据上。$docType 见 api 的 DOC_TYPES。 */
function doc_files_save(string $docType, int $docId, array $files, string $actor): int
{
    if ($docId <= 0 || empty($files['name'][0])) {
        return 0;
    }
    $saved = 0;
    foreach ((array) $files['name'] as $i => $orig) {
        $tmp = (string) ($files['tmp_name'][$i] ?? '');
        if ($tmp === '' || (int) ($files['error'][$i] ?? 1) !== UPLOAD_ERR_OK) { continue; }
        if ((int) ($files['size'][$i] ?? 0) > 20 * 1024 * 1024) { continue; }
        $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', basename((string) $orig));
        $dest = UPLOAD_DIR . '/' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
        if (!@move_uploaded_file($tmp, $dest)) { continue; }
        @chmod($dest, 0640);
        $r = api_post('/doc-files', [
            'docType' => $docType,
            'docId' => $docId,
            'fileName' => (string) $orig,
            'fileType' => strtolower(pathinfo($safe, PATHINFO_EXTENSION)) ?: 'other',
            'fileSize' => (int) filesize($dest),
            'sha256' => (string) hash_file('sha256', $dest),
            'storagePath' => $dest,
            'actor' => $actor,
        ]);
        if ($r['ok']) { $saved++; }
    }
    return $saved;
}


/**
 * 导出菜单：一个按钮，下拉里选简中 / 繁中 / 英文。
 * PDF 导出采用「一个按钮 + 语言/模板选择」，页面上不摆多个并列按钮。
 */
function export_menu(array $items, string $label = '导出 PDF', string $cls = 'btn primary'): string
{
    if (!$items) { return ''; }
    if (count($items) === 1) {
        $href = (string) ($items[0]['href'] ?? '');
        return '<a class="' . e($cls) . '" target="_blank" href="' . e($href) . '">'
             . e($label) . '</a>';
    }
    $h = '<details class="exp-menu"><summary class="' . e($cls) . '">' . e($label)
       . ' <span class="exp-caret" aria-hidden="true">▾</span></summary><div class="exp-list">';
    foreach ($items as $it) {
        $h .= '<a target="_blank" href="' . e((string) ($it['href'] ?? '')) . '">'
            . '<span>' . e((string) ($it['label'] ?? '')) . '</span>'
            . '<span class="exp-desc">' . e((string) ($it['desc'] ?? '')) . '</span></a>';
    }
    return $h . '</div></details>';
}

/** 凭证打印的三语下拉：简中 / 繁中 / English（直接指向 voucher.php） */
function voucher_menu(array $query, string $label, string $cls = 'btn sm'): string
{
    $L = function_exists('lang') ? lang() : 'zh_cn';
    $NAMES = [
        'zh_cn' => ['zh_cn' => '简体中文', 'zh_hk' => '簡體中文', 'en' => 'Simplified Chinese'],
        'zh_hk' => ['zh_cn' => '繁体中文', 'zh_hk' => '繁體中文', 'en' => 'Traditional Chinese'],
        'en'    => ['zh_cn' => 'English',  'zh_hk' => 'English', 'en' => 'English'],
    ];
    $DESCS = [
        'zh_cn' => ['zh_cn' => '中文凭证', 'zh_hk' => '中文憑證', 'en' => 'Chinese voucher'],
        'zh_hk' => ['zh_cn' => '繁体凭证', 'zh_hk' => '繁體憑證', 'en' => 'Traditional Chinese voucher'],
        'en'    => ['zh_cn' => '英文凭证', 'zh_hk' => '英文憑證', 'en' => 'English voucher'],
    ];
    $items = [];
    foreach (['zh_cn', 'zh_hk', 'en'] as $code) {
        $q = $query; $q['lang'] = $code;
        $items[] = ['label' => $NAMES[$code][$L] ?? $code,
                    'desc'  => $DESCS[$code][$L] ?? '',
                    'href'  => '/pdf/voucher.php?' . http_build_query($q)];
    }
    return export_menu($items, $label, $cls);
}

/** 同一份报表的三种语言导出链接。 */
function export_lang_items(string $path, array $query = []): array
{
    $q = $query;
    $out = [];
    // 语言名与说明跟着界面语言走：英文界面里不该出现「简体中文 / Trad. Chinese (內文與科目名)」
    $L = function_exists('lang') ? lang() : 'zh_cn';
    $NAMES = [
        'zh_cn' => ['zh_cn' => '简体中文', 'zh_hk' => '簡體中文', 'en' => 'Simplified Chinese'],
        'zh_hk' => ['zh_cn' => '繁体中文', 'zh_hk' => '繁體中文', 'en' => 'Traditional Chinese'],
        'en'    => ['zh_cn' => 'English', 'zh_hk' => 'English', 'en' => 'English'],
    ];
    $DESCS = [
        'zh_cn' => ['zh_cn' => '中文（内文与科目名）', 'zh_hk' => '中文（內文與科目名）', 'en' => 'Chinese text and account names'],
        'zh_hk' => ['zh_cn' => '繁体（内文与科目名）', 'zh_hk' => '繁體（內文與科目名）', 'en' => 'Traditional Chinese text and account names'],
        'en'    => ['zh_cn' => '英文（内文与科目名）', 'zh_hk' => '英文（內文與科目名）', 'en' => 'English text and account names'],
    ];
    foreach (['zh_cn', 'zh_hk', 'en'] as $code) {
        $meta = [$NAMES[$code][$L] ?? $NAMES[$code]['zh_cn'], $DESCS[$code][$L] ?? $DESCS[$code]['zh_cn']];
        $q['lang'] = $code;
        // 路径本身可能已经带查询串（/reports/pdf?kind=pnl），再接一个 ? 会变成
        // /reports/pdf?kind=pnl?lang=zh_cn —— kind 被污染，接口报「不支持的报表类型」
        $sep = str_contains($path, '?') ? '&' : '?';
        $out[] = ['label' => $meta[0], 'desc' => $meta[1],
                  'href' => '/pdf/go.php?l=' . $code
                          . '&u=' . rawurlencode($path . $sep . http_build_query($q))];
    }
    return $out;
}


/**
 * 报表期间：预设 + 自定义 + 对比。
 * 返回 ['from','to','preset','compare','label','prevFrom','prevTo']；报表页据此取数。
 * $today 可注入，便于单元测试；不传时取系统当天。
 */
function report_period(?DateTimeImmutable $today = null): array
{
    $today ??= new DateTimeImmutable('today');
    $preset = (string) ($_GET['preset'] ?? ($_COOKIE['ledu_report_preset'] ?? 'fiscal_year'));
    $from = (string) ($_GET['from'] ?? '');
    $to   = (string) ($_GET['to'] ?? '');
    $compare = (string) ($_GET['compare'] ?? ($_COOKIE['ledu_report_compare'] ?? 'none'));

    // 财务年度：按公司设定的年结日推
    $fye = (string) ($_SESSION['company_fye'] ?? '04-30');
    [$m, $d] = array_map('intval', explode('-', $fye) + [0, 0]);
    $end = new DateTimeImmutable(sprintf('%d-%02d-%02d', (int) $today->format('Y'), $m ?: 12, $d ?: 31));
    if ($today > $end) { $end = $end->modify('+1 year'); }
    $start = $end->modify('-1 year')->modify('+1 day');
    $prevEnd = $start->modify('-1 day');
    $prevStart = $prevEnd->modify('-1 year')->modify('+1 day');

    if ($preset === 'custom' && $from !== '' && $to !== '') {
        $f = $from; $t = $to;
    } else {
        switch ($preset) {
            case 'this_month':
                $f = $today->format('Y-m-01'); $t = $today->format('Y-m-t'); break;
            case 'last_month':
                $f = $today->modify('first day of last month')->format('Y-m-d');
                $t = $today->modify('last day of last month')->format('Y-m-d'); break;
            case 'this_quarter':
                $q = (int) ceil((int) $today->format('n') / 3);
                $f = sprintf('%d-%02d-01', (int) $today->format('Y'), ($q - 1) * 3 + 1);
                $t = (new DateTimeImmutable($f))->modify('+2 months')->format('Y-m-t'); break;
            case 'this_year':
                $f = $today->format('Y-01-01'); $t = $today->format('Y-12-31'); break;
            case 'last_year':
                $f = ((int) $today->format('Y') - 1) . '-01-01';
                $t = ((int) $today->format('Y') - 1) . '-12-31'; break;
            case 'prev_fiscal':
                $f = $prevStart->format('Y-m-d'); $t = $prevEnd->format('Y-m-d'); break;
            case 'fiscal_year':
            default:
                $preset = 'fiscal_year';
                $f = $start->format('Y-m-d'); $t = $today->format('Y-m-d'); break;
        }
    }
    // 「本财务年度」一笔分录都没有时，落到账簿最后一笔所在的财务年度，避免打开就是空表
    if ($preset === 'fiscal_year') {
        $__last = (string) (api_get('/journal?limit=1')['data']['entries'][0]['entry_date'] ?? '');
        if ($__last !== '' && $__last < $f) {
            $__a = new DateTimeImmutable($__last);
            $__e = new DateTimeImmutable(sprintf('%d-%02d-%02d', (int) $__a->format('Y'), $m ?: 12, $d ?: 31));
            if ($__a > $__e) { $__e = $__e->modify('+1 year'); }
            $__s = $__e->modify('-1 year')->modify('+1 day');
            $f = $__s->format('Y-m-d');
            $t = $__e->format('Y-m-d');
            $prevEnd = $__s->modify('-1 day');
            $prevStart = $prevEnd->modify('-1 year')->modify('+1 day');
        }
    }
    if (!in_array($compare, ['none', 'prev', 'yoy'], true)) { $compare = 'none'; }
    if (!headers_sent()) {
        setcookie('ledu_report_preset', $preset, ['expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax']);
        setcookie('ledu_report_compare', $compare, ['expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax']);
    }
    $labels = ['this_month' => '本月', 'last_month' => '上月', 'this_quarter' => '本季度',
               'this_year' => '本年度', 'last_year' => '上年度',
               'fiscal_year' => '本财务年度', 'prev_fiscal' => '上一财务年度',
               'custom' => '自定义'];
    return ['from' => $f, 'to' => $t, 'preset' => $preset, 'compare' => $compare,
            'label' => $labels[$preset] ?? '本财务年度',
            'prevFrom' => $prevStart->format('Y-m-d'), 'prevTo' => $prevEnd->format('Y-m-d')];
}

/** 报表期间工具条：预设下拉 + 自定义起止 + 对比 + 刷新。 */
function report_period_bar(array $p): string
{
    $opt = function (string $k, string $label, string $cur): string {
        return '<option value="' . e($k) . '"' . ($cur === $k ? ' selected' : '') . '>' . e($label) . '</option>';
    };
    // 损益表的「对比口径」并进期间条，避免卡片头再出现一套期间控件
    $compare = '';
    if ((string) ($_GET['p'] ?? '') === 'report-pnl') {
        $cmp = (string) ($_GET['compare'] ?? 'fy');
        $compare = '<select name="compare" onchange="this.form.submit()" class="period-compare">'
            . '<option value="fy"' . ($cmp === 'fy' ? ' selected' : '') . '>对比：上一财务年度</option>'
            . '<option value="1"' . ($cmp === '1' ? ' selected' : '') . '>对比：上年同期</option>'
            . '<option value="0"' . ($cmp === '0' ? ' selected' : '') . '>不对比</option>'
            . '</select>';
    }
    $h = '<form method="get" class="period-bar">'
       . '<input type="hidden" name="p" value="' . e((string) ($_GET['p'] ?? '')) . '">'
       . '<select name="preset" onchange="this.form.submit()" class="period-preset">'
       . $opt('fiscal_year', '本财务年度', $p['preset'])
       . $opt('prev_fiscal', '上一财务年度', $p['preset'])
       . $opt('this_month', '本月', $p['preset'])
       . $opt('last_month', '上月', $p['preset'])
       . $opt('this_quarter', '本季度', $p['preset'])
       . $opt('this_year', '本年度', $p['preset'])
       . $opt('last_year', '上年度（日历年）', $p['preset'])
       . $opt('custom', '自定义', $p['preset'])
       . '</select>'
       . $compare
       . '<span class="period-dates" id="periodDates" style="' . ($p['preset'] === 'custom' ? '' : 'display:none') . '">'
       . '<input type="date" name="from" value="' . e($p['from']) . '">'
       . '<span class="hint">至</span>'
       . '<input type="date" name="to" value="' . e($p['to']) . '">'
       . '</span>'
       . '<button class="btn sm">应用</button>'
       . '<span class="period-label">' . e($p['from']) . ' ~ ' . e($p['to'])
       . '<span class="hint" style="margin-left:8px">财务年度按年结日划分</span>'
       . '</span>'
       . '</form>'
       . '<script>(function(){var s=document.querySelector(".period-preset"),d=document.getElementById("periodDates");'
       . 'if(!s||!d)return;s.addEventListener("change",function(){d.style.display=s.value==="custom"?"":"none";'
       . 'if(s.value==="custom"){document.querySelector(".period-bar").submit();}});})();</script>';
    return $h;
}


/**
 * 多报表 × 多语言导出矩阵：一个「导出 ▾」，里面按报表分行，每行三种语言。
 * 比在页面上并排摆四个下拉清爽，也不会每个下拉各弹一次。
 */
function export_matrix(array $items, string $label = '导出', string $cls = 'btn primary'): string
{
    if (!$items) { return ''; }
    $h = '<details class="exp-menu exp-matrix"><summary class="' . e($cls) . '">' . e($label)
       . ' <span class="exp-caret" aria-hidden="true">▾</span></summary><div class="exp-list">';
    // 语言按钮跟随界面语言：英文界面用 SC / TC / EN
    $__labs = lang() === 'en'
        ? ['zh_cn' => 'SC', 'zh_hk' => 'TC', 'en' => 'EN']
        : ['zh_cn' => '简', 'zh_hk' => '繁', 'en' => 'EN'];
    foreach ($items as $it) {
        $h .= '<div class="exp-row"><span class="exp-title">' . e((string) ($it['title'] ?? '')) . '</span>'
            . '<span class="exp-langs">';
        foreach ($it['langs'] as $code => $meta) {
            $q = ($it['query'] ?? []);
            $q['lang'] = $code;
            $p0 = (string) $it['path'];
            $sep = str_contains($p0, '?') ? '&' : '?';
            $href = '/pdf/go.php?l=' . $code . '&u=' . rawurlencode(
                $p0 . $sep . http_build_query($q));
            $h .= '<a class="exp-lang" title="' . e($meta) . '" target="_blank" href="' . e($href) . '">'
                . e($__labs[$code] ?? $code) . '</a>';
        }
        $h .= '</span></div>';
    }
    return $h . '</div></details>';
}

/**
 * 已按月锁定/关闭的期间集合（period => true），页面按需判断能否修改凭证。
 */
function locked_periods(): array
{
    static $cache = null;
    if ($cache !== null) { return $cache; }
    $cache = [];
    $r = api_get('/period-locks');
    foreach (($r['data']['locks'] ?? []) as $lk) {
        if (in_array((string) ($lk['status'] ?? ''), ['locked', 'closed'], true)) {
            $cache[(string) ($lk['period'] ?? '')] = true;
        }
    }
    return $cache;
}

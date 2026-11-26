<?php
/*
 * LtBooks — index.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** Lt-AI-Books Ver 1.1 — PHP 前端入口（服务端渲染、强制登录、三语界面）。 */
declare(strict_types=1);

// 业务时区：香港。数据库时间戳仍存 UTC，但单据日期、编号日期按香港本地日算
date_default_timezone_set('Asia/Hong_Kong');

require __DIR__ . '/lib/api.php';
require __DIR__ . '/lib/ui.php';
require __DIR__ . '/lib/help.php';
require __DIR__ . '/lib/version.php';
require __DIR__ . '/lib/theme.php';
require __DIR__ . '/lib/auth.php';

ini_set('session.use_strict_mode', '1');
ini_set('session.cookie_httponly', '1');
ini_set('session.cookie_secure', '1');
ini_set('session.cookie_samesite', 'Lax');
session_name('ledu_console');
session_start();
require_once __DIR__ . '/lib/i18n.php';

// 语言必须在任何页面逻辑之前确定：登录后各页会立即调用 API，
// 而 API 请求会把当前语言带给后端（科目名等按语言取），晚设置就会拿到旧语言。
if (isset($_GET['lang'])) {
    set_lang((string) $_GET['lang']);
}
ob_start();

$PAGES = [
    'command'      => ['AI 工作台', '识别、分析、建单、报表与导出都在这里完成'],
    'today'        => ['仪表盘', '今天该做什么、有多少钱'],
    'fast-new'     => ['快速建单', '单据'],
    'quotes'       => ['报价单', '销售'],
    'credit-notes' => ['贷记单', '会计'],
    'recurring'    => ['循环交易', '销售'],
    'recurring-invoices' => ['经常性发票', '销售'],
    'recurring-bills'    => ['经常性账单', '采购'],
    'settle'       => ['核销工作台', '会计'],
    'period-close' => ['月结', '会计'],
    'tax'          => ['利得税', '报表'],
    'report-center'=> ['报表中心', '报表'],
    'agents'       => ['智能体管理', '系统'],
    'ai'           => ['AI 工作台', '智能处理'],
    'invoices'     => ['发票', '销售'],
    'invoice-new'  => ['新建发票', '销售'],
    'invoice-view' => ['发票详情', '销售'],
    'doc-view'     => ['单据详情', '单据'],
    'party-view'   => ['往来单位详情', '档案'],
    'ai-close'     => ['月结概览', 'AI'],
    'settings-llm' => ['大模型设置', '系统'],
    'theme'        => ['外观与配色', '系统'],
    'sales-orders'    => ['销售订单', '销售'],
    'purchase-orders' => ['采购订单', '采购'],
    'order-view'      => ['订单详情', '订单'],
    'customers'    => ['客户', '销售'],
    'bills'        => ['账单', '采购'],
    'bill-view'    => ['账单详情', '采购'],
    'expenses'     => ['费用', '采购'],
    'bill-new'     => ['新建账单', '采购'],
    'expense-new'  => ['新建费用', '采购'],
    'vendors'      => ['供应商', '采购'],
    'receipts'     => ['收款', '销售'],
    'payments'     => ['付款', '采购'],
    'payment-view' => ['收付款详情', '采购'],
    'banks'        => ['银行账户', '银行'],
    'bank-transactions' => ['交易记录', '银行'],
    'bank-rules'        => ['银行规则', '银行'],
    'bank-transfer'     => ['转账', '银行'],
    'opening-balances'  => ['期初余额', '会计'],
    'guide'             => ['使用说明', '帮助'],
    'bank-import'  => ['导入月结单', '银行'],
    'reconcile'    => ['对账工作区', '银行'],
    'accounts'     => ['会计科目', '会计'],
    'journal'      => ['日记账', '会计'],
    'journal-view' => ['分录详情', '会计'],
    'journal-new'  => ['手工分录', '会计'],
    'revalue'      => ['期末重估', '会计'],
    'rates'        => ['汇率维护', '会计'],
    'locks'        => ['期间锁定', '会计'],
    'pending'      => ['待复核', '会计'],
    'pending-rec'  => ['复核队列', '会计'],
    'report-tb'    => ['试算表', '报表'],
    'report-account-types' => ['账户类型摘要', '报表'],
    'report-gl-detail'     => ['详细的总分类账', '报表'],
    'report-pnl'   => ['损益及其他全面收益表', '报表'],
    'report-bs'    => ['财务状况表', '报表'],
    'report-cf'    => ['现金流量表', '报表'],
    'report-aging' => ['账龄分析表', '报表'],
    'report-bank'  => ['银行账户余额表', '报表'],
    'report-fx'    => ['汇兑损益表', '报表'],
    'report-tax'   => ['利得税计算表', '报表'],
    'report-statements' => ['财务报表', '报表'],
    'report-ratios' => ['财务比率表', '报表'],
    'report-customer-balance' => ['客户余额表', '报表'],
    'report-vendor-balance' => ['供应商余额表', '报表'],
    'report-gl'    => ['总分类账', '报表'],
    'report-daybook' => ['日记簿', '报表'],
    'report-sales' => ['销售明细表', '报表'],
    'report-purchase' => ['采购明细表', '报表'],
    'audit'        => ['审计探索器', '审计'],

    'license'      => ['开源许可证', '系统'],
    'backup'       => ['备份与恢复', '数据库、上传票据与附件'],
    'email'        => ['邮件', '系统'],
    'company'      => ['公司信息', '系统'],
    'account'      => ['账号', '系统'],
    'search'       => ['搜索', '仪表板'],
];

$NAV = [
    // 一人公司的导航：常用的一层点得到，少用的收进「设置」或报表中心。
    // 原来的「审计探索器」「系统」两组并进「设置」——对一个人来说，
    // 那些是偶尔看一眼的东西，不该天天占着一行。
    '仪表盘' => ['today'],
    // 业务顺序：档案 → 报价/订单 → 发票/账单 → 收付款 → 调整/循环。
    '销售'   => ['customers', 'quotes', 'sales-orders', 'invoices',
                 'receipts', 'credit-notes', 'recurring-invoices'],
    '采购'   => ['vendors', 'purchase-orders', 'bills',
                 'expenses', 'payments', 'recurring-bills'],
    // 银行顺序：账户与规则 → 导入流水 → 核对交易 → 对账 → 调拨。
    '银行'   => ['banks', 'bank-rules', 'bank-import', 'bank-transactions', 'reconcile', 'bank-transfer'],
    // 会计顺序：科目与期初 → 日常分录 → 汇率 → 复核 → 月结。
    '会计'   => ['accounts', 'opening-balances', 'journal-new', 'journal',
                 'rates', 'pending', 'period-close'],
    // 明细报表统一从报表中心进入，避免与左侧逐项菜单形成两套重叠入口。
    '报表'   => ['report-center', 'report-statements', 'tax'],
    '设置'   => ['company', 'account', 'settings-llm', 'theme', 'email', 'backup', 'agents', 'audit', 'guide'],
];

// 这些页面自己渲染页头（需要自定义副标题与操作按钮），入口不再重复渲染
$SELF_HEAD = ['command', 'today', 'fast-new', 'quotes', 'credit-notes', 'recurring', 'guide',
              'recurring-invoices', 'recurring-bills',
              'bank-transactions', 'bank-rules', 'bank-transfer', 'opening-balances',
              'accounts',
              'settle', 'period-close', 'report-center', 'agents',
              'party-view', 'doc-view', 'order-view', 'ai-close', 'journal-view'];

$page = (string) ($_GET['p'] ?? 'today');

// ---------- 登录 ----------
$loginError = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'login') {
    $res = login_user(trim((string) ($_POST['username'] ?? '')),
                      (string) ($_POST['password'] ?? ''));
    if ($res['ok']) {
        set_session_cookie((string) $res['data']['sessionId']);
        session_regenerate_id(true);
        $_SESSION['user'] = $res['data']['user'];
        $_SESSION['csrf'] = (string) $res['data']['csrfToken'];
        // 登录时选好的使用模式：AI 模式直接进指令台，人工模式进「今天」
        $mode = ((string) ($_POST['mode'] ?? '')) === 'manual' ? 'manual' : 'ai';
        $_SESSION['mode'] = $mode;
        setcookie('ledu_mode', $mode, [
            'expires' => time() + 31536000, 'path' => '/',
            'samesite' => 'Lax', 'secure' => true, 'httponly' => false,
        ]);
        // 审计角色一律落「今天」：AI 指令台与录入页都不给进
        $_role_is_auditor = (($res['data']['user']['role'] ?? '') === 'auditor');
        header('Location: ?p=' . (($mode === 'ai' && !$_role_is_auditor) ? 'command' : 'today'));
        exit;
    }
    $loginError = (string) $res['error'];
}

// ---------- 会话校验 ----------
$user = current_user();
if ($user !== null) {
    $_SESSION['user'] = $user;
    $_SESSION['csrf'] = (string) ($user['csrfToken'] ?? '');
} else {
    unset($_SESSION['user'], $_SESSION['csrf']);
}

if ($user === null) {
    $err = $loginError;
    require __DIR__ . '/pages/login.php';
    exit;
}

// ---------- CSRF ----------
if ($_SERVER['REQUEST_METHOD'] === 'POST' && !csrf_ok()) {
    http_response_code(400);
    echo localize_html('<div class="errbox"><b>400 请求被拒绝</b><div>表单已过期或来源不可信，请刷新页面重试。</div></div>');
    exit;
}

// ---------- 登出 ----------
// 必须 POST + CSRF：否则第三方页面放一张 <img src="?p=logout"> 就能把用户踢下线。
// 旧的 GET 链接仍保留，但只做跳转、不执行登出。
if ($page === 'logout') {
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') === 'logout') {
        logout_user();
        session_destroy();
        header('Location: ?p=login');
        exit;
    }
    header('Location: ?p=today');
    exit;
}

$role      = (string) ($user['role'] ?? 'accountant');
$isAuditor = $role === 'auditor';
$displayName = (string) ($user['displayName'] ?? $user['username'] ?? '');

// ---------- 切换使用模式 ----------
// 放在取到角色之后，审计账号不能进入 AI 指令台
if ($page === 'switch-mode') {
    $m = ((string) ($_GET['m'] ?? '')) === 'manual' ? 'manual' : 'ai';
    $_SESSION['mode'] = $m;
    setcookie('ledu_mode', $m, [
        'expires' => time() + 31536000, 'path' => '/',
        'samesite' => 'Lax', 'secure' => true, 'httponly' => false,
    ]);
    header('Location: ?p=' . (($m === 'ai' && !$isAuditor) ? 'command' : 'today'));
    exit;
}

if ($page === 'dashboard') { $page = 'today'; }
// AI 工作台只属于 AI 模式：人工模式下手动访问 command / ai-close 一律回「今天」
if (function_exists('ui_mode') && ui_mode() !== 'ai'
    && in_array($page, ['command', 'ai-close'], true)) {
    header('Location: ?p=today');
    exit;
}
if ($page === 'login') { $page = ui_mode_home(); }
if (!isset($PAGES[$page])) { $page = ui_mode_home(); }

// 审计角色不允许进入录入类页面
// 审计角色：录入类页面 + 系统设置类页面一律不给进（设置里含密钥与权限，审计师不需要）
$AUDITOR_BLOCKED = ['invoice-new', 'bill-new', 'expense-new', 'journal-new',
                    'settings-llm', 'agents', 'company', 'account', 'email', 'theme', 'backup',
                    'command', 'ai-close'];
if ($isAuditor && in_array($page, $AUDITOR_BLOCKED, true)) {
    header('Location: ?p=today');
    exit;
}

$flash = null;

// 报表页统一提供 PDF 导出
$PDF_KIND = [
    'report-tb' => 'trial-balance', 'report-pnl' => 'pnl', 'report-bs' => 'balance-sheet',
    'report-cf' => 'cash-flow', 'report-aging' => 'aging', 'report-bank' => 'bank-balances',
    'report-fx' => 'fx', 'report-gl' => 'gl', 'report-daybook' => 'daybook',
    'report-sales' => 'sales-detail', 'report-purchase' => 'purchase-detail',
    'report-ratios' => 'ratios', 'report-customer-balance' => 'customer-balances',
    'report-vendor-balance' => 'vendor-balances',
];
$pageActions = '';
if (isset($PDF_KIND[$page])) {
    // 一张报表一个导出按钮，语言在按钮里选（简中 / 繁中 / 英文）
    $qs = [];
    foreach (['from', 'to'] as $k) {
        if (!empty($_GET[$k])) { $qs[$k] = (string) $_GET[$k]; }
    }
    $pageActions = export_menu(export_lang_items('/reports/pdf?kind=' . $PDF_KIND[$page], $qs));
} elseif ($page === 'report-statements') {
    $f = (string) ($_GET['from'] ?? (date('Y') . '-01-01'));
    $t = (string) ($_GET['to'] ?? date('Y-m-d'));
    $pageActions = export_menu(
        export_lang_items('/reports/statements/pdf', ['from' => $f, 'to' => $t]),
        '下载完整报表包');
} elseif ($role !== 'auditor') {
    // 主操作统一放在页面标题右侧（与报价单、贷记单一致），筛选条里不再重复
    $__newPages = [
        'invoices'  => ['invoice-new', '新建发票'],
        'bills'     => ['bill-new', '新建账单'],
        'expenses'  => ['expense-new', '新建费用'],
        'customers' => ['customers&new=1', '新建客户'],
        'vendors'   => ['vendors&new=1', '新建供应商'],
        'sales-orders'    => ['sales-orders&new=1', '新建销售订单'],
        'purchase-orders' => ['purchase-orders&new=1', '新建采购订单'],
        'journal'         => ['journal-new', '新建分录'],
        'banks'           => ['banks&new=1', '新建银行账户'],
        'bank-import'     => ['bank-import&upload=1', '导入月结单'],
    ];
    if (isset($__newPages[$page])) {
        [$__newPage, $__newLabel] = $__newPages[$page];
        $pageActions = '<a class="btn primary" href="?p=' . $__newPage . '">＋ ' . e(t($__newLabel)) . '</a>';
        // 已经在新建/编辑态时不再重复显示「新建」主按钮
        if (in_array($page, ['sales-orders', 'purchase-orders', 'customers', 'vendors'], true)
            && (($_GET['new'] ?? '') === '1' || (int) ($_GET['edit'] ?? 0) > 0)) {
            $pageActions = '';
        } elseif ($page === 'banks' && ($_GET['new'] ?? '') === '1') {
            $pageActions = '';
        } elseif ($page === 'bank-import' && ($_GET['upload'] ?? '') === '1') {
            $pageActions = '';
        }
    }
}

// ---------- 表单动作 ----------
if ($_SERVER['REQUEST_METHOD'] === 'POST' && ($_POST['action'] ?? '') !== 'login') {
    $action = (string) ($_POST['action'] ?? '');
    $id     = (int) ($_POST['id'] ?? 0);
    $writeActions = ['post_invoice', 'reverse_entry', 'resolve_review', 'confirm_match',
                     'revalue', 'import_statement', 'create_payment', 'create_tax_adj',
                     'lock_period', 'unlock_period', 'add_rate', 'save_customer', 'save_vendor', 'save_company',
                     'upload_file', 'upload_bill_file', 'create_journal', 'extract', 'post_bill',
                     'add_tax_line', 'delete_tax_line', 'toggle_account', 'delete_draft'];
    if (in_array($action, $writeActions, true)) {
        require_writer();
    }

    $res = null;
    // 过账前若未复核：管理员可一人走完（提交 → 批准 → 过账），其他角色直接提示
    $ensureApproved = function (string $kind, int $docId) use ($role, $displayName, $user): ?string {
        if ($role !== 'admin') {
            return null;   // 非管理员交给后端拦，给出原始错误
        }
        $actor = (string) ($user['username'] ?? '') ?: $displayName;
        $base  = $kind === 'bill' ? '/bills/' : '/invoices/';
        $body  = ['actor' => $actor, 'role' => $role];
        api_post($base . $docId . '/submit-review', $body);   // 失败也无妨，可能已在待复核
        $ap = api_post($base . $docId . '/approve', $body);
        return $ap['ok'] ? null : (string) $ap['error'];
    };

    if ($action === 'delete_draft') {
        $kind = (string) ($_POST['kind'] ?? '');
        $allowedKinds = ['quote', 'invoice', 'bill', 'expense', 'credit_note', 'order',
                         'payment_received', 'payment_made', 'journal'];
        if ($id <= 0 || !in_array($kind, $allowedKinds, true)) {
            $flash = ['err', '草稿删除参数不合法'];
        } else {
            $res = api_post('/drafts/' . $kind . '/' . $id . '/delete', ['actor' => $displayName]);
            $flash = $res['ok'] ? ['ok', '草稿已删除'] : ['err', (string) $res['error']];
        }
    } elseif ($action === 'post_bill') {
        $res = api_post('/bills/' . $id . '/post', ['actor' => $displayName]);
        if (!$res['ok'] && $role === 'admin') {
            $ensureApproved('bill', $id);
            $res = api_post('/bills/' . $id . '/post', ['actor' => $displayName]);
        }
        $flash = $res['ok']
            ? ['ok', '采购发票已过账：' . ($res['data']['entryNo'] ?? '')]
            : ['err', (string) $res['error']];
    } elseif ($action === 'post_invoice') {
        $res = api_post('/invoices/' . $id . '/post', ['actor' => $displayName]);
        if (!$res['ok'] && $role === 'admin') {
            $ensureApproved('invoice', $id);
            $res = api_post('/invoices/' . $id . '/post', ['actor' => $displayName]);
        }
        $flash = $res['ok'] ? ['ok', '已过账：' . ($res['data']['entryNo'] ?? '')] : ['err', (string) $res['error']];
    } elseif ($action === 'reverse_entry') {
        $res = api_post('/journal/' . $id . '/reverse',
            ['reason' => $_POST['reason'] ?? '更正', 'actor' => $displayName]);
        $flash = $res['ok'] ? ['ok', '已冲销，生成 ' . ($res['data']['entryNo'] ?? '')] : ['err', (string) $res['error']];
    } elseif ($action === 'resolve_review') {
        $res = api_post('/pending-review/' . $id . '/resolve',
            ['action' => $_POST['mode'] ?? 'resolve',
             'resolution' => $_POST['resolution'] ?? '', 'actor' => $displayName]);
        $flash = $res['ok'] ? ['ok', '待复核项已处理'] : ['err', (string) $res['error']];
    } elseif ($action === 'confirm_match') {
        $res = api_post('/bank/confirm-match', [
            'lineId' => (int) ($_POST['lineId'] ?? 0),
            'docId'  => (int) ($_POST['docId'] ?? 0),
            'rule'   => $_POST['rule'] ?? 'P2',
            'reason' => $_POST['reason'] ?? null,
            'actor'  => $displayName,
        ]);
        $flash = $res['ok'] ? ['ok', '匹配已确认'] : ['err', (string) $res['error']];
    } elseif ($action === 'revalue') {
        $res = api_post('/fx/revalue', ['period' => $_POST['period'] ?? '', 'actor' => $displayName]);
        if ($res['ok']) {
            $d = $res['data'];
            $flash = ['ok', !empty($d['alreadyRun'])
                ? (string) $d['note']
                : '重估完成：生成 ' . count($d['entriesWritten'] ?? []) . ' 张分录，汇兑差额 '
                  . money($d['totalGainLossFunctional'] ?? null, 'HKD')];
        } else {
            $flash = ['err', (string) $res['error']];
        }
    } elseif ($action === 'export_csv') {
        $res = api_post('/export', [
            'kind' => $_POST['kind'] ?? 'journal',
            'purpose' => $_POST['purpose'] ?? '审计复核',
            'recipient' => $_POST['recipient'] ?? '内部审计',
            'actor' => $displayName,
            'lang' => lang(),
        ]);
        if ($res['ok']) {
            $_SESSION['last_export'] = [
                'file' => (string) ($res['data']['file'] ?? ''),
                'sha256' => (string) ($res['data']['sha256'] ?? ''),
                'rows' => (int) ($res['data']['rows'] ?? 0),
            ];
            $flash = ['ok', t('已导出') . ' ' . ($res['data']['file'] ?? '')];
        } else {
            $flash = ['err', (string) $res['error']];
        }
    }

    if ($flash !== null && $flash[0] === 'ok') {
        $back = (string) ($_POST['back'] ?? $page);
        $back = isset($PAGES[$back]) ? $back : $page;
        // 详情类页面回跳时必须带上单据 id，否则会掉到「缺少单据 ID」
        $keepId = in_array($back, ['bill-view', 'invoice-view', 'journal-view'], true)
               && (int) ($_POST['id'] ?? $id) > 0;
        header('Location: ?p=' . urlencode($back)
             . ($keepId ? '&id=' . (int) ($_POST['id'] ?? $id) : '')
             . '&msg=' . urlencode($flash[1]));
        exit;
    }
}

if ($flash === null && isset($_GET['msg'])) {
    $flash = [($_GET['t'] ?? 'ok') === 'err' ? 'err' : 'ok', (string) $_GET['msg']];
}

$PAGE_TITLE_I18N = [
    'bank-import'  => ['zh_hk' => '匯入月結單', 'en' => 'Import Statement'],
    'journal-view' => ['zh_hk' => '分錄詳情', 'en' => 'Journal Entry'],
    'report-statements' => ['zh_hk' => '財務報表', 'en' => 'Financial Statements'],
    'report-tb'    => ['zh_hk' => '試算表', 'en' => 'Trial Balance'],
    'report-pnl'   => ['zh_hk' => '損益及其他全面收益表', 'en' => 'Statement of Profit or Loss and OCI'],
    'report-bs'    => ['zh_hk' => '財務狀況表', 'en' => 'Statement of Financial Position'],
    'report-cf'    => ['zh_hk' => '現金流量表', 'en' => 'Statement of Cash Flows'],
    'report-aging' => ['zh_hk' => '賬齡分析表', 'en' => 'Aging Analysis'],
    'report-bank'  => ['zh_hk' => '銀行賬戶餘額表', 'en' => 'Bank Account Balances'],
    'report-fx'    => ['zh_hk' => '匯兌損益表', 'en' => 'Exchange Gain or Loss'],
    'report-tax'   => ['zh_hk' => '利得稅計算表', 'en' => 'Profits Tax Computation'],
    'report-gl'    => ['zh_hk' => '總分類賬', 'en' => 'General Ledger'],
    'report-daybook' => ['zh_hk' => '日記簿', 'en' => 'Journal Day Book'],
    'report-sales' => ['zh_hk' => '銷售明細表', 'en' => 'Sales Details'],
    'report-purchase' => ['zh_hk' => '採購明細表', 'en' => 'Purchase Details'],
    'report-ratios' => ['zh_hk' => '財務比率表', 'en' => 'Financial Ratios'],
    'report-customer-balance' => ['zh_hk' => '客戶餘額表', 'en' => 'Customer Balances'],
    'report-vendor-balance' => ['zh_hk' => '供應商餘額表', 'en' => 'Vendor Balances'],
];
// 侧栏折叠状态存 Cookie，服务端直接渲染，避免刷新时闪一下
$navCookie = (string) ($_COOKIE['ledu_nav'] ?? '');
// 默认展开：导航就是这台机器的仪表盘，藏起来只会让人找不到东西
// 没手动设置过时：AI 模式默认收起功能条，人工模式默认展开
$navCollapsed = $navCookie === 'collapsed'
    || ($navCookie === '' && function_exists('ui_mode') && ui_mode() === 'ai');

// 顶栏需要公司名，会话缓存 10 分钟即可
if (empty($_SESSION['company_name']) || ($_SESSION['company_at'] ?? 0) < time() - 600) {
    $co = api_get('/company');
    $_SESSION['company_name'] = $co['ok'] && !empty($co['data']['name'])
        ? (string) $co['data']['name'] : 'LEDU TECH CO., LIMITED';
    $_SESSION['company_at'] = time();
}
$companyName = (string) $_SESSION['company_name'];

$title = $PAGES[$page][0];
// 页面标题跟界面语言走；report_lang() 只管 PDF 与导出，不再左右界面文字
$_lg = lang();
if ($_lg !== 'zh_cn' && isset($PAGE_TITLE_I18N[$page][$_lg])) {
    $title = $PAGE_TITLE_I18N[$page][$_lg];
}

// 新建 / 编辑态用独立标题，和列表页区分（与报价单、贷记单一致）
$__formTitles = [
    'customers'       => ['新建客户', '编辑客户'],
    'vendors'         => ['新建供应商', '编辑供应商'],
    'sales-orders'    => ['新建销售订单', '编辑销售订单'],
    'purchase-orders' => ['新建采购订单', '编辑采购订单'],
    'banks'           => ['新建银行账户', '编辑银行账户'],
];
if (isset($__formTitles[$page])) {
    if ((string) ($_GET['new'] ?? '') === '1') {
        $title = t($__formTitles[$page][0]);
    } elseif ((int) ($_GET['edit'] ?? 0) > 0) {
        $title = t($__formTitles[$page][1]);
    }
}

function nav_link(string $p, string $label, string $cur, bool $isAuditor, string $role): string
{
    $restricted = ['invoice-new', 'bill-new', 'expense-new', 'journal-new'];
    if (($isAuditor && in_array($p, $restricted, true)) || ($p === 'backup' && $role !== 'admin')) {
        return '';
    }
    $cls = $p === $cur ? 'nav-item active' : 'nav-item';
    return '<a class="' . $cls . '" href="?p=' . urlencode($p) . '">' . e($label) . '</a>';
}
?>
<!doctype html>
<html lang="<?= lang_html() ?>">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= e($title) ?> — Lt-AI-Books</title>
<link rel="icon" type="image/png" href="assets/favicon.png?v=<?= @filemtime(__DIR__ . '/assets/favicon.png') ?>">
<link rel="apple-touch-icon" href="<?= company_logo(192) ?>">
<link rel="stylesheet" href="assets/app.css?v=<?= @filemtime(__DIR__ . '/assets/app.css') ?>">
<?php if (theme_css() !== ''): ?><style><?= theme_css() ?></style><?php endif; ?>
</head>
<?php
$isAiMode = function_exists('ui_mode') && ui_mode() === 'ai';
if (isset($_GET['theme']) && array_key_exists((string) $_GET['theme'], theme_presets())) {
    setcookie('ledu_theme', (string) $_GET['theme'], [
        'expires' => time() + 31536000, 'path' => '/', 'samesite' => 'Lax', 'secure' => true]);
    $qs = $_GET; unset($qs['theme']);
    header('Location: ' . ($_SERVER['PHP_SELF'] ?? '/') . ($qs ? '?' . http_build_query($qs) : ''));
    exit;
}
?>
<body class="<?= $navCollapsed ? 'nav-collapsed' : '' ?><?= $isAiMode ? ' mode-ai' : '' ?><?= in_array($page, ['command', 'ai-close'], true) ? ' ai-page' : '' ?>">
<div class="topbar">
  <button class="nav-collapse" id="navCollapse" aria-label="折叠左侧功能条" aria-expanded="<?= $navCollapsed ? 'false' : 'true' ?>" aria-controls="sidebar" title="折叠／展开左侧功能条">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M2.5 3.5h11v9h-11z"/><path d="M6 3.5v9"/><path class="arrow" d="M10 6.5L8 8l2 1.5"/>
    </svg>
  </button>
  <button class="nav-toggle" id="navToggle" aria-label="打开导航菜单" aria-expanded="false" aria-controls="sidebar">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
      <path d="M2 4h12M2 8h12M2 12h12"/>
    </svg>
  </button>
  <a class="brand" href="?p=today" title="Lt-AI-Books Ver 1.1" aria-label="Lt-AI-Books Ver 1.1">
    <img class="brand-logo" src="<?= e(company_logo(64)) ?>?v=<?= (int) @filemtime(__DIR__ . '/' . company_logo(64)) ?>" alt="LEDU" width="34" height="34">
    <span class="brand-text">
      <span class="brand-main">Lt<span>-AI-Books</span><small>1.1</small></span>
      <span class="brand-co"><?= e($companyName) ?></span>
    </span>
  </a>
  <div class="spacer"></div>
  <?php // 使用模式：AI 模式以指令台为主入口，人工模式以「今天」为主入口
        $__mode = ui_mode(); ?>
  <div class="mode-switch" role="group" aria-label="<?= e(t('使用模式')) ?>">
    <a class="ms<?= $__mode === 'ai' ? ' on' : '' ?>" href="?p=switch-mode&m=ai"
       title="<?= e(t('AI 模式：一句话说清要做什么，AI 给出草稿，你确认')) ?>"><?= e(t('AI 模式')) ?></a>
    <a class="ms<?= $__mode === 'manual' ? ' on' : '' ?>" href="?p=switch-mode&m=manual"
       title="<?= e(t('人工模式：自己点菜单，逐项操作')) ?>"><?= e(t('人工模式')) ?></a>
  </div>
  <?= lang_switcher() ?>
  <form method="get" class="search-form">
    <input type="hidden" name="p" value="search">
    <input type="text" name="q" placeholder="搜索单据 / 流水"
           value="<?= e((string) ($_GET['q'] ?? '')) ?>" class="topbar-search">
  </form>
  <div class="role-switch">
    <span><?= e($displayName) ?> · <?= e($role) ?></span>
    <a class="btn sm" href="?p=account">账号</a>
    <form method="post" action="?p=logout" style="display:inline">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="logout">
      <button class="btn sm" type="submit">退出</button>
    </form>
  </div>
</div>

<div class="nav-backdrop" id="navBackdrop"></div>
<div class="shell">
  <nav class="sidebar" id="sidebar">
    <?php
    // 手风琴：同一时间只展开一个分组。
    // 默认展开当前页所在分组；用户点过则以 Cookie 为准（空值表示全部收起）。
    $pageGroup = null;
    foreach ($NAV as $g => $items) {
        if (in_array($page, $items, true)) { $pageGroup = md5($g); break; }
    }
    // 当前页有归属分组时一律展开它 —— 否则导航后当前项会被藏在已收起的分组里。
    // 仅当页面不属于任何分组（搜索、许可证等）时才回退到 Cookie 记录。
    $openKey = $_COOKIE['ledu_nav_open'] ?? null;
    $openGroup = $pageGroup !== null
        ? $pageGroup
        : ($openKey !== null ? (string) $openKey : (string) ($NAV ? md5(array_key_first($NAV)) : ''));
    ?>
    <?php foreach ($NAV as $group => $items): ?>
      <?php
      $links = '';
      foreach ($items as $it) {
          if (isset($PAGES[$it])) {
              $links .= nav_link($it, $PAGES[$it][0], $page, $isAuditor, $role);
          }
      }
      if ($links === '') { continue; }
      $gkey = md5($group);
      $isOpen = ($gkey === $openGroup);

      // 只有一项的分组直接渲染为入口，省掉一次展开（AI 工作台、审计探索器）
      $visible = array_values(array_filter($items, fn($it) => isset($PAGES[$it])
          && !($isAuditor && in_array($it, ['invoice-new', 'bill-new', 'expense-new', 'journal-new'], true))));
      if (count($visible) === 1):
          $one = $visible[0];
          $cls = $one === $page ? 'nav-flat active' : 'nav-flat';
          ?>
      <a class="<?= $cls ?>" href="?p=<?= e($one) ?>"><?= e($PAGES[$one][0]) ?></a>
      <?php else: ?>
      <details class="nav-group" name="ledu-nav" data-g="<?= e($gkey) ?>"<?= $isOpen ? ' open' : '' ?>>
        <summary class="nav-title">
          <span><?= e($group) ?></span>
          <svg class="nav-chev" width="10" height="10" viewBox="0 0 10 10" fill="none"
               stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true"><path d="M3 4l2 2 2-2"/></svg>
        </summary>
        <div class="nav-links"><?= $links ?></div>
      </details>
      <?php endif; ?>
    <?php endforeach; ?>
  </nav>

  <main class="main">
    <?php if (!in_array($page, $SELF_HEAD, true)): ?>
    <div class="page-head">
      <div>
        <h1 class="page-title"><?= e($title) ?></h1>
        <?php if (isset($PAGES[$page])): ?>
          <?php if ($PAGES[$page][1] !== $title): ?>
          <div class="page-sub"><?= e($PAGES[$page][1]) ?></div>
          <?php endif; ?>
        <?php endif; ?>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <?= $pageActions ?? '' ?>
      </div>
    </div>
    <?= help_html($page) ?>
    <?php endif; ?>
    <?php if ($flash !== null): ?>
      <?php if ($flash[0] === 'ok'): ?>
        <div class="banner PASS"><span class="banner-icon">✓</span>
          <div class="banner-body"><div class="banner-title">操作成功</div>
          <div class="banner-reason"><?= e($flash[1]) ?></div>
          <?php if (!empty($_SESSION['last_export'])):
              $ex = $_SESSION['last_export']; unset($_SESSION['last_export']); ?>
            <div style="margin-top:10px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
              <a class="btn primary" href="download.php?f=<?= rawurlencode($ex['file']) ?>">
                <?= e(str_replace('{n}', (string) (int) $ex['rows'], t('下载 CSV（{n} 行）'))) ?>
              </a>
              <span class="hint" style="font-family:var(--mono)">
                SHA-256 <?= e(substr($ex['sha256'], 0, 16)) ?>…
              </span>
            </div>
          <?php endif; ?>
          </div></div>
      <?php else: ?>
        <?= errbox($flash[1]) ?>
      <?php endif; ?>
    <?php endif; ?>

    <?php
    // 报表页统一带期间工具条（预设 + 自定义 + 对比）
    $REPORT_PAGES = ['report-tb','report-pnl','report-bs','report-cf','report-gl',
                     'report-gl-detail','report-daybook','report-sales','report-purchase','report-ratios',
                     'report-customer-balance','report-vendor-balance','report-fx',
                     'report-aging','report-bank','report-statements','report-account-types','tax','report-tax'];
    if (in_array($page, $REPORT_PAGES, true)) {
        $GLOBALS['RP'] = report_period();
        echo '<div class="period-wrap">' . report_period_bar($GLOBALS['RP']) . '</div>';
    }
    $file = __DIR__ . '/pages/' . $page . '.php';
    if (is_file($file)) { require $file; } else { echo empty_state('页面不存在：' . $page); }
    ?>

    <div class="footer-note">
      <span>Copyright (c) 2026 Ledu Tech Co., Limited</span><span class="hint">·</span>
      <span class="hint"><?= e(t('数字来自账簿分录，AI 只做建议，记账由你确认')) ?></span>
    </div>
  </main>
</div>

<!-- 确认窗：记账 / 作废 / 冲销 / 锁账 / 对外发送 五件事必弹（D-01） -->
<div id="cfm" role="dialog" aria-modal="true" aria-labelledby="cfmTitle">
  <div class="cfm-card">
    <div class="cfm-kicker">需要你确认</div>
    <div class="cfm-title" id="cfmTitle">确认执行</div>
    <div class="cfm-body"></div>
    <div class="cfm-note"></div>
    <div class="cfm-actions">
      <button type="button" class="btn" data-cfm-cancel>取消</button>
      <button type="button" class="btn primary" data-cfm-ok>确认执行</button>
    </div>
  </div>
</div>

<script>
/* 全站确认窗：任何 form / a 带 data-confirm 都会先弹窗，确认后才真的提交 */
(function () {
  var mask = document.getElementById('cfm');
  if (!mask) return;
  var elTitle = mask.querySelector('.cfm-title'),
      elBody  = mask.querySelector('.cfm-body'),
      elNote  = mask.querySelector('.cfm-note'),
      btnOk   = mask.querySelector('[data-cfm-ok]'),
      btnNo   = mask.querySelector('[data-cfm-cancel]');
  var pending = null;

  function open(text, note, onOk, okLabel) {
    var parts = String(text || '').split('\n');
    elTitle.textContent = parts.shift() || '确认执行';
    elBody.textContent = parts.join('\n');
    if (note) { elNote.textContent = note; elNote.style.display = ''; }
    else { elNote.style.display = 'none'; }
    btnOk.textContent = okLabel || '确认执行';
    pending = onOk;
    mask.classList.add('show');
    setTimeout(function () { btnNo.focus(); }, 30);
  }
  function close() { mask.classList.remove('show'); pending = null; }

  btnNo.addEventListener('click', close);
  mask.addEventListener('click', function (e) { if (e.target === mask) { close(); } });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && mask.classList.contains('show')) { close(); }
  });
  btnOk.addEventListener('click', function () {
    var f = pending; close(); if (f) { f(); }
  });

  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f || !f.dataset) { return; }
    var src = (e.submitter && e.submitter.dataset && e.submitter.dataset.confirm)
      ? e.submitter : (f.dataset.confirm ? f : null);
    if (!src || f.dataset.cfmDone) { return; }
    e.preventDefault();
    open(src.dataset.confirm, src.dataset.confirmNote || '', function () {
      f.dataset.cfmDone = '1';
      if (f.requestSubmit) { f.requestSubmit(e.submitter || undefined); } else { f.submit(); }
    }, src.dataset.confirmOk || '');
  }, true);

  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest ? e.target.closest('a[data-confirm]') : null;
    if (!a) { return; }
    e.preventDefault();
    open(a.dataset.confirm, a.dataset.confirmNote || '', function () {
      window.location.href = a.getAttribute('href');
    }, a.dataset.confirmOk || '');
  }, true);
})();
</script>
<script>
/* 为每个 label.f 关联紧随其后的控件，保证表单有可访问名称 */
(function () {
  var seq = 0;
  document.querySelectorAll('label.f').forEach(function (lab) {
    var next = lab.nextElementSibling;
    if (!next || !/^(INPUT|SELECT|TEXTAREA)$/.test(next.tagName)) {
      var box = lab.parentElement;
      next = box ? box.querySelector('input,select,textarea') : null;
    }
    if (!next) return;
    if (!next.id) next.id = 'fld' + (++seq);
    lab.setAttribute('for', next.id);
  });
})();
(function () {
  // 手风琴导航：同时只展开一个分组；把展开的那个写入 Cookie，刷新后保持
  var groups = Array.prototype.slice.call(document.querySelectorAll('details.nav-group'));
  function save(openKey) {
    document.cookie = 'ledu_nav_open=' + openKey
      + ';path=/;max-age=31536000;samesite=lax';
  }
  groups.forEach(function (d) {
    d.addEventListener('toggle', function () {
      if (!d.open) {
        // 关掉当前展开项：记录为空，全部收起
        if (!groups.some(function (x) { return x.open; })) { save(''); }
        return;
      }
      // 打开一个 → 收起其余（兼容不支持 details[name] 的浏览器）
      groups.forEach(function (x) { if (x !== d && x.open) { x.open = false; } });
      save(d.dataset.g);
    });
  });
})();
(function () {
  var c = document.getElementById('navCollapse');
  if (c) {
    c.addEventListener('click', function () {
      var on = document.body.classList.toggle('nav-collapsed');
      c.setAttribute('aria-expanded', on ? 'false' : 'true');
      document.cookie = 'ledu_nav=' + (on ? 'collapsed' : 'expanded')
        + ';path=/;max-age=31536000;samesite=lax';
    });
  }
})();
(function () {
  var t = document.getElementById('navToggle'),
      s = document.getElementById('sidebar'),
      b = document.getElementById('navBackdrop');
  if (!t || !s) return;
  function close() { s.classList.remove('open'); b.classList.remove('show'); }
  t.addEventListener('click', function () {
    var open = s.classList.toggle('open');
    b.classList.toggle('show', open);
    t.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  b.addEventListener('click', close);
  s.addEventListener('click', function (e) {
    if (e.target.classList.contains('nav-item')) close();
  });
  window.addEventListener('resize', function () {
    if (window.innerWidth > 900) close();
  });
})();
</script>
<?php
// 全站语言翻译：只处理文本节点与可翻译属性，脚本块已保护
$__html = ob_get_clean();
echo localize_html($__html, account_names_for_lang());
?>
<script src="assets/select-search.js?v=<?= @filemtime(__DIR__ . '/assets/select-search.js') ?>"></script>
<script src="assets/shortcuts.js?v=<?= @filemtime(__DIR__ . '/assets/shortcuts.js') ?>"></script>

<script>
/* 表格内的下拉菜单：展开时放开 .table-wrap 的 overflow，靠近底部时向上弹 */
(function () {
  function place(det) {
    var wrap = det.closest('.table-wrap');
    if (!wrap) return;
    if (det.open) {
      wrap.classList.add('is-menu-open');
      var r = det.getBoundingClientRect();
      var menu = det.querySelector('.exp-list');
      var need = menu ? menu.offsetHeight + 16 : 200;
      det.classList.toggle('up', r.bottom + need > window.innerHeight && r.top > need);
    } else {
      wrap.classList.remove('is-menu-open');
    }
  }
  document.addEventListener('toggle', function (e) {
    var t = e.target;
    if (t && t.tagName === 'DETAILS' && t.classList.contains('exp-menu')) place(t);
  }, true);
  document.addEventListener('click', function (e) {
    document.querySelectorAll('details.exp-menu[open]').forEach(function (d) {
      if (!d.contains(e.target)) { d.open = false; place(d); }
    });
  });
})();
</script>
</body>
</html>

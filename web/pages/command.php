<?php
/*
 * LtBooks — pages/command.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * AI 工作台 —— AI 模式的主界面（?p=command）
 *
 * 结构（自上而下）
 *   .ai-strip     顶部工具带：查账 / 开单 / 记账 / 对账 / 出报表 / 月结 · 最近记账 · 岗位切换
 *   .ai-drawer    最近记账抽屉（默认收起）
 *   .cmd-log      对话区：唯一会滚动的区域
 *   .composer     输入框：永远贴底（空状态也一样）
 *
 * 空状态（$__hasContent 为 false）
 *   居中大标题 + 6 个磁贴；点磁贴只预填指令，不自动提交。
 *
 * 约束
 *   · AI 不能自己记账：任何写操作都走「确认卡片」，由人点确认
 *   · 与人工台同一套权限、复核与审计链，只是入口分开
 *   · 人工模式下访问本页会被 index.php 踢回「今天」
 */

/** 指令台：AI 为主模式的主屏。一句自然语言 → 智能体处理 → 弹窗确认。 */

/** 把智能体回复渲染成安全 HTML。
 *  先整体转义，再只加我们认识的标记（**强调**、- 列表、# 标题、| 表格）；
 *  气泡本身是 white-space:pre-wrap，所以正文不插 <br>，否则每行会多一个空行。
 */
$fmt = static function (string $t): string {
    $src = e($t);
    $src = preg_replace('/[ \t]+$/mu', '', $src);
    $lines = explode("\n", $src);

    // 数字列右对齐、等宽：金额一类的单元格不要左对齐
    $isNum = static fn(string $c): bool =>
        (bool) preg_match('/^[\(\-]?\s*(HKD\s*)?[\d,]+(\.\d+)?\s*\)?%?$/u', $c);

    $out = [];
    $n = count($lines);
    for ($i = 0; $i < $n; $i++) {
        $line = rtrim(ltrim($lines[$i], " \t"));
        // ---- 表格：连续的 | a | b | 行 ----
        if (preg_match('/^\|.*\|$/', $line)) {
            $block = [];
            while ($i < $n && preg_match('/^\|.*\|$/', rtrim(ltrim($lines[$i], " \t")))) {
                $block[] = rtrim(ltrim($lines[$i], " \t"));
                $i++;
            }
            $i--;
            $head = null; $body = [];
            foreach ($block as $bi => $row) {
                $cells = array_map('trim', explode('|', trim($row, '|')));
                if ($bi === 1 && preg_match('/^[\s\-:|]+$/', implode('', $cells))) {
                    continue;                    // |---|---| 分隔行
                }
                if ($head === null) { $head = $cells; continue; }
                $body[] = $cells;
            }
            $h = '<table class="cmd-table">';
            if ($head !== null) {
                $h .= '<thead><tr>';
                foreach ($head as $c) {
                    $h .= '<th' . ($isNum($c) ? ' class="num"' : '') . '>' . $c . '</th>';
                }
                $h .= '</tr></thead>';
            }
            $h .= '<tbody>';
            foreach ($body as $cells) {
                $h .= '<tr>';
                foreach ($cells as $c) {
                    $h .= '<td' . ($isNum($c) ? ' class="num"' : '') . '>' . $c . '</td>';
                }
                $h .= '</tr>';
            }
            $h .= '</tbody></table>';
            $out[] = $h;
            continue;
        }
        // ---- 普通行 ----
        $line = preg_replace('/^[ \t]*[\-*][ \t]+/u', '· ', $line);
        $line = preg_replace('/^#{1,6}[ \t]*(.+)$/u', '<b>$1</b>', $line);
        $line = preg_replace('/\*\*(.+?)\*\*/us', '<b>$1</b>', $line);
        $out[] = $line;
    }
    $html = implode("\n", $out);
    // 结尾这句我们自己会在气泡底部统一加，模型也常自己写一遍，去掉重复
    $html = preg_replace('/\s*AI-assisted,\s*subject to human review\s*$/iu', '', $html);
    return trim((string) $html);
};
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'owner');

// 执行方式：默认「可直接执行」（会计/出纳有满权限）；可切回「只提案」
if (isset($_GET['agentwrite'])) {
    $aw = ((string) $_GET['agentwrite']) === '0' ? '0' : '1';
    setcookie('ledu_agent_write', $aw, ['expires' => time() + 31536000, 'path' => '/',
        'samesite' => 'Lax', 'secure' => true]);
    header('Location: ?p=command');
    exit;
}
$allowWrite = ((string) ($_COOKIE['ledu_agent_write'] ?? '1')) !== '0';
$text = trim((string) ($_POST['text'] ?? ''));
// 当前岗位：表单提交优先，其次 URL（左栏切换岗位走 URL）
$__AGENTS = ['controller' => '财务主管', 'accountant' => '会计', 'cashier' => '出纳',
             'guard' => '复核守门人', 'doc_analyst' => '单据分析',
             'tax_advisor' => '税务顾问', 'compliance' => '合规管家'];
$agent = (string) ($_POST['agent'] ?? $_GET['agent'] ?? 'controller');
if (!isset($__AGENTS[$agent])) { $agent = 'controller'; }
$reply = null; $err = null; $runId = 0;
$cards = [];        // 待确认卡片（本次导入 / 智能体提案 / 页面上还没处理的）
/**
 * 「建一张发票，我来填」这类意图：不追问，直接在指令台里给表单。
 * 只认没有具体数字的请求——带了金额/单号说明已经有数据，交给智能体。
 */
function blank_doc_kind(string $text): ?string
{
    $t = trim($text);
    if ($t === '' || mb_strlen($t) > 40 || preg_match('/\d{2,}/', $t)) {
        return null;
    }
    $verb = '/(建|开|做|生成|新建|来一张|来一张)/u';
    if (preg_match('/(销售发票|开票|开发票|invoice)/iu', $t) && preg_match($verb, $t)) {
        return 'invoice';
    }
    if (preg_match('/(采购发票|账单|bill)/iu', $t) && preg_match($verb, $t)) {
        return 'bill';
    }
    return null;
}

$outcome = null;    // 确认或放弃后的结果
$writes = [];       // 本轮真正写进账套的动作
$errHint = null;    // 导入失败时给一条去处（例如「去导入银行流水」）
$act = (string) ($_POST['action'] ?? '');

// 科目表（确认卡片里手工改选科目用）：识别/建议科目不对时，人可以直接点选
$__accts = [];
$__ar = api_get('/accounts?limit=0');
if ($__ar['ok']) {
    foreach ((array) ($__ar['data']['accounts'] ?? $__ar['data']['items'] ?? []) as $__x) {
        $__code = (string) ($__x['account_code'] ?? '');
        if ($__code === '') { continue; }
        $__accts[] = ['code' => $__code,
                      'name' => acc_name((string) $__code, (string) ($__x['account_name'] ?? $__code)),
                      'cat'  => (string) ($__x['category'] ?? '')];
    }
}
usort($__accts, fn($a, $b) => strcmp($a['code'], $b['code']));

// 银行账户：贷方可以选「先挂应付」或「当场从某个银行账户付掉」
$__banks = [];
$__br = api_get('/bank-accounts');
if ($__br['ok']) {
    foreach ((array) ($__br['data']['accounts'] ?? []) as $__b) {
        if ((string) ($__b['status'] ?? 'active') !== 'active') { continue; }
        $__banks[] = ['id' => (int) $__b['account_id'],
                      'name' => (string) ($__b['name'] ?? ''),
                      'ccy' => (string) ($__b['currency'] ?? 'HKD')];
    }
}

/** 采购/费用卡片复用统一单据分析；首次上传可读取完整 OCR，历史卡片用已保存摘要。 */
$analyzeExpenseCard = static function (array $a, string $type): array {
    if (!in_array($type, ['create_bill', 'create_expense'], true)) { return []; }
    $actionId = (int) ($a['actionId'] ?? $a['action_id'] ?? 0);
    if ($actionId > 0 && is_array($_SESSION['ledu_expense_analysis'][$actionId] ?? null)) {
        return (array) $_SESSION['ledu_expense_analysis'][$actionId];
    }
    $remember = static function (array $analysis) use ($actionId): array {
        if ($actionId > 0 && array_key_exists('expenseNature', $analysis)) {
            $_SESSION['ledu_expense_analysis'][$actionId] = $analysis;
            if (count($_SESSION['ledu_expense_analysis']) > 12) {
                array_shift($_SESSION['ledu_expense_analysis']);
            }
        }
        return $analysis;
    };
    if (is_array($a['analysis'] ?? null) && array_key_exists('expenseNature', $a['analysis'])) {
        return $remember((array) $a['analysis']);
    }
    $sum = is_array($a['summary'] ?? null) ? $a['summary'] : [];
    $fields = is_array($a['fields'] ?? null) ? $a['fields'] : [];
    $party = '';
    $parts = [];
    foreach (($sum['rows'] ?? []) as $row) {
        $key = (string) ($row['k'] ?? '');
        if ($key === '支出性质') { continue; } // 不把旧提案的默认结论当成新证据
        $value = (string) ($row['v'] ?? '');
        $parts[] = $key . ' ' . $value;
        if ($key === '往来单位') { $party = $value === '—' ? '' : $value; }
    }
    if (!empty($fields['partyName'])) { $party = (string) $fields['partyName']; }
    $lines = is_array($sum['lines'] ?? null) ? $sum['lines'] : [];
    foreach ($lines as $line) {
        $desc = trim((string) ($line['description'] ?? ''));
        if ($desc !== '') { $parts[] = $desc; }
    }
    $extracted = ['actionType' => $type, 'partyName' => $party];
    foreach (['date', 'docNo', 'currency', 'amountOriginal', 'taxOriginal'] as $key) {
        if (isset($fields[$key]) && $fields[$key] !== '') { $extracted[$key] = $fields[$key]; }
    }
    $request = ['party' => $party, 'lines' => $lines, 'extracted' => $extracted];
    $tmpPath = (string) ($a['_sourceTmpPath'] ?? '');
    if ($tmpPath !== '' && is_file($tmpPath)) {
        $r = api_post('/ai/analyze-document', $request + ['path' => $tmpPath]);
        if ($r['ok']) { return $remember((array) $r['data']); }
    }
    $text = trim(implode("\n", array_filter($parts, static fn($v) => trim($v) !== '')));
    if ($text === '') { return []; }
    $r = api_post('/ai/analyze-document', $request + ['text' => $text]);
    return $r['ok'] ? $remember((array) $r['data']) : [];
};

/** 确认卡片：字段、匹配结果、风险、明细，加两个按钮。 */
$renderCard = static function (array $a) use ($actor, $role, $__accts, $__banks, $analyzeExpenseCard): string {
    $sum = is_array($a['summary'] ?? null) ? $a['summary'] : [];
    $id = (int) ($a['actionId'] ?? $a['action_id'] ?? 0);
    $type = (string) ($a['actionType'] ?? $a['action_type'] ?? '');
    $isPost = $type === 'post_document';
    $h = '<div class="ai-card">';
    $titleText = (string) ($a['title'] ?? '');
    if (($a['actionType'] ?? $a['action_type'] ?? '') === 'import_bank_statement') {
        $acctName = '';
        foreach (($sum['rows'] ?? []) as $rr) {
            if (($rr['k'] ?? '') === '账户') { $acctName = (string) $rr['v']; }
        }
        $nRows = 0;
        foreach (($sum['rows'] ?? []) as $rr) {
            if (($rr['k'] ?? '') === '笔数') { $nRows = (int) $rr['v']; }
        }
        $titleText = t('银行对账单') . ($acctName !== '' ? ' · ' . $acctName : '')
                   . ($nRows ? ' · ' . $nRows . ' ' . t('笔') : '');
    }
    // 标题行就是操作行：确认/放弃永远在第一眼看得见的位置，不用滚到卡片底部
    $confirmLabel = $isPost ? t('确认记账')
        : (($type === 'import_bank_statement') ? t('确认导入流水')
        : (($type === 'import_opening') ? t('确认并生成分录') : t('确认导入')));
    $h .= '<div class="ai-card-head">'
        . '<span class="tag tag-warn">' . e(t('待确认')) . '</span>'
        . '<span class="ai-card-title">' . e($titleText) . '</span>'
        . '<div class="ai-card-acts">'
        . '<form method="post" style="margin:0" id="cfmStmt' . $id . '">' . csrf_field()
        . '<input type="hidden" name="action" value="ai_confirm">'
        . '<input type="hidden" name="id" value="' . $id . '">'
        . '</form>'
        . '<button class="btn sm primary" type="submit" form="cfmStmt' . $id . '"'
        . ($isPost ? ' data-confirm="' . e(t('确认记账？')) . '"'
                    . ' data-confirm-note="' . e(t('将依次执行：提交复核 → 批准 → 记账。记账后不可修改或删除，只能冲销。')) . '"'
                    . ' data-confirm-ok="' . e(t('确认记账')) . '"' : '')
        . '>' . e($confirmLabel) . '</button>'
        . '<form method="post" style="margin:0">' . csrf_field()
        . '<input type="hidden" name="action" value="ai_cancel">'
        . '<input type="hidden" name="id" value="' . $id . '">'
        . '<button class="btn sm" type="submit">' . e(t('放弃')) . '</button></form>'
        . '</div></div>';

    // 关键字段横排。挑字段要看人真正用来判断的东西：
    // 什么单、跟谁、哪天、多少钱 —— 其余（方向说明、对方单号、科目）收进细节。
    $PRIORITY = ['单据类型', '往来单位', '日期', '价税合计', '金额（不含税）', '金额', '税额', '币种'];
    $picked = [];
    $rest = [];
    foreach (($sum['rows'] ?? []) as $row) {
        $val = (string) $row['v'];
        // 只有「科目建议」这种由代码生成的说明才翻译；其余是业务数据，原样显示
        if (($row['i18n'] ?? '') === 'why' && preg_match('/^(\S+)\s*·\s*(.+)$/u', $val, $mm)) {
            $val = $mm[1] . ' · ' . t($mm[2]);
        }
        $rawK = (string) $row['k'];
        // 支出性质只在采购/费用卡片下方按证据渲染，销售卡片即使带旧数据也不显示。
        if ($rawK === '支出性质') { continue; }
        $item = ['k' => t($rawK), 'v' => $val, 'strong' => !empty($row['strong']),
                 'num' => (bool) preg_match('/^[\d,\.]+$/', $val)];
        if (in_array($rawK, $PRIORITY, true)) { $picked[$rawK] = $item; } else { $rest[] = $item; }
    }
    $quick = [];
    foreach ($PRIORITY as $pk) {
        if (isset($picked[$pk]) && count($quick) < 4) { $quick[] = $picked[$pk]; }
    }
    $extra = $rest;
    if ($quick) {
        $h .= '<div class="ai-fgrid">';
        foreach ($quick as $it) {
            $h .= '<div class="ai-fg' . ($it['strong'] ? ' is-strong' : '') . '">'
                . '<div class="ai-fg-k">' . e($it['k']) . '</div>'
                . '<div class="ai-fg-v' . ($it['num'] ? ' num' : '') . '">' . e($it['v']) . '</div></div>';
        }
        $h .= '</div>';
    }

        // 手工改选科目：先算出系统建议科目，供下面的科目下拉预选/提示
        $__isDocAcct = in_array($type, ['create_bill', 'create_expense', 'create_invoice'], true);
        $__suggested = '';
        $__catLabel = [];
        if ($__isDocAcct && $__accts) {
            foreach (($sum['rows'] ?? []) as $__row) {
                if (($__row['k'] ?? '') === '费用/收入科目' && preg_match('/^(\S+)\s*·/', (string) ($__row['v'] ?? ''), $__mm)) {
                    $__suggested = $__mm[1];
                }
            }
            $__catLabel = ['expense' => t('费用'), 'revenue' => t('收入'), 'asset' => t('资产'),
                           'liability' => t('负债'), 'equity' => t('权益'), 'cogs' => t('成本')];
        }

        if (in_array($type, ['create_bill', 'create_expense'], true)) {
            $__analysis = $analyzeExpenseCard($a, $type);
            $__nat = (string) ($__analysis['expenseNature'] ?? '');
            $__natWhy = (string) ($__analysis['expenseNatureWhy'] ?? '');
            $__natConf = (string) ($__analysis['expenseNatureConfidence'] ?? '');
            $__natReliable = in_array($__nat, ['company', 'reimburse'], true)
                && in_array($__natConf, ['high', 'medium'], true)
                && empty($__analysis['expenseNatureNeedsConfirmation'])
                && ($__analysis['expenseNatureApplicable'] ?? true);
            if ($__natReliable) {
                $__natLabel = $__nat === 'reimburse'
                    ? t('个人报销（贷 其他应付款—员工）')
                    : t('公司直接支出（贷 应付账款 / 银行）');
                $h .= '<div class="field" style="margin-top:8px"><div class="f">' . e(t('支出性质')) . '</div>'
                    . '<input type="hidden" name="expenseNature" value="' . e($__nat) . '" form="cfmStmt' . $id . '">'
                    . '<div>' . e($__natLabel) . '</div>'
                    . '<span class="hint">' . e(t('已根据往来单位、OCR 与科目建议自动判断'))
                    . ($__natWhy !== '' ? '：' . e(t($__natWhy)) : '') . '</span></div>';
            } else {
                // 没有可靠证据时不沿用后端默认 company，必须由人明确选择。
                $h .= '<div class="field" style="margin-top:8px"><label class="f">' . e(t('支出性质')) . '</label>'
                    . '<select name="expenseNature" form="cfmStmt' . $id . '" required>'
                    . '<option value="" selected>' . e(t('— 无法自动判断，请选择 —')) . '</option>'
                    . '<option value="company">' . e(t('公司直接支出（贷 应付账款 / 银行）')) . '</option>'
                    . '<option value="reimburse">' . e(t('个人报销（贷 其他应付款—员工）')) . '</option>'
                    . '</select><span class="hint">' . e(t('决定贷方科目：报销先挂员工应付款')) . '</span></div>';
            }
        }

        $h .= '<div class="field" style="margin-top:8px"><label class="f">' . e(t('入账科目')) . '</label>'
            . '<select name="accountCode" form="cfmStmt' . $id . '">'
            . '<option value="">' . e(t('— 选科目 —')) . '</option>';
        foreach ($__accts as $__ac) {
            $__sel = ($__ac['code'] === $__suggested) ? ' selected' : '';
            $__lab = $__ac['code'] . ' · ' . $__ac['name']
                   . (($__catLabel[$__ac['cat']] ?? '') !== '' ? '（' . ($__catLabel[$__ac['cat']] ?? '') . '）' : '');
            $h .= '<option value="' . e($__ac['code']) . '"' . $__sel . '>' . e($__lab) . '</option>';
        }
        $h .= '</select>';
        if ($__suggested !== '') {
            $h .= '<span class="hint">' . e(t('系统建议')) . '：' . e($__suggested) . '</span>';
        }
        $h .= '</div>';

        // 贷方（对方科目）：先挂应付，或当场从银行付掉
        $h .= '<div class="field" style="margin-top:8px"><label class="f">' . e(t('贷方科目（付款方式）')) . '</label>'
            . '<select name="creditKey" form="cfmStmt' . $id . '">'
            . '<option value="ap">' . e(t('应付账款（先挂账，稍后付款）')) . '</option>';
        foreach ($__banks as $__bk) {
            $h .= '<option value="bank:' . (int) $__bk['id'] . '">'
                . e(t('立即付款') . '：' . $__bk['name'] . '（' . $__bk['ccy'] . '）') . '</option>';
        }
        $h .= '</select><span class="hint">'
            . e(t('选银行账户＝确认后直接记一笔付款，借款两清')) . '</span></div>';

    $h .= '<details class="ai-more"><summary>' . e(t('查看识别细节')) . '</summary><div class="ai-more-body">';
    if ($extra) {
        $h .= '<div class="ai-fgrid">';
        foreach ($extra as $it) {
            $h .= '<div class="ai-fg' . ($it['strong'] ? ' is-strong' : '') . '">'
                . '<div class="ai-fg-k">' . e($it['k']) . '</div>'
                . '<div class="ai-fg-v' . ($it['num'] ? ' num' : '') . '">' . e($it['v']) . '</div></div>';
        }
        $h .= '</div>';
    }
    $m = $sum['match'] ?? null;
    // 上年结转没有往来单位，别显示「按这个名称建单」这类提示
    if (is_array($m) && ($type === 'import_opening' || !$m)) {
        $m = null;
    }
    if (is_array($m)) {
        if (!empty($m['matched'])) {
            $lvl = ($m['level'] ?? '') === 'exact' ? t('名称完全一致') : t('名称近似匹配');
            $h .= '<div class="ai-match ok">' . e(t('已匹配到档案')) . '：'
                . e((string) ($m['name'] ?? '')) . '（' . e((string) ($m['code'] ?? '')) . '，'
                . e($lvl) . '）</div>';
        } else {
            $uses = (int) ($m['historyUses'] ?? 0);
            if ($uses > 0) {
                $h .= '<div class="ai-match">'
                    . e(t('档案里没有这个往来单位，但历史单据用过这个名称')) . ' ' . $uses . ' '
                    . e(t('次；确认后按此名称建单，可稍后建档'))
                    . '</div>';
            } else {
                $h .= '<div class="ai-match">' . e(t('档案里没有这个往来单位；确认后会按这个名称建单，可稍后再建档'))
                    . '</div>';
            }
            if (!empty($m['candidates'])) {
                $names = array_map(fn($c) => (string) $c['name'], $m['candidates']);
                $h .= '<div class="ai-match">' . e(t('可能是')) . '：'
                    . e(implode(' / ', $names)) . '</div>';
            }
        }
    }

    if (!empty($sum['lines'])) {
        $h .= '<table class="cmd-table"><thead><tr><th>' . e(t('明细')) . '</th>'
            . '<th class="num">' . e(t('金额')) . '</th></tr></thead><tbody>';
        foreach (array_slice($sum['lines'], 0, 8) as $ln) {
            $h .= '<tr><td>' . e((string) ($ln['description'] ?? '')) . '</td>'
                . '<td class="num">' . e(number_format((float) ($ln['amount'] ?? 0), 2)) . '</td></tr>';
        }
        $h .= '</tbody></table>';
    }

    if (!empty($sum['risks'])) {
        $h .= '<div class="ai-risks">';
        foreach ($sum['risks'] as $rk) {
            $h .= '<div>· ' . e((string) $rk) . '</div>';
        }
        $h .= '</div>';
    }
    if (!empty($sum['afterConfirm'])) {
        $h .= '<div class="ai-after">' . e(t('确认后')) . ' · ' . e(t((string) $sum['afterConfirm'])) . '</div>';
    }

    $isStmt = ($type === 'import_bank_statement');
    // 拿不准的地方直接问人：每个问题一组单选，默认选项带「推荐」
    if (!empty($sum['asks'])) {
        $h .= '<div class="ai-asks"><div class="ai-asks-h">' . e(t('需要你确认')) . '</div>';
        foreach ($sum['asks'] as $q) {
            $qtext = (string) ($q['q'] ?? '');
            if (($q['key'] ?? '') === 'fx' && !empty($q['ccy'])) {
                $qtext = t('识别到') . ' ' . $q['ccy'] . ' · ' . t('不是港币，折算金额怎么定？');
            } else {
                $qtext = t($qtext);
            }
            $h .= '<div class="ai-ask"><div class="ai-ask-q">' . e($qtext) . '</div>';
            foreach (($q['options'] ?? []) as $o) {
                $h .= '<label class="ai-opt"><input type="radio" name="answers[' . e((string) $q['key']) . ']"'
                    . ' form="cfmStmt' . $id . '" value="' . e((string) $o['v']) . '"'
                    . (!empty($o['rec']) ? ' checked' : '') . '>'
                    . '<span>' . e(t((string) $o['t']))
                    . (!empty($o['n']) ? ' · ' . e(t((string) $o['n'])) : '')
                    . (!empty($o['rec']) ? '<em>' . e(t('推荐')) . '</em>' : '')
                    . '</span></label>';
            }
            $h .= '</div>';
        }
        $h .= '</div>';
    }
    // 卡片上的可改字段：/ai/import 会直接给 fields；对话里产生的提案从 summary 行里还原
    if (empty($a['fields']) && !$isStmt && !$isPost) {
        $alias = ['往来单位' => 'partyName', '对方单号' => 'docNo', '日期' => 'date',
                  '币种' => 'currency', '金额（不含税）' => 'amountOriginal', '税额' => 'taxOriginal'];
        $fb = [];
        foreach (($sum['rows'] ?? []) as $row) {
            $k = $alias[(string) ($row['k'] ?? '')] ?? '';
            if ($k !== '') {
                $fb[$k] = preg_replace('/[^0-9.\-]/', '',
                    (string) ($row['v'] ?? '')) ?: (string) ($row['v'] ?? '');
                $fb[$k] = (string) ($row['v'] ?? '');
            }
        }
        if ($fb) { $a['fields'] = $fb; }
    }
    if (!empty($a['fields']) && !$isStmt && !$isPost) {
        $fv = (array) $a['fields'];
        $h .= '<div class="ai-edit"><div class="ai-edit-h">' . e(t('识别结果（可直接改，改过的会记住）')) . '</div>';
        $defs = [
            ['partyName', '往来单位', 'text'],
            ['date', '日期', 'date'],
            ['docNo', '对方单号', 'text'],
            ['amountOriginal', '金额', 'number'],
            ['taxOriginal', '税额', 'number'],
        ];
        if (!empty($sum['needsFunctional'])) {
            $defs[] = ['amountFunctional', '折算金额（HKD）', 'number'];
        }
        foreach ($defs as [$k, $lab, $tp]) {
            $h .= '<label class="ai-edit-row"><span>' . e(t($lab)) . '</span>'
                . '<input type="' . $tp . '" name="fields[' . $k . ']" form="cfmStmt' . $id . '"'
                . ($tp === 'number' ? ' step="0.01"' : '')
                . ' value="' . e((string) ($fv[$k] ?? '')) . '"></label>';
        }
        $h .= '</div>';
    }

    if ($isStmt && !empty($a['accounts'])) {
        $h .= '<div class="field" style="margin-top:8px"><label class="f">' . e(t('入账账户')) . '</label>'
            . '<select name="bankAccountId" form="cfmStmt' . $id . '">';
        foreach ($a['accounts'] as $ac) {
            $sel = ((int) ($sum['accountId'] ?? 0) === (int) $ac['accountId']) ? ' selected' : '';
            $h .= '<option value="' . (int) $ac['accountId'] . '"' . $sel . '>'
                . e($ac['name'] . ' · ' . $ac['currency'] . ' · ' . $ac['account']) . '</option>';
        }
        $h .= '</select></div>';
    }
    $isOpening = ($type === 'import_opening');
    $h .= '</div></details>';
    $h .= '</div>';
    return $h;
};

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    // 识别一张单据要走 OCR + 模型，常见 5–15 秒，慢的时候更久；
    // PHP 默认 30 秒会把它掐断，这里单独放宽。
    @set_time_limit(180);
    $hasFile = !empty($_FILES['file']['tmp_name']) && is_uploaded_file($_FILES['file']['tmp_name']);

    if ($act === 'ai_import' || ($act === 'ai_chat' && $hasFile)) {
        // ① 导入一张单据：上传 → OCR/提取 → 匹配 → 生成待确认提案（不入账）
        if (!$hasFile) {
            $err = '请先选择要导入的单据文件（PDF 或图片）';
        } else {
            $up = api_upload('/ai/import', 'file', (string) $_FILES['file']['tmp_name'],
                             (string) $_FILES['file']['name'],
                             ['actor' => $actor,
                              'progressToken' => (string) ($_POST['progressToken'] ?? '')]);
            if ($up['ok']) {
                // OCR 按扩展名选解析器；给无扩展名的 PHP 临时文件建一个本请求内有效的链接。
                $ext = strtolower(pathinfo((string) $_FILES['file']['name'], PATHINFO_EXTENSION));
                if (in_array($ext, ['pdf', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tif', 'tiff', 'txt', 'csv'], true)) {
                    $base = tempnam(sys_get_temp_dir(), 'ledu_ai_');
                    $analysisPath = $base !== false ? $base . '.' . $ext : '';
                    if ($analysisPath !== '') {
                        @unlink($base);
                        if (@symlink((string) $_FILES['file']['tmp_name'], $analysisPath)) {
                            $up['data']['_sourceTmpPath'] = $analysisPath;
                            register_shutdown_function(static function () use ($analysisPath): void {
                                if (is_link($analysisPath)) { @unlink($analysisPath); }
                            });
                        }
                    }
                }
                $cards[] = $up['data'];
            } else {
                $err = (string) $up['error'];
                $errHint = is_array($up['hint'] ?? null) ? $up['hint'] : null;
            }
        }
    } elseif ($act === 'ai_confirm') {
        $fields = [];
        foreach ((array) ($_POST['fields'] ?? []) as $k => $v) {
            if (is_string($v) && trim($v) !== '') { $fields[(string) $k] = trim($v); }
        }
        $answers = [];
        foreach ((array) ($_POST['answers'] ?? []) as $k => $v) {
            if (is_string($v) && $v !== '') { $answers[(string) $k] = $v; }
        }
        $r = api_post('/ai/actions/' . (int) ($_POST['id'] ?? 0) . '/confirm',
                      ['actor' => $actor, 'fields' => $fields,
                       'answers' => $answers,
                       'accountCode' => (string) ($_POST['accountCode'] ?? ''),
                       'creditKey' => (string) ($_POST['creditKey'] ?? 'ap'),
                       'expenseNature' => (string) ($_POST['expenseNature'] ?? ''),
                       'bankAccountId' => (int) ($_POST['bankAccountId'] ?? 0)]);
        if ($r['ok']) {
            $res = $r['data']['result'] ?? [];
            $outcome = ['ok' => true, 'result' => $res,
                        'correction' => $r['data']['correction'] ?? null];
        } else {
            $err = (string) $r['error'];
        }
    } elseif ($act === 'doc_new') {
        $kind = (string) ($_POST['kind'] ?? 'invoice');
        $lines = [];
        foreach ((array) ($_POST['line'] ?? []) as $i => $row) {
            $desc = trim((string) ($row['description'] ?? ''));
            if ($desc === '') { continue; }
            $lines[] = [
                'description' => $desc,
                'quantity'    => (string) ($row['quantity'] ?? '1'),
                'unitPrice'   => (string) ($row['unitPrice'] ?? '0'),
                'taxRate'     => (string) ($row['taxRate'] ?? ''),
            ];
        }
        $payload = [
            'currency'   => (string) ($_POST['currency'] ?? 'HKD'),
            'invoiceDate' => (string) ($_POST['docDate'] ?? date('Y-m-d')),
            'date'       => (string) ($_POST['docDate'] ?? date('Y-m-d')),
            'lines'      => $lines,
            'actor'      => $actor,
            'role'       => $role,
        ];
        // 空字符串会写进 DATE / VARCHAR 校验，宁可不下发这些键
        if (trim((string) ($_POST['dueDate'] ?? '')) !== '') {
            $payload['dueDate'] = (string) $_POST['dueDate'];
        }
        if (trim((string) ($_POST['docNo'] ?? '')) !== '') {
            $payload['invoiceNo'] = (string) $_POST['docNo'];
            $payload['vendorInvoiceNo'] = (string) $_POST['docNo'];
        }
        // 手填单据没有履约义务信息：按「已履行、一次性确认」处理，
        // 否则 HKFRS15 判不出来，分录为空，过账会被自己的校验挡住。
        $payload['performanceObligationStatus'] = 'fulfilled';
        $payload['recognitionPattern'] = 'point_in_time';
        if ($kind === 'invoice') {
            $payload['customerId'] = (int) ($_POST['partyId'] ?? 0) ?: null;
            $payload['customerName'] = trim((string) ($_POST['party'] ?? ''));
        } else {
            $payload['vendorId'] = (int) ($_POST['partyId'] ?? 0) ?: null;
            $payload['vendorName'] = trim((string) ($_POST['party'] ?? ''));
        }
        $r = api_post($kind === 'invoice' ? '/invoices' : '/bills', $payload);
        if ($r['ok']) {
            $d = $r['data'];
            $outcome = ['ok' => true, 'result' => [
                'docType' => $kind,
                'docId' => $kind === 'invoice' ? ($d['invoiceId'] ?? 0) : ($d['billId'] ?? 0),
                'docNo' => $kind === 'invoice' ? ($d['invoiceNo'] ?? '') : ($d['billNo'] ?? ''),
                'href' => $kind === 'invoice'
                    ? '?p=invoice-view&id=' . (int) ($d['invoiceId'] ?? 0)
                    : '?p=bill-view&id=' . (int) ($d['billId'] ?? 0),
            ]];
        } else {
            $err = (string) $r['error'];
        }
    } elseif ($act === 'ai_post') {
        // 在 AI 页面把刚建好的草稿直接记账：仍是人点一下（记账属五件危险动作之一）
        $kind = (string) ($_POST['kind'] ?? 'bill');
        $docId = (int) ($_POST['docId'] ?? 0);
        $r = api_post('/fast/post', ['kind' => $kind, 'docId' => $docId,
                                     'actor' => $actor, 'role' => $role]);
        if ($r['ok']) {
            $outcome = ['ok' => true, 'posted' => $r['data'], 'kind' => $kind, 'docId' => $docId];
        } else {
            $err = (string) $r['error'];
        }
    } elseif ($act === 'ai_cancel') {
        $r = api_post('/ai/actions/' . (int) ($_POST['id'] ?? 0) . '/cancel',
                      ['actor' => $actor]);
        if ($r['ok']) {
            $outcome = ['ok' => true, 'cancelled' => true];
        } else {
            $err = (string) $r['error'];
        }
    } elseif ($blankKind = blank_doc_kind($text)) {
        // 只说「建一张发票，我来填」：不要在聊天里追问，直接给表单
        $newDocKind = $blankKind;
    } elseif ($text !== '') {
        // ② 普通对话
        $r = api_post('/agents/run', [
            'agent' => $agent,
            'text'  => $text,
            'scene' => 'command',
            'actor' => $actor,
            'allowWrite' => $allowWrite,
            'progressToken' => (string) ($_POST['progressToken'] ?? ''),
            // 报表 PDF 跟随界面语言：用户在繁体界面就该拿到繁体报表
            'lang' => function_exists('lang') ? lang() : 'en',
        ]);
        if ($r['ok'] && !empty($r['data']['ok'])) {
            $reply = (string) ($r['data']['text'] ?? '');
            $runId = (int) ($r['data']['runId'] ?? 0);
            $writes = (array) ($r['data']['writes'] ?? []);
            foreach ((array) ($r['data']['proposed'] ?? []) as $p) {
                $cards[] = ['actionId' => (int) $p['actionId'], 'title' => $p['title'],
                            'summary' => $p['summary'], 'actionType' => $p['actionType']];
            }
        } else {
            $err = (string) ($r['error'] ?? ($r['data']['error'] ?? '智能体暂时不可用'));
        }
    }
}

// 页面上还没处理的提案：刷新后也还在，不会因为离开页面就丢
if (!$cards && $outcome === null) {
    $pend = api_get('/ai/actions?status=proposed&limit=3');
    if ($pend['ok']) {
        foreach ((array) ($pend['data']['actions'] ?? []) as $p) {
            $cards[] = ['actionId' => (int) $p['action_id'], 'title' => $p['title'],
                        'summary' => $p['summary'], 'actionType' => $p['action_type']];
        }
    }
}
$since = api_get('/journal?limit=0');
$pending = 0;
if ($since['ok']) {
    foreach (($since['data']['entries'] ?? []) as $x) {
        if (($x['status'] ?? '') === 'draft') { $pending++; }
    }
}
// 首页概览用的今日待办统计（一次调用，四个数字）
$todo = api_get('/workbench/todo');
$todoSum = $todo['ok'] ? (array) ($todo['data']['summary'] ?? []) : [];
$nTotal   = (int) ($todoSum['total'] ?? 0);
$nReview  = (int) ($todoSum['pending'] ?? 0);
$nOverdue = (int) ($todoSum['overdue'] ?? 0);
$nBank    = (int) ($todoSum['bank'] ?? 0);
$agents = $__AGENTS;
?>
<?php
// 空状态：还没有任何对话 —— 把输入框放到屏幕中间，像开始一件事，而不是打开一个后台
$__hasContent = ($text !== '') || $err || $reply || !empty($pending) || !empty($cards);
?>
<div class="aiw" id="aiShell">
  <aside class="aiw-rail">
    <p class="aiw-sec-h"><?= e(t('快捷指令')) ?></p>
    <div class="aiw-navs">
      <button type="button" class="aiw-nav" data-fill="<?= e(t('这个月赚了多少')) ?>"><?= e(t('查账')) ?><i><?= e(t('收入、费用、净利')) ?></i></button>
      <button type="button" class="aiw-nav" data-fill="<?= e(t('给客户开一张发票')) ?>"><?= e(t('开单')) ?><i><?= e(t('生成发票或账单草稿')) ?></i></button>
      <button type="button" class="aiw-nav" data-fill="<?= e(t('把这个月的发票都记了')) ?>"><?= e(t('记账')) ?><i><?= e(t('批量过账，逐张确认')) ?></i></button>
      <button type="button" class="aiw-nav" data-fill="<?= e(t('把 11 月银行流水对一下')) ?>"><?= e(t('对账')) ?><i><?= e(t('匹配流水与单据')) ?></i></button>
      <button type="button" class="aiw-nav" data-fill="<?= e(t('给我这个月的利润表 PDF')) ?>"><?= e(t('出报表')) ?><i><?= e(t('利润表、资产负债表')) ?></i></button>
      <button type="button" class="aiw-nav" data-fill="<?= e(t('请在这里显示本月月结六步进度与缺口，并给出可继续办理的建议')) ?>"><?= e(t('月结')) ?><i><?= e(t('六步进度与缺口')) ?></i></button>
    </div>

    <p class="aiw-sec-h"><?= e(t('由谁处理')) ?></p>
    <div class="aiw-roles">
      <?php foreach ($agents as $k => $v): ?>
        <a class="aiw-role<?= $k === $agent ? ' is-on' : '' ?>" href="?p=command&agent=<?= e($k) ?>"><?= e(t($v)) ?></a>
      <?php endforeach; ?>
    </div>
  </aside>

  <?php
  $__recent = api_get('/journal?limit=6');
  $__rows = $__recent['ok'] ? ($__recent['data']['entries'] ?? []) : [];
  ?>
  <div class="ai-main aiw-main">
    <header class="aiw-head">
      <div>
        <h1><?= e(t('AI 工作台')) ?></h1>
        <p>
          <span class="mono"><?= e($todayLabel ?? date('Y-m-d')) ?></span>
          <span><?= e(t('与')) ?> <?= e(t($agents[$agent] ?? $agents['controller'])) ?> <?= e(t('对话中')) ?></span>
          <?php if ($allowWrite): ?>
            <span class="aiw-chip is-warn"><?= e(t('可直接执行')) ?></span>
            <a class="ai-link" href="?p=command&agentwrite=0"><?= e(t('改为只提案')) ?></a>
          <?php else: ?>
            <span class="aiw-chip is-ok"><?= e(t('只提案')) ?></span>
            <a class="ai-link" href="?p=command&agentwrite=1"><?= e(t('改为可直接执行')) ?></a>
          <?php endif; ?>
        </p>
      </div>
      <div class="aiw-head-r">
        <button type="button" class="aiw-btn" id="aiRecentBtn"><?= e(t('最近记账')) ?></button>
        <?php if ($__hasContent): ?>
          <a class="aiw-btn" href="?p=command"><?= e(t('新对话')) ?></a>
        <?php endif; ?>
      </div>
    </header>

    <?= help_html('command') ?>

    <div class="ai-drawer" id="aiRecentDrawer" hidden>
      <?php foreach ($__rows as $x): ?>
        <div class="ai-drawer-row">
          <span class="mono"><?= e((string) $x['entry_no']) ?></span>
          <span class="ai-drawer-desc"><?= e((string) ($x['description'] ?? '')) ?></span>
          <span class="hint"><?= e((string) $x['entry_date']) ?></span>
          <span class="num"><?= money($x['total_debit'], 'HKD') ?></span>
        </div>
      <?php endforeach; ?>
    </div>

  <div class="cmd-log" id="cmdLog">
    <?php if (!$__hasContent): ?>
    <section class="aiw-welcome">
      <h2><?= e(t('今天要做什么？')) ?></h2>
      <p><?= e(t('说一句就行：建单、记账、对账、查数。写进账前一定会给你确认卡片，AI 不能自己记账。')) ?></p>

      <div class="aiw-stats">
        <button type="button" class="aiw-stat" data-fill="<?= e(t('请在这里列出我的待处理事项，并给出可直接办理的建议')) ?>">
          <span><?= e(t('待处理')) ?></span><b><?= $nTotal ?><i><?= e(t('条')) ?></i></b>
        </button>
        <button type="button" class="aiw-stat<?= $nReview ? ' is-amber' : '' ?>" data-fill="<?= e(t('请在这里列出待复核单据，并给出可确认的复核操作')) ?>">
          <span><?= e(t('待复核')) ?></span><b><?= $nReview ?><i><?= e(t('条')) ?></i></b>
        </button>
        <button type="button" class="aiw-stat<?= $nOverdue ? ' is-red' : '' ?>" data-fill="<?= e(t('请在这里列出逾期应收及账龄，并给出跟进建议')) ?>">
          <span><?= e(t('逾期应收')) ?></span><b><?= $nOverdue ?><i><?= e(t('笔')) ?></i></b>
        </button>
        <button type="button" class="aiw-stat<?= $nBank ? ' is-blue' : '' ?>" data-fill="<?= e(t('请在这里列出未匹配银行流水，并提出逐笔核销建议')) ?>">
          <span><?= e(t('未匹配流水')) ?></span><b><?= $nBank ?><i><?= e(t('笔')) ?></i></b>
        </button>
      </div>

      <p class="aiw-try"><?= e(t('试试这样问')) ?></p>
      <div class="aiw-sug">
        <button type="button" class="aiw-sug-b" data-fill="<?= e(t('这个月赚了多少')) ?>">
          <b><?= e(t('这个月赚了多少')) ?></b><span><?= e(t('收入、费用、净利，一句话给数')) ?></span>
        </button>
        <button type="button" class="aiw-sug-b" data-fill="<?= e(t('谁还欠我钱')) ?>">
          <b><?= e(t('谁还欠我钱')) ?></b><span><?= e(t('应收账龄与未结发票')) ?></span>
        </button>
        <button type="button" class="aiw-sug-b" data-fill="<?= e(t('把 11 月银行流水对一下')) ?>">
          <b><?= e(t('把流水对一下')) ?></b><span><?= e(t('未匹配流水与候选单据')) ?></span>
        </button>
        <button type="button" class="aiw-sug-b" data-fill="<?= e(t('看看这个月的月结状态')) ?>">
          <b><?= e(t('看月结状态')) ?></b><span><?= e(t('六步进度与缺口')) ?></span>
        </button>
      </div>
    </section>
    <?php endif; ?>



    <?php if ($text !== ''): ?>
      <div class="cmd-row cmd-user"><div class="cmd-bubble"><?= e($text) ?></div></div>
    <?php endif; ?>

    <?php if ($err): ?>
      <div class="cmd-row cmd-ai">
        <div class="cmd-avatar">AI</div>
        <div class="cmd-bubble cmd-error">
          <?php if ($errHint === null): ?><?= e(t('没听懂或智能体不可用：')) ?><?php endif; ?><?= e(t($err)) ?>
          <?php if ($errHint): ?>
            <?php
              $hintPage = (string) ($errHint['page'] ?? 'dashboard');
              $manualIntents = [
                  'invoice-new' => '建一张销售发票，我来填',
                  'bill-new' => '建一张采购账单，我来填',
                  'expense-new' => '我要登记一笔费用，请在这里给我录入表单或待确认提案，不要跳转页面',
                  'journal-new' => '我要新建一张手工凭证，请在这里给我待确认提案，不要跳转页面',
                  'bank-import' => '我要导入银行对账单；我会上传 CSV、XLSX 或 PDF 附件，请在这里解析并给我确认卡片',
              ];
            ?>
            <div class="cmd-actions">
              <?php if (isset($manualIntents[$hintPage])): ?>
                <button type="button" class="btn" data-fill="<?= e(t($manualIntents[$hintPage])) ?>">
                  <?= e(t((string) ($errHint['label'] ?? '在这里录入'))) ?>
                </button>
                <span class="hint"><?= e(t('已在工作台预填指令，无需跳转人工录入页')) ?></span>
              <?php else: ?>
                <button type="button" class="btn"
                        data-fill="<?= e(t('请在这里帮我') . t((string) ($errHint['label'] ?? '继续处理')) . t('；不要跳转人工页面，如需附件或确认卡片请直接告诉我。')) ?>">
                  <?= e(t((string) ($errHint['label'] ?? '在这里处理'))) ?>
                </button>
                <span class="hint"><?= e(t('留在工作台继续，不跳转人工页面')) ?></span>
              <?php endif; ?>
            </div>
          <?php else: ?>
            <div class="hint" style="margin-top:8px"><?= e(t('可以换个说法再试一次，或上传原件让我重新识别。')) ?></div>
          <?php endif; ?>
        </div>
      </div>
    <?php elseif ($reply !== null): ?>
      <div class="cmd-row cmd-ai">
        <div class="cmd-avatar">AI</div>
        <div class="cmd-bubble">
          <?= $fmt($reply) ?>
          <?php if ($writes): ?>
            <div class="ai-writes">
              <div class="ai-writes-h"><?= e(t('本轮写入了这些')) ?></div>
              <?php foreach ($writes as $w): ?>
                <?php
                  $dw = (string) ($w['danger'] ?? '');
                  $cls = in_array($dw, ['post', 'reverse', 'lock'], true) ? 'danger'
                       : (in_array($dw, ['cash'], true) ? 'warn' : 'info');
                  $res = $w['result'] ?? [];
                ?>
                <div class="ai-write-row">
                  <span class="tag tag-<?= e($cls) ?>"><?= e((string) ($w['tool'] ?? '')) ?></span>
                  <?php if (!empty($w['docNo'])): ?>
                    <b class="mono"><?= e((string) $w['docNo']) ?></b>
                  <?php endif; ?>
                  <?php if (!empty($res['entryNo'])): ?>
                    <span class="hint"><?= e(t('凭证')) ?> <?= e((string) $res['entryNo']) ?></span>
                  <?php endif; ?>
                  <?php if (!empty($w['error'])): ?>
                    <span class="hint" style="color:var(--c-danger)"><?= e((string) $w['error']) ?></span>
                  <?php endif; ?>
                  <?php
                    // 智能体刚建好的草稿，就地给一个「现在记账」，不用跳页面
                    $wtool = (string) ($w['tool'] ?? '');
                    $wkind = str_starts_with($wtool, 'create_invoice') ? 'invoice'
                           : (str_starts_with($wtool, 'create_bill') ? 'bill' : '');
                    $wid = (int) ($res['docId'] ?? 0);
                  ?>
                  <?php if ($wkind !== '' && $wid > 0 && ($res['status'] ?? '') === 'draft'): ?>
                    <form method="post" style="margin:0;display:inline">
                      <?= csrf_field() ?>
                      <input type="hidden" name="action" value="ai_post">
                      <input type="hidden" name="kind" value="<?= e($wkind) ?>">
                      <input type="hidden" name="docId" value="<?= $wid ?>">
                      <button class="btn sm" type="submit"
                        data-confirm="<?= e(t('确认现在记账？')) ?>"
                        data-confirm-note="<?= e(t('将依次执行：提交复核 → 批准 → 记账。记账后不可修改或删除，只能冲销。')) ?>"
                        data-confirm-ok="<?= e(t('确认记账')) ?>"><?= e(t('现在记账')) ?></button>
                    </form>
                  <?php endif; ?>
                </div>
              <?php endforeach; ?>
            </div>
          <?php endif; ?>
          <?php
            $files = [];
            foreach ((array) ($r['data']['tools'] ?? []) as $tw) {
                if (!empty($tw['file']['href'])) { $files[] = $tw['file']; }
            }
          ?>
          <?php if ($files): ?>
            <div class="ai-files">
              <?php foreach ($files as $f): ?>
                <?php
                  $lmap = ['zh_hk' => t('繁體'), 'zh_cn' => t('简体'), 'en' => 'EN'];
                  $llab = $lmap[(string) ($f['lang'] ?? '')] ?? '';
                ?>
                <a class="btn primary sm" href="<?= e((string) $f['href']) ?>" download>
                  <?= e(t('下载 PDF')) ?><?= $llab !== '' ? ' · ' . e($llab) : '' ?>
                  <?= $f['from'] ? ' · ' . e((string) $f['from']) . ' ~ ' . e((string) $f['to']) : '' ?>
                </a>
              <?php endforeach; ?>
            </div>
          <?php endif; ?>
          <div class="cmd-actions">
            <span class="hint"><?= e(t('AI 辅助，需人工复核')) ?></span>
          </div>
        </div>
      </div>
    <?php endif; ?>

    <?php if ($err === null && $cards): ?>
      <?php foreach ($cards as $c): ?>
        <div class="cmd-row cmd-ai">
          <div class="cmd-avatar">AI</div>
          <div class="cmd-bubble"><?= $renderCard($c) ?></div>
        </div>
      <?php endforeach; ?>
    <?php endif; ?>

    <?php if ($outcome !== null): ?>
      <div class="cmd-row cmd-ai">
        <div class="cmd-avatar">AI</div>
        <div class="cmd-bubble cmd-out">
          <?php if (!empty($outcome['cancelled'])): ?>
            <?= e(t('已放弃，这张单据没有写进系统。')) ?>
          <?php else: ?>
            <?php $res = $outcome['result'] ?? []; ?>
            <?php if (isset($res['docNo'])): ?>
              <?php $tlab = ['bill' => t('采购发票'), 'invoice' => t('销售发票'),
                             'expense' => t('费用'), 'opening' => t('上年结转分录')]
                             [(string) ($res['docType'] ?? '')]
                             ?? (string) ($res['docType'] ?? ''); ?>
              <?= e(t('已建单')) ?> <b><?= e((string) $res['docNo']) ?></b>
              <span class="hint"><?= e($tlab) ?> ·
                <?= e(($res['status'] ?? '') === 'posted' ? t('已入账') : t('草稿，未入账')) ?></span>
              <?php if (!empty($outcome['correction']['recorded']) && !empty($outcome['correction']['changed'])): ?>
                <div class="hint" style="margin-top:4px">
                  <?= e(t('已记住这次的修改')) ?>：
                  <?php
                    $chg = array_map(fn($c) => t($c['field']) . ' ' . $c['from'] . ' → ' . $c['to'],
                                     (array) ($outcome['correction']['changed'] ?? []));
                    echo e(implode('；', $chg));
                  ?>
                </div>
              <?php endif; ?>
              <?php if (!empty($res['attachment']['ok'])): ?>
                <div class="hint" style="margin-top:4px">
                  <?= e(t('原件已附上')) ?> · <?= e((string) ($res['attachment']['fileName'] ?? '')) ?>
                  · SHA-256 <?= e(substr((string) ($res['attachment']['sha256'] ?? ''), 0, 12)) ?>…
                </div>
              <?php elseif (!empty($res['attachment']['error'])): ?>
                <div class="hint" style="margin-top:4px;color:var(--c-warn)">
                  <?= e(t('单据已建，但原件没挂上')) ?> · <?= e((string) $res['attachment']['error']) ?>
                </div>
              <?php endif; ?>
              <div class="cmd-actions" style="flex-wrap:wrap">
                <?php if (($res['docType'] ?? '') === 'bill' || ($res['docType'] ?? '') === 'invoice'): ?>
                  <form method="post" style="margin:0">
                    <?= csrf_field() ?>
                    <input type="hidden" name="action" value="ai_post">
                    <input type="hidden" name="kind" value="<?= e((string) $res['docType']) ?>">
                    <input type="hidden" name="docId" value="<?= (int) ($res['docId'] ?? 0) ?>">
                    <button class="btn primary" type="submit"
                      data-confirm="<?= e(t('确认现在记账？')) ?>"
                      data-confirm-note="<?= e(t('将依次执行：提交复核 → 批准 → 记账。记账后不可修改或删除，只能冲销。')) ?>"
                      data-confirm-ok="<?= e(t('确认记账')) ?>"><?= e(t('现在记账')) ?></button>
                  </form>
                <?php endif; ?>
                <button type="button" class="btn" data-fill="<?= e(t('请在这里显示单据') . ' ' . (string) ($res['docNo'] ?? '') . t(' 的完整内容、状态和后续可办事项，不要跳转页面')) ?>"><?= e(t('看单据')) ?></button>
                <span class="hint"><?= e(t('不记账也可以，先放着')) ?></span>
              </div>
            <?php elseif (!empty($outcome['posted'])): ?>
              <?php $pd = $outcome['posted']; ?>
              <?= e(t('已记账')) ?> · <?= e(t('凭证')) ?> <b><?= e((string) ($pd['entryNo'] ?? '')) ?></b>
              <span class="hint"><?= e(implode(' → ', array_map(fn($x) => t((string) $x), (array) ($pd['steps'] ?? [])))) ?></span>
              <div class="cmd-actions">
                <button type="button" class="btn" data-fill="<?= e(t('请在这里显示单据') . ' ' . (string) ($outcome['docNo'] ?? $pd['entryNo'] ?? '') . t(' 的完整内容、状态和后续可办事项，不要跳转页面')) ?>">
                  <?= e(t('看单据')) ?>
                </button>
              </div>
            <?php elseif (isset($res['imported'])): ?>
              <?php if (!empty($res['duplicate'])): ?>
                <?= e(t('这份对账单之前已导入过')) ?>
                （<?= (int) ($res['skipped'] ?? 0) ?> <?= e(t('笔已存在')) ?>），<?= e(t('本次只做了匹配')) ?> ·
              <?php else: ?>
                <?= e(t('已导入流水')) ?> <b><?= (int) $res['imported'] ?></b> <?= e(t('笔')) ?>
                <?php if (!empty($res['skipped'])): ?>
                  （<?= e(t('重复跳过')) ?> <?= (int) $res['skipped'] ?> <?= e(t('笔')) ?>）
                <?php endif; ?> ·
              <?php endif; ?>
              <?= e(t('自动核销')) ?> <b><?= (int) ($res['matched'] ?? 0) ?></b> <?= e(t('笔')) ?> ·
              <?= e(t('待对账')) ?> <?= (int) ($res['pending'] ?? 0) ?> ·
              <?= e(t('无候选')) ?> <?= (int) ($res['unmatched'] ?? 0) ?>
              <div class="cmd-actions">
                <?php if (($res['pending'] ?? 0) + ($res['unmatched'] ?? 0) > 0): ?>
                  <form method="post" style="margin:0">
                    <?= csrf_field() ?>
                    <input type="hidden" name="action" value="ai_chat">
                    <input type="hidden" name="agent" value="cashier">
                    <input type="hidden" name="text" value="<?= e(t('把这次导入的流水逐笔对一下，能确定的直接确认，不确定的列出来')) ?>">
                    <button class="btn primary" type="submit"><?= e(t('让出纳继续对完')) ?></button>
                  </form>
                <?php endif; ?>
                <button type="button" class="btn" data-fill="<?= e(t('请在这里显示本次对账的未匹配流水、匹配结果和后续核销建议') . ' (batchId=' . (int) ($res['batchId'] ?? 0) . ')') ?>"><?= e(t('看对账明细')) ?></button>
              </div>
            <?php elseif (isset($res['docs'])): ?>
              <?= e(t('已记账')) ?>：<?= (int) ($res['ok'] ?? 0) ?>/<?= (int) $res['docs'] ?> <?= e(t('张')) ?>
              <?php if (!empty($res['failed'])): ?>，<?= e(t('失败')) ?> <?= (int) $res['failed'] ?><?php endif; ?>
            <?php else: ?>
              <?= e(t('已执行')) ?>
            <?php endif; ?>
          <?php endif; ?>
        </div>
      </div>
    <?php endif; ?>
  </div>

  <?php if (($newDocKind ?? null) !== null): ?>
    <?php $isInv = $newDocKind === 'invoice'; ?>
    <div class="card newdoc">
      <div class="card-head">
        <h2 class="card-title"><?= e($isInv ? t('新建销售发票') : t('新建采购账单')) ?></h2>
        <span class="hint"><?= e(t('填完直接建草稿，不用去别的页面')) ?></span>
      </div>
      <form method="post" class="newdoc-form">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="doc_new">
        <input type="hidden" name="kind" value="<?= e($newDocKind) ?>">
        <div class="newdoc-grid">
          <label class="field"><span class="f"><?= e($isInv ? t('客户') : t('供应商')) ?></span>
            <input type="text" name="party" required placeholder="<?= e(t('名称，可稍后建档')) ?>"></label>
          <label class="field"><span class="f"><?= e(t('日期')) ?></span>
            <input type="date" name="docDate" value="<?= e(date('Y-m-d')) ?>"></label>
          <label class="field"><span class="f"><?= e(t('到期日')) ?></span>
            <input type="date" name="dueDate"></label>
          <label class="field"><span class="f"><?= e(t('币种')) ?></span>
            <select name="currency">
              <option>HKD</option><option>USD</option><option>CNY</option>
            </select></label>
          <label class="field"><span class="f"><?= e(t('对方单号')) ?></span>
            <input type="text" name="docNo" placeholder="<?= e(t('可空')) ?>"></label>
        </div>
        <table class="newdoc-lines">
          <thead><tr>
            <th><?= e(t('摘要')) ?></th><th style="width:90px"><?= e(t('数量')) ?></th>
            <th style="width:120px"><?= e(t('单价')) ?></th>
            <th style="width:90px"><?= e(t('税率')) ?>%</th><th style="width:44px"></th>
          </tr></thead>
          <tbody id="newdocLines">
            <tr>
              <td><input type="text" name="line[0][description]" placeholder="<?= e(t('写清楚是什么')) ?>"></td>
              <td><input type="number" step="0.01" name="line[0][quantity]" value="1"></td>
              <td><input type="number" step="0.01" name="line[0][unitPrice]" value="0"></td>
              <td><input type="number" step="0.01" name="line[0][taxRate]" value=""></td>
              <td><button type="button" class="btn sm ghost rmline" aria-label="<?= e(t('删掉这行')) ?>">×</button></td>
            </tr>
          </tbody>
        </table>
        <div class="newdoc-actions">
          <button type="button" class="btn sm" id="newdocAdd"><?= e(t('加一行')) ?></button>
          <button type="submit" class="btn primary"><?= e(t('建这张单')) ?></button>
          <a class="btn" href="?p=command"><?= e(t('先不建')) ?></a>
        </div>
      </form>
    </div>
    <script>
    (function () {
      var body = document.getElementById('newdocLines');
      var add = document.getElementById('newdocAdd');
      var n = 1;
      if (add) add.addEventListener('click', function () {
        var tr = body.rows[0].cloneNode(true);
        tr.querySelectorAll('input').forEach(function (el) {
          el.name = el.name.replace(/line\[\d+\]/, 'line[' + n + ']');
          if (el.name.indexOf('quantity') > -1) el.value = '1';
          else if (el.name.indexOf('unitPrice') > -1) el.value = '0';
          else el.value = '';
        });
        body.appendChild(tr); n++;
      });
      body.addEventListener('click', function (e) {
        if (e.target.classList.contains('rmline') && body.rows.length > 1) {
          e.target.closest('tr').remove();
        }
      });
    })();
    </script>
  <?php endif; ?>

  <form method="post" class="composer" enctype="multipart/form-data" id="cmdForm">
    <?= csrf_field() ?>
    <input type="hidden" name="progressToken" id="cmdTok" value="">
    <div class="composer-box">
      <textarea name="text" id="cmdText" rows="1" autocomplete="off"
        placeholder="<?= e(t('给 AI 下指令，或直接贴一段文字……')) ?>"></textarea>
      <div class="composer-bar">
        <div class="composer-left">
          <select name="agent" class="composer-agent" aria-label="<?= e(t('由谁处理')) ?>">
            <?php foreach ($agents as $k => $v): ?>
              <option value="<?= e($k) ?>" <?= $k === $agent ? 'selected' : '' ?>><?= e(t($v)) ?></option>
            <?php endforeach; ?>
          </select>
          <input type="file" id="cmdFile" name="file"
                 accept="image/*,application/pdf,.pdf,.csv,.txt,.xlsx,.xls" hidden>
          <button type="button" class="composer-attach" id="cmdCameraBtn"
                  title="<?= e(t('调用手机后置相机拍摄票据，识别后先给你确认')) ?>">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
              <circle cx="12" cy="13" r="3.5"/>
            </svg>
            <span><?= e(t('拍摄票据')) ?></span>
          </button>
          <button type="button" class="composer-attach" id="cmdAttachBtn"
                  title="<?= e(t('从相册或文件中选择图片、PDF、CSV、XLSX；识别后先给你确认')) ?>">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21.4 11.6l-8.5 8.5a5.5 5.5 0 0 1-7.8-7.8l8.6-8.5a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.5a1.8 1.8 0 0 1-2.6-2.6l7.9-7.8"/>
            </svg>
            <span id="cmdFileName"><?= e(t('上传附件')) ?></span>
          </button>
        </div>
        <div class="composer-right">
          <span class="composer-hint" id="cmdHint"><?= e(t('Enter 发送 · Shift+Enter 换行')) ?></span>
          <button class="composer-send" type="submit" name="action" value="ai_chat" id="cmdSend"
                  aria-label="<?= e(t('发送')) ?>">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M12 19V5M5 12l7-7 7 7"/>
            </svg>
          </button>
        </div>
      </div>
      <div id="cmdBusy" class="composer-busy" hidden>
        <span class="spinner" aria-hidden="true"></span>
        <b id="cmdBusyStage"><?= e(t('正在处理')) ?></b>
        <span class="hint" id="cmdBusyHint"><?= e(t('已经用了 0 秒')) ?></span>
      </div>
    </div>
    <div class="composer-foot">
      <span class="hint"><?= e(t('支持拍照或选择图片、PDF；识别与建单都会先给确认卡片，确认才写账')) ?></span>
      <button type="button" class="link-btn" id="cmdClear"><?= e(t('清空这一屏（日志保留）')) ?></button>
    </div>
  </form>
  </div><!-- /ai-main -->


</div>
<script>
/**
 * 提交时不整页跳转，改用 fetch：整页提交会让浏览器冻结旧页面，
 * 计时器与进度轮询都会停，用户看到的就永远是「0 秒」。
 * 拿到 HTML 后再 document.write 换上去，URL 与脚本都照常。
 */
(function () {
  var form = document.getElementById('cmdForm');
  if (!form) return;
  var tok = document.getElementById('cmdTok');
  var busy = document.getElementById('cmdBusy');
  var stageEl = document.getElementById('cmdBusyStage');
  var hintEl = document.getElementById('cmdBusyHint');
  var tplElapsed = <?= json_encode(t('已经用了 {s} 秒'), JSON_UNESCAPED_UNICODE) ?>;
  var lblReading = <?= json_encode(t('正在读取文件…'), JSON_UNESCAPED_UNICODE) ?>;
  var lblThink = <?= json_encode(t('正在处理你的问题…'), JSON_UNESCAPED_UNICODE) ?>;
  var lblSlow = <?= json_encode(t('这一步要 OCR + 模型，通常 5–15 秒；超过 60 秒请刷新重试'), JSON_UNESCAPED_UNICODE) ?>;
  var STAGES = <?= json_encode([
      'start' => t('收到，开始处理'),
      'ocr' => t('正在读取文件并提取文字（OCR）'),
      'classify' => t('正在判断这是发票还是对账单'),
      'parse_statement' => t('正在解析对账单流水'),
      'extract' => t('正在用模型识别字段（金额、日期、往来单位）'),
      'propose' => t('正在核对往来单位、科目与重复单据'),
      'agent' => t('正在理解你的问题'),
      'done' => t('识别完成'),
  ], JSON_UNESCAPED_UNICODE) ?>;
  var start = 0, timer = null, poll = null, running = false;

  function tick() {
    var s = Math.round((Date.now() - start) / 1000);
    hintEl.textContent = tplElapsed.replace('{s}', s) + (s >= 20 ? ' · ' + lblSlow : '');
  }
  function stop() {
    running = false;
    if (timer) { clearInterval(timer); timer = null; }
    if (poll) { clearInterval(poll); poll = null; }
  }

  form.addEventListener('submit', function (ev) {
    if (running) { ev.preventDefault(); return; }
    var btn = ev.submitter || document.activeElement;
    var isImport = btn && btn.value === 'ai_import';
    // 只读动作（发送 / 识别）走 fetch；记账这类很快的操作保持普通提交
    ev.preventDefault();
    var t = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    tok.value = t;
    var fd = new FormData(form);
    fd.set('action', isImport ? 'ai_import' : 'ai_chat');
    fd.set('progressToken', t);

    running = true;
    // 记下这次发出去的原话：响应回来时只清「还是这句」的输入框，
    // 用户等待期间已经敲的下一句不会被清掉
    try { sessionStorage.setItem('ledu_sent', String(fd.get('text') || '')); } catch (e) {}
    start = Date.now();
    busy.hidden = false;
    stageEl.textContent = isImport ? lblReading : lblThink;
    tick();
    timer = setInterval(tick, 1000);

    {
      poll = setInterval(function () {
        fetch('/pdf/progress.php?tok=' + encodeURIComponent(t))
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d) { return; }
            var txt = (d.stage && STAGES[d.stage]) || d.label;
            if (txt) { stageEl.textContent = txt; }
          })
          .catch(function () {});
      }, 1200);
    }

    fetch(window.location.href, {method: 'POST', body: fd, credentials: 'same-origin'})
      .then(function (r) { return r.text(); })
      .then(function (html) {
        stop();
        busy.hidden = true;
        // 只换 main 的内容：整页重写会丢掉已绑定的事件与滚动位置，
        // 而本页的交互都是 document 级委托，换内容不会失效。
        try {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          var fresh = doc.querySelector('main');
          var here = document.querySelector('main');
          if (fresh && here) {
            here.innerHTML = fresh.innerHTML;
            // innerHTML 里插入的 <script> 不会执行，需要重新创建节点
            here.querySelectorAll('script').forEach(function (old) {
              var sc = document.createElement('script');
              if (old.src) { sc.src = old.src; } else { sc.textContent = old.textContent; }
              old.parentNode.replaceChild(sc, old);
            });
            window.scrollTo(0, 0);
            // 浏览器会把刚才输入的内容恢复回来；只清「还是刚发出去那句」的情况
            var t2 = document.getElementById('cmdText');
            try {
              var sent = sessionStorage.getItem('ledu_sent') || '';
              if (t2 && sent !== '' && t2.value.trim() === sent.trim()) {
                t2.value = ''; t2.style.height = 'auto';
              }
              sessionStorage.removeItem('ledu_sent');
            } catch (e) {}
            return;
          }
        } catch (e) {}
        document.open(); document.write(html); document.close();
      })
      .catch(function () {
        stop();
        busy.hidden = true;
        alert(<?= json_encode(t('提交失败，请刷新后重试'), JSON_UNESCAPED_UNICODE) ?>);
      });
  });

  window.addEventListener('pageshow', function () { stop(); if (busy) busy.hidden = true; });
})();
</script>

<style>
.cmd-shell{display:grid;grid-template-columns:264px minmax(0,1fr);gap:0;align-items:stretch;
  height:calc(100vh - var(--topbar-h));max-width:none;margin:0;width:100%;
  overflow:hidden}   /* 整页不滚：左右各自滚，滚动条不抖 */
@media (max-width:1100px){.cmd-shell{grid-template-columns:minmax(0,1fr);height:auto;overflow:visible}}
.cmd-log{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:18px;
  padding:20px 24px 24px}
.cmd-hello h1{font-size:var(--f-2xl);font-weight:400;letter-spacing:-.02em;margin:0 0 6px}
.cmd-mode{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px}
.cmd-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.chip-btn{border:1px solid var(--c-border);background:var(--c-surface);color:var(--c-text-2);
  border-radius:var(--r-pill);padding:7px 14px;font-size:var(--f-xs);cursor:pointer;font-family:inherit}
.chip-btn:hover{background:var(--c-surface-alt);color:var(--c-text)}
.cmd-row{display:flex;gap:10px;align-items:flex-start;min-width:0}
.cmd-ai{min-width:0}
.cmd-ai .cmd-bubble{flex:1 1 auto;min-width:0}
.cmd-user{justify-content:flex-end}
.cmd-user .cmd-bubble{background:var(--c-primary);color:#fff;border-radius:12px 12px 3px 12px}
.cmd-ai .cmd-bubble{background:var(--c-surface);border:1px solid var(--c-border);
  border-radius:12px 12px 12px 3px}
.cmd-bubble{padding:12px 16px;font-size:var(--f-sm);line-height:1.75;max-width:640px;
  min-width:0;white-space:pre-wrap;overflow-wrap:anywhere}
.cmd-bubble b{font-weight:600}
.cmd-table{border-collapse:collapse;margin:8px 0;font-size:var(--f-xs);white-space:normal;
  display:block;overflow-x:auto;max-width:100%;min-width:0}
/* 手机端全局 table{min-width:560px} 是给 .table-wrap 用的，聊天气泡里的表不能被它撑开 */
.cmd-bubble .cmd-table{min-width:0}
.cmd-table th,.cmd-table td{border-bottom:1px solid var(--c-border);padding:6px 10px;text-align:left}
.cmd-table th{background:var(--c-surface-alt);font-weight:400;color:var(--c-text-3);
  font-size:var(--f-2xs);letter-spacing:.04em;white-space:nowrap}
.cmd-table td.num,.cmd-table th.num{text-align:right;font-family:var(--mono);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.cmd-file{cursor:pointer;display:inline-flex;align-items:center;white-space:nowrap}
.cmd-file.has-file{border-color:var(--c-primary);color:var(--c-primary)}
/* 待确认卡片 */
.ai-card{border:1px solid var(--c-border);border-radius:var(--r-md);padding:12px 14px;
  background:var(--c-surface)}
.ai-card-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.ai-card-title{font-size:var(--f-sm);color:var(--c-text)}
.ai-fields th{width:132px;white-space:nowrap;color:var(--c-text-3);font-weight:400;
  background:none;padding-left:0}
.ai-fields td{padding-left:0}
.ai-fields tr.strong td{color:var(--c-text)}
.ai-match{margin-top:6px;font-size:var(--f-xs);color:var(--c-text-2)}
.ai-match.ok{color:var(--c-ok)}
.ai-risks{margin-top:8px;padding:8px 10px;border-radius:var(--r-sm);
  background:var(--c-warn-soft);border:1px solid var(--c-warn-border);
  color:var(--c-warn);font-size:var(--f-2xs);line-height:1.7}
.ai-after{margin-top:8px;font-size:var(--f-2xs);color:var(--c-text-3)}
.ai-card-actions{display:flex;gap:8px;margin-top:12px;padding-top:10px;
  border-top:1px solid var(--c-border)}
/* 结果气泡：模板里的缩进不能当正文显示 */
.cmd-out{white-space:normal}
/* 本轮写入清单：记账/冲销/锁账用红色，收付款用橙色，建单用蓝色 */
.ai-asks{margin-top:10px;padding:10px 12px;border:1px solid var(--c-warn-border);
  border-radius:var(--r-sm);background:var(--c-warn-soft)}
.ai-asks-h{font-size:var(--f-2xs);color:var(--c-warn);letter-spacing:.06em;margin-bottom:6px}
.ai-ask{margin:8px 0}
.ai-ask-q{font-size:var(--f-xs);color:var(--c-text);margin-bottom:4px}
.ai-opt{display:flex;align-items:center;gap:6px;font-size:var(--f-xs);color:var(--c-text-2);
  padding:3px 0;cursor:pointer}
.ai-opt input{width:auto;height:auto;margin:0}
.ai-opt em{font-style:normal;color:var(--c-ok);margin-left:6px;font-size:var(--f-2xs)}
.ai-edit{margin-top:10px;padding:10px 12px;border:1px solid var(--c-border);
  border-radius:var(--r-sm);background:var(--c-surface-alt)}
.ai-edit-h{font-size:var(--f-2xs);color:var(--c-text-3);margin-bottom:6px;letter-spacing:.04em}
.ai-edit-row{display:grid;grid-template-columns:96px minmax(0,1fr);gap:8px;align-items:center;
  margin:4px 0;font-size:var(--f-xs);color:var(--c-text-2)}
.ai-edit-row input{height:30px;font-size:var(--f-xs)}
.ai-writes{margin-top:12px;padding:10px 12px;border-radius:var(--r-sm);
  background:var(--c-surface-alt);border:1px solid var(--c-border);white-space:normal}
.ai-writes-h{font-size:var(--f-2xs);color:var(--c-text-3);margin-bottom:6px;letter-spacing:.04em}
.ai-write-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:3px 0}
.ai-write-row b{font-size:var(--f-xs);font-weight:400}
.cmd-empty{display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:28px 0;color:var(--c-text-3)}
.cmd-avatar{width:26px;height:26px;border-radius:50%;background:var(--c-primary-soft);
  color:var(--c-primary);display:grid;place-items:center;font-size:var(--f-2xs);flex-shrink:0;margin-top:2px}
.cmd-error{border-color:#FECACA;background:#FEF2F2;color:#B91C1C}
.cmd-actions{display:flex;gap:10px;align-items:center;margin-top:12px;padding-top:10px;
  border-top:1px solid var(--c-border)}
.ai-files{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.newdoc{margin-bottom:12px}
.newdoc-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px 12px;margin-bottom:10px}
.newdoc-lines{width:100%;border-collapse:collapse;margin-bottom:10px}
.newdoc-lines th{font-size:var(--f-2xs);color:var(--c-text-3);text-align:left;padding:6px 4px;font-weight:400}
.newdoc-lines td{padding:4px}
.newdoc-lines input{height:32px}
.newdoc-actions{display:flex;gap:8px;align-items:center}
@media (max-width:720px){
  .newdoc-grid{grid-template-columns:1fr}
  .newdoc-lines th:nth-child(3),.newdoc-lines td:nth-child(3){display:none}
}
.spinner{width:15px;height:15px;border:2px solid var(--c-border);border-top-color:var(--c-primary);
  border-radius:50%;animation:spin .8s linear infinite;flex:0 0 15px}
@keyframes spin{to{transform:rotate(360deg)}}
/* 输入区（参照 DSH 的输入框）：圆角容器、上面多行输入、下面工具条 */
.composer{position:static;background:var(--c-bg);padding:10px 0 6px;
  border-top:1px solid var(--c-border)}
.composer-box{background:var(--c-surface);border:1px solid var(--c-border);
  border-radius:var(--r-lg);box-shadow:var(--sh-sm);transition:border-color .15s,box-shadow .15s}
.composer-box:focus-within{border-color:var(--c-primary);box-shadow:0 0 0 3px var(--c-primary-soft)}
.composer textarea{display:block;width:100%;border:0;background:transparent;resize:none;
  padding:12px 14px 6px;font-family:inherit;font-size:var(--f-sm);line-height:1.6;
  color:var(--c-text);max-height:132px;overflow-y:hidden}
.composer textarea:focus{outline:none}
.composer textarea::placeholder{color:var(--c-text-3)}
.composer-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:6px 8px 8px 10px;border-top:1px solid transparent}
.composer-left,.composer-right{display:flex;align-items:center;gap:8px;min-width:0}
.composer-agent{height:28px;width:auto;border:1px solid var(--c-border);border-radius:var(--r-sm);
  background:var(--c-surface);font-family:inherit;font-size:var(--f-2xs);padding:0 26px 0 8px;
  color:var(--c-text-2);cursor:pointer}
.composer-attach{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 9px;
  border:1px solid var(--c-border);border-radius:var(--r-sm);color:var(--c-text-2);
  font-size:var(--f-2xs);cursor:pointer;max-width:220px}
.composer-attach span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.composer-attach:hover{background:var(--c-surface-alt);color:var(--c-text)}
.composer-attach.has-file{border-color:var(--c-primary);color:var(--c-primary);
  background:var(--c-primary-soft)}
.composer-hint{font-size:var(--f-2xs);color:var(--c-text-3);white-space:nowrap}
.composer-send{display:inline-flex;align-items:center;justify-content:center;
  width:34px;height:34px;border-radius:var(--r-md);border:1px solid var(--c-primary);
  background:var(--c-primary);color:#fff;cursor:pointer;transition:background .15s,transform .1s}
.composer-send:hover{background:var(--c-primary-hover);border-color:var(--c-primary-hover)}
.composer-send:active{transform:translateY(1px)}
.composer-send.is-attach{background:var(--c-accent);border-color:var(--c-accent)}
.composer-busy{display:flex;align-items:center;gap:8px;padding:8px 12px;
  border-top:1px solid var(--c-border);font-size:var(--f-2xs);color:var(--c-text-2)}
.composer-busy[hidden]{display:none}
.composer-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:6px 4px 0}
.link-btn{border:0;background:none;padding:0;color:var(--c-text-3);font:inherit;
  font-size:var(--f-2xs);cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.link-btn:hover{color:var(--c-text)}
.link-btn:disabled{color:var(--c-text-3);text-decoration:none;cursor:default;opacity:.7}
@media (max-width: 640px) {
  .composer-hint{display:none}
  .composer-attach{max-width:140px}
}
</style>
<script>
/* 输入区：随内容长高 · 回车发送 · Shift+回车换行（输入法组字时不误发） */
(function () {
  var form = document.getElementById('cmdForm');
  var ta   = document.getElementById('cmdText');
  var f    = document.getElementById('cmdFile');
  var cameraBtn = document.getElementById('cmdCameraBtn');
  var attachBtn = document.getElementById('cmdAttachBtn');
  var nameEl = document.getElementById('cmdFileName');
  var send = document.getElementById('cmdSend');
  var hint = document.getElementById('cmdHint');
  var clear = document.getElementById('cmdClear');
  var hasFile = false;
  var LBL_ATTACH = <?= json_encode(t('上传附件'), JSON_UNESCAPED_UNICODE) ?>;
  var LBL_SEND_HINT = <?= json_encode(t('Enter 发送 · Shift+Enter 换行'), JSON_UNESCAPED_UNICODE) ?>;
  var LBL_FILE_HINT = <?= json_encode(t('Enter 识别 · 会先给确认卡片'), JSON_UNESCAPED_UNICODE) ?>;
  var LBL_CLEARED  = <?= json_encode(t('已清空（日志已保留）'), JSON_UNESCAPED_UNICODE) ?>;

  function grow() {
    if (!ta) return;
    ta.style.height = 'auto';
    var max = 132;
    ta.style.height = Math.min(ta.scrollHeight, max) + 'px';
    ta.style.overflowY = ta.scrollHeight > max ? 'auto' : 'hidden';
  }
  if (ta) {
    // 整页重写（document.write）时浏览器会恢复表单值：还停在那句才清
    try {
      var sent0 = sessionStorage.getItem('ledu_sent') || '';
      if (sent0 !== '' && ta.value.trim() === sent0.trim()) {
        ta.value = '';
      }
      sessionStorage.removeItem('ledu_sent');
    } catch (e) {}
    ta.addEventListener('input', grow);
    grow();
    // 桌面端聚焦输入框；移动端不聚焦，否则页面会被拽到底部
    if (window.matchMedia('(min-width: 900px)').matches) { ta.focus({ preventScroll: true }); }
    var composing = false;
    ta.addEventListener('compositionstart', function () { composing = true; });
    ta.addEventListener('compositionend', function () { composing = false; });
    ta.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || e.shiftKey || composing || e.isComposing) return;
      e.preventDefault();
      if (ta.value.trim() === '' && !hasFile) return;
      if (form.requestSubmit) { form.requestSubmit(send); } else { send.click(); }
    });
  }

  if (f) {
    // 同一个 file input 提供两条入口：拍票时临时加 capture，普通附件则移除。
    // 部分手机浏览器只要看到 capture 就强制打开相机，拆开按钮才能保留两种选择。
    if (cameraBtn) {
      cameraBtn.addEventListener('click', function () {
        f.setAttribute('accept', 'image/*');
        f.setAttribute('capture', 'environment');
        f.click();
      });
    }
    if (attachBtn) {
      attachBtn.addEventListener('click', function () {
        f.removeAttribute('capture');
        f.setAttribute('accept', 'image/*,application/pdf,.pdf,.csv,.txt,.xlsx,.xls');
        f.click();
      });
    }
    f.addEventListener('change', function () {
      hasFile = !!(f.files && f.files.length);
      if (nameEl) { nameEl.textContent = hasFile ? f.files[0].name : LBL_ATTACH; }
      if (attachBtn) { attachBtn.classList.toggle('has-file', hasFile); }
      if (send) {
        send.setAttribute('name', 'action');
        send.value = hasFile ? 'ai_import' : 'ai_chat';
        send.classList.toggle('is-attach', hasFile);
      }
      if (hint) { hint.textContent = hasFile ? LBL_FILE_HINT : LBL_SEND_HINT; }
    });
  }

  if (clear) {
    clear.addEventListener('click', function () {
      var log = document.getElementById('cmdLog');
      if (log) { log.innerHTML = ''; }
      clear.textContent = LBL_CLEARED;
      clear.disabled = true;
    });
  }

  // 示例问句：老的 chip 与新的能力卡都靠 data-fill 预填指令框
  document.querySelectorAll('.chip-btn, [data-fill]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (!ta) return;
      ta.value = b.dataset.fill || b.getAttribute('data-fill') || '';
      ta.focus(); grow();
      var h = document.getElementById('cmdForm');
      if (h && b.tagName === 'A') { h.scrollIntoView({behavior:'smooth', block:'center'}); }
    });
  });
})();
</script>

<script>
/* 左栏常用工具：可收起，选择记在 localStorage */
(function () {
  var rail = document.getElementById('aiRail');
  var btn  = document.getElementById('aiRailToggle');
  var shell = document.querySelector('.ai-layout');
  if (!rail || !btn || !shell) return;
  var key = 'ledu_ai_rail_collapsed';
  if (localStorage.getItem(key) === '1') shell.classList.add('rail-collapsed');
  btn.addEventListener('click', function () {
    var off = shell.classList.toggle('rail-collapsed');
    localStorage.setItem(key, off ? '1' : '0');
  });
})();
</script>

<script>
/* 顶部「最近记账」抽屉 */
(function () {
  var btn = document.getElementById('aiRecentBtn');
  var box = document.getElementById('aiRecentDrawer');
  if (!btn || !box) return;
  btn.addEventListener('click', function () { box.hidden = !box.hidden; });
})();
</script>

<script>
/* AI 卡片里的下拉（科目 100+ 项）要能搜索：页面渲染完再补一次增强，
   免得卡片是后插入的、select-search 首次扫描时漏掉。 */
(function () {
  function boot() {
    if (typeof window.enhanceSelects !== 'function') { return setTimeout(boot, 120); }
    window.enhanceSelects(document.querySelector('.ai-main') || document);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();
</script>

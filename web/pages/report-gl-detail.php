<?php
/*
 * LtBooks — pages/report-gl-detail.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 詳細的總分類帳：每科目 期初餘額 → 逐筆流水 → 結餘。 */
$from = (string) ($_GET['from'] ?? date('Y-m-01'));
$to   = (string) ($_GET['to'] ?? date('Y-m-t'));
$acc  = trim((string) ($_GET['account'] ?? ''));
$url  = '/reports/general-ledger-detail?from=' . urlencode($from) . '&to=' . urlencode($to)
      . ($acc !== '' ? '&account=' . urlencode($acc) : '');
$r = api_get($url);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start();
if (!$d['accounts']) {
    echo empty_state('本期没有分录');
} else {
    foreach ($d['accounts'] as $a) {
        echo '<div style="margin-bottom:18px">';
        echo '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">'
           . '<b class="mono">' . e((string) $a['accountCode']) . '</b> '
           . '<span>' . e((string) $a['accountName']) . '</span>'
           . '<span class="hint">' . e(t('本期合计')) . '：'
           . money($a['debit']) . ' / ' . money($a['credit']) . '</span></div>';
        echo '<div class="table-wrap"><table><thead><tr>'
           . '<th style="width:110px">' . e(t('日期')) . '</th>'
           . '<th>' . e(t('交易明细')) . '</th>'
           . '<th style="width:150px">' . e(t('凭证号')) . '</th>'
           . '<th class="num" style="width:110px">' . e(t('借项')) . '</th>'
           . '<th class="num" style="width:110px">' . e(t('贷项')) . '</th>'
           . '<th class="num" style="width:120px">' . e(t('余额')) . '</th></tr></thead><tbody>';
        echo '<tr class="hint"><td>' . e($from) . '</td><td>' . e(t('期初余额')) . '</td><td></td>'
           . '<td class="num"></td><td class="num"></td>'
           . '<td class="num">' . money($a['opening']) . '</td></tr>';
        foreach ($a['lines'] as $ln) {
            echo '<tr><td class="nowrap">' . e((string) $ln['date']) . '</td>'
               . '<td class="truncate" style="max-width:420px">' . e((string) $ln['description']) . '</td>'
               . '<td class="mono hint">' . e((string) $ln['entryNo']) . '</td>'
               . '<td class="num">' . ($ln['debit'] ? money($ln['debit']) : '') . '</td>'
               . '<td class="num">' . ($ln['credit'] ? money($ln['credit']) : '') . '</td>'
               . '<td class="num">' . money($ln['balance']) . '</td></tr>';
        }
        echo '<tr class="total"><td colspan="3">' . e(t('期末余额')) . '</td>'
           . '<td class="num">' . money($a['debit']) . '</td>'
           . '<td class="num">' . money($a['credit']) . '</td>'
           . '<td class="num">' . money($a['closing']) . '</td></tr>';
        echo '</tbody></table></div></div>';
    }
}
$tools = '<form method="get" style="display:flex;gap:6px;align-items:center">'
    . '<input type="hidden" name="p" value="report-gl-detail">'
    . '<input type="hidden" name="from" value="' . e($from) . '">'
    . '<input type="hidden" name="to" value="' . e($to) . '">'
    . '<input type="text" name="account" value="' . e($acc) . '" placeholder="'
    . e(t('科目代码（可不填）')) . '" style="width:130px">'
    . '<button class="btn sm">' . e(t('应用')) . '</button>'
    . '</form>'
    . export_menu(export_lang_items('/reports/pdf',
        ['kind' => 'gl-detail', 'from' => $from, 'to' => $to, 'account' => $acc]), '导出 PDF', 'btn btn-file');
echo card(t('详细的总分类账'), ob_get_clean(), $tools, false);

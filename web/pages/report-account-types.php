<?php
/*
 * LtBooks — pages/report-account-types.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$__rp = $GLOBALS['RP'] ?? report_period();
/** 账户类型摘要：按科目类型汇总本期借贷（资产负债类也含）。 */
$from = (string) ($_GET['from'] ?? date('Y-m-01'));
$to   = (string) ($_GET['to'] ?? date('Y-m-t'));
$r = api_get('/reports/account-types?from=' . urlencode($from) . '&to=' . urlencode($to));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
  <thead><tr><th><?= e(t('账户类型')) ?></th><th class="num"><?= e(t('借方')) ?></th>
    <th class="num"><?= e(t('贷方')) ?></th></tr></thead>
  <tbody>
  <?php foreach (($d['groups'] ?? []) as $g): ?>
    <tr class="group"><td colspan="3"><b><?= e(t((string) $g['label'])) ?></b></td></tr>
    <?php foreach ($g['items'] as $it): ?>
      <tr>
        <td style="padding-left:22px"><?= e(t((string) $it['type'])) ?>
          <span class="hint mono"><?= e(implode(' / ', (array) $it['accounts'])) ?></span></td>
        <td class="num"><?= money($it['debit']) ?></td>
        <td class="num"><?= money($it['credit']) ?></td>
      </tr>
    <?php endforeach; ?>
  <?php endforeach; ?>
    <tr class="total"><td><?= e(t('合计')) ?></td>
      <td class="num"><?= money($d['debit']) ?></td>
      <td class="num"><?= money($d['credit']) ?></td></tr>
  </tbody>
</table></div>
<?php
$tools = '<form method="get" style="display:flex;gap:6px;align-items:center">'
    . '<input type="hidden" name="p" value="report-account-types">'
    . '<input type="hidden" name="from" value="' . e($from) . '">'
    . '<input type="hidden" name="to" value="' . e($to) . '">'
    . '<button class="btn sm">' . e(t('应用')) . '</button>'
    . '</form>'
    . export_menu(export_lang_items('/reports/pdf',
        ['kind' => 'account-types', 'from' => $from, 'to' => $to]), '导出 PDF', 'btn btn-file');
echo card(t('账户类型摘要'), ob_get_clean(), $tools, false);

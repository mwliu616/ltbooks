<?php
/*
 * LtBooks — pages/report-bs.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$rp = $GLOBALS['RP'] ?? report_period();
$r = api_get('/reports/balance-sheet?asOf=' . urlencode($rp['to']));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
ob_start(); ?>
<div class="table-wrap"><table>
<thead><tr><th>项目</th><th>科目</th><th class="num">金额（HKD）</th></tr></thead>
<tbody>
<?php
$secs = [['资产', $d['assets']], ['负债', $d['liabilities']],
         [t('权益') . '（' . t('累计损益（截至期末）') . ' ' . number_format((float) $d['equity']['currentYearProfit'], 2) . '）', $d['equity']]];
foreach ($secs as [$lab, $sec]): ?>
  <tr style="background:#FAFBFC"><td colspan="2"><b><?= e($lab) ?></b></td>
      <td class="num"><b><?= money($sec['total']) ?></b></td></tr>
  <?php foreach ($sec['items'] as $i): ?>
    <tr><td><?= e(acc_name($i['accountCode'] ?? '', $i['accountName'] ?? '')) ?><?= !empty($i['reclassedTo']) ? ' <span class="hint">（重分类至 ' . e($i['reclassedTo']) . '）</span>' : '' ?></td>
        <td><?= e($i['accountCode']) ?></td>
        <td class="num"><?= money($i['amount']) ?></td></tr>
  <?php endforeach; ?>
<?php endforeach; ?>
<tr class="total"><td colspan="2">资产 −（负债+权益）：<?= $d['check']['balanced'] ? '平衡' : '不平衡' ?></td>
<td class="num" style="color:<?= $d['check']['balanced'] ? '#2E7D32' : 'var(--fail)' ?>"><?= money($d['check']['difference']) ?></td></tr>
</tbody></table></div>
<?php echo card('资产负债表', ob_get_clean(), '', false);

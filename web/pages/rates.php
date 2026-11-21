<?php
/*
 * LtBooks — pages/rates.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'add_rate') {
    $r = api_post('/fx/rates', [
        'fromCcy' => strtoupper(trim((string) ($_POST['fromCcy'] ?? ''))),
        'toCcy' => strtoupper(trim((string) ($_POST['toCcy'] ?? ''))),
        'rate' => (float) ($_POST['rate'] ?? 0),
        'rateDate' => (string) ($_POST['rateDate'] ?? ''),
        'source' => 'MANUAL',
        'actor' => $displayName ?? 'system',
    ]);
    $msg = $r['ok'] ? '汇率已保存' : null;
    $errMsg = $r['ok'] ? null : (string) $r['error'];
}
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

[$page, $per] = pager_state('ledu_rates_per', 25);
$limit = $per === 0 ? 0 : $per;
$offset = $per === 0 ? 0 : ($page - 1) * $per;
$r = api_get('/fx/rates/list?limit=' . $limit . '&offset=' . $offset);
$rows = $r['ok'] ? ($r['data']['rates'] ?? []) : [];
$total = (int) ($r['data']['total'] ?? count($rows));
ob_start();
if (!$rows) { echo empty_state('暂无汇率'); } else { ?>
<div class="table-wrap"><table>
<thead><tr><th>日期</th><th>来源币</th><th>目标币</th><th class="num">汇率</th><th>来源</th><th>抓取时间</th><th>回退</th></tr></thead>
<tbody>
<?php foreach ($rows as $x): ?>
<tr><td><?= e((string) $x['rate_date']) ?></td>
<td><?= e((string) $x['from_ccy']) ?></td>
<td><?= e((string) $x['to_ccy']) ?></td>
<td class="num"><?= number_format((float) $x['rate'], (float) $x['rate'] >= 1 ? 2 : 4, '.', ',') ?></td>
<td class="hint"><?= e(($x['source'] ?? '') === 'MANUAL' ? t('手工录入') : (string) $x['source']) ?></td>
<td class="hint" style="white-space:nowrap"><?= e((string) ($x['fetched_at'] ?? '—')) ?></td>
<td><?= $x['is_fallback'] ? '<span class="badge review">回退</span>' : '—' ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php }
$lastEcb = null;
if ($page === 1) {
    foreach ($rows as $x0) {
        if (($x0['source'] ?? '') === 'ECB' && !empty($x0['fetched_at'])) { $lastEcb = (string) $x0['fetched_at']; break; }
    }
}
$rateMeta = '<span class="status-chip is-ok" title="数据源 Frankfurter（ECB 参考汇率），每天 09:00 自动抓取">'
          . '<b>✓</b> 自动更新 09:00'
          . ($lastEcb ? '<span class="status-chip-num">· ' . e(t('上次')) . ' ' . e($lastEcb) . '</span>' : '') . '</span>';
echo card('汇率', ob_get_clean(), $rateMeta . pager_html($page, $per, $total, ['p' => 'rates']), false);

if ($role !== 'auditor'):
ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="add_rate">
  <div class="grid">
    <div class="field"><label class="f">日期</label><input type="date" name="rateDate" value="<?= e(date('Y-m-d')) ?>" required></div>
    <div class="field"><label class="f">来源币</label>
      <?php
      // 汇率通常是「外币 → 港币」，默认来源取第一个非功能货币，避免默认成 HKD→HKD
      $baseC = base_currency();
      $list = currencies();
      // 优先美元（最常用），否则取第一个非功能货币
      $fromDefault = in_array('USD', $list, true) ? 'USD' : $baseC;
      if (strtoupper($fromDefault) === strtoupper($baseC)) {
          foreach ($list as $c) {
              if (strtoupper($c) !== strtoupper($baseC)) { $fromDefault = $c; break; }
          }
      }
      ?>
      <select name="fromCcy"><?= currency_options($fromDefault) ?></select></div>
    <div class="field"><label class="f">目标币</label>
      <select name="toCcy"><?= currency_options(base_currency()) ?></select></div>
    <div class="field"><label class="f">汇率</label>
      <input type="number" step="0.0001" min="0.0001" name="rate" required placeholder="如 7.80">
      <div class="hint">外币→港币填两位小数（如 7.80）；港币→外币这类小于 1 的汇率填四位</div></div>
  </div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0"><button class="btn primary">保存汇率</button></div>
</form>
<?php echo card('录入汇率', ob_get_clean());
endif; ?>

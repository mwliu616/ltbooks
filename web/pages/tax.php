<?php
/*
 * LtBooks — pages/tax.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 利得税：香港两级制，课税年度 4/1–3/31。资格未定就不算税。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;

$curYear = function (): string {
    $t = new DateTimeImmutable('today', new DateTimeZone('Asia/Hong_Kong'));
    $y = (int) $t->format('n') >= 4 ? (int) $t->format('Y') : (int) $t->format('Y') - 1;
    return sprintf('%d/%02d', $y, ($y + 1) % 100);
};
// 评估年度由期间条的「止日」推出（香港税务年度 4 月 1 日 ~ 次年 3 月 31 日）
$__rp = $GLOBALS['RP'] ?? report_period();
// 课税年度：URL 显式给了就用它，否则按期间条止日推（4 月 1 日划年）
$__qy = (string) ($_GET['year'] ?? '');
if (preg_match('#^\d{4}/\d{2}$#', $__qy)) {
    $year = $__qy;
} else {
    $__endT = new DateTimeImmutable($__rp['to']);
    $__y = (int) $__endT->format('n') >= 4 ? (int) $__endT->format('Y') : (int) $__endT->format('Y') - 1;
    $year = sprintf('%d/%02d', $__y, ($__y + 1) % 100);
}

// ---------------------------------------------------------------- 两级制资格
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'set_two_tier') {
    if ($role !== 'admin') {
        $errMsg = '只有管理员可以修改两級制稅率資格（这是税务事实认定）';
    } else {
        $res = api_post('/entity/two-tier', [
            'status' => (string) ($_POST['status'] ?? 'undetermined'),
            'basis' => trim((string) ($_POST['basis'] ?? '')),
        ]);
        if ($res['ok']) {
            header('Location: ?p=tax&year=' . urlencode($year)
                 . '&msg=' . urlencode('两级制资格已更新'));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}

$r = api_get('/tax/profit-tax?year=' . urlencode($year));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];

$status = (string) ($d['twoTierStatus'] ?? 'undetermined');
$ST = [
    'nominated'     => [t('已提名两级制'), 'ok', t('首 200 万应评税利润按 8.25%，其余 16.5%')],
    'not_nominated' => [t('未提名两级制'), 'warn', t('全额按 16.5% 计征')],
    'undetermined'  => [t('资格未确定'), 'danger', t('未确定前禁止计算税额（不得估算）')],
];
[$stLab, $stCls, $stNote] = $ST[$status] ?? $ST['undetermined'];

$years = [];
$y0 = (int) substr($curYear(), 0, 4);
for ($i = 0; $i <= 6; $i++) {
    $y = $y0 - $i;
    $years[] = sprintf('%d/%02d', $y, ($y + 1) % 100);
}

$__y0 = (int) substr($year, 0, 4);
$prevYear = sprintf('%d/%02d', $__y0 - 1, $__y0 % 100);
$nextYear = sprintf('%d/%02d', $__y0 + 1, ($__y0 + 2) % 100);
$gross = (float) $d['grossProfit'];
$tax = $d['taxPayable'];
?>

<div class="toolbar" style="margin-bottom:10px">
  <a class="btn" href="?p=report-tax">利得税计算表</a>
  <span class="grow"></span>
  <?= export_menu(export_lang_items('/reports/pdf', ['kind' => 'profit-tax', 'year' => $year])) ?>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>

<div class="hint" style="margin:0 0 10px">
  <?= e(t('课税年度')) ?> <b><?= e($year) ?></b>
  · <?= e(t('基期')) ?> <span class="mono"><?= e((string) ($d['start'] ?? '')) ?> ~ <?= e((string) ($d['end'] ?? '')) ?></span>
  <?php if (abs((float) ($d['assessableProfit'] ?? 0)) >= 0.005): ?>
    · <?= e(t('应评税利润')) ?> <span class="mono"><?= money((float) $d['assessableProfit'], 'HKD') ?></span>
  <?php endif; ?>
  <a class="link" href="?p=tax&amp;year=<?= e(urlencode($prevYear ?? $year)) ?>" style="margin-left:8px">
    <?= e(t('切换课税年度')) ?></a>
</div>

<?php if ($status === 'undetermined'): ?>
  <div class="banner FAIL">
    <span class="banner-icon">!</span>
    <div class="banner-body">
      <div class="banner-title">两级制资格未确定，本年度不能计算应缴税额</div>
      <div class="banner-reason">
        这是税务事实认定，必须由管理员显式选择。系统不会替你猜：猜错会使报税表金额错误。
        请在下方「两级制资格」中确认后，税额才会计算。
      </div>
    </div>
  </div>
<?php endif; ?>

<?= help_html('tax') ?>
<div class="metrics metrics-sm">
  <div class="metric c3">
    <div class="lbl">应评税利润</div>
    <div class="val"><?= money($d['accountingProfit'], 'HKD') ?></div>
    <div class="hint">收入 − 销售成本 − 经营费用</div>
  </div>
  <div class="metric c3">
    <div class="lbl">应缴利得税</div>
    <div class="val"><?= $tax === null ? '—' : money($tax, 'HKD') ?></div>
    <div class="hint"><?= e($tax === null ? '未确定资格前不计算' : $stNote) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">适用税率</div>
    <div class="val" style="font-size:var(--f-lg)"><?= e((string) ($d['rate'] ?? '未定')) ?></div>
    <div class="hint">两级制首 200 万 8.25%</div>
  </div>
  <div class="metric c3">
    <div class="lbl">两级制资格</div>
    <div class="val" style="font-size:var(--f-lg)"><?= e($stLab) ?></div>
    <div class="hint"><?= e($stNote) ?></div>
  </div>
</div>

<section class="card">
  <div class="card-head">
    <h2>计算过程</h2>
    <span class="hint"><?= e((string) ($d['basis'] ?? '')) ?></span>
  </div>
  <div class="table-wrap">
    <table>
      <tbody>
        <tr><td>收入</td><td class="num"><?= money($d['revenue'], 'HKD') ?></td></tr>
        <tr><td>减：销售成本</td><td class="num">(<?= money($d['costOfSales'], 'HKD') ?>)</td></tr>
        <tr class="total"><td>毛利</td><td class="num"><?= money($gross, 'HKD') ?></td></tr>
        <tr><td>加：其他收入</td><td class="num"><?= money($d['otherIncome'], 'HKD') ?></td></tr>
        <tr><td>加：其他收益／（亏损）（含汇兑）</td>
            <td class="num"><?= money($d['otherGains'], 'HKD') ?></td></tr>
        <tr><td>减：经营费用</td><td class="num">(<?= money($d['operatingExpenses'], 'HKD') ?>)</td></tr>
        <tr><td>减：财务费用</td><td class="num">(<?= money($d['financeCosts'], 'HKD') ?>)</td></tr>
        <tr class="total"><td>除税前溢利（会计利润＝应评税利润）</td>
            <td class="num"><?= money($d['accountingProfit'], 'HKD') ?></td></tr>
        <tr>
          <td>应缴利得税<?= $tax === null ? '' : '（' . e((string) $stNote) . '）' ?></td>
          <td class="num"><b style="font-weight:400;color:var(--c-text)">
            <?= $tax === null ? '— 未计算' : money($tax, 'HKD') ?>
          </b></td>
        </tr>
      </tbody>
    </table>
  </div>
</section>

<section class="card">
  <div class="card-head">
    <h2>两级制资格</h2>
    <span class="hint">税务事实认定，只有管理员可改；每次修改都写入审计链</span>
  </div>
  <?php if ($role !== 'admin'): ?>
    <div class="card-body">
      <p class="hint" style="margin:0">
        当前：<span class="tag tag-<?= e($stCls) ?>"><?= e($stLab) ?></span> ·
        需要修改请联系管理员。
      </p>
    </div>
  <?php else: ?>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="set_two_tier">
    <input type="hidden" name="year" value="<?= e($year) ?>">
    <div style="display:flex;gap:var(--s-5);flex-wrap:wrap;margin-bottom:var(--s-4)">
      <?php foreach ([
          'nominated' => '已提名两级制（首 200 万 8.25%）',
          'not_nominated' => '未提名（全额 16.5%）',
          'undetermined' => '暂不确定（不算税）',
      ] as $k => $lab): ?>
        <label style="display:flex;align-items:center;gap:8px;font-size:var(--f-sm)">
          <input type="radio" name="status" value="<?= e($k) ?>"
                 <?= $status === $k ? 'checked' : '' ?> style="width:auto">
          <?= e($lab) ?>
        </label>
      <?php endforeach; ?>
    </div>
    <div class="field" style="max-width:560px">
      <label class="f" for="basis">依据（写进审计记录）</label>
      <input type="text" id="basis" name="basis" placeholder="例：集团内仅一间公司选择两级制，本公司为唯一 nominee"
             value="<?= e((string) ($_POST['basis'] ?? '')) ?>">
    </div>
    <div class="card-actions" style="display:flex;justify-content:flex-end;margin-top:var(--s-4)">
      <button class="btn primary" type="submit"
        data-confirm="<?= e(t('确认修改两级制资格？')) ?>"
        data-confirm-note="<?= e(t('这会改变本年度应缴税额的计算方式，并写入审计链。资格认定错误会直接导致报税表金额错误。')) ?>"
        data-confirm-ok="<?= e(t('确认修改')) ?>">保存资格</button>
    </div>
  </form>
  <?php endif; ?>
</section>

<section class="card">
  <div class="card-head">
    <h2>香港利得税要点</h2>
  </div>
  <div class="card-body">
    <div class="kvg">
      <div class="kvg-item"><div class="kvg-k">课税年度</div>
        <div class="kvg-v">每年 4 月 1 日至次年 3 月 31 日</div></div>
      <div class="kvg-item"><div class="kvg-k">两级制税率</div>
        <div class="kvg-v">首 HKD 2,000,000 应评税利润 8.25%，其余 16.5%</div></div>
      <div class="kvg-item"><div class="kvg-k">两级制限制</div>
        <div class="kvg-v">同一集团只能有一间关联实体享有两级制</div></div>
      <div class="kvg-item"><div class="kvg-k">申报表</div>
        <div class="kvg-v">BIR51 / BIR52，连同财务报表一并提交</div></div>
      <div class="kvg-item"><div class="kvg-k">不适用</div>
        <div class="kvg-v">香港不征增值税，无进项抵扣；利得税只对源自香港的利润征收</div></div>
    </div>
  </div>
</section>

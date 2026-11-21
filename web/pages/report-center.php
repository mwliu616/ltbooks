<?php
/*
 * LtBooks — pages/report-center.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 报表中心：一个期间的总览，往下接各张报表与 PDF。 */
$role = isset($role) ? $role : 'accountant';
$__rp = report_period();
$from = $__rp['from'];
$to   = $__rp['to'];
$period = substr($to, 0, 7);

// 导出语言名跟着界面语言走，避免简中界面出现繁体字、英文界面出现中文
$__lang_langs = [
    'zh_cn' => ['zh_cn' => '简体中文', 'zh_hk' => '繁体中文', 'en' => '英文'],
    'zh_hk' => ['zh_cn' => '簡體中文', 'zh_hk' => '繁體中文', 'en' => '英文'],
    'en'    => ['zh_cn' => 'Simplified Chinese', 'zh_hk' => 'Traditional Chinese', 'en' => 'English'],
][lang()] ?? ['zh_cn' => '简体中文', 'zh_hk' => '繁体中文', 'en' => '英文'];

$r = api_get('/reports/summary?period=' . urlencode($period)
           . '&from=' . urlencode($from) . '&to=' . urlencode($to));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
$cur = $d['pnl']['current'] ?? [];
$prev = $d['pnl']['previous'] ?? [];
$delta = $d['pnl']['delta'] ?? [];
$bal = $d['balance'] ?? [];
$tb = $d['trialBalance'] ?? [];
$prevPeriod = (string) ($d['prevPeriod'] ?? '');

$pct = function (float $now, float $before): string {
    if (abs($before) < 0.005) { return $now == 0.0 ? '—' : t('新增'); }
    $v = ($now - $before) / abs($before) * 100;
    return sprintf('%+.1f%%', $v);
};
$margin = function (array $x): string {
    $rev = (float) ($x['revenue'] ?? 0);
    // 收入不足 100 港币时算净利率没有意义，直接不显示
    if (abs($rev) < 100) { return '—'; }
    return sprintf('%.1f%%', (float) ($x['netProfit'] ?? 0) / $rev * 100);
};
$links = [
    ['report-statements', '财务报表', '三表齐全，PDF 报表包'],
    ['report-tb', '试算表', '全部科目借贷与余额'],
    ['report-pnl', '损益及其他全面收益表', '按 HKAS 1 分节列报'],
    ['report-bs', '财务状况表', '资产 / 负债 / 权益'],
    ['report-cf', '现金流量表', '经营 / 投资 / 筹资'],
    ['report-aging', '账龄分析表', '应收应付账龄'],
    ['report-gl', '总分类账', '按科目看发生额'],
    ['report-daybook', '日记簿', '按日期看全部分录'],
    ['report-sales', '销售明细表', '逐张发票'],
    ['report-purchase', '采购明细表', '逐张账单'],
    ['tax', '利得税', '两级制与应缴税款'],
    ['report-ratios', '财务比率表', '流动性 / 盈利能力'],
    ['report-account-types', t('账户类型摘要'), t('按科目类型看本期借贷')],
    ['report-gl-detail', t('详细的总分类账'), t('逐笔流水与余额')],
    ['report-fx', t('汇兑损益表'), t('已实现与未实现')],
    ['report-bank', t('银行账户余额表'), t('按币种折 HKD')],
    ['report-tax', t('税务报表'), t('利得税计算明细')],
    ['report-customer-balance', t('客户余额表'), t('按客户看应收')],
    ['report-vendor-balance', t('供应商余额表'), t('按供应商看应付')],
];
?>
<div class="page-head">
  <div>
    <h1 class="page-title">报表中心</h1>
    <div class="page-sub"><?= e(t('按凭证日期归期 · 数字来自已过账分录，港币本位')) ?></div>
  </div>
  <div class="page-actions">

  </div>
</div>

<?php
// 年度 PDF 包：后台任务，前端轮询进度
if (($_GET['act'] ?? '') === 'pack_start' && csrf_ok()) {
    $yr = (int) ($_POST['year'] ?? date('Y'));
    $parts = [];
    foreach (['reports', 'invoices', 'bills'] as $k) {
        if (!empty($_POST['part_' . $k])) { $parts[] = $k; }
    }
    $r = api_post('/reports/year-pack/start', [
        'year' => $yr,
        'lang' => (string) ($_POST['lang'] ?? 'zh_cn'),
        'from' => (string) ($_POST['from'] ?? '') ?: null,
        'to' => (string) ($_POST['to'] ?? '') ?: null,
        'parts' => $parts,
    ]);
    $packJob = $r['ok'] ? (string) ($r['data']['jobId'] ?? '') : '';
    $packErr = $r['ok'] ? '' : (string) $r['error'];
}
$packJob = $packJob ?? '';
?>
<?= report_period_bar($__rp) ?>
<?= help_html('report-center') ?>
<div class="rc-stack">
<div class="card" id="yearPack">
  <div class="card-head">
    <h2 class="card-title"><?= e(t('年度 PDF 包')) ?></h2>
    <div class="hint"><?= e(t('报表 + 销售单 + 采购单，打成一个 ZIP；单据多时需要等几分钟')) ?></div>
  </div>
  <div class="card-body">
    <form method="post" action="?p=report-center&act=pack_start">
      <?= csrf_field() ?>
      <div class="pack-grid">
        <label class="field" style="margin:0">
          <span class="f">起始日期</span>
          <input type="date" name="from" value="<?= e($__packFrom ?? date('Y-01-01')) ?>" required>
        </label>
        <label class="field" style="margin:0">
          <span class="f">截止日期</span>
          <input type="date" name="to" value="<?= e($__packTo ?? date('Y-m-d')) ?>" required>
        </label>
        <label class="field" style="margin:0">
          <span class="f">语言</span>
          <select name="lang">
            <?php foreach ($__lang_langs as $__code => $__lname): ?>
              <option value="<?= e($__code) ?>"><?= e($__lname) ?></option>
            <?php endforeach; ?>
          </select>
        </label>
        <label class="field" style="margin:0">
          <span class="f">编号年份</span>
          <input type="number" name="year" value="<?= (int) date('Y') ?>" min="2000" max="2100" style="width:100px">
        </label>
      </div>
      <div class="pack-parts">
        <label class="chk"><input type="checkbox" name="part_reports" checked>
          财务报表包<span class="hint">（资产负债表 · 损益表 · 权益变动 · 现金流量 · 试算表 · 总分类账 · 附注）</span></label>
        <label class="chk"><input type="checkbox" name="part_invoices" checked> <?= e(t('销售单 PDF')) ?></label>
        <label class="chk"><input type="checkbox" name="part_bills" checked> <?= e(t('采购单 PDF')) ?></label>
      </div>
      <div class="toolbar" style="margin:12px 0 0">
        <button class="btn primary btn-file" type="submit"><?= e(t('生成报表包（ZIP）')) ?></button>
        <span class="hint">后台生成，可离开页面；单据多时几分钟</span>
      </div>
    </form>
    <?php if (!empty($packErr)): ?>
      <div class="alert alert-err" style="margin-top:10px"><?= e($packErr) ?></div>
    <?php endif; ?>
    <div id="packStatus" class="hint" style="margin-top:10px" data-job="<?= e($packJob) ?>"
         data-tpl="<?= e(t('正在生成：{done}/{total}')) ?>"
         data-ready="<?= e(t('已生成，点下面下载')) ?>"
         data-failed="<?= e(t('生成失败')) ?>"
         data-dl="<?= e(t('下载 ZIP')) ?>"></div>
    <div id="packDone" style="margin-top:8px"></div>
    <div class="hint" style="margin-top:10px">
      <?= e(t('只想要报表：取消勾选销售单与采购单，几十秒就好。')) ?>
    </div>
  </div>
</div>
<script>
(function () {
  var box = document.getElementById('packStatus');
  if (!box) return;
  var job = box.getAttribute('data-job');
  if (!job) return;
  var tpl = box.getAttribute('data-tpl');
  var done = document.getElementById('packDone');
  function poll() {
    var url = '/pdf/pack.php?job=' + encodeURIComponent(job);
    fetch('/pdf/pack_status.php?job=' + encodeURIComponent(job))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.error) { box.textContent = d.message || ''; return; }
        if (d.status === 'done') {
          box.textContent = box.getAttribute('data-ready');
          done.innerHTML = '<a class="btn primary" href="' + url + '">' + box.getAttribute('data-dl') + '</a>';
          return;
        }
        if (d.status === 'failed') {
          box.textContent = box.getAttribute('data-failed') + '：' + (d.error || '');
          return;
        }
        box.textContent = tpl.replace('{done}', d.done || 0).replace('{total}', d.total || 0);
        setTimeout(poll, 3000);
      })
      .catch(function () { setTimeout(poll, 4000); });
  }
  poll();
})();
</script>

<div class="metrics metrics-sm rc-metrics">
  <div class="metric c3">
    <div class="lbl">收入</div>
    <div class="val"><?= money($cur['revenue'] ?? 0, 'HKD') ?></div>
    <div class="hint">上月 <?= money($prev['revenue'] ?? 0, 'HKD') ?>
      · <?= e($pct((float) ($cur['revenue'] ?? 0), (float) ($prev['revenue'] ?? 0))) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">毛利</div>
    <div class="val"><?= money($cur['grossProfit'] ?? 0, 'HKD') ?></div>
    <div class="hint">上月 <?= money($prev['grossProfit'] ?? 0, 'HKD') ?>
      · <?= e($pct((float) ($cur['grossProfit'] ?? 0), (float) ($prev['grossProfit'] ?? 0))) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">净利</div>
    <div class="val"><?= money($cur['netProfit'] ?? 0, 'HKD') ?></div>
    <div class="hint"><?= e(t('净利率')) ?> <?= e($margin($cur)) ?> · <?= e(t('上月')) ?> <?= e($margin($prev)) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">资产总额</div>
    <div class="val"><?= money($bal['assets'] ?? 0, 'HKD') ?></div>
    <div class="hint"><?= e(t('负债')) ?> <?= money($bal['liabilities'] ?? 0, 'HKD') ?>
      · <?= e(t('权益')) ?> <?= money($bal['equity'] ?? 0, 'HKD') ?></div>
  </div>
</div>



<div class="cols cols-2 rc-cols">
  <section class="card">
    <div class="card-head"><h2>勾稽校验</h2></div>
    <div class="card-body">
      <div class="kvg">
        <div class="kvg-item">
          <div class="kvg-k">资产负债表</div>
          <div class="kvg-v">
            <?php if (!empty($bal['balanced'])): ?>
              <span class="tag tag-ok">平衡</span>
              资产 = 负债 + 权益
            <?php else: ?>
              <span class="tag tag-danger">不平衡</span>
              差额 <?= money($bal['difference'] ?? 0, 'HKD') ?>
            <?php endif; ?>
          </div>
        </div>
        <div class="kvg-item">
          <div class="kvg-k">试算表</div>
          <div class="kvg-v">
            <?php if (!empty($tb['balanced'])): ?>
              <span class="tag tag-ok">平衡</span>
              借贷合计相等
            <?php else: ?>
              <span class="tag tag-danger">不平衡</span>
              差额 <?= money($tb['difference'] ?? 0, 'HKD') ?>
            <?php endif; ?>
          </div>
        </div>
      </div>
      <p class="hint" style="margin:var(--s-3) 0 0">
        任何一张报表数字对不上，先看这两项；不平衡时不要对外出具报表。
      </p>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>导出</h2>
      <span class="hint">每份报表可选简体 / 繁体 / 英文</span></div>
    <div class="card-body export-body">
      <?= export_matrix([
            ['title' => '损益及其他全面收益表', 'path' => '/reports/pdf',
             'query' => ['kind' => 'pnl', 'from' => $from, 'to' => $to],
             'langs' => $__lang_langs],
            ['title' => '财务状况表', 'path' => '/reports/pdf',
             'query' => ['kind' => 'balance-sheet', 'to' => $to],
             'langs' => $__lang_langs],
            ['title' => '试算表', 'path' => '/reports/pdf',
             'query' => ['kind' => 'trial-balance', 'to' => $to],
             'langs' => $__lang_langs],
            ['title' => '总分类账', 'path' => '/reports/pdf',
             'query' => ['kind' => 'gl', 'from' => $from, 'to' => $to],
             'langs' => $__lang_langs],
            ['title' => '完整报表包（含附注）', 'path' => '/reports/statements/pdf',
             'query' => ['from' => $from, 'to' => $to],
             'langs' => $__lang_langs],
          ], '导出报表') ?>
      <span class="hint"><?= e(t('一份报表一行，右边点语言即可下载')) ?></span>
    </div>
  </section>
</div>

<section class="card">
  <div class="card-head">
    <h2>全部报表</h2>
    <span class="hint">点标题进报表页；带 PDF 的可直接下载</span>
  </div>
  <div class="card-body">
    <div class="rc-reports">
      <?php foreach ($links as [$p, $label, $note]): ?>
        <a class="rc-report" href="?p=<?= e($p) ?>">
          <span class="rc-report-title"><?= e($label) ?></span>
          <span class="rc-report-note"><?= e($note) ?></span>
        </a>
      <?php endforeach; ?>
    </div>
  </div>
</section>
</div>

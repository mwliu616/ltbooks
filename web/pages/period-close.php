<?php
/*
 * LtBooks — pages/period-close.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 月结：六步流水线。可自动的三步一键跑，其余由人确认；最后一步锁账。 */
$role = isset($role) ? $role : 'accountant';
$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;
$period = (string) ($_GET['period'] ?? $_POST['period'] ?? date('Y-m'));
if (!preg_match('/^\d{4}-\d{2}$/', $period)) { $period = date('Y-m'); }

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor'
    && ($_POST['action'] ?? '') === 'close_run') {
    $step = (string) ($_POST['step'] ?? 'all');
    if ($step === 'lock') {
        // 锁账是 D-01 五件事之一：先确认，再锁期间，再记流水线步骤
        $lk = api_post('/period-locks', ['period' => $period, 'status' => 'locked',
                                        'note' => '月结收尾锁账', 'actor' => $actor]);
        if (!$lk['ok']) {
            $errMsg = (string) $lk['error'];
        }
    }
    if ($errMsg === null) {
        $res = api_post('/period-close/run', ['period' => $period, 'step' => $step, 'actor' => $actor]);
        if ($res['ok']) {
            $ran = (array) ($res['data']['ran'] ?? []);
            $names = array_map(fn($x) => t((string) $x['name']), $ran);
            $msg = t('已执行：') . implode(' / ', $names)
                 . ($step === 'lock' ? ' · ' . t('期间已锁定') : '');
            header('Location: ?p=period-close&period=' . urlencode($period)
                 . '&msg=' . urlencode($msg));
            exit;
        }
        $errMsg = (string) $res['error'];
    }
}

// 反结账：将 locked 期间重新打开；closed 期间受数据库触发器保护不可重开，需改分录更正
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && $role !== 'auditor'
    && ($_POST['action'] ?? '') === 'reopen') {
    $res = api_post('/period-locks', [
        'period' => $period,
        'status' => 'open',
        'note' => '反结账：' . trim((string) ($_POST['reason'] ?? '')),
        'actor' => $actor,
    ]);
    if ($res['ok']) {
        header('Location: ?p=period-close&period=' . urlencode($period)
             . '&msg=' . urlencode('期间 ' . $period . ' 已重新打开'));
        exit;
    }
    $errMsg = (string) $res['error'];
}

$r = api_get('/period-close?period=' . urlencode($period));
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$steps = $r['data']['steps'] ?? [];
$done = (int) ($r['data']['done'] ?? 0);
$total = (int) ($r['data']['total'] ?? 6);
$pct = $total ? (int) round($done / $total * 100) : 0;

$lkR = api_get('/period-locks');
$lockState = null;
foreach (($lkR['ok'] ? ($lkR['data']['locks'] ?? []) : []) as $l) {
    if ((string) $l['period'] === $period) { $lockState = (string) $l['status']; }
}
$ST = [
    'pending' => [status_label('not_started'), 'draft'], 'done' => [status_label('done'), 'ok'],
    'failed' => ['需处理', 'danger'], 'skipped' => ['已跳过', 'warn'],
];
?>
<div class="page-head">
  <div>
    <h1 class="page-title">月结</h1>
    <div class="page-sub">六步收尾；可自动的步骤一键跑，其余由人确认</div>
  </div>
  <div class="page-actions">
    <form method="get" style="display:flex;gap:6px;align-items:center;margin:0">
      <input type="hidden" name="p" value="period-close">
      <input type="month" name="period" value="<?= e($period) ?>" style="width:150px">
      <button class="btn sm">切换期间</button>
    </form>
    <?php if ($role !== 'auditor'): ?>
      <form method="post" style="margin:0">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="close_run">
        <input type="hidden" name="period" value="<?= e($period) ?>">
        <input type="hidden" name="step" value="all">
        <button class="btn primary">执行可自动的步骤</button>
      </form>
    <?php endif; ?>
  </div>
</div>

<?php if ($errMsg !== null): ?><?= errbox($errMsg) ?><?php endif; ?>

<?= help_html('period-close') ?>
<div class="metrics metrics-sm">
  <div class="metric c3">
    <div class="lbl">本期</div>
    <div class="val mono" style="font-size:var(--f-lg)"><?= e($period) ?></div>
    <div class="hint">按香港财政年度 4/1–3/31 归期</div>
  </div>
  <div class="metric c3">
    <div class="lbl">完成进度</div>
    <div class="val"><?= (int) $done ?>/<?= (int) $total ?></div>
    <div class="hint"><?= (int) $pct ?><?= e(t('% 完成')) ?></div>
  </div>
  <div class="metric c3">
    <div class="lbl">期间状态</div>
    <div class="val" style="font-size:var(--f-lg)">
      <?= $lockState === 'locked' ? '已锁定' : ($lockState === 'closed' ? '已关闭' : '未锁定') ?>
    </div>
    <div class="hint">锁后不可再写入分录</div>
  </div>
  <div class="metric c3">
    <div class="lbl">下一步</div>
    <div class="val" style="font-size:var(--f-lg)">
      <?php
        $next = '全部完成';
        foreach ($steps as $s) {
            if ((string) $s['status'] !== 'done') { $next = (string) $s['name']; break; }
        }
        echo e($next);
      ?>
    </div>
    <div class="hint">按顺序往下做</div>
  </div>
</div>

<?php if ($lockState === 'locked' && $role !== 'auditor'): ?>
<section class="card" style="border-color:var(--c-danger-soft)">
  <header class="card-head"><h2>⚠️ 反结账（解锁期间 <?= e($period) ?>）</h2></header>
  <div class="card-body">
    <p style="margin:0 0 8px">将已锁定的期间重新打开，允许再次录入/修改分录。
       本次操作会记录审计日志，请填写原因。</p>
    <form method="post" onsubmit="return confirm('确认反结账 <?= e($period) ?>？请确保已与财务负责人沟通。')">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="reopen">
      <input type="hidden" name="period" value="<?= e($period) ?>">
      <div class="field" style="max-width:480px;margin-bottom:8px">
        <label class="f">反结账原因 *</label>
        <input type="text" name="reason" required maxlength="200"
               placeholder="例：发现发票日期填错需要重录">
      </div>
      <button type="submit" class="btn" style="background:var(--c-danger);color:#fff;border-color:var(--c-danger)">
        重新打开期间 <?= e($period) ?>
      </button>
      <span class="hint" style="margin-left:10px">
        已关闭（closed）期间受数据库保护不可直接重开，请在下个期间做调整分录更正。
      </span>
    </form>
  </div>
</section>
<?php elseif ($lockState === 'closed'): ?>
<section class="card">
  <header class="card-head"><h2>期间 <?= e($period) ?> 已关闭</h2></header>
  <div class="card-body">
    <p style="margin:0">已关闭期间不可重新打开（数据库触发器强制）。如需更正，请在下个期间录入
      <a href="?p=journal-new">手工调整分录</a>。</p>
  </div>
</section>
<?php endif; ?>

<section class="card">
  <div class="card-head">
    <h2>月结流水线</h2>
    <span class="hint">银行对账、汇率、重估可自动跑；应收应付核对、计提、锁账由人确认</span>
  </div>
  <div class="steps">
    <?php foreach ($steps as $i => $s): ?>
      <?php
        $key = (string) $s['key'];
        $st = (string) $s['status'];
        [$stLab, $stCls] = $ST[$st] ?? [status_label('not_started'), 'draft'];
        $isAuto = !empty($s['auto']);
        $rowCls = $st === 'done' ? 'done' : ($st === 'failed' ? 'failed' : '');
        // 步骤说明按当前语言现场组织：库里存的是当时的记录（审计用），界面不照抄
        $detail = (string) ($s['detail'] ?? '');
        $prm = $s['params'] ?? null;
        if (is_array($prm)) {
            if ($key === 'recon') {
                $n = (int) ($prm['unmatched'] ?? 0);
                $detail = $n > 0
                    ? $n . ' ' . t('笔银行流水未匹配，需人工处理')
                    : t('全部匹配');
            } elseif ($key === 'ar_ap') {
                $detail = t('应收') . ' ' . (int) ($prm['arCount'] ?? 0) . ' ' . t('张 /')
                        . ' ' . money($prm['arAmount'] ?? 0, 'HKD')
                        . ' · ' . t('应付') . ' ' . (int) ($prm['apCount'] ?? 0) . ' ' . t('张 /')
                        . ' ' . money($prm['apAmount'] ?? 0, 'HKD');
            } elseif ($key === 'fx') {
                $n = (int) ($prm['ecbRows'] ?? 0);
                $detail = $n > 0
                    ? t('本月已抓取') . ' ' . $n . ' ' . t('条 ECB 汇率')
                    : t('本月没有 ECB 汇率，请检查汇率更新任务');
            }
        }
        if ($detail === '') { $detail = '尚未执行'; }
        $detail = t($detail);   // 库里存的中文句子若能命中词典就直接换掉
      ?>
      <div class="step <?= e($rowCls) ?>">
        <div class="step-no"><?= $st === 'done' ? '✓' : (int) ($i + 1) ?></div>
        <div>
          <div class="step-name">
            <?= e((string) $s['name']) ?>
            <?php if ($isAuto): ?>
              <span class="tag tag-info" style="margin-left:6px"><?= e(status_label('auto')) ?></span>
            <?php endif; ?>
          </div>
          <div class="step-detail"><?= e($detail) ?></div>
        </div>
        <div class="step-detail"><?= e((string) ($s['finishedAt'] ?? '')) ?></div>
        <div><span class="tag tag-<?= e($stCls) ?>"><?= e($stLab) ?></span></div>
        <div style="text-align:right">
          <?php if ($role === 'auditor'): ?>
            <span class="hint">只读</span>
          <?php elseif ($key === 'lock' && $lockState === 'locked'): ?>
            <a class="btn sm" href="?p=locks">期间锁定</a>
          <?php else: ?>
            <form method="post" class="inline-form">
              <?= csrf_field() ?>
              <input type="hidden" name="action" value="close_run">
              <input type="hidden" name="period" value="<?= e($period) ?>">
              <input type="hidden" name="step" value="<?= e($key) ?>">
              <button class="btn sm<?= $st === 'done' ? '' : ' primary' ?>"
                <?php if ($key === 'lock'): ?>
                  data-confirm="<?= e(t('确认锁定期间？')) ?>"
                  data-confirm-note="<?= e(t('锁定后该期间不能再写入任何分录（数据库触发器强制）。解锁需要另行操作并留痕。请确认本期银行对账、应收应付、汇率、重估、计提都已处理完。')) ?>"
                  data-confirm-ok="<?= e(t('确认锁账')) ?>"
                <?php elseif ($key === 'revalue'): ?>
                  data-confirm="<?= e(t('确认已完成外币重估？')) ?>"
                  data-confirm-note="<?= e(t('这一步只记录月结进度，不会自动生成重估分录。外币余额的重估请先到「期末重估」执行。')) ?>"
                  data-confirm-ok="<?= e(t('确认完成')) ?>"
                <?php endif; ?>
              ><?= $st === 'done' ? '重做' : ($key === 'lock' ? '锁账并完成' : '执行') ?></button>
            </form>
          <?php endif; ?>
        </div>
      </div>
    <?php endforeach; ?>
  </div>
</section>

<section class="card">
  <div class="card-head">
    <h2>相关页面</h2>
  </div>
  <div class="card-body" style="display:flex;gap:8px;flex-wrap:wrap">
    <a class="btn" href="?p=reconcile">对账工作区</a>
    <a class="btn" href="?p=settle">核销工作台</a>
    <a class="btn" href="?p=rates">汇率维护</a>
    <a class="btn" href="?p=revalue">期末重估</a>
    <a class="btn" href="?p=locks">期间锁定</a>
    <a class="btn" href="?p=report-statements">财务报表</a>
    <a class="btn" href="?p=report-center">报表中心</a>
  </div>
</section>

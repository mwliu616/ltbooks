<?php
/*
 * LtBooks — pages/agents.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 智能体管理：岗位编制、运行记录、学习台账、工具权限与成本。 */
$role = isset($role) ? $role : 'accountant';
$tab = (string) ($_GET['tab'] ?? 'team');

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $act = (string) ($_POST['action'] ?? '');
    if ($act === 'promote') {
        // 手动固化与定时任务同一套逻辑：先降级冲突，再固化
        api_post('/jobs/learning/run', ['actor' => (string) ($user['username'] ?? 'system')]);
    }
    if ($act === 'promote_extractor') {
        api_post('/agents/extractor/promote', []);
    }
    if ($act === 'rule_status') {
        api_post('/agents/learning/' . (int) ($_POST['ruleId'] ?? 0) . '/status',
                 ['status' => (string) ($_POST['status'] ?? 'paused')]);
    }
    header('Location: ?p=agents&tab=' . urlencode((string) ($_POST['back'] ?? 'learning')));
    exit;
}

$listR = api_get('/agents/list');
$agents = $listR['ok'] ? ($listR['data']['agents'] ?? []) : [];
$tools  = $listR['ok'] ? ($listR['data']['tools'] ?? []) : [];
$writeToolNames = ['create_invoice', 'create_bill', 'create_expense', 'create_journal',
                   'post_document', 'reverse_entry', 'create_payment',
                   'confirm_bank_match', 'lock_period'];
$statsR = api_get('/agents/stats');
$stats = $statsR['ok'] ? ($statsR['data']['stats'] ?? []) : [];
$sum   = $statsR['ok'] ? ($statsR['data']['learning'] ?? []) : [];
$runsR = api_get('/agents/runs?limit=60');
$runs  = $runsR['ok'] ? ($runsR['data']['runs'] ?? []) : [];
$lr    = api_get('/agents/learning');
$rules = $lr['ok'] ? ($lr['data']['rules'] ?? []) : [];
$exR   = api_get('/agents/extractor/learning');
$ex    = $exR['ok'] ? ($exR['data'] ?? []) : [];
$exSum = $ex['summary'] ?? [];
$exRules = $ex['rules'] ?? [];
$exRecent = $ex['recent'] ?? [];
$jobR  = api_get('/jobs/learning');
$job   = $jobR['ok'] ? $jobR['data'] : [];
$obs   = $job['observation'] ?? [];
$jobHistory = $job['history'] ?? [];
$jobSchedule = $job['schedule'] ?? [];

$roleAgents = array_values(array_filter($agents, fn($a) => $a['role'] === 'role'));
$advAgents  = array_values(array_filter($agents, fn($a) => $a['role'] === 'advisor'));
$byAgent = [];
foreach ($stats as $s) { $byAgent[$s['agent']] = $s; }
$tabs = ['team' => '编制', 'runs' => '运行记录', 'learning' => '学习台账', 'tools' => '工具'];
?>
<div class="page-head">
  <div>
    <h1 class="page-title"><?= e(t('智能体管理')) ?></h1>
    <div class="page-sub" style="margin-top:0">
      三个岗位 + 复核守门人 + 三参谋 · 会计管账不管钱、出纳管钱不管账 · 每笔都记 agent:‹岗位›
    </div>
  </div>
  <div class="page-actions">
    <div class="segmented">
      <?php foreach ($tabs as $k => $v): ?>
        <a href="?p=agents&tab=<?= e($k) ?>" <?= $tab === $k ? 'aria-current="true"' : '' ?>><?= e($v) ?></a>
      <?php endforeach; ?>
    </div>
  </div>
</div>

<?php if ($tab === 'team'): ?>
<?= help_html('agents') ?>
  <div class="agent-grid">
    <?php foreach ($roleAgents as $a): $st = $byAgent[$a['id']] ?? null; ?>
      <div class="card agent-card">
        <div class="card-head">
          <h2 class="card-title"><?= e(t('岗位:' . (string) $a['label'])) ?></h2>
          <span class="status-chip is-ok"><b>✓</b> 在线</span>
        </div>
        <div class="card-body">
          <?= kv_grid([
            ['今日/30 天调用', $st ? num((int) $st['runs']) : '0'],
            ['累计 tokens', $st ? num((int) $st['tokens']) : '0'],
            ['失败次数', $st ? (string) (int) $st['errors'] : '0'],
            ['工具数', (string) count($a['tools'])],
          ]) ?>
          <div class="hint" style="margin-top:10px">
            <?= e(t('白名单：')) ?><?= e(implode(' / ', $a['tools'])) ?>
          </div>
        </div>
      </div>
    <?php endforeach; ?>
  </div>

  <div class="card">
    <div class="card-head"><h2 class="card-title">参谋（被调用，不单独出面对话）</h2></div>
    <div class="card-body">
      <div class="agent-grid">
        <?php foreach ($advAgents as $a): ?>
          <div class="agent-card-sm">
            <div style="font-size:var(--f-sm)"><?= e(t('岗位:' . (string) $a['label'])) ?></div>
            <div class="hint"><?= e(implode('、', $a['tools']) ?: '无工具') ?></div>
          </div>
        <?php endforeach; ?>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><h2 class="card-title">学习情况</h2></div>
    <div class="card-body">
      <?php $s = $sum['rules'] ?? []; $f = $sum['feedback'] ?? []; ?>
      <?= kv_grid([
        ['生效规则', (string) (int) ($s['active'] ?? 0)],
        ['观察中', (string) (int) ($s['observing'] ?? 0)],
        ['已停用', (string) (int) ($s['paused'] ?? 0)],
        ['建议采纳率', isset($f['rate']) && $f['rate'] !== null
            ? number_format((float) $f['rate'] * 100, 1) . '%' : '—'],
      ]) ?>
    </div>
  </div>

<?php elseif ($tab === 'runs'): ?>
  <div class="card">
    <div class="card-head">
      <h2 class="card-title">运行记录（最近 60 次）</h2>
      <span class="hint">每次调用都留痕：谁、何时、用了哪些工具、多少 tokens、结论</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="width:130px">时间</th><th style="width:110px">智能体</th>
          <th>场景 / 输入</th><th style="width:90px">结论</th>
          <th class="num" style="width:90px">tokens</th>
          <th class="num" style="width:90px">耗时</th><th>错误</th>
        </tr></thead>
        <tbody>
        <?php if (!$runs): ?>
          <tr><td colspan="7" class="muted" style="text-align:center;padding:24px">还没有运行记录</td></tr>
        <?php endif; ?>
        <?php foreach ($runs as $r): ?>
          <tr>
            <td class="hint"><?= e((string) $r['created_at']) ?></td>
            <td><?= e((string) $r['agent']) ?></td>
            <td class="hint truncate" style="max-width:340px"><?= e((string) ($r['scene'] ?? '')) ?></td>
            <td>
              <?php $v = (string) ($r['verdict'] ?? ''); ?>
              <?php if ($v === 'PASS'): ?><span class="badge pass">PASS</span>
              <?php elseif ($v === 'REVIEW'): ?><span class="badge review">REVIEW</span>
              <?php elseif ($v === 'FAIL'): ?><span class="badge fail">FAIL</span>
              <?php else: ?><span class="hint">—</span><?php endif; ?>
            </td>
            <td class="num"><?= num((int) $r['tokens']) ?></td>
            <td class="num"><?= num((int) $r['latency_ms']) ?> ms</td>
            <td class="hint"><?= e((string) ($r['error'] ?? '')) ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
  </div>

<?php elseif ($tab === 'learning'): ?>
  <div class="card">
    <div class="card-head">
      <h2 class="card-title"><?= e(t('票据识别学习')) ?></h2>
      <form method="post" style="margin:0">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="promote_extractor">
        <input type="hidden" name="back" value="learning">
        <button class="btn sm" type="submit"><?= e(t('立刻固化识别规则')) ?></button>
      </form>
    </div>
    <div class="card-body" style="padding-bottom:0">
      <div class="hint" style="margin-bottom:12px">
        <?= e(t('你在确认卡片上改过的字段会被记下来：同一供应商同一字段稳定出现并且你改过，就固化成规则；识别之后由确定性代码直接改写，不靠模型记性。只学字段长相，不学判断口径。')) ?>
      </div>
      <div class="metrics" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:12px">
        <div class="metric"><div class="lbl"><?= e(t('纠正样本')) ?></div>
          <div class="val"><?= (int) ($exSum['samples'] ?? 0) ?></div></div>
        <div class="metric"><div class="lbl"><?= e(t('生效规则')) ?></div>
          <div class="val"><?= (int) ($exSum['rules']['active'] ?? 0) ?></div></div>
        <div class="metric"><div class="lbl"><?= e(t('最近改正的字段')) ?></div>
          <div class="val" style="font-size:var(--f-lg)">
            <?php
              $xs = [];
              foreach (($exSum['topFields'] ?? []) as $f) { $xs[] = t((string) ($f['label'] ?? $f['field'])); }
              echo e($xs ? implode(' / ', $xs) : '—');
            ?>
          </div></div>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th><?= e(t('供应商')) ?></th><th style="width:130px"><?= e(t('字段')) ?></th>
          <th><?= e(t('固定为')) ?></th><th class="num" style="width:80px"><?= e(t('样本')) ?></th>
          <th style="width:80px"><?= e(t('状态')) ?></th></tr></thead>
        <tbody>
        <?php if (!$exRules): ?>
          <tr><td colspan="5" class="hint" style="text-align:center;padding:20px">
            <?= e(t('还没有识别规则。你在确认卡片上改一次字段，系统就开始学。')) ?>
          </td></tr>
        <?php endif; ?>
        <?php foreach ($exRules as $r): ?>
          <tr>
            <td class="hint mono"><?= e((string) $r['vendor_key']) ?></td>
            <td><?= e(t((string) ($r['label'] ?? $r['field']))) ?></td>
            <td class="truncate" style="max-width:360px"><?= e((string) $r['value']) ?></td>
            <td class="num"><?= (int) $r['samples'] ?></td>
            <td><span class="badge pass"><?= e(t('生效')) ?></span></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <h2 class="card-title">固化任务</h2>
      <span class="hint">每天 <?= e((string) ($jobSchedule['localTime'] ?? '02:30 Asia/Hong_Kong')) ?> 自动跑一次</span>
    </div>
    <div class="card-body">
      <div style="display:flex;gap:var(--s-6);flex-wrap:wrap;align-items:flex-start">
        <div style="min-width:220px">
          <div class="hint" style="margin-bottom:4px">冷启动观察期</div>
          <div style="font-size:var(--f-lg)">
            <?= (int) ($obs['days'] ?? 0) ?> / <?= (int) ($obs['need'] ?? 30) ?> 天
          </div>
          <div class="hint" style="margin-top:4px">
            <?php if (!empty($obs['ready'])): ?>
              <span class="tag tag-ok">已过观察期</span> 可以固化
            <?php else: ?>
              <span class="tag tag-warn">只观察不固化</span> 满 30 天才开始固化
            <?php endif; ?>
          </div>
        </div>
        <div style="min-width:220px">
          <div class="hint" style="margin-bottom:4px">反馈样本</div>
          <div style="font-size:var(--f-lg)"><?= (int) ($obs['total'] ?? 0) ?></div>
          <div class="hint" style="margin-top:4px">
            第一条 <?= e((string) ($obs['firstAt'] ?? '—')) ?>
          </div>
        </div>
        <div style="flex:1;min-width:280px">
          <div class="hint" style="margin-bottom:6px">最近动作（写入审计链，可回滚）</div>
          <?php if (!$jobHistory): ?>
            <div class="hint">还没有固化记录</div>
          <?php else: ?>
            <table>
              <tbody>
              <?php foreach (array_slice($jobHistory, 0, 4) as $h): ?>
                <tr>
                  <td class="hint mono" style="white-space:nowrap;width:160px"><?= e((string) $h['at']) ?></td>
                  <td>
                    <?php if ($h['action'] === 'ai_learning.promote'): ?>
                      <span class="tag tag-ok">固化</span>
                    <?php else: ?>
                      <span class="tag tag-warn">降级</span>
                    <?php endif; ?>
                    <?= e((string) ($h['detail']['learned'] ?? $h['detail']['rules'][0]['learned'] ?? '')) ?>
                  </td>
                </tr>
              <?php endforeach; ?>
              </tbody>
            </table>
          <?php endif; ?>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <h2 class="card-title">学习台账</h2>
      <form method="post" style="margin:0">
        <?= csrf_field() ?>
        <input type="hidden" name="action" value="promote">
        <input type="hidden" name="back" value="learning">
        <button class="btn sm" type="submit"
          data-confirm="<?= e(t('确认现在跑一次固化？')) ?>"
          data-confirm-note="<?= e(t('先降级近期被推翻的规则，再把达到门槛（≥5 次一致、≥80% 采纳）的偏好固化成规则。固化只影响填写习惯与默认值，不改变任何判断口径或税率。每次动作都写入审计链。')) ?>"
          data-confirm-ok="<?= e(t('确认固化')) ?>">立刻固化一次</button>
      </form>
    </div>
    <div class="card-body" style="padding-bottom:0">
      <div class="hint" style="margin-bottom:12px">
        只学「你怎么做」（科目映射、填写格式、期间习惯、常用默认值）；
        不学「什么是对的」（准则判断、税率、科目性质、校验结论）。
        同一场景 ≥5 次一致采纳才固化；固化后同类不再调模型。
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>场景</th><th>学到什么</th><th class="num" style="width:80px">样本</th>
          <th style="width:80px">置信</th><th style="width:90px">状态</th>
          <th style="width:150px">更新时间</th><th style="width:110px"></th>
        </tr></thead>
        <tbody>
        <?php if (!$rules): ?>
          <tr><td colspan="7" class="muted" style="text-align:center;padding:24px">
            还没有学到规则。系统会在你日常操作中观察（前 30 天只观察不固化）。
          </td></tr>
        <?php endif; ?>
        <?php foreach ($rules as $x): ?>
          <tr>
            <td class="hint"><?= e((string) $x['scene_desc']) ?></td>
            <td><?= e((string) $x['learned']) ?></td>
            <td class="num"><?= (int) $x['samples'] ?></td>
            <td class="hint"><?= e((string) $x['confidence']) ?></td>
            <td>
              <?php $stt = (string) $x['status']; ?>
              <?php if ($stt === 'active'): ?><span class="badge pass">生效</span>
              <?php elseif ($stt === 'observing'): ?><span class="badge review">观察中</span>
              <?php elseif ($stt === 'paused'): ?><span class="pill">已停用</span>
              <?php else: ?><span class="pill">已退役</span><?php endif; ?>
            </td>
            <td class="hint"><?= e((string) $x['updated_at']) ?></td>
            <td>
              <form method="post" style="margin:0;display:inline">
                <?= csrf_field() ?>
                <input type="hidden" name="action" value="rule_status">
                <input type="hidden" name="ruleId" value="<?= (int) $x['rule_id'] ?>">
                <input type="hidden" name="back" value="learning">
                <input type="hidden" name="status" value="<?= $stt === 'active' ? 'paused' : 'active' ?>">
                <button class="btn sm"><?= $stt === 'active' ? '停用' : '启用' ?></button>
              </form>
            </td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
  </div>

<?php else: ?>
  <div class="card">
    <div class="card-head">
      <h2 class="card-title"><?= e(t('工具白名单')) ?> <span class="hint"><?= count($tools) ?></span></h2>
      <?php $nWrite = count(array_filter($tools, fn($t) => (string)($t['level'] ?? '') === 'write')); ?>
      <span class="status-chip <?= $nWrite ? 'is-warn' : 'is-ok' ?>">
        <b><?= $nWrite ? '!' : '✓' ?></b> <?= $nWrite ?> <?= e(t('个可执行')) ?>
      </span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th style="width:210px">工具</th><th style="width:110px"><?= e(t('权限')) ?></th><th><?= e(t('用途')) ?></th></tr></thead>
        <tbody>
        <?php foreach ($tools as $t): ?>
          <?php $lv = (string) ($t['level'] ?? 'read'); ?>
          <tr>
            <td class="mono"><?= e((string) $t['name']) ?></td>
            <td>
              <?php
                $isWrite = in_array((string) $t['name'], $writeToolNames ?? [], true);
              ?>
              <?php if ($isWrite): ?>
                <span class="badge fail"><?= e(t('可执行')) ?></span>
              <?php elseif ($lv === 'propose'): ?>
                <span class="badge review"><?= e(t('只提案')) ?></span>
              <?php else: ?>
                <span class="badge pass"><?= e(t('只读')) ?></span>
              <?php endif; ?>
            </td>
            <td class="hint"><?= e((string) $t['desc']) ?></td>
          </tr>
        <?php endforeach; ?>
        </tbody>
      </table>
    </div>
    <div class="card-body" style="border-top:1px solid var(--c-border)">
      <div class="banner FAIL" style="margin-bottom:12px">
        <span class="banner-icon">!</span>
        <div class="banner-body">
          <div class="banner-title"><?= e(t('会计管账不管钱，出纳管钱不管账')) ?></div>
          <div class="banner-reason">
            <?= e(t('会计可建单、记分录、记账、冲销、锁账，但不登记收付款、不确认银行匹配；出纳可登记收付款、核销、确认银行匹配、建单，但不做分录、不记账、不冲销、不锁账。每次执行以 agent:<岗位> 记入审计链。指令台可切换为「只提案」。')) ?>
          </div>
        </div>
      </div>
      <div class="hint">
        标「Can write」的 9 个工具会直接写账套，只有会计与出纳能用，
        每笔以 agent:‹岗位› 记入审计链（带上发起人）。
        propose_document 是「只提案」模式下的路径：只写待确认提案，人点确认才建单。
        指令台可一键切换「可直接执行 / 只提案」。
      </div>
    </div>
  </div>
<?php endif; ?>

<style>
.agent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--s-3)}
.agent-card{margin-bottom:var(--s-3)}
.agent-card .card-body{padding:var(--s-4) var(--s-5)}
.agent-card-sm{border:1px solid var(--c-border);border-radius:var(--r-sm);padding:10px 12px}
@media (max-width:1000px){.agent-grid{grid-template-columns:1fr}}
</style>

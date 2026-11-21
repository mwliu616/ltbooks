<?php
/*
 * LtBooks — pages/reconcile.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$acc = api_get('/bank-accounts');
if (!$acc['ok']) { echo errbox((string) $acc['error']); return; }
$accounts = $acc['data']['accounts'] ?? [];
$acctId = (int) ($_GET['account'] ?? 0);
if (!$acctId && $accounts) {
    // 默认打开港币账户，而不是按币种字母序排在第一个的账户
    $base = base_currency();
    $pick = null;
    foreach ($accounts as $a) {
        if (strtoupper((string) $a['currency']) === strtoupper($base)) { $pick = $a; break; }
    }
    $acctId = (int) ($pick ?: $accounts[0])['account_id'];
}
$cur = null;
foreach ($accounts as $a) { if ((int) $a['account_id'] === $acctId) { $cur = $a; } }

$linesR = api_get('/bank-lines?accountId=' . $acctId);
$lines  = $linesR['data']['lines'] ?? [];
$matchR = api_post('/bank/match', ['bankAccountId' => $acctId]);
$mdata  = $matchR['ok'] ? $matchR['data'] : [];
$matches = $mdata['matches'] ?? [];
$pending = $mdata['pending'] ?? [];

$selLine = (int) ($_GET['line'] ?? 0);
$cands = [];
foreach (array_merge($matches, $pending) as $m) {
    if ((int) ($m['lineId'] ?? 0) === $selLine) { $cands[] = $m; }
}
$role = isset($role) ? $role : 'accountant';  // 来自服务端会话

// 无单据的银行流水（手续费、利息等）直接入账
$postMsg = null; $postErr = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'post_line') {
    $r = api_post('/bank/lines/' . (int) ($_POST['lineId'] ?? 0) . '/post', [
        'accountCode' => (string) ($_POST['accountCode'] ?? ''),
        'description' => trim((string) ($_POST['description'] ?? '')),
        'actor' => $displayName ?? 'system',
    ]);
    if ($r['ok']) {
        $postMsg = '已入账：' . $r['data']['entryNo'] . '（科目 ' . $r['data']['accountCode']
                 . '，金额 ' . number_format((float) $r['data']['amount'], 2) . '）';
        $selLine = 0;
    } else { $postErr = (string) $r['error']; }
}

// 流水附件：上传 / 下载
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'upload_line_file') {
    $lid = (int) ($_POST['lineId'] ?? 0);
    if (empty($_FILES['file']['tmp_name']) || ($_FILES['file']['error'] ?? 1) !== UPLOAD_ERR_OK) {
        $postErr = '上传失败：未选择文件';
    } elseif (($_FILES['file']['size'] ?? 0) > 20 * 1024 * 1024) {
        $postErr = '文件超过 20MB 上限';
    } else {
        $orig = basename((string) $_FILES['file']['name']);
        $ext = strtolower(pathinfo($orig, PATHINFO_EXTENSION));
        $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', $orig);
        $dest = UPLOAD_DIR . '/' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
        if (!move_uploaded_file($_FILES['file']['tmp_name'], $dest)) {
            $postErr = '文件落盘失败';
        } else {
            @chmod($dest, 0640);
            $r = api_post('/bank/lines/' . $lid . '/files', [
                'fileName' => $orig, 'fileType' => $ext !== '' ? $ext : 'other',
                'fileSize' => filesize($dest), 'sha256' => hash_file('sha256', $dest),
                'storagePath' => $dest, 'actor' => $displayName ?? 'system',
            ]);
            if ($r['ok']) { $postMsg = '附件已上传：' . $orig; $selLine = $lid; }
            else { @unlink($dest); $postErr = (string) $r['error']; }
        }
    }
}

if (isset($_GET['dlfile'])) {
    $r2 = api_get('/bank-line-files/' . (int) $_GET['dlfile']);
    if ($r2['ok']) {
        // 接口返回的是 storage_path（数据库原字段名）
        $path = $r2['data']['storage_path'] ?? null;
        if ($path && is_file($path)) {
            send_file((string) $path, (string) ($r2['data']['file_name'] ?? 'file'));
        }
    }
    $postErr = '文件不存在';
}

// 可记账科目：费用 / 收入 / 成本 / 资产（现金）
$accAll = api_get('/accounts/tree');
$postable = [];
$suggest = '6400';
$selLineObj = null;
foreach ($lines as $l) { if ((int) $l['line_id'] === $selLine) { $selLineObj = $l; } }
$lineFiles = [];
if ($selLineObj !== null) {
    $lf = api_get('/bank/lines/' . (int) $selLineObj['line_id'] . '/files');
    $lineFiles = $lf['ok'] ? ($lf['data']['files'] ?? []) : [];
}
if ($selLineObj !== null) {
    $desc = strtoupper((string) ($selLineObj['counterparty_name'] ?? ''));
    $inflow = (float) $selLineObj['amount_functional'] > 0;
    if (preg_match('/INTEREST/', $desc)) {
        $suggest = $inflow ? '4500' : '7100';
    } elseif (preg_match('/CHARGE|FEE|手续费|服务费|SERVICE/i', $desc)) {
        $suggest = '6400';
    } elseif (preg_match('/ATM|WITHDRAWAL|CASH/i', $desc)) {
        $suggest = '1110';
    }
}
if ($accAll['ok']) {
    foreach ($accAll['data']['accounts'] as $a) {
        if (!in_array($a['category'], ['expense', 'revenue', 'cogs', 'asset'], true)) { continue; }
        if (!$a['is_active']) { continue; }
        if (strlen((string) $a['account_code']) > 4 && $a['category'] !== 'expense') { continue; }
        $postable[] = $a;
    }
}
?>
<?php if ($postMsg): ?>
  <div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body">
    <div class="banner-title">流水已入账</div><div class="banner-reason"><?= e($postMsg) ?></div>
  </div></div>
<?php endif; ?>
<?php if ($postErr): ?><?= errbox($postErr) ?><?php endif; ?>

<div class="toolbar">
  <h2 style="margin:0;font-size:var(--f-lg);font-weight:400">银行对账</h2>
  <form method="get" style="display:flex;gap:8px;align-items:center">
    <input type="hidden" name="p" value="reconcile">
    <select name="account" onchange="this.form.submit()">
      <?php foreach ($accounts as $a): ?>
        <option value="<?= (int) $a['account_id'] ?>"<?= (int) $a['account_id'] === $acctId ? ' selected' : '' ?>>
          <?= e($a['currency'] . ' · ' . $a['name']) ?>
        </option>
      <?php endforeach; ?>
    </select>
  </form>
  <?php if ($matchR['ok']): ?>
    <span class="hint">自动核销 <?= num(count($matches)) ?> · 待复核 <?= num(count($pending)) ?>
      · 未匹配 <?= num(count($mdata['unmatched'] ?? [])) ?></span>
  <?php else: ?>
    <span class="hint">匹配服务不可用：<?= e((string) $matchR['error']) ?></span>
  <?php endif; ?>
</div>

<div class="cols">
  <!-- 左：银行流水 -->
  <div class="col">
    <div class="col-head">银行流水<?= $cur ? '（' . e((string) $cur['currency']) . '）' : '' ?></div>
    <div class="col-body" style="padding:0">
      <?php if (!$lines): ?>
        <?= empty_state('没有流水') ?>
      <?php else: ?>
      <div class="table-wrap"><table>
      <thead><tr><th>日期</th><th>对手方</th><th class="num">原币</th><th class="num">折HKD</th><th>状态</th></tr></thead>
      <tbody>
      <?php foreach ($lines as $l): ?>
        <tr class="clickable<?= (int) $l['line_id'] === $selLine ? ' sel' : '' ?>"
            onclick="location.href='?p=reconcile&account=<?= $acctId ?>&line=<?= (int) $l['line_id'] ?>'">
          <td><?= e((string) $l['txn_date']) ?></td>
          <td><?= e((string) ($l['counterparty_name'] ?: '—')) ?></td>
          <td class="num"><?= money($l['amount_original'], (string) $l['currency']) ?></td>
          <td class="num"><?= $l['currency'] === 'HKD' ? '—' : money($l['amount_functional'], 'HKD') ?></td>
          <td><?= status_pill((string) $l['match_status']) ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody></table></div>
      <?php endif; ?>
    </div>
  </div>

  <!-- 中：匹配操作 -->
  <div class="col">
    <div class="col-head">匹配操作</div>

    <?php if ($selLineObj !== null): ?>
      <div style="padding:12px 14px;border-bottom:1px solid var(--c-border)">
        <div style="font-size:var(--f-xs);font-weight:400;margin-bottom:4px">
          <?= e((string) $selLineObj['txn_date']) ?> ·
          <?= money($selLineObj['amount_functional'], 'HKD') ?>
        </div>
        <div class="hint"><?= e((string) ($selLineObj['counterparty_name'] ?: '—')) ?>
          <?php if (!empty($selLineObj['bank_ref'])): ?> · <?= e((string) $selLineObj['bank_ref']) ?><?php endif; ?>
        </div>
        <div style="margin-top:10px;padding-top:10px;border-top:1px dashed var(--c-border)">
          <div style="font-size:var(--f-2xs);font-weight:400;margin-bottom:6px"><?= e(t('附件（可即时上传）')) ?></div>
          <?php if ($lineFiles): ?>
            <div style="display:grid;gap:4px;margin-bottom:8px">
              <?php foreach ($lineFiles as $f): ?>
                <div style="display:flex;gap:6px;align-items:center;font-size:var(--f-2xs)">
                  <a href="?p=reconcile&account=<?= $acctId ?>&line=<?= (int) $selLineObj['line_id'] ?>&dlfile=<?= (int) $f['file_id'] ?>">
                    <?= e((string) $f['file_name']) ?>
                  </a>
                  <span class="hint"><?= (int) $f['file_size'] < 1024
                    ? (int) $f['file_size'] . ' B'
                    : number_format((int) $f['file_size'] / 1024, 0) . ' KB' ?></span>
                </div>
              <?php endforeach; ?>
            </div>
          <?php endif; ?>
          <?php if ($role !== 'auditor'): ?>
          <form method="post" enctype="multipart/form-data" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <?= csrf_field() ?>
            <input type="hidden" name="action" value="upload_line_file">
            <input type="hidden" name="lineId" value="<?= (int) $selLineObj['line_id'] ?>">
            <input type="file" name="file" required style="font-size:var(--f-2xs);max-width:210px">
            <button class="btn sm">上传</button>
          </form>
          <div class="hint">收款回单、存款单、支票影像等；上限 20MB，保存 7 年</div>
          <?php endif; ?>
        </div>

        <?php if (($selLineObj['match_status'] ?? '') === 'unmatched'): ?>
        <details class="postform">
          <summary class="btn sm" style="display:inline-flex;margin-top:8px">无单据：直接入账</summary>
          <form method="post" style="margin-top:10px">
            <?= csrf_field() ?>
            <input type="hidden" name="action" value="post_line">
            <input type="hidden" name="lineId" value="<?= (int) $selLineObj['line_id'] ?>">
            <div class="field"><label class="f">对方科目 *</label>
              <select name="accountCode" required>
                <?php foreach ($postable as $a): ?>
                  <option value="<?= e($a['account_code']) ?>"<?= $a['account_code'] === $suggest ? ' selected' : '' ?>>
                    <?= e($a['account_code'] . ' · ' . acc_name($a['account_code'], $a['account_name'])) ?>
                  </option>
                <?php endforeach; ?>
              </select>
              <div class="hint">银行手续费通常记 6400；利息收入 4500；ATM 取现 1110</div>
            </div>
            <div class="field" style="margin-top:8px"><label class="f">摘要</label>
              <input type="text" name="description" value="<?= e((string) ($selLineObj['counterparty_name'] ?: '银行流水')) ?>"></div>
            <div class="toolbar form-actions" style="margin-top:10px;margin-bottom:0">
              <button class="btn primary">确认入账</button>
              <span class="hint">
                <?= (float) $selLineObj['amount_functional'] < 0 ? '借 费用 ／ 贷 银行' : '借 银行 ／ 贷 收入' ?>
              </span>
            </div>
          </form>
        </details>
        <?php else: ?>
          <div class="hint" style="margin-top:8px">
            该流水状态为 <?= e((string) $selLineObj['match_status']) ?>，无需再匹配。
          </div>
        <?php endif; ?>
      </div>
    <?php endif; ?>
    <div class="col-body">
      <?php if (!$selLine): ?>
        点击左侧流水，再选右侧候选，然后确认匹配。
      <?php elseif (!$cands): ?>
        <?= e(t('该流水没有候选单据')) ?>。
      <?php else: ?>
        <?php foreach ($cands as $m): ?>
          <?php
          $c = $m['candidate'] ?? $m;
          $same = !empty($c['sameCurrency']);
          $over = abs((float) ($c['differencePercent'] ?? 0)) > 1 && (float) ($c['difference'] ?? 0) !== 0;
          $ruleOk = in_array($m['rule'] ?? '', ['P1', 'P2'], true);
          $disabled = $over && $same;
          ?>
          <div style="border:1px solid var(--border);border-radius:5px;padding:9px;margin-bottom:8px">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span><b><?= e((string) ($c['docNo'] ?? ('单据 ' . ($c['docId'] ?? '')))) ?></b>
                <?= badge($ruleOk ? 'PASS' : 'REVIEW') ?></span>
              <span class="num"><?= money($c['outstandingOriginal'] ?? null, (string) ($c['docCurrency'] ?? '')) ?></span>
            </div>
            <?php if (!empty($c['conversion'])): $cv = $c['conversion']; ?>
              <div class="hint" style="margin-top:4px">
                折算：<?= e((string) $cv['from']) ?>→<?= e((string) $cv['to']) ?>
                @ <?= e((string) $cv['rate']) ?> = <?= money($cv['convertedAmount'] ?? null, (string) $cv['to']) ?>
                （汇率日 <?= e((string) $cv['rateDate']) ?>）
              </div>
            <?php endif; ?>
            <?php if ((float) ($c['difference'] ?? 0) !== 0): ?>
              <div class="hint" style="color:<?= $over ? 'var(--fail)' : '#8A5A00' ?>;margin-top:3px">
                差异 <?= money($c['difference']) ?>（<?= e((string) ($c['differencePercent'] ?? 0)) ?>%）
                <?= $over ? ' · 超出容差，须人工确认' : '' ?>
              </div>
            <?php endif; ?>
            <?php if ($role === 'auditor'): ?>
              <div class="hint" style="margin-top:6px">审计只读</div>
            <?php else: ?>
              <form method="post" style="margin-top:7px">
  <?= csrf_field() ?>
                <input type="hidden" name="action" value="confirm_match">
                <input type="hidden" name="lineId" value="<?= (int) $m['lineId'] ?>">
                <input type="hidden" name="docId" value="<?= (int) ($m['docId'] ?? 0) ?>">
                <input type="hidden" name="rule" value="<?= e((string) ($m['rule'] ?? 'P2')) ?>">
                <input type="hidden" name="actor" value="<?= e($role) ?>">
                <input type="hidden" name="back" value="reconcile">
                <?php if (!$same): ?>
                  <div class="field" style="margin-bottom:6px">
                    <label class="f">跨币种须填人工确认理由（§4.3.4）</label>
                    <input type="text" name="reason" value="已核对折算汇率与合同" required>
                  </div>
                <?php endif; ?>
                <button class="btn sm primary" <?= $disabled ? 'disabled' : '' ?>
                  title="<?= $disabled ? '容差超限，需人工处理' : '' ?>">确认匹配</button>
              </form>
            <?php endif; ?>
          </div>
        <?php endforeach; ?>
      <?php endif; ?>
    </div>
  </div>

  <!-- 右：候选与规则说明 -->
  <div class="col">
    <div class="col-head">候选单据</div>
    <div class="col-body">
      <div class="hint" style="line-height:1.7">
        P1/P2 绿色可直接确认；P3/P4 黄色需人工判断；跨币种一律人工确认并留折算汇率。
        仅 P1/P2 且 high、同币种、金额精确才自动核销。
      </div>
      <?php if ($pending): ?>
        <div style="margin-top:10px"><b>待复核原因</b>
          <ul class="hint" style="margin:6px 0 0;padding-left:16px;line-height:1.6">
          <?php foreach (array_slice($pending, 0, 5) as $p): ?>
            <li><?= e((string) ($p['reason'] ?? '')) ?></li>
          <?php endforeach; ?>
          </ul>
        </div>
      <?php endif; ?>
    </div>
  </div>
</div>

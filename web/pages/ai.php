<?php
/*
 * LtBooks — pages/ai.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$answer = null; $errMsg = null; $extracted = null; $ocrMeta = null;

// ---- 问账 ----
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'ask') {
    $q = trim((string) ($_POST['question'] ?? ''));
    if ($q === '') {
        $errMsg = '请输入问题';
    } else {
        $r = api_post('/ai/ask', ['question' => $q]);
        if ($r['ok']) { $answer = $r['data']; }
        else { $errMsg = (string) $r['error']; }
    }
}

// ---- 发票识别 ----
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'extract') {
    $text = trim((string) ($_POST['text'] ?? ''));
    $payload = ['text' => $text];

    if (!empty($_FILES['file']['tmp_name']) && ($_FILES['file']['error'] ?? 1) === UPLOAD_ERR_OK) {
        if (($_FILES['file']['size'] ?? 0) > 20 * 1024 * 1024) {
            $errMsg = '文件超过 20MB';
        } else {
            $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', basename((string) $_FILES['file']['name']));
            $dest = UPLOAD_DIR . '/ocr-' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
            if (move_uploaded_file($_FILES['file']['tmp_name'], $dest)) {
                @chmod($dest, 0640);
                $payload = ['path' => $dest];
            } else {
                $errMsg = '文件落盘失败';
            }
        }
    }

    if ($errMsg === null && (empty($payload['text']) && empty($payload['path']))) {
        $errMsg = '请粘贴文本或上传文件';
    }
    if ($errMsg === null) {
        $r = api_post('/ai/extract-invoice', $payload);
        if ($r['ok']) {
            $extracted = $r['data'];
            $ocrMeta = $extracted['ocr'] ?? null;
            // 完整预填：识别出的字段全部带过去，供采购/销售表单直接回填
            $_SESSION['ai_prefill'] = [
                'invoiceNo' => $extracted['invoiceNo'] ?? '',
                'vendorInvoiceNo' => $extracted['invoiceNo'] ?? '',
                'supplierName' => $extracted['supplierName'] ?? '',
                'customerName' => $extracted['customerName'] ?? '',
                'supplierAddress' => $extracted['supplierAddress'] ?? '',
                'supplierPhone' => $extracted['supplierPhone'] ?? '',
                'supplierTaxId' => $extracted['supplierTaxId'] ?? '',
                'invoiceDate' => $extracted['invoiceDate'] ?? '',
                'dueDate' => $extracted['dueDate'] ?? '',
                'currency' => $extracted['currency'] ?? 'HKD',
                'amountOriginal' => $extracted['amountOriginal'] ?? '',
                'taxOriginal' => $extracted['taxOriginal'] !== null ? $extracted['taxOriginal'] : '',
                'grossOriginal' => $extracted['grossOriginal'] ?? '',
                'lines' => $extracted['lines'] ?? [],
                'paymentAccounts' => $extracted['paymentAccounts'] ?? [],
                'paymentTerms' => $extracted['paymentTerms'] ?? '',
                'notes' => $extracted['notes'] ?? '',
                'ocr' => $ocrMeta ?? null,
            ];
        } else {
            $errMsg = (string) $r['error'];
        }
    }
}

$status = api_get('/ai/ocr-status');
$tools = $status['ok'] ? ($status['data']['tools'] ?? []) : [];
$llmOk = $status['ok'] ? ($status['data']['llmConfigured'] ?? false) : false;
$model = $status['ok'] ? ($status['data']['model'] ?? '') : '';

if ($errMsg) { echo errbox($errMsg); }
?>

<div class="banner REVIEW" style="background:var(--c-primary-soft);border-color:var(--c-primary-border);color:var(--c-primary)">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title">先分清方向：收到的是支出，开出的是收入</div>
    <div class="banner-reason">
      <b>采购发票</b>（供应商开给你）→ 借 成本/费用 ＋ 进项税额，贷 应付账款 —— 这是支出。<br>
      <b>销售发票</b>（你开给客户）→ 借 应收/合同资产，贷 收入 —— 这才是收入。
    </div>
  </div>
</div>

<?php
$ag = api_get('/agent/tools');
$agOk = $ag['ok'] && !empty($ag['data']['available']);
$agTools = $ag['ok'] ? ($ag['data']['tools'] ?? []) : [];
$agLabel = ['finance_journal_entry_check' => '分录校验',
            'finance_reconciliation_snapshot' => '对账快照',
            'finance_variance_bridge' => '差异桥接',
            'mysql_query' => '只读查询'];
?>
<?php
$agList = implode('、', array_map(fn($t) => $agLabel[$t] ?? $t, $agTools));
?>
<div class="toolbar" style="margin-bottom:12px">
  <span class="hint">校验由 DSH「HKFRS 财务守门人」智能体执行，只读、白名单固定：<?= e($agList) ?></span>
  <span class="grow"></span>
  <span class="status-chip <?= $agOk ? 'is-ok' : 'is-fail' ?>"
        title="<?= e('系统不复刻校验逻辑，全部结果由智能体返回。' . ($agOk ? '' : ' 当前不可用：所有校验按 FAIL 处理，禁止过账。')) ?>">
    <b><?= $agOk ? '✓' : '✕' ?></b>
    智能体<?= $agOk ? '运行中' : '不可用' ?>
  </span>
  <span class="status-chip <?= $llmOk ? 'is-ok' : 'is-warn' ?>">
    <b><?= $llmOk ? '✓' : '!' ?></b>
    模型<?= $llmOk ? '已配置' : '未配置' ?>
  </span>
</div>

<?php if (!$llmOk): ?>
  <div class="hint" style="margin-bottom:12px">
    未检测到模型密钥，问答与字段识别不可用；OCR 文本抽取仍可用。
  </div>
<?php endif; ?>

<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="ask">
  <div class="field">
    <label class="f">用中文问账（只读查询，不会改动任何数据）</label>
    <input type="text" name="question" placeholder="例如：按币种列出未收款金额；本月有哪些分录被冲销"
           value="<?= e((string) ($_POST['question'] ?? '')) ?>" required>
  </div>
  <div class="toolbar form-actions" style="margin-top:10px;margin-bottom:0">
    <button class="btn primary" <?= $llmOk ? '' : 'disabled' ?>>提问</button>
    <span class="hint">模型 <?= e($model ?: '未配置') ?></span>
  </div>
</form>
<?php echo card('自然语言查账', ob_get_clean()); ?>

<?php if ($answer !== null): ?>
  <?php ob_start(); ?>
  <div style="font-size:var(--f-xs);line-height:1.8;white-space:pre-wrap"><?= e((string) $answer['answer']) ?></div>
  <details style="margin-top:12px">
    <summary class="hint" style="cursor:pointer">查看执行的 SQL 与返回数据（<?= (int) $answer['rowCount'] ?> 行）</summary>
    <pre style="background:#F7F9FB;border:1px solid var(--border);border-radius:4px;padding:10px;overflow-x:auto;font-size:var(--f-2xs);margin-top:8px"><?= e((string) $answer['sql']) ?></pre>
    <?php if (!empty($answer['rows'])): ?>
      <div class="table-wrap" style="margin-top:8px"><table style="min-width:0">
      <thead><tr><?php foreach (array_keys($answer['rows'][0]) as $h): ?><th><?= e((string) $h) ?></th><?php endforeach; ?></tr></thead>
      <tbody>
      <?php foreach (array_slice($answer['rows'], 0, 20) as $row): ?>
        <tr><?php foreach ($row as $v): ?><td><?= e(is_scalar($v) || $v === null ? (string) $v : json_encode($v, JSON_UNESCAPED_UNICODE)) ?></td><?php endforeach; ?></tr>
      <?php endforeach; ?>
      </tbody></table></div>
    <?php endif; ?>
  </details>
  <div class="hint" style="margin-top:10px"><?= e((string) $answer['disclaimer']) ?></div>
  <?php echo card('回答', ob_get_clean()); ?>
<?php endif; ?>

<?php ob_start(); ?>
<form method="post" enctype="multipart/form-data">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="extract">
  <div class="field">
    <label class="f">上传发票（PDF / 图片 / 文本）— 默认按「我收到的发票（支出）」处理</label>
    <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.txt,.csv">
    <div class="hint">
      PDF 优先抽取文字层；扫描件与图片走 OCR（<?= $tools['tesseract'] ?? false ? '已就绪' : '未安装' ?>）。
      上限 20MB。
    </div>
  </div>
  <div class="field" style="margin-top:12px">
    <label class="f">或直接粘贴发票文字</label>
    <textarea name="text" rows="7" style="width:100%;font-family:inherit;font-size:var(--f-xs);padding:9px;border:1px solid #D0D5DD;border-radius:4px"
      placeholder="把发票内容粘贴到这里，例如：&#10;ACME TRADING LIMITED&#10;发票号: INV-2026-8899&#10;开票日期: 2026-11-05&#10;小计 50000.00  税 6500.00  合计 56500.00"></textarea>
  </div>
  <div class="toolbar form-actions" style="margin-top:10px;margin-bottom:0">
    <button class="btn primary" <?= $llmOk ? '' : 'disabled' ?>>识别并提取字段</button>
    <span class="hint">识别结果只作建议，须人工确认后才可入账</span>
  </div>
</form>
<?php echo card('发票智能识别', ob_get_clean()); ?>

<?php if ($extracted !== null): ?>
  <?php
  $conf = (string) ($extracted['confidence'] ?? 'low');
  $confStatus = $conf === 'high' ? 'PASS' : ($conf === 'medium' ? 'REVIEW' : 'FAIL');
  ob_start(); ?>
  <div style="margin-bottom:10px">
    <?= badge($confStatus) ?>
    <span class="hint">置信度 <?= e($conf) ?><?= $ocrMeta ? ' · 抽取方式 ' . e((string) $ocrMeta['method']) : '' ?>
      · 源文本 <?= (int) ($extracted['sourceChars'] ?? 0) ?> 字</span>
  </div>
  <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px 26px">
    <?php foreach ([
        'invoiceNo' => '发票号', 'invoiceDate' => '开票日期', 'dueDate' => '到期日',
        'currency' => '币种', 'supplierName' => '开票方', 'customerName' => '受票方',
        'supplierAddress' => '开票方地址', 'supplierPhone' => '开票方电话',
        'supplierTaxId' => '开票方税号',
        'amountOriginal' => '不含税金额', 'taxOriginal' => '税额',
        'grossOriginal' => '价税合计', 'taxRate' => '反推税率',
    ] as $k => $lab):
      $v = $extracted[$k] ?? null;
      if ($k === 'taxRate' && $v !== null && is_numeric($v)) { $v = rtrim(rtrim(sprintf('%.4f', (float) $v * 100), '0'), '.') . '%'; }
      if (is_array($v)) { $v = implode(' / ', $v); }
    ?>
      <div class="kv"><b><?= e($lab) ?></b><span><?= e($v === null || $v === '' ? '—' : (string) $v) ?></span></div>
    <?php endforeach; ?>
  </div>
  <?php if (!empty($extracted['lines'])): ?>
    <div style="margin-top:10px"><b>明细</b>
      <div class="table-wrap" style="margin-top:6px"><table style="min-width:0">
      <thead><tr><th>项目</th><th>服务期间</th><th class="num" style="width:140px">金额</th></tr></thead>
      <tbody>
      <?php foreach ($extracted['lines'] as $ln): ?>
        <tr><td><?= e((string) ($ln['description'] ?? '')) ?></td>
            <td class="hint"><?= e((string) (($ln['period'] ?? '') ?: '—')) ?></td>
            <td class="num"><?= is_numeric($ln['amount'] ?? null) ? money((float) $ln['amount']) : '—' ?></td></tr>
      <?php endforeach; ?>
      </tbody></table></div>
    </div>
  <?php endif; ?>
  <?php if (!empty($extracted['paymentAccounts'])): ?>
    <div style="margin-top:12px"><b>收款账户</b>
      <div class="table-wrap" style="margin-top:6px"><table style="min-width:0">
      <thead><tr><th>银行</th><th>账号</th><th>户名</th></tr></thead>
      <tbody>
      <?php foreach ($extracted['paymentAccounts'] as $pa): ?>
        <tr><td><?= e((string) ($pa['bank'] ?? '—')) ?></td>
            <td><code><?= e((string) ($pa['account'] ?? '—')) ?></code></td>
            <td class="hint"><?= e((string) (($pa['holder'] ?? '') ?: '—')) ?></td></tr>
      <?php endforeach; ?>
      </tbody></table></div>
    </div>
  <?php endif; ?>

  <?php if (!empty($extracted['paymentTerms']) || !empty($extracted['notes'])): ?>
    <div style="margin-top:12px">
      <?php if (!empty($extracted['paymentTerms'])): ?>
        <div class="kv"><b>付款条款</b><span><?= nl2br(e((string) $extracted['paymentTerms'])) ?></span></div>
      <?php endif; ?>
      <?php if (!empty($extracted['notes'])): ?>
        <div class="kv"><b>备注</b><span><?= nl2br(e((string) $extracted['notes'])) ?></span></div>
      <?php endif; ?>
    </div>
  <?php endif; ?>

  <?php if (!empty($extracted['warnings'])): ?>
    <div class="errbox" style="margin-top:10px"><b>需注意</b>
      <ul style="margin:6px 0 0;padding-left:16px">
      <?php foreach ($extracted['warnings'] as $w): ?><li><?= e((string) $w) ?></li><?php endforeach; ?>
      </ul>
    </div>
  <?php endif; ?>
  <div class="toolbar" style="margin-top:12px;margin-bottom:0;gap:10px">
    <a class="btn primary" href="?p=bill-new&prefill=1">作为采购发票（支出）</a>
    <a class="btn" href="?p=invoice-new&prefill=1">作为销售发票（收入）</a>
  </div>
  <div class="hint" style="margin-top:8px">
    供应商开给你的发票选「采购发票」，你自己开给客户的选「销售发票」。
    方向错了会把支出记成收入，记账前请确认。
  </div>
  <div class="hint" style="margin-top:8px"><?= e((string) ($extracted['disclaimer'] ?? '')) ?></div>
  <?php echo card('识别结果', ob_get_clean()); ?>
<?php endif; ?>

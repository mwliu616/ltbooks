<?php
/*
 * LtBooks — pages/bank-import.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null; $detail = null;

$accR = api_get('/bank-accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];

// ---- 上传文件并解析（CSV / XLSX / XLS / PDF）----
$parsed = null;
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'parse_file') {
    $up = $_FILES['statement'] ?? null;
    if (!$up || ($up['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
        $errMsg = '请选择要上传的对账单文件';
    } else {
        $r = api_upload('/bank/parse-statement', 'file', $up['tmp_name'], (string) $up['name']);
        if ($r['ok']) {
            $parsed = $r['data'];
            $parsed['uploadedName'] = (string) $up['name'];
            $parsed['bankAccountId'] = (int) ($_POST['bankAccountId'] ?? 0);
        } else {
            $errMsg = (string) $r['error'];
        }
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'import_statement') {
    $acctId = (int) ($_POST['bankAccountId'] ?? 0);
    $raw = (string) ($_POST['csv'] ?? '');
    $fileName = trim((string) ($_POST['fileName'] ?? 'statement.csv'));

    // 文件解析的结果用 base64 JSON 传递，避免 CSV 在 textarea 里被 HTML 转义
    $lines = [];
    $parseErr = null;
    $packed = (string) ($_POST['parsedRows'] ?? '');
    if ($packed !== '') {
        $decoded = json_decode((string) base64_decode($packed, true), true);
        if (!is_array($decoded) || !$decoded) {
            $parseErr = '解析结果已损坏，请重新上传文件';
        } else {
            foreach ($decoded as $r) {
                $lines[] = [
                    'date' => (string) ($r['date'] ?? ''),
                    'amount' => (float) ($r['amount'] ?? 0),
                    'ref' => (string) ($r['ref'] ?? ''),
                    'counterparty' => (string) ($r['description'] ?? ''),
                ];
            }
            $raw = 'file:' . $fileName;
        }
    }
    foreach (($packed !== '' ? [] : preg_split('/\r\n|\r|\n/', trim($raw))) as $i => $row) {
        if ($i === 0 && stripos($row, 'date') !== false) { continue; }  // 跳过表头
        if (trim($row) === '') { continue; }
        $c = str_getcsv($row);
        if (count($c) < 2) { $parseErr = '第 ' . ($i + 1) . ' 行列数不足'; break; }
        $amt = is_numeric(trim($c[1])) ? (float) trim($c[1]) : null;
        if ($amt === null) { $parseErr = '第 ' . ($i + 1) . ' 行金额不是数字'; break; }
        $lines[] = [
            'date' => trim($c[0]),
            'amount' => $amt,
            'ref' => trim($c[2] ?? ''),
            'counterparty' => trim($c[3] ?? ''),
        ];
    }

    if ($parseErr !== null) {
        $errMsg = 'CSV 解析失败：' . $parseErr;
    } elseif (!$lines) {
        $errMsg = '没有解析到任何明细行';
    } else {
        $sha = hash('sha256', $raw);
        $r = api_post('/bank/import', [
            'bankAccountId' => $acctId,
            'fileName' => $fileName,
            'fileFormat' => 'csv',
            'sha256' => $sha,
            'header' => [
                'periodStart' => $_POST['periodStart'] ?: null,
                'periodEnd' => $_POST['periodEnd'] ?: null,
                'openingBalance' => (float) ($_POST['openingBalance'] ?? 0),
                'closingBalance' => (float) ($_POST['closingBalance'] ?? 0),
                'totalDebits' => (float) ($_POST['totalDebits'] ?? 0),
                'totalCredits' => (float) ($_POST['totalCredits'] ?? 0),
            ],
            'lines' => $lines,
            'actor' => $displayName ?? 'system',
        ]);
        if ($r['ok']) {
            $msg = (string) ($r['data']['note'] ?? '导入完成');
        } elseif ($r['status'] === 409) {
            $errMsg = (string) ($r['data']['reason'] ?? '重复导入');
        } else {
            $errMsg = (string) $r['error'];
            $detail = $r['data']['detail'] ?? null;
        }
    }
}

if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">导入成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }
if ($detail) { echo '<div class="errbox"><b>算术校验明细</b><div>' . e(implode('；', (array) $detail)) . '</div></div>'; }

?>
<?php $uploadMode = !empty($_GET['upload']); ?>
<?php if (!$uploadMode): ?>
<?php
$impR = api_get('/bank/statement-imports');
$imports = $impR['ok'] ? ($impR['data']['imports'] ?? []) : [];
?>
<?php ob_start(); ?>
<div class="toolbar" style="padding:10px 14px;border-bottom:1px solid var(--c-border)">
  <span class="hint"><?= e(t('已导入的月结单按时间倒序；查看跳转到该账户流水，下载为原始文件。')) ?></span>
  <?php if ($role !== 'auditor'): ?>
  <a class="btn primary sm" style="margin-left:auto" href="?p=bank-import&upload=1">＋ <?= e(t('导入月结单')) ?></a>
  <?php endif; ?>
</div>
<div class="table-wrap"><table>
<thead><tr>
  <th style="width:150px"><?= e(t('导入时间')) ?></th>
  <th><?= e(t('文件名')) ?></th>
  <th style="width:150px"><?= e(t('银行账户')) ?></th>
  <th style="width:170px"><?= e(t('期间')) ?></th>
  <th class="num" style="width:70px"><?= e(t('行数')) ?></th>
  <th style="width:100px"><?= e(t('操作')) ?></th>
</tr></thead>
<tbody>
<?php if (!$imports): ?>
  <tr><td colspan="6"><?= empty_state(t('还没有导入月结单。点击右上角「导入月结单」上传文件。')) ?></td></tr>
<?php endif; ?>
<?php foreach ($imports as $x): ?>
  <tr>
    <td style="white-space:nowrap"><?= e((string) ($x['imported_at'] ?? '—')) ?></td>
    <td><?= e((string) ($x['file_name'] ?? '—')) ?></td>
    <td><?= e((string) ($x['account_name'] ?? '—')) ?></td>
    <td style="white-space:nowrap"><?= e(trim(($x['period_start'] ?? '') . ' ~ ' . ($x['period_end'] ?? ''), ' ~') ?: '—') ?></td>
    <td class="num"><?= (int) ($x['line_count'] ?? 0) ?></td>
    <td>
      <a class="btn sm" href="?p=bank-transactions&account=<?= (int) ($x['bank_account_id'] ?? 0) ?>"><?= e(t('查看')) ?></a>
      <?php if (!empty($x['has_file'])): ?>
      <a class="btn sm" href="download.php?statement=<?= (int) $x['batch_id'] ?>"><?= e(t('下载')) ?></a>
      <?php endif; ?>
    </td>
  </tr>
<?php endforeach; ?>
</tbody></table></div>
<?php echo card('已导入的月结单', ob_get_clean(), '', false); ?>
<?php else: ?>
<?php if ($role === 'auditor'): ?>
<?= empty_state('审计角色不可导入') ?>
<?php else: ?>
<div class="toolbar" style="padding:0 0 10px"><a class="btn sm" href="?p=bank-import">← <?= e(t('返回列表')) ?></a></div>
<?php ob_start(); ?>
<form method="post" enctype="multipart/form-data" id="uploadForm">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="parse_file">
  <div class="field">
    <label class="f"><?= e(t('银行账户')) ?></label>
    <select name="bankAccountId" required>
      <?php foreach ($accounts as $a): ?>
        <option value="<?= (int) $a['account_id'] ?>"><?= e((string) $a['currency']) ?> · <?= e((string) $a['name']) ?></option>
      <?php endforeach; ?>
    </select>
    <?php if (!$accounts): ?><div class="hint"><?= e(t('还没有银行账户，请先在「银行 → 银行账户」新建。')) ?></div><?php endif; ?>
  </div>
  <div class="field">
    <label class="f">上传月结单</label>
    <input type="file" name="statement" required
           accept=".csv,.xlsx,.xls,.pdf,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf">
    <div class="hint">
      <?= e(t('支持电子表格（CSV / XLSX / XLS）与 PDF（含扫描件，自动 OCR）')) ?>
      <?= e(t('上限 20MB。上传后先出预览，确认无误再导入。')) ?>
    </div>
  </div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <button class="btn primary">上传并解析</button>
    <span class="hint">解析只读取文件，不写库；导入仍要过算术校验</span>
  </div>
</form>
<?php echo card('① 从文件导入', ob_get_clean(), '', false); ?>

<?php if ($parsed): ?>
<?php
$srcLabel = ['csv' => 'CSV', 'xlsx' => 'Excel (XLSX)', 'xls' => 'Excel (XLS)',
             'pdf' => 'PDF（文字层）', 'pdf-ocr' => 'PDF（扫描件 OCR）'];
$m = $parsed['meta'] ?? [];
$open = $m['openingBalance'] ?? 0;
$close = $m['closingBalance'] ?? 0;
$deb = $m['totalDebits'] ?? $parsed['sumDebits'];
$cre = $m['totalCredits'] ?? $parsed['sumCredits'];
$expect = $open + $cre - $deb;
$okMath = abs($expect - $close) < 0.005;
$dates = array_values(array_filter(array_map(fn($r) => (string) ($r['date'] ?? ''), $parsed['rows'])));
$pStart = $dates ? min($dates) : '';
$pEnd = $dates ? max($dates) : '';
$fmt = fn($v) => money($v, 'HKD');
$reason = strtr(t($okMath
    ? '期初 {open} + 存入 {in} − 支出 {out} = {expect}，与期末 {close} 一致'
    : '期初 {open} + 存入 {in} − 支出 {out} = {expect}，但期末为 {close}，差额 {diff}'), [
    '{open}' => $fmt($open), '{in}' => $fmt($cre), '{out}' => $fmt($deb),
    '{expect}' => $fmt($expect), '{close}' => $fmt($close), '{diff}' => $fmt($expect - $close),
]);
ob_start(); ?>
<div class="metrics">
  <div class="metric"><div class="lbl">来源</div><div class="val" style="font-size:var(--f-lg)"><?= e($srcLabel[$parsed['source']] ?? $parsed['source']) ?></div></div>
  <div class="metric"><div class="lbl">交易行</div><div class="val"><?= num($parsed['rowCount']) ?></div></div>
  <div class="metric"><div class="lbl">支出合计</div><div class="val" style="font-size:var(--f-lg)"><?= money($parsed['sumDebits'], 'HKD') ?></div></div>
  <div class="metric"><div class="lbl">存入合计</div><div class="val" style="font-size:var(--f-lg)"><?= money($parsed['sumCredits'], 'HKD') ?></div></div>
</div>
<div class="banner <?= $okMath ? 'PASS' : 'REVIEW' ?>">
  <span class="banner-icon"><?= $okMath ? '✓' : '!' ?></span>
  <div class="banner-body">
    <div class="banner-title"><?= e($okMath ? t('算术校验通过') : t('算术校验不一致，请核对')) ?></div>
    <div class="banner-reason"><?= e($reason) ?></div>
  </div>
</div>
<?php if (!empty($parsed['warnings'])): ?>
  <div class="errbox"><b>解析提示</b><div><?= e(implode('；', (array) $parsed['warnings'])) ?></div></div>
<?php endif; ?>
<div class="table-wrap" style="max-height:420px;overflow:auto"><table>
<thead><tr><th>日期</th><th>摘要</th><th class="num">支出</th><th class="num">存入</th><th class="num">余额</th></tr></thead>
<tbody>
<?php foreach ($parsed['rows'] as $r): ?>
  <tr><td style="white-space:nowrap"><?= e((string) $r['date']) ?></td>
  <td><?= e((string) $r['description']) ?></td>
  <td class="num"><?= $r['debit'] > 0 ? money($r['debit']) : '—' ?></td>
  <td class="num"><?= $r['credit'] > 0 ? money($r['credit']) : '—' ?></td>
  <td class="num"><?= $r['balance'] !== null ? money($r['balance']) : '—' ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php if (!empty($parsed['truncated'])): ?>
  <div class="hint" style="padding:8px 14px">仅预览前 500 行，导入时按全部 <?= num($parsed['rowCount']) ?> 行处理</div>
<?php endif; ?>
<div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
  <form method="post" style="display:inline">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="import_statement">
    <input type="hidden" name="bankAccountId" value="<?= (int) ($parsed['bankAccountId'] ?? 0) ?>">
    <input type="hidden" name="fileName" value="<?= e($parsed['uploadedName'] ?? 'statement.csv') ?>">
    <input type="hidden" name="parsedRows" value="<?= e(base64_encode((string) json_encode($parsed['rows'], JSON_UNESCAPED_UNICODE))) ?>">
    <input type="hidden" name="periodStart" value="<?= e($pStart) ?>">
    <input type="hidden" name="periodEnd" value="<?= e($pEnd) ?>">
    <input type="hidden" name="openingBalance" value="<?= e((string) $open) ?>">
    <input type="hidden" name="closingBalance" value="<?= e((string) $close) ?>">
    <input type="hidden" name="totalDebits" value="<?= e((string) $deb) ?>">
    <input type="hidden" name="totalCredits" value="<?= e((string) $cre) ?>">
    <button class="btn primary" onclick="return confirm('<?= e(t('确认将解析结果导入系统？')) ?>')">导入并校验</button>
  </form>
  <span class="hint">确认预览无误后导入；同一文件不会重复入账</span>
</div>
<?php echo card('② 解析预览', ob_get_clean(), '', false); ?>
<?php endif; ?>
<?php endif; ?>
<?php endif; ?>
<style>
.bank-upload{margin-top:14px}
</style>

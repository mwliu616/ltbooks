<?php
/*
 * LtBooks — pages/bank-import.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$msg = null; $errMsg = null; $detail = null;

// 多文件上传时总大小可能超过 post_max_size，此时 PHP 会清空 $_POST/$_FILES，需给出明确提示。
if ($_SERVER['REQUEST_METHOD'] === 'POST' && empty($_POST) && empty($_FILES)
    && (int) ($_SERVER['CONTENT_LENGTH'] ?? 0) > 0) {
    $errMsg = '上传内容超过服务器限制（post_max_size=' . ini_get('post_max_size') . '），请减少文件数量或分批上传';
}

$accR = api_get('/bank-accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];

// ---- 上传文件并解析（CSV / XLSX / XLS / PDF），支持一次多份 ----
$parsedFiles = [];
$uploadErrors = [];
if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'parse_file') {
    $acctId = (int) ($_POST['bankAccountId'] ?? 0);
    $up = $_FILES['statement'] ?? null;

    // 单文件时 $_FILES 是标量；多文件（name="statement[]"）时每个字段都是数组。
    $files = [];
    if (is_array($up) && isset($up['name']) && is_array($up['name'])) {
        foreach ($up['name'] as $i => $name) {
            $files[] = [
                'name' => (string) $name,
                'tmp' => (string) ($up['tmp_name'][$i] ?? ''),
                'error' => (int) ($up['error'][$i] ?? UPLOAD_ERR_NO_FILE),
            ];
        }
    } elseif (is_array($up) && isset($up['name'])) {
        $files[] = [
            'name' => (string) $up['name'],
            'tmp' => (string) ($up['tmp_name'] ?? ''),
            'error' => (int) ($up['error'] ?? UPLOAD_ERR_NO_FILE),
        ];
    }
    $files = array_values(array_filter($files, static fn($f) => $f['name'] !== '' && $f['error'] !== UPLOAD_ERR_NO_FILE));

    if (!$files) {
        $errMsg = '请选择要上传的对账单文件';
    } elseif (count($files) > 10) {
        $errMsg = '一次最多上传 10 份月结单';
    } else {
        foreach ($files as $f) {
            if ($f['error'] !== UPLOAD_ERR_OK) {
                $uploadErrors[] = $f['name'] . '：上传失败（错误码 ' . $f['error'] . '）';
                continue;
            }
            $r = api_upload('/bank/parse-statement', 'file', $f['tmp'], $f['name']);
            if ($r['ok']) {
                $p = $r['data'];
                $p['uploadedName'] = $f['name'];
                $p['bankAccountId'] = $acctId;
                $parsedFiles[] = $p;
            } else {
                $uploadErrors[] = $f['name'] . '：' . $r['error'];
            }
        }
        if (!$parsedFiles) {
            $errMsg = implode('；', $uploadErrors) ?: '文件解析失败';
        }
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'import_statement') {
    // 一次可提交多份解析结果：base64 JSON，避免大段文本被 HTML 转义。
    $packed = (string) ($_POST['batch'] ?? '');
    $items = $packed !== '' ? json_decode((string) base64_decode($packed, true), true) : null;

    if (!is_array($items) || !$items) {
        $errMsg = '解析结果已损坏，请重新上传文件';
    } else {
        $done = [];
        $failed = [];
        foreach ($items as $it) {
            $fileName = trim((string) ($it['fileName'] ?? '')) ?: 'statement.csv';
            $rows = $it['rows'] ?? null;

            $lines = [];
            $rowErr = null;
            if (is_array($rows)) {
                foreach ($rows as $row) {
                    if (!isset($row['amount']) || !is_numeric($row['amount'])) {
                        $rowErr = '有明细行的金额不是数字';
                        break;
                    }
                    $lines[] = [
                        'date' => (string) ($row['date'] ?? ''),
                        'amount' => (float) $row['amount'],
                        'ref' => (string) ($row['ref'] ?? ''),
                        'counterparty' => (string) ($row['description'] ?? ''),
                    ];
                }
            }
            if ($rowErr !== null) {
                $failed[] = $fileName . '：' . $rowErr;
                continue;
            }
            if (!$lines) {
                $failed[] = $fileName . '：没有解析到任何明细行';
                continue;
            }

            $hdr = is_array($it['header'] ?? null) ? $it['header'] : [];
            $r = api_post('/bank/import', [
                'bankAccountId' => (int) ($it['bankAccountId'] ?? 0),
                'fileName' => $fileName,
                'fileFormat' => (string) ($it['fileFormat'] ?? 'csv'),
                'sha256' => (string) ($it['sha256'] ?? ''),
                'header' => [
                    'periodStart' => ($hdr['periodStart'] ?? '') ?: null,
                    'periodEnd' => ($hdr['periodEnd'] ?? '') ?: null,
                    'openingBalance' => (float) ($hdr['openingBalance'] ?? 0),
                    'closingBalance' => (float) ($hdr['closingBalance'] ?? 0),
                    'totalDebits' => (float) ($hdr['totalDebits'] ?? 0),
                    'totalCredits' => (float) ($hdr['totalCredits'] ?? 0),
                ],
                'lines' => $lines,
                'actor' => $displayName ?? 'system',
            ]);
            if ($r['ok']) {
                $done[] = $fileName . '：' . (string) ($r['data']['note'] ?? '导入完成');
            } elseif (!empty($r['data']['duplicate'])) {
                $done[] = $fileName . '：' . (string) ($r['data']['note'] ?? '该对账单已导入过');
            } else {
                $failed[] = $fileName . '：' . (string) $r['error'];
                if (!empty($r['data']['detail'])) {
                    $detail = $r['data']['detail'];
                }
            }
        }
        if ($done) { $msg = implode('；', $done); }
        if ($failed) { $errMsg = implode('；', $failed); }
    }
}

// 每份文件的期间、合计与算术校验，预览和批量导入共用。
$bankFileStats = static function (array $p): array {
    $m = $p['meta'] ?? [];
    $open = (float) ($m['openingBalance'] ?? 0);
    $close = (float) ($m['closingBalance'] ?? 0);
    $deb = (float) ($m['totalDebits'] ?? ($p['sumDebits'] ?? 0));
    $cre = (float) ($m['totalCredits'] ?? ($p['sumCredits'] ?? 0));
    $rows = is_array($p['rows'] ?? null) ? $p['rows'] : [];
    $dates = array_values(array_filter(array_map(static fn($r) => (string) ($r['date'] ?? ''), $rows)));
    return [
        'open' => $open, 'close' => $close, 'deb' => $deb, 'cre' => $cre,
        'expect' => $open + $cre - $deb,
        'okMath' => abs($open + $cre - $deb - $close) < 0.005,
        'pStart' => $dates ? min($dates) : '',
        'pEnd' => $dates ? max($dates) : '',
    ];
};

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
    <input type="file" name="statement[]" required multiple
           accept=".csv,.xlsx,.xls,.pdf,text/csv,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf">
    <div class="hint">
      <?= e(t('支持电子表格（CSV / XLSX / XLS）与 PDF（含扫描件，自动 OCR）')) ?>
      <?= e(t('上限 20MB。上传后先出预览，确认无误再导入。')) ?>
      <?= e(t('可一次选择多个文件（最多 10 份）。')) ?>
    </div>
  </div>
  <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
    <button class="btn primary">上传并解析</button>
    <span class="hint">解析只读取文件，不写库；导入仍要过算术校验</span>
  </div>
</form>
<?php echo card('① 从文件导入', ob_get_clean(), '', false); ?>

<?php if ($uploadErrors && $parsedFiles): ?>
<div class="errbox"><b><?= e(t('部分文件未能解析：')) ?></b><div><?= e(implode('；', $uploadErrors)) ?></div></div>
<?php endif; ?>

<?php if ($parsedFiles): ?>
<?php
$srcLabel = ['csv' => 'CSV', 'xlsx' => 'Excel (XLSX)', 'xls' => 'Excel (XLS)',
             'pdf' => 'PDF（文字层）', 'pdf-ocr' => 'PDF（扫描件 OCR）'];
$batch = [];
foreach ($parsedFiles as $p) {
    $st = $bankFileStats($p);
    $batch[] = [
        'fileName' => (string) ($p['uploadedName'] ?? 'statement.csv'),
        'sha256' => (string) ($p['sha256'] ?? ''),
        'fileFormat' => (string) ($p['fileFormat'] ?? 'csv'),
        'bankAccountId' => (int) ($p['bankAccountId'] ?? 0),
        'header' => [
            'periodStart' => $st['pStart'], 'periodEnd' => $st['pEnd'],
            'openingBalance' => $st['open'], 'closingBalance' => $st['close'],
            'totalDebits' => $st['deb'], 'totalCredits' => $st['cre'],
        ],
        'rows' => $p['rows'] ?? [],
    ];
}
$batchJson = base64_encode((string) json_encode($batch, JSON_UNESCAPED_UNICODE));
?>
<?php foreach ($parsedFiles as $p): ?>
<?php
$st = $bankFileStats($p);
$okMath = $st['okMath'];
$rowCount = (int) ($p['rowCount'] ?? count($p['rows'] ?? []));
$fmt = fn($v) => money($v, 'HKD');
$reason = strtr(t($okMath
    ? '期初 {open} + 存入 {in} − 支出 {out} = {expect}，与期末 {close} 一致'
    : '期初 {open} + 存入 {in} − 支出 {out} = {expect}，但期末为 {close}，差额 {diff}'), [
    '{open}' => $fmt($st['open']), '{in}' => $fmt($st['cre']), '{out}' => $fmt($st['deb']),
    '{expect}' => $fmt($st['expect']), '{close}' => $fmt($st['close']),
    '{diff}' => $fmt($st['expect'] - $st['close']),
]);
ob_start(); ?>
<div class="metrics">
  <div class="metric"><div class="lbl">来源</div><div class="val" style="font-size:var(--f-lg)"><?= e($srcLabel[$p['source']] ?? (string) $p['source']) ?></div></div>
  <div class="metric"><div class="lbl">交易行</div><div class="val"><?= num($rowCount) ?></div></div>
  <div class="metric"><div class="lbl">支出合计</div><div class="val" style="font-size:var(--f-lg)"><?= money($p['sumDebits'] ?? 0, 'HKD') ?></div></div>
  <div class="metric"><div class="lbl">存入合计</div><div class="val" style="font-size:var(--f-lg)"><?= money($p['sumCredits'] ?? 0, 'HKD') ?></div></div>
</div>
<div class="banner <?= $okMath ? 'PASS' : 'REVIEW' ?>">
  <span class="banner-icon"><?= $okMath ? '✓' : '!' ?></span>
  <div class="banner-body">
    <div class="banner-title"><?= e($okMath ? t('算术校验通过') : t('算术校验不一致，请核对')) ?></div>
    <div class="banner-reason"><?= e($reason) ?></div>
  </div>
</div>
<?php if (!empty($p['warnings'])): ?>
  <div class="errbox"><b>解析提示</b><div><?= e(implode('；', (array) $p['warnings'])) ?></div></div>
<?php endif; ?>
<div class="table-wrap" style="max-height:420px;overflow:auto"><table>
<thead><tr><th>日期</th><th>摘要</th><th class="num">支出</th><th class="num">存入</th><th class="num">余额</th></tr></thead>
<tbody>
<?php foreach (array_slice($p['rows'] ?? [], 0, 500) as $r): ?>
  <tr><td style="white-space:nowrap"><?= e((string) $r['date']) ?></td>
  <td><?= e((string) $r['description']) ?></td>
  <td class="num"><?= $r['debit'] > 0 ? money($r['debit']) : '—' ?></td>
  <td class="num"><?= $r['credit'] > 0 ? money($r['credit']) : '—' ?></td>
  <td class="num"><?= $r['balance'] !== null ? money($r['balance']) : '—' ?></td></tr>
<?php endforeach; ?>
</tbody></table></div>
<?php if ($rowCount > 500): ?>
  <div class="hint" style="padding:8px 14px">仅预览前 500 行，导入时按全部 <?= num($rowCount) ?> 行处理</div>
<?php endif; ?>
<?php echo card('② 解析预览 · ' . (string) ($p['uploadedName'] ?? ''), ob_get_clean(), '', false); ?>
<?php endforeach; ?>

<div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
  <form method="post" style="display:inline">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="import_statement">
    <input type="hidden" name="batch" value="<?= e($batchJson) ?>">
    <button class="btn primary" onclick="return confirm('<?= e('确认将选中的 ' . count($parsedFiles) . ' 份解析结果导入系统？') ?>')">
      <?= e(t('全部导入并校验')) ?>（<?= count($parsedFiles) ?> 份）
    </button>
  </form>
  <span class="hint">确认预览无误后导入；同一文件不会重复入账</span>
</div>
<?php endif; ?>
<?php endif; ?>
<?php endif; ?>
<style>
.bank-upload{margin-top:14px}
</style>

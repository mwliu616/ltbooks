<?php
/*
 * LtBooks — pages/order-view.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/**
 * 订单详情：明细、合同附件、履行登记、转发票。
 *
 * 顺序就是业务顺序：订单（+ 合同扫描件）→ 履行（采购收货 / 销售交付）→ 转发票。
 * 前三步都不产生分录；只有发票过账才进账。
 */
$role = isset($role) ? $role : 'accountant';
$id = (int) ($_GET['id'] ?? 0);
if (!$id) { echo errbox(t('没有指定订单')); return; }
$actor = (string) ($user['username'] ?? 'system');
$errMsg = null;
$okMsg = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok()) {
    $act = (string) ($_POST['action'] ?? '');
    if ($act === 'order_fulfil') {
        $lines = [];
        foreach ((array) ($_POST['qty'] ?? []) as $lineId => $q) {
            $q = trim((string) $q);
            if ($q !== '' && (float) $q > 0) { $lines[] = ['lineId' => (int) $lineId, 'quantity' => $q]; }
        }
        $r = api_post('/orders/' . $id . '/fulfil', [
            'docDate' => (string) ($_POST['docDate'] ?? date('Y-m-d')),
            'note' => trim((string) ($_POST['note'] ?? '')),
            'lines' => $lines, 'actor' => $actor,
        ]);
        if ($r['ok']) {
            header('Location: ?p=order-view&id=' . $id . '&msg=' . urlencode(t('已登记') . '：' . ($r['data']['docNo'] ?? '')));
            exit;
        }
        $errMsg = (string) $r['error'];
    } elseif ($act === 'order_convert') {
        $r = api_post('/orders/' . $id . '/convert', [
            'onlyDone' => !empty($_POST['onlyDone']),
            'date' => (string) ($_POST['date'] ?? date('Y-m-d')),
            'accountCode' => trim((string) ($_POST['accountCode'] ?? '')) ?: null,
            'actor' => $actor,
        ]);
        if ($r['ok']) {
            header('Location: ' . ($r['data']['href'] ?? '?p=orders')
                 . '&msg=' . urlencode(t('已转成发票草稿') . '：' . ($r['data']['docNo'] ?? '')));
            exit;
        }
        $errMsg = (string) $r['error'];
    } elseif ($act === 'order_status') {
        $r = api_post('/orders/' . $id . '/status', [
            'status' => (string) ($_POST['status'] ?? ''), 'actor' => $actor,
        ]);
        if ($r['ok']) {
            header('Location: ?p=order-view&id=' . $id . '&msg=' . urlencode(t('状态已更新')));
            exit;
        }
        $errMsg = (string) $r['error'];
    } elseif ($act === 'order_file') {
        // 合同扫描件：先落盘，再登记到附件表（与发票/账单同一套 SHA-256 与留存规则）
        if (empty($_FILES['file']['tmp_name']) || ($_FILES['file']['error'] ?? 1) !== UPLOAD_ERR_OK) {
            $errMsg = t('上传失败：未选择文件');
        } elseif (($_FILES['file']['size'] ?? 0) > 20 * 1024 * 1024) {
            $errMsg = t('文件超过 20MB 上限');
        } else {
            $orig = basename((string) $_FILES['file']['name']);
            $ext = strtolower(pathinfo($orig, PATHINFO_EXTENSION));
            $safe = preg_replace('/[^A-Za-z0-9._-]/', '_', $orig);
            $dest = UPLOAD_DIR . '/' . date('Ymd') . '-' . bin2hex(random_bytes(6)) . '-' . $safe;
            if (!move_uploaded_file($_FILES['file']['tmp_name'], $dest)) {
                $errMsg = t('文件落盘失败');
            } else {
                @chmod($dest, 0640);
                $reg = api_post('/order-files', [
                    'orderId' => $id, 'fileName' => $orig,
                    'fileType' => $ext !== '' ? $ext : 'other',
                    'fileSize' => filesize($dest),
                    'sha256' => hash_file('sha256', $dest),
                    'storagePath' => $dest, 'actor' => $actor,
                ]);
                if ($reg['ok']) {
                    header('Location: ?p=order-view&id=' . $id . '&msg=' . urlencode(t('合同附件已上传') . '：' . $orig));
                    exit;
                }
                @unlink($dest);
                $errMsg = (string) $reg['error'];
            }
        }
    }
}

$r = api_get('/orders/' . $id);
if (!$r['ok']) { echo errbox((string) $r['error']); return; }
$d = $r['data'];
$isSales = (string) $d['direction'] === 'sales';
$open = !in_array($d['status'], ['closed', 'cancelled'], true);
$allDone = (string) $d['status'] === 'fulfilled';
$orderFunctional = (string) ($d['functional_currency'] ?? '');
$orderIsForeign = $orderFunctional !== ''
    && strtoupper((string) $d['currency']) !== strtoupper($orderFunctional);
$orderGrossFunctional = null;
if (isset($d['amount_functional'])) {
    $candidate = (float) $d['amount_functional'];
    if ((float) $d['gross_original'] == 0.0 || $candidate != 0.0) { $orderGrossFunctional = $candidate; }
}
$orderFx = isset($d['exchange_rate']) && (float) $d['exchange_rate'] > 0 ? (float) $d['exchange_rate'] : null;
if ($orderGrossFunctional === null) { $orderFx = null; }
$orderRateText = $orderFx !== null ? e((string) $orderFx) : '—';
if ($errMsg) { echo errbox($errMsg); }
?>
<div class="page-head">
  <div>
    <h1 class="page-title mono"><?= e((string) $d['order_no']) ?></h1>
    <div class="page-sub">
      <?= e((string) $d['party_name']) ?> · <?= e((string) $d['order_date']) ?>
      <?php if (!empty($d['expected_date'])): ?>
        · <?= e($isSales ? t('预计交付') : t('预计到货')) ?> <?= e((string) $d['expected_date']) ?>
      <?php endif; ?>
      <?php if (!empty($d['reference'])): ?>
        · <?= e(t('参考号')) ?> <?= e((string) $d['reference']) ?>
      <?php endif; ?>
      <?php if (!empty($d['contract_note'])): ?>
        · <?= e((string) $d['contract_note']) ?>
      <?php endif; ?>
      <?php if (!empty($d['notes'])): ?>
        · <?= e((string) $d['notes']) ?>
      <?php endif; ?>
    </div>
  </div>
  <div class="page-actions">
    <?php if ($role !== 'auditor' && !empty($d['editable'])): ?>
      <a class="btn primary" href="?p=<?= $isSales ? 'sales-orders' : 'purchase-orders' ?>&amp;edit=<?= $id ?>#new"><?= e(t('编辑订单')) ?></a>
    <?php endif; ?>
    <?php if ($role !== 'auditor' && (string) $d['status'] === 'draft'): ?>
      <?= draft_delete_form('order', $id, $isSales ? 'sales-orders' : 'purchase-orders') ?>
    <?php endif; ?>
    <span class="tag tag-<?= e($allDone ? 'ok' : (in_array($d['status'], ['closed','cancelled'], true) ? 'danger' : 'info')) ?>">
      <?= e(t((string) $d['statusLabel'])) ?></span>
    <a class="btn sm" target="_blank"
       href="/pdf/reports.php?u=<?= e(rawurlencode('/orders/' . $id . '/pdf?lang=' . report_lang())) ?>"><?= e(t('打印 / PDF')) ?></a>
    <a class="btn sm" href="?p=email&amp;docType=<?= $isSales ? 'sales_order' : 'purchase_order' ?>&amp;docId=<?= $id ?>"><?= e(t('发送邮件')) ?></a>
    <?= pdf_lang_switcher($_GET, false) ?>
    <a class="btn" href="?p=<?= $isSales ? 'sales-orders' : 'purchase-orders' ?>"><?= e(t('返回列表')) ?></a>
  </div>
</div>

<?= help_html('order-view') ?>

<div class="banner REVIEW" style="margin-bottom:var(--s-4)">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title"><?= e(t('订单不进总账')) ?></div>
    <div class="banner-reason"><?= e(t('订单与履行登记都不产生分录；转成发票并过账后才形成应收 / 应付')) ?></div>
  </div>
</div>

<section class="card">
  <div class="card-head">
    <h2 class="card-title"><?= e(t('明细')) ?></h2>
    <div class="hint"><?= e($orderIsForeign ? t('原币合计') : t('合计')) ?>：<b class="mono"><?= money($d['gross_original'], (string) $d['currency']) ?></b></div>
  </div>
  <?php if ($orderIsForeign): ?>
    <div class="card-body"><?= kv_grid([
      ['折合功能货币', $orderGrossFunctional !== null ? money($orderGrossFunctional, $orderFunctional) : '— ' . e($orderFunctional)],
      ['汇率', $orderRateText],
    ]) ?></div>
  <?php endif; ?>
  <div class="table-wrap"><table>
    <thead><tr>
      <th style="width:40px">#</th><th><?= e(t('摘要')) ?></th>
      <th class="num"><?= e(t('数量')) ?></th>
      <th class="num"><?= e($isSales ? t('已交付') : t('已收')) ?></th>
      <th class="num"><?= e($isSales ? t('未交付') : t('未收')) ?></th>
      <th class="num"><?= e(t('单价')) ?></th><th class="num"><?= e(t('金额')) ?></th>
    </tr></thead>
    <tbody>
    <?php foreach ($d['lines'] as $ln): ?>
      <tr>
        <td class="hint"><?= (int) $ln['line_no'] ?></td>
        <td><?= e((string) $ln['description']) ?>
          <?php if (!empty($ln['unit'])): ?><span class="hint"> · <?= e((string) $ln['unit']) ?></span><?php endif; ?></td>
        <td class="num"><?= rtrim(rtrim(number_format((float) $ln['quantity'], 4, '.', ''), '0'), '.') ?></td>
        <td class="num"><?= rtrim(rtrim(number_format((float) $ln['done_qty'], 4, '.', ''), '0'), '.') ?></td>
        <td class="num"><?= rtrim(rtrim(number_format((float) $ln['remaining_qty'], 4, '.', ''), '0'), '.') ?></td>
        <td class="num"><?= money($ln['unit_price'], (string) $d['currency']) ?></td>
        <td class="num"><?= money($ln['amount'], (string) $d['currency']) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</section>

<section class="card">
  <div class="card-head">
    <h2 class="card-title"><?= e(t('合同扫描件')) ?></h2>
    <span class="hint"><?= e(t('已签署的合同扫描件作为订单附件上传；上限 20MB，保存 7 年')) ?></span>
  </div>
  <?php if (!empty($d['files'])): ?>
  <div class="table-wrap"><table>
    <thead><tr><th><?= e(t('文件')) ?></th><th class="num"><?= e(t('大小')) ?></th>
      <th><?= e(t('上传人')) ?></th><th><?= e(t('SHA-256')) ?></th><th><?= e(t('上传时间')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($d['files'] as $f): ?>
      <tr>
        <td><a class="mono" href="?p=file&id=<?= (int) $f['file_id'] ?>"><?= e((string) $f['file_name']) ?></a></td>
        <td class="num hint"><?= number_format(((int) $f['file_size']) / 1024, 0) ?> KB</td>
        <td class="hint"><?= e((string) $f['uploaded_by']) ?></td>
        <td class="hint mono" style="max-width:180px;overflow:hidden;text-overflow:ellipsis">
          <?= e(substr((string) $f['sha256_hash'], 0, 16)) ?>…</td>
        <td class="hint nowrap"><?= e((string) ($f['uploaded_at'] ?: '—')) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
  <?php else: ?>
    <div class="card-body"><?= empty_state('还没有上传合同扫描件') ?></div>
  <?php endif; ?>
  <?php if ($role !== 'auditor' && $open): ?>
  <form method="post" enctype="multipart/form-data" class="card-body"
        style="border-top:1px solid var(--c-border);padding-top:var(--s-4)">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="order_file">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff" required>
      <button class="btn primary"><?= e(t('上传合同')) ?></button>
      <span class="hint"><?= e(t('PDF 或图片；上传即计算 SHA-256 并写入审计日志')) ?></span>
    </div>
  </form>
  <?php endif; ?>
</section>

<?php if ($role !== 'auditor' && $open): ?>
<section class="card">
  <div class="card-head">
    <h2 class="card-title"><?= e($isSales ? t('登记交付') : t('登记收货 / 验收')) ?></h2>
    <span class="hint"><?= e(t('可以分批；只改数量，不生成分录')) ?></span>
  </div>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="order_fulfil">
    <div class="grid">
      <div class="field"><label class="f" for="fDate"><?= e($isSales ? t('交付日期') : t('收货日期')) ?></label>
        <input type="date" id="fDate" name="docDate" value="<?= e(date('Y-m-d')) ?>"></div>
      <div class="field span-full"><label class="f" for="fNote"><?= e(t('备注')) ?></label>
        <input type="text" id="fNote" name="note" placeholder="<?= e(t('例：部分到货 / 验收合格')) ?>"></div>
    </div>
    <div class="table-wrap" style="margin-top:12px"><table>
      <thead><tr><th><?= e(t('摘要')) ?></th>
        <th class="num"><?= e($isSales ? t('未交付') : t('未收')) ?></th>
        <th style="width:140px"><?= e($isSales ? t('本次交付') : t('本次收货')) ?></th></tr></thead>
      <tbody>
      <?php foreach ($d['lines'] as $ln): ?>
        <tr>
          <td><?= e((string) $ln['description']) ?></td>
          <td class="num"><?= rtrim(rtrim(number_format((float) $ln['remaining_qty'], 4, '.', ''), '0'), '.') ?></td>
          <td><input type="number" step="0.0001" min="0"
                     name="qty[<?= (int) $ln['line_id'] ?>]" placeholder="0"
                     <?= (float) $ln['remaining_qty'] <= 0 ? 'disabled' : '' ?>></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table></div>
    <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
      <button class="btn primary"><?= e($isSales ? t('登记交付') : t('登记收货')) ?></button>
    </div>
  </form>
</section>
<?php endif; ?>

<?php if ($open || $allDone): ?>
<section class="card">
  <div class="card-head">
    <h2 class="card-title"><?= e($isSales ? t('转成销售发票') : t('转成采购发票')) ?></h2>
    <span class="hint"><?= e(t('生成一张发票草稿并回指本单；发票过账后才进账')) ?></span>
  </div>
  <?php if (!empty($d['docs'])): ?>
    <div class="card-body" style="padding-bottom:0">
      <div class="hint" style="margin-bottom:6px"><?= e(t('已转出')) ?>：</div>
      <?php foreach ($d['docs'] as $doc): ?>
        <div style="margin-bottom:4px">
          <a class="mono" href="?p=<?= $isSales ? 'invoice-view' : 'bill-view' ?>&id=<?= (int) $doc['id'] ?>"><?= e((string) $doc['no']) ?></a>
          <span class="hint"><?= e((string) $doc['date']) ?> ·
            <?= money($doc['gross_original'], (string) $d['currency']) ?> · <?= e(t((string) $doc['status'])) ?></span>
        </div>
      <?php endforeach; ?>
    </div>
  <?php endif; ?>
  <?php if ($role !== 'auditor'): ?>
  <form method="post" class="card-body">
    <?= csrf_field() ?>
    <input type="hidden" name="action" value="order_convert">
    <div class="grid">
      <div class="field"><label class="f" for="cvDate"><?= e(t('发票日期')) ?></label>
        <input type="date" id="cvDate" name="date" value="<?= e(date('Y-m-d')) ?>"></div>
      <div class="field"><label class="f" for="cvAcc"><?= e($isSales ? t('收入科目') : t('费用科目')) ?></label>
        <input type="text" id="cvAcc" name="accountCode" value="<?= $isSales ? '4100' : '6200' ?>">
        <div class="hint"><?= e(t('发票草稿先记这个科目，进详情还能改')) ?></div></div>
      <div class="field"><label class="f"><?= e(t('数量范围')) ?></label>
        <select name="onlyDone">
          <option value="1" <?= $allDone ? 'selected' : '' ?>><?= e(t('只按已履行数量（部分开票）')) ?></option>
          <option value="0" <?= $allDone ? '' : 'selected' ?>><?= e(t('按订单全部数量')) ?></option>
        </select></div>
    </div>
    <div class="toolbar form-actions" style="margin-top:12px;margin-bottom:0">
      <button class="btn primary"><?= e($isSales ? t('转成销售发票草稿') : t('转成采购发票草稿')) ?></button>
    </div>
  </form>
  <?php endif; ?>
</section>
<?php endif; ?>

<?php if (!empty($d['fulfilments'])): ?>
<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e($isSales ? t('交付记录') : t('收货记录')) ?></h2></div>
  <div class="table-wrap"><table>
    <thead><tr><th><?= e(t('单号')) ?></th><th><?= e(t('日期')) ?></th>
      <th><?= e(t('备注')) ?></th><th><?= e(t('录入人')) ?></th></tr></thead>
    <tbody>
    <?php foreach ($d['fulfilments'] as $f): ?>
      <tr>
        <td class="mono"><?= e((string) $f['doc_no']) ?></td>
        <td class="nowrap"><?= e((string) $f['doc_date']) ?></td>
        <td class="hint"><?= e((string) ($f['note'] ?: '—')) ?></td>
        <td class="hint"><?= e((string) $f['created_by']) ?></td>
      </tr>
    <?php endforeach; ?>
    </tbody>
  </table></div>
</section>
<?php endif; ?>

<?php if ($role !== 'auditor' && $open): ?>
<section class="card">
  <div class="card-head"><h2 class="card-title"><?= e(t('关闭 / 取消')) ?></h2>
    <span class="hint"><?= e(t('不再需要这张订单时用；已转出的发票不受影响')) ?></span></div>
  <div class="card-body">
    <form method="post" style="display:inline">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="order_status">
      <input type="hidden" name="status" value="closed">
      <button class="btn"><?= e(t('标记已关闭')) ?></button>
    </form>
    <form method="post" style="display:inline;margin-left:8px">
      <?= csrf_field() ?>
      <input type="hidden" name="action" value="order_status">
      <input type="hidden" name="status" value="cancelled">
      <button class="btn danger"><?= e(t('取消订单')) ?></button>
    </form>
  </div>
</section>
<?php endif; ?>

<?php
/*
 * LtBooks — pages/journal-new.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';
$inlineErr = handle_inline_account_create(
    ['asset', 'liability', 'equity', 'revenue', 'cogs', 'expense'], 'journal-new', $user ?? []);
$newAcc = (string) ($_GET['newacc'] ?? '');
if ($role === 'auditor') { echo empty_state('审计角色不可录入'); return; }
$msg = null; $errMsg = $inlineErr;
$editId = (int) ($_POST['edit'] ?? $_GET['edit'] ?? 0);
$editing = null;
$editLines = [];
if ($editId > 0) {
    $editR = api_get('/journal/' . $editId);
    if (!$editR['ok']) { echo errbox((string) $editR['error']); return; }
    $editing = $editR['data']['entry'] ?? null;
    $editLines = $editR['data']['lines'] ?? [];
    if (!$editing || (string) ($editing['status'] ?? '') !== 'draft') {
        echo errbox('只有草稿状态的分录可以编辑；已过账分录请用冲销更正'); return;
    }
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && csrf_ok() && ($_POST['action'] ?? '') === 'create_journal') {
    $lines = [];
    foreach ((array) ($_POST['lines'] ?? []) as $ln) {
        $code = trim((string) ($ln['accountCode'] ?? ''));
        $d = (float) ($ln['debit'] ?? 0);
        $c = (float) ($ln['credit'] ?? 0);
        if ($code === '' && $d == 0 && $c == 0) { continue; }
        $lines[] = ['accountCode' => $code, 'debit' => $d, 'credit' => $c,
                    'description' => trim((string) ($ln['description'] ?? ''))];
    }
    $r = api_post($editing ? '/journal/' . $editId . '/update' : '/journal', [
        'entryDate' => (string) ($_POST['entryDate'] ?? ''),
        'description' => trim((string) ($_POST['description'] ?? '')),
        'lines' => $lines,
        'actor' => (string) ($user['username'] ?? 'system'),
    ]);
    if ($r['ok']) {
        $jid = (int) ($r['data']['entryId'] ?? 0);
        if ($jid > 0 && !empty($_FILES['attach']['name'][0])) {
            doc_files_save('journal', $jid, $_FILES['attach'], (string) ($user['username'] ?? 'system'));
        }
        if ($editing) {
            header('Location: ?p=journal&msg=' . urlencode(
                '草稿已保存：' . $r['data']['entryNo'] . '，未执行过账'));
            exit;
        }
        $msg = '分录已过账：' . $r['data']['entryNo'] . '，借贷各 ' . money($r['data']['totalDebit'], 'HKD');
    } else {
        $errMsg = (string) $r['error'];
    }
}
if ($msg) { echo '<div class="banner PASS"><span class="banner-icon">✓</span><div class="banner-body"><div class="banner-title">操作成功</div><div class="banner-reason">' . e($msg) . '</div></div></div>'; }
if ($errMsg) { echo errbox($errMsg); }

$accR = api_get('/accounts');
$accounts = $accR['ok'] ? ($accR['data']['accounts'] ?? []) : [];
$accountOptions = static function (string $selected = '') use ($accounts): string {
    $out = '';
    foreach ($accounts as $a) {
        $code = (string) $a['account_code'];
        $out .= '<option value="' . e($code) . '"' . ($selected === $code ? ' selected' : '') . '>'
              . e($code . ' · ' . acc_name($code, (string) $a['account_name'])) . '</option>';
    }
    return $out;
};
$formLines = [];
if (isset($lines) && is_array($lines)) {
    $formLines = $lines;
} elseif ($editing) {
    foreach ($editLines as $ln) {
        $formLines[] = ['accountCode' => (string) $ln['account_code'],
                        'description' => (string) ($ln['description'] ?? ''),
                        'debit' => (string) $ln['debit'], 'credit' => (string) $ln['credit']];
    }
}
$formDescription = (string) ($_POST['description'] ?? ($editing['description'] ?? ''));
$formEntryDate = (string) ($_POST['entryDate'] ?? ($editing['entry_date'] ?? date('Y-m-d')));
?>
<?php ob_start(); ?>
<form method="post" enctype="multipart/form-data" id="journalForm">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="create_journal">
  <?php if ($editing): ?><input type="hidden" name="edit" value="<?= $editId ?>"><?php endif; ?>

  <div class="zform">
    <div class="zcol">
      <div class="zsec-h">凭证摘要</div>
      <div class="field"><label class="f">摘要 *</label>
        <input type="text" name="description" placeholder="例如：计提 11 月租金" required
               value="<?= e($formDescription) ?>">
        <div class="hint">会出现在日记账与总账里，写清「为什么记这笔」</div>
      </div>
      <div class="field"><label class="f">备注</label>
        <textarea name="reference" rows="3" placeholder="参考单据、合同号（选填）"></textarea>
      </div>
    </div>
    <div class="zcol zcol-2">
      <div class="zsec-h">凭证信息</div>
      <div class="z2">
        <div class="field"><label class="f">凭证编号</label>
          <input type="text" name="entryNo" class="mono" style="font-size:12.5px"
                 value="<?= e($editing ? (string) $editing['entry_no'] : next_doc_no($formEntryDate, 'journal')) ?>"
                 placeholder="自动生成"<?= $editing ? ' readonly' : '' ?>>
        </div>
        <div class="field"><label class="f">分录日期 *</label>
          <input type="date" name="entryDate" value="<?= e($formEntryDate) ?>" required>
        </div>
        <div class="field"><label class="f">币种</label>
          <select name="currency"><?= currency_options((string) ($_POST['currency'] ?? ($editLines[0]['ccy'] ?? base_currency()))) ?></select>
        </div>
        <div class="field"><label class="f">状态</label>
          <input type="text" value="<?= $editing ? '草稿（保存不会过账）' : '保存即过账' ?>" readonly style="background:var(--c-surface-alt)">
        </div>
      </div>
    </div>
  </div>

  <div style="margin-top:18px">
    <div class="table-wrap"><table id="jnTable">
      <thead><tr>
        <th style="width:38px" class="num">#</th>
        <th style="width:34%">科目</th>
        <th>说明</th>
        <th class="num" style="width:140px">借方</th>
        <th class="num" style="width:140px">贷方</th>
        <th style="width:40px"></th>
      </tr></thead>
      <tbody id="jnBody">
      <?php // 新建默认一借一贷；编辑时完整回填历史草稿行。
            $__rows = max(2, count($formLines));
            for ($i = 0; $i < $__rows; $i++): $__ln = $formLines[$i] ?? []; ?>
        <tr>
          <td class="jn-seq mono hint"><?= $i + 1 ?></td>
          <td><select name="lines[<?= $i ?>][accountCode]" style="width:100%" data-allow-create="1">
            <option value="">— 选择科目 —</option><?= $accountOptions((string) ($__ln['accountCode'] ?? '')) ?></select></td>
          <td><input type="text" name="lines[<?= $i ?>][description]" style="width:100%" placeholder="这一行的说明"
               value="<?= e((string) ($__ln['description'] ?? '')) ?>"></td>
          <td><input type="number" step="0.01" min="0" name="lines[<?= $i ?>][debit]" class="jn-dr" style="width:100%"
               value="<?= e((string) ($__ln['debit'] ?? '')) ?>"></td>
          <td><input type="number" step="0.01" min="0" name="lines[<?= $i ?>][credit]" class="jn-cr" style="width:100%"
               value="<?= e((string) ($__ln['credit'] ?? '')) ?>"></td>
          <td><button type="button" class="btn sm jn-del" title="删除本行">×</button></td>
        </tr>
      <?php endfor; ?>
      </tbody>
    </table></div>
    <div class="toolbar" style="margin-top:10px">
      <button type="button" class="btn sm" id="jnAdd">＋ 添加一行</button>
      <span class="grow"></span>
      <span class="hint">借方合计 <b id="jnDr" class="mono">0.00</b> · 贷方合计 <b id="jnCr" class="mono">0.00</b> ·
        差额 <b id="jnDiff" class="mono">0.00</b></span>
    </div>
  </div>

  <?= attach_dropzone('attach', '把支撑材料拖到这里', '计提依据、合同、计算表 · 保存后挂到这张凭证') ?>

  <div class="pc-box" id="aiPrecheck"></div>

  <div class="card-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:18px">
    <a class="btn" href="?p=journal">取消</a>
    <button class="btn primary" <?= $editing ? 'data-shortcut-save' : 'data-shortcut-post' ?>><?= $editing ? '保存草稿' : '保存并过账' ?></button>
  </div>
  <div class="hint" style="margin-top:8px;text-align:right">
    借贷必须相等；同一行不能同时填借方与贷方；<?= $editing ? '保存草稿不会过账' : '期间锁定后会被数据库拒绝' ?>
  </div>
</form>
<script src="assets/precheck.js?v=<?= @filemtime(__DIR__ . '/../assets/precheck.js') ?>"></script>
<script>
(function () {
  var f = document.getElementById('journalForm');
  if (!f || !window.LeduPrecheck) return;
  function v(name) { var el = f.elements[name]; return el ? el.value : ''; }
  function gather() {
    var lines = [];
    f.querySelectorAll('#jnBody tr').forEach(function (tr) {
      var g = function (sel) { var e = tr.querySelector(sel); return e ? e.value : ''; };
      lines.push({accountCode: g('select[name*="[accountCode]"]'),
                  description: g('input[name*="[description]"]'),
                  debit: g('input[name*="[debit]"]'), credit: g('input[name*="[credit]"]')});
    });
    return {description: v('description'), entryDate: v('entryDate'), currency: v('currency'), lines: lines};
  }
  window.LeduPrecheck.attach({
    el: '#aiPrecheck', form: f, workflow: 'journal', agentLabel: '会计', auto: true, collect: gather,
    ready: function (p) {
      return p.lines.filter(function (l) {
        return (parseFloat(l.debit) > 0 || parseFloat(l.credit) > 0);
      }).length >= 2;
    }
  });
})();
</script>
<script>
(function () {
  var body = document.getElementById('jnBody'), add = document.getElementById('jnAdd');
  if (!body || !add) return;
  function n(el) { var v = parseFloat(el.value); return isFinite(v) ? v : 0; }
  function calc() {
    var dr = 0, cr = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      dr += n(tr.querySelector('.jn-dr')); cr += n(tr.querySelector('.jn-cr'));
    });
    document.getElementById('jnDr').textContent = dr.toFixed(2);
    document.getElementById('jnCr').textContent = cr.toFixed(2);
    var d = dr - cr;
    var el = document.getElementById('jnDiff');
    el.textContent = d.toFixed(2);
    el.style.color = Math.abs(d) < 0.005 ? 'var(--c-ok)' : 'var(--c-fail)';
  }
  function renum() {
    body.querySelectorAll('tr').forEach(function (tr, i) {
      tr.querySelector('.jn-seq').textContent = i + 1;
      tr.querySelectorAll('select,input').forEach(function (el) {
        if (el.name) { el.name = el.name.replace(/lines\[\d+\]/, 'lines[' + i + ']'); }
      });
    });
  }
  function bind(tr) {
    tr.querySelectorAll('.jn-dr,.jn-cr').forEach(function (i) { i.addEventListener('input', calc); });
    tr.querySelector('.jn-del').addEventListener('click', function () {
      if (body.querySelectorAll('tr').length > 1) { tr.remove(); renum(); calc(); }
    });
  }
  body.querySelectorAll('tr').forEach(bind);
  add.addEventListener('click', function () {
    var tr = body.querySelector('tr').cloneNode(true);
    tr.querySelectorAll('input').forEach(function (i) { i.value = ''; });
    tr.querySelectorAll('select').forEach(function (s) { s.selectedIndex = 0; });
    body.appendChild(tr); bind(tr); renum(); calc();
  });
  calc();
})();
</script>
<?php echo card($editing ? '编辑日记账草稿' : '手工日记账分录', ob_get_clean()); ?>

<?php echo inline_account_create_panel(['expense','cogs','asset','liability','equity','revenue'], $newAcc); ?>

<?php
/*
 * LtBooks — pages/revalue.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$role = isset($role) ? $role : 'accountant';  // 来自服务端会话
$period = (string) ($_POST['period'] ?? date('Y-m'));
?>
<?php ob_start(); ?>
<form method="post">
  <?= csrf_field() ?>
  <input type="hidden" name="action" value="revalue">
  <input type="hidden" name="actor" value="<?= e($role) ?>">
  <div class="toolbar" style="margin-bottom:0">
    <div class="field" style="width:180px">
      <label class="f">期间（YYYY-MM）</label>
      <input type="text" name="period" value="<?= e($period) ?>" pattern="\d{4}-\d{2}" required>
    </div>
    <button class="btn primary" <?= $role === 'auditor' ? 'disabled' : '' ?>>执行重估</button>
  </div>
  <div class="hint" style="margin-top:10px;line-height:1.7">
    覆盖外币应收、外币应付、外币银行账户；汇率缺失转待复核，不估算。
    同一期间幂等，不重复计提。
  </div>
</form>
<?php echo card('期末货币重估', ob_get_clean()); ?>

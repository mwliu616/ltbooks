<?php
/*
 * LtBooks — pages/license.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
$year = date('Y');
$body = <<<TXT
MIT License

Copyright (c) {$year} LEDU TECH CO., LIMITED

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
TXT;
?>
<div class="banner INFO">
  <span class="banner-icon">i</span>
  <div class="banner-body">
    <div class="banner-title">LtBooks Ver 1.0 · MIT License</div>
    <div class="banner-reason">
      本系统以 MIT 许可证开源发布：可自由使用、修改、分发、商用，
      但须保留版权声明与许可声明；软件按「现状」提供，不附任何担保。
    </div>
  </div>
</div>

<?php ob_start(); ?>
<div class="grid" style="margin-bottom:0">
  <div class="kv"><b>版权方</b><span>LEDU TECH CO., LIMITED</span></div>
  <div class="kv"><b>许可证</b><span>MIT</span></div>
  <div class="kv"><b>年份</b><span><?= $year ?></span></div>
</div>
<div class="hint" style="padding:10px 14px">
  MIT 是宽松型（permissive）许可证，允许闭源再分发，但不得移除本版权与许可声明。
</div>
<?php echo card('授权概要', ob_get_clean()); ?>

<?php ob_start(); ?>
<pre style="margin:0;padding:16px;background:var(--c-surface-alt);border-radius:var(--r-md);
            font-family:var(--mono);font-size:var(--f-2xs);line-height:1.75;white-space:pre-wrap;
            color:var(--c-text-2);overflow-x:auto"><?= e($body) ?></pre>
<?php echo card('许可证全文', ob_get_clean(), '', false); ?>

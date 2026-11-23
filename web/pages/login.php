<?php
/*
 * LtBooks — pages/login.php
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 */
/** 登录页：左品牌右表单的分屏布局，不套用主框架。 */
ob_start();
$err = $err ?? null;
$zhName = '樂度科技有限公司';
$nvR = api_get('/company/name-variants');
if ($nvR['ok'] && !empty($nvR['data']['zhHk'])) { $zhName = (string) $nvR['data']['zhHk']; }
?>
<!doctype html>
<html lang="<?= e(lang_html()) ?>">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= e(t('登录')) ?> — Lt-AI-Books</title>
<link rel="icon" type="image/png" href="assets/favicon.png?v=<?= @filemtime(__DIR__ . '/../assets/favicon.png') ?>">
<link rel="stylesheet" href="assets/app.css?v=<?= @filemtime(__DIR__ . '/../assets/app.css') ?>">
<style>
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }

/* 整页深色底，登录卡居中 */
body.auth-page {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  background: #0B1220; color: #fff; padding: 70px 20px 54px; position: relative; overflow: hidden;
}
body.auth-page::after {            /* 极淡同心圆，唯一装饰 */
  content: ''; position: absolute; right: -220px; bottom: -260px;
  width: 700px; height: 700px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,.045);
  box-shadow: 0 0 0 100px rgba(255,255,255,.013), 0 0 0 200px rgba(255,255,255,.008);
  pointer-events: none;
}

/* 左上角品牌角标 */
.auth-mark { position: absolute; top: 30px; left: 36px; z-index: 2;
             display: flex; align-items: center; gap: 12px; }
.auth-mark img { width: 38px; height: 38px; object-fit: contain; background: #fff;
                 padding: 4px; border-radius: 9px; }
.auth-mark .pn { font-size:var(--f-md); letter-spacing: .02em; }
.auth-mark .pv { font-size:var(--f-2xs); color: rgba(255,255,255,.45); letter-spacing: .2em;
                 text-transform: uppercase; margin-top: 2px; }

/* 居中登录卡 */
.auth-card { position: relative; z-index: 2; width: 100%; max-width: 396px;
             background: var(--c-surface); color: var(--c-text); border-radius: 14px;
             padding: 34px 34px 26px; box-shadow: 0 24px 70px rgba(0,0,0,.42); }
.auth-card h1 { font-size: var(--f-2xl); font-weight: 400; margin: 0 0 5px; letter-spacing: -.01em; }
.auth-card .sub { font-size: var(--f-xs); color: var(--c-text-3); margin-bottom: 26px; }

.auth-field { margin-bottom: 16px; }
.auth-field label { display: block; font-size:var(--f-2xs); color: var(--c-text-3);
                    letter-spacing: .04em; margin-bottom: 7px; }
.auth-field input {
  width: 100%; height: 44px; padding: 0 14px; font-size:var(--f-md); color: var(--c-text);
  background: var(--c-surface); border: 1px solid var(--c-border); border-radius: 8px;
  transition: border-color .15s, box-shadow .15s;
}
.auth-field input:focus { outline: none; border-color: var(--c-primary);
                          box-shadow: 0 0 0 3px rgba(30,64,175,.10); }
.auth-btn { width: 100%; height: 44px; margin-top: 6px; font-size:var(--f-md); border-radius: 8px; }

.auth-msg { display: flex; gap: 8px; align-items: flex-start; padding: 11px 13px;
            background: var(--c-danger-soft); border: 1px solid var(--c-danger-border); border-radius: 8px;
            color: var(--c-danger); font-size: var(--f-xs); line-height: 1.55; margin-bottom: 18px; }


/* 进入方式：两种模式，登录时选一次 */
.auth-mode { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 4px 0 18px; }
.auth-mode > .am-card { position: relative; cursor: pointer; }
.auth-mode input { position: absolute; inset: 0; width: 100%; height: 100%;
                   margin: 0; opacity: 0; cursor: pointer; }
.auth-mode .am-body {
  display: block; padding: 11px 12px; border: 1px solid var(--c-border);
  border-radius: 8px; background: var(--c-surface); transition: border-color .15s, background .15s;
}
.auth-mode .am-t { display: block; font-size:var(--f-xs); color: var(--c-text); }
.auth-mode .am-d { display: block; margin-top: 3px; font-size:var(--f-2xs); line-height: 1.5;
                   color: var(--c-text-3); }
.auth-mode input:checked ~ .am-body {
  border-color: var(--c-primary); background: var(--c-primary-soft);
}
.auth-mode input:focus-visible ~ .am-body { outline: 2px solid var(--c-primary); outline-offset: 2px; }
.auth-mode-lbl { font-size:var(--f-2xs); color: var(--c-text-3); letter-spacing: .04em; margin-bottom: 7px; }

@media (max-width: 380px) { .auth-mode { grid-template-columns: 1fr; } }

.auth-note { margin-top: 22px; padding-top: 14px; border-top: 1px solid var(--c-border);
             font-size: var(--f-2xs); color: var(--c-text-3); line-height: 1.7; }

/* 底部公司信息 */
.auth-foot { position: absolute; bottom: 20px; left: 0; right: 0; z-index: 2;
             text-align: center; font-size: var(--f-2xs); color: rgba(255,255,255,.32);
             line-height: 1.7; padding: 0 20px; }
.auth-foot .co { color: rgba(255,255,255,.5); letter-spacing: .06em; }
.auth-foot .ver { margin-top: 4px; color: rgba(255,255,255,.3); }
.auth-foot .ver a { color: rgba(255,255,255,.45); text-decoration: none; }
.auth-foot .ver a:hover { color: rgba(255,255,255,.7); }
.auth-foot .ver-tag { font-family: var(--mono, ui-monospace, Menlo, monospace);
                      letter-spacing: .02em; color: rgba(255,255,255,.45); }
.auth-foot .ver-sep { margin: 0 6px; opacity: .5; }
</style>
</head>
<body class="auth-page">

  <div class="auth-mark">
    <img src="<?= e(company_logo(192)) ?>?v=<?= (int) @filemtime(__DIR__ . '/../' . company_logo(192)) ?>" alt="LEDU" width="38" height="38">
    <div>
      <div class="pn">Lt-AI-Books</div>
      <div class="pv">Ver 1.1</div>
    </div>
  </div>

  <div class="auth-card">
    <h1>登录</h1>
    <div class="sub">使用分配给你的账号进入系统</div>

    <?php if ($err !== null && $err !== ''): ?>
      <div class="auth-msg"><span>⚠</span><div><?= e($err) ?></div></div>
    <?php endif; ?>

    <form method="post" action="?p=login">
      <input type="hidden" name="action" value="login">
      <div class="auth-field">
        <label for="u">用户名</label>
        <input id="u" type="text" name="username"
               value="<?= e((string) ($_POST['username'] ?? '')) ?>"
               autocomplete="username" required autofocus>
      </div>
      <div class="auth-field">
        <label for="p">口令</label>
        <input id="p" type="password" name="password" autocomplete="current-password" required>
      </div>

      <?php
        $pickMode = ((string) ($_COOKIE['ledu_mode'] ?? 'ai')) === 'manual' ? 'manual' : 'ai';
      ?>
      <div class="auth-mode-lbl"><?= e(t('使用模式（登录后可在顶栏切换）')) ?></div>
      <div class="auth-mode">
        <label class="am-card">
          <input type="radio" name="mode" value="ai" <?= $pickMode === 'ai' ? 'checked' : '' ?>>
          <span class="am-body">
            <span class="am-t"><?= e(t('AI 模式')) ?></span>
            <span class="am-d"><?= e(t('一句话说清要做什么，AI 出草稿，你确认后才入账')) ?></span>
          </span>
        </label>
        <label class="am-card">
          <input type="radio" name="mode" value="manual" <?= $pickMode === 'manual' ? 'checked' : '' ?>>
          <span class="am-body">
            <span class="am-t"><?= e(t('人工模式')) ?></span>
            <span class="am-d"><?= e(t('自己点菜单，逐项录入与复核')) ?></span>
          </span>
        </label>
      </div>

      <button class="btn primary auth-btn" type="submit"><?= e(t('登录')) ?></button>
    </form>

    <div class="auth-note">
      <strong>HKFRS</strong> · 复式记账 · 四眼复核 · 审计哈希链
    </div>
  </div>

  <div class="auth-foot">
    <div class="co"><?= e($zhName) ?> · LEDU TECH CO., LIMITED</div>
    <div>金额由确定性代码计算 · 校验结果不构成过账授权 · AI 辅助，需人工复核</div>
    <div class="ver">
      <span class="ver-tag"><?= e(ltbooks_version_line()) ?></span>
      <span class="ver-sep">·</span>
      <a href="?p=license">MIT License</a>
      <span class="ver-sep">·</span>
      <span><?= e(t('香港有限公司 · 港币本位 · HKFRS')) ?></span>
    </div>
  </div>

<?php echo localize_html(ob_get_clean()); ?>
</body>
</html>

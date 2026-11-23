/*
 * LtBooks — assets/precheck.js
 * Copyright (c) 2026 LEDU TECH CO., LIMITED
 * SPDX-License-Identifier: MIT
 *
 * 人工台「AI 预判」小组件：把当前表单交给对应岗位智能体审一遍。
 * 只显示结论，不改表单；科目与金额仍由人确认。
 */
(function () {
  'use strict';

  var BADGE = { ok: '通过', warn: '需注意', block: '有阻断' };
  var LEVEL = { info: '提示', warn: '注意', block: '阻断' };

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s === null || s === undefined ? '' : String(s);
    return d.innerHTML;
  }

  function num(n) {
    var v = Number(n);
    return isFinite(v) ? v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
  }

  function fmtTime(s) {
    s = Math.max(0, Math.floor(Number(s) || 0));
    var m = Math.floor(s / 60), ss = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (ss < 10 ? '0' : '') + ss;
  }

  // 后端是同步请求，前端拿不到真实阶段；按耗时切换提示语，让用户能感知「还在跑、没宕机」。
  function phaseFor(s) {
    if (s < 4) return '正在连接服务…';
    if (s < 12) return '正在执行规则校验…';
    if (s < 30) return 'AI 正在思考，请稍候…';
    if (s < 60) return '耗时偏长，模型可能繁忙，仍在运行中…';
    return '已超过 60 秒，建议检查网络或稍后重试';
  }

  function renderLoading(host, opts) {
    host.setAttribute('data-state', 'loading');
    host.innerHTML =
      '<div class="pc-head">'
      + '<div class="pc-title">AI 预判 <span class="pc-agent">' + esc(opts.agentLabel || '智能体') + '</span>'
      + '<span class="pc-badge pc-loading-badge">运行中</span></div>'
      + '<button type="button" class="btn sm pc-cancel">取消</button></div>'
      + '<div class="pc-loading">'
      + '<div class="pc-bar"><span></span></div>'
      + '<div class="pc-phase">正在连接服务…</div>'
      + '<div class="pc-elapsed">已耗时 00:00</div>'
      + '</div>';
  }

  function render(host, data) {
    var v = data.verdict || 'warn';
    var rows = (data.findings || []).filter(function (f) { return f && f.text; });
    var accounts = data.accounts || [];
    var jl = (data.journalPreview && data.journalPreview.lines) || [];
    var confirm = data.confirm || [];
    var html = '';

    html += '<div class="pc-head">'
      + '<div class="pc-title">AI 预判 <span class="pc-agent">' + esc(data.agentLabel || '') + '</span>'
      + '<span class="pc-badge pc-' + esc(v) + '">' + esc(BADGE[v] || v) + '</span></div>'
      + '<button type="button" class="btn sm pc-rerun">重新预判</button></div>';

    html += '<div class="pc-summary">' + esc(data.summary || '') + '</div>';

    if (rows.length) {
      html += '<ul class="pc-findings">';
      rows.forEach(function (f) {
        var lv = LEVEL[f.level] ? f.level : 'info';
        html += '<li class="pc-f pc-f-' + lv + '"><span class="pc-dot"></span>'
          + '<span class="pc-lv">' + esc(LEVEL[lv]) + '</span>' + esc(f.text) + '</li>';
      });
      html += '</ul>';
    }

    if (accounts.length) {
      html += '<div class="pc-sec">建议科目</div><div class="pc-chips">';
      accounts.forEach(function (a) {
        html += '<span class="pc-chip"><b>' + esc(a.code) + '</b> ' + esc(a.name || '')
          + (a.reason ? '<i>' + esc(a.reason) + '</i>' : '') + '</span>';
      });
      html += '</div>';
    }

    if (jl.length) {
      html += '<div class="pc-sec">分录预览 · 原币 ' + esc((data.journalPreview && data.journalPreview.currency) || '') + '</div>';
      html += '<table class="pc-jl"><thead><tr><th style="width:40px">方向</th><th style="width:70px">科目</th><th>名称</th><th class="num" style="width:110px">金额</th></tr></thead><tbody>';
      jl.forEach(function (x) {
        html += '<tr><td class="' + (x.side === 'debit' ? 'pc-dr' : 'pc-cr') + '">'
          + (x.side === 'debit' ? '借' : '贷') + '</td><td class="mono">' + esc(x.account)
          + '</td><td>' + esc(x.name || '') + '</td><td class="num mono">' + num(x.amount) + '</td></tr>';
      });
      html += '</tbody></table>';
    }

    if (confirm.length) {
      html += '<div class="pc-sec">需要你确认</div><ul class="pc-confirm">';
      confirm.forEach(function (c) { html += '<li>' + esc(c) + '</li>'; });
      html += '</ul>';
    }

    html += '<div class="pc-foot">' + esc(data.disclaimer || 'AI-assisted, subject to human review')
      + ' · 来源：' + (data.source === 'ai' ? 'AI' : '规则校验')
      + (data.llmError ? '（模型暂不可用，已退回规则）' : '') + '</div>';

    host.innerHTML = html;
    host.setAttribute('data-state', v);
    var btn = host.querySelector('.pc-rerun');
    if (btn) { btn.addEventListener('click', function () { run(true); }); }
  }

  function attach(opts) {
    var host = typeof opts.el === 'string' ? document.querySelector(opts.el) : opts.el;
    if (!host) { return null; }
    var form = typeof opts.form === 'string' ? document.querySelector(opts.form) : opts.form;
    var timer = null;
    var lastKey = '';
    var running = false;
    var queued = false;
    var hbTimer = null;      // 心跳：每秒更新已耗时与阶段文案
    var controller = null;   // fetch AbortController，用于取消/超时
    var toTimer = null;      // 超时定时器
    var userCancelled = false;
    var startedAt = 0;

    function csrf() {
      var scope = form || document;
      var el = scope.querySelector('input[name="_csrf"]') || document.querySelector('input[name="_csrf"]');
      return el ? el.value : '';
    }

    function collect() {
      if (typeof opts.collect === 'function') {
        try { return opts.collect() || {}; } catch (e) { return {}; }
      }
      return {};
    }

    function ready(p) {
      if (typeof opts.ready === 'function') { return !!opts.ready(p); }
      return opts.docId ? true : JSON.stringify(p || {}).length > 20;
    }

    function stopHeartbeat() {
      if (hbTimer) { clearInterval(hbTimer); hbTimer = null; }
    }

    function startHeartbeat() {
      stopHeartbeat();
      startedAt = Date.now();
      var tick = function () {
        var s = (Date.now() - startedAt) / 1000;
        var el = host.querySelector('.pc-elapsed');
        if (el) { el.textContent = '已耗时 ' + fmtTime(s); }
        var ph = host.querySelector('.pc-phase');
        if (ph) { ph.textContent = phaseFor(s); }
        var wrap = host.querySelector('.pc-loading');
        if (wrap) { wrap.classList.toggle('pc-slow', s >= 30); }
        var btn = host.querySelector('.pc-cancel');
        if (btn) { btn.textContent = s >= 60 ? '重试' : '取消'; }
      };
      tick();
      hbTimer = setInterval(tick, 1000);
    }

    function renderIdle() {
      host.setAttribute('data-state', 'idle');
      host.innerHTML = '<div class="pc-head"><div class="pc-title">AI 预判 <span class="pc-agent">'
        + esc(opts.agentLabel || '智能体') + '</span></div>'
        + '<button type="button" class="btn sm pc-run">开始预判</button></div>'
        + '<div class="pc-summary pc-idle">' + esc(opts.hint || '提交前让对应岗位智能体先审一遍；不会改动单据。') + '</div>';
      var b = host.querySelector('.pc-run');
      if (b) { b.addEventListener('click', function () { run(true); }); }
    }

    function errorBox(msg) {
      return '<div class="pc-head"><div class="pc-title">AI 预判</div>'
        + '<button type="button" class="btn sm pc-rerun">重试</button></div>'
        + '<div class="pc-summary pc-err">' + esc(msg) + '</div>';
    }

    function bindRetry(h) {
      var b = h.querySelector('.pc-rerun');
      if (b) { b.addEventListener('click', function () { run(true); }); }
    }

    function run(manual) {
      var payload = collect();
      var key = JSON.stringify([opts.workflow, opts.docId || 0, payload]);
      if (!manual && (!ready(payload) || key === lastKey)) { return; }
      if (running) { queued = true; return; }
      running = true;
      userCancelled = false;
      lastKey = key;
      renderLoading(host, opts);
      startHeartbeat();
      // 取消按钮：中止请求并回到待命态；超过 60 秒后按钮文案自动变成「重试」。
      var cancelBtn = host.querySelector('.pc-cancel');
      if (cancelBtn) {
        cancelBtn.addEventListener('click', function () {
          userCancelled = true;
          if (controller) { try { controller.abort(); } catch (e) {} }
        });
      }
      controller = new AbortController();
      var timedOut = false;
      toTimer = setTimeout(function () {
        timedOut = true;
        if (controller) { try { controller.abort(); } catch (e) {} }
      }, 95000);
      fetch('precheck.php', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          workflow: opts.workflow,
          docId: opts.docId || null,
          payload: payload,
          csrf: csrf()
        }),
        signal: controller.signal
      }).then(function (r) { return r.json(); }).then(function (res) {
        clearTimeout(toTimer); toTimer = null;
        running = false;
        stopHeartbeat();
        if (!res.ok) {
          host.setAttribute('data-state', 'error');
          host.innerHTML = errorBox(res.error || '预判失败');
          bindRetry(host);
          return;
        }
        render(host, res.data || {});
        if (queued) { queued = false; setTimeout(function () { run(false); }, 300); }
      }).catch(function () {
        clearTimeout(toTimer); toTimer = null;
        running = false;
        stopHeartbeat();
        if (userCancelled) { renderIdle(); return; }
        host.setAttribute('data-state', 'error');
        var msg = timedOut
          ? '预判超时（已等待 95 秒），请检查网络或稍后重试'
          : '网络错误，请稍后重试';
        host.innerHTML = errorBox(msg);
        bindRetry(host);
      });
    }

    renderIdle();

    if (opts.auto !== false) {
      setTimeout(function () { run(false); }, 700);
      if (form) {
        var debounce = function () {
          clearTimeout(timer);
          timer = setTimeout(function () { run(false); }, 1600);
        };
        form.addEventListener('input', debounce);
        form.addEventListener('change', debounce);
      }
    }
    return { run: run };
  }

  window.LeduPrecheck = { attach: attach };
})();

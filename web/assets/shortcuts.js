/**
 * LtBooks — 全局键盘快捷键
 *   Ctrl+S / Cmd+S     → 保存当前最近的表单（带 data-shortcut-save）
 *   Ctrl+Enter / Cmd+Enter → 聚焦保存并过账按钮（带 data-shortcut-post）
 */
(function () {
  'use strict';

  document.addEventListener('keydown', function (ev) {
    var mod = ev.ctrlKey || ev.metaKey;
    if (!mod) return;

    // Ctrl+S — 保存
    if (ev.key === 's') {
      // 不拦截输入框内的原生保存（如富文本编辑器），但拦截普通表单
      var target = ev.target;
      var isEditable = target && (
        target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' || target.isContentEditable
      );
      // 让浏览器原生行为走 —— 但我们同时尝试提交
      var saveBtn = document.querySelector('[data-shortcut-save]');
      if (saveBtn) {
        ev.preventDefault();
        saveBtn.click();
        _flash(saveBtn);
        return;
      }
      // 兜底：找第一个 POST 表单的 submit 按钮
      var form = document.querySelector('form[method="post"]:not([target])');
      if (form) {
        ev.preventDefault();
        var btn = form.querySelector('button[type=submit]');
        if (btn) { btn.click(); _flash(btn); }
        else form.submit();
      }
      return;
    }

    // Ctrl+Enter — 过账
    if (ev.key === 'Enter') {
      var postBtn = document.querySelector('[data-shortcut-post]');
      if (postBtn) {
        ev.preventDefault();
        // 过账是高风险操作，走 confirm
        if (confirm('确认过账？过账后不可直接修改，只能红冲。')) {
          postBtn.click();
          _flash(postBtn);
        }
      }
    }
  });

  function _flash(el) {
    el.style.transition = 'box-shadow .15s';
    el.style.boxShadow = '0 0 0 3px rgba(76,175,80,.45)';
    setTimeout(function () { el.style.boxShadow = ''; }, 500);
  }
})();

/**
 * LtBooks — localStorage 缓存工具
 *   LtCache.put('customers', data, 300000)  → 写缓存（5min TTL）
 *   LtCache.get('customers')                → 读缓存（未过期返回 data，否则 null）
 *   LtCache.invalidate('customers')         → 手动失效
 */
window.LtCache = (function () {
  'use strict';
  var PREFIX = 'ltbooks_';
  var DEFAULT_TTL = 5 * 60 * 1000;

  function put(key, data, ttl) {
    try {
      localStorage.setItem(PREFIX + key, JSON.stringify({
        ts: Date.now(),
        ttl: ttl || DEFAULT_TTL,
        data: data
      }));
    } catch (e) { /* 隐私模式/满了 — 静默 */ }
  }

  function get(key) {
    try {
      var raw = localStorage.getItem(PREFIX + key);
      if (!raw) return null;
      var obj = JSON.parse(raw);
      if (!obj || typeof obj !== 'object' || !('ts' in obj) || !('data' in obj)) {
        localStorage.removeItem(PREFIX + key);
        return null;
      }
      if (Date.now() - obj.ts > (obj.ttl || DEFAULT_TTL)) {
        localStorage.removeItem(PREFIX + key);
        return null;
      }
      return obj.data;
    } catch (e) { return null; }
  }

  function invalidate(key) {
    try { localStorage.removeItem(PREFIX + key); } catch (e) {}
  }

  return { put: put, get: get, invalidate: invalidate };
})();

/**
 * LtBooks — 客户/供应商列表缓存同步
 *   PHP render 后已经把 window._customers / window._vendors 输出，这里写入 localStorage，
 *   后续新建页（报价/订单/贷记单）用 LtCache.get() 即可避开重复全量拉。
 */
(function () {
  if (window._customers && Array.isArray(window._customers.length !== undefined ? window._customers : [])) {
    // 已由 PHP 渲染完成 — 写入缓存
    LtCache.put('customers', window._customers, 5 * 60 * 1000);
  }
  if (window._vendors && Array.isArray(window._vendors)) {
    LtCache.put('vendors', window._vendors, 5 * 60 * 1000);
  }
})();

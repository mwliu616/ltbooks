/**
 * 可搜索下拉：给原生 <select> 加一个搜索框。
 *
 * 设计取舍：
 *  - 原生 select 保留在 DOM 中（表单提交、必填校验、change 事件照旧）；
 *  - 仅在选项数 ≥ 8 时增强，少量选项仍用原生控件，避免多余点击；
 *  - 不引入任何第三方库，离线可用。
 */
(function () {
  'use strict';

  var MIN_OPTIONS = 8;
  var _sselCounter = 0;

  function labelOf(opt) {
    return (opt.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function enhance(select) {
    if (!select || select.dataset.ssReady === '1') return;
    if (select.multiple) return;
    // 选项少时通常不必搜索；但带「可新建」的下拉一律增强，
    // 否则选项不多时就没有「搜不到就建」的入口了。
    var allowCreate = select.hasAttribute('data-allow-create');
    if (select.options.length < MIN_OPTIONS && !allowCreate) return;
    if (select.hasAttribute('data-no-search')) return;
    if (select.closest('.ssel')) return;

    select.dataset.ssReady = '1';

    var wrap = document.createElement('div');
    wrap.className = 'ssel';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ssel-btn';
    btn.setAttribute('aria-haspopup', 'listbox');
    btn.setAttribute('aria-expanded', 'false');

    var pop = document.createElement('div');
    pop.className = 'ssel-pop';
    pop.hidden = true;

    var input = document.createElement('input');
    input.type = 'text';
    input.className = 'ssel-input';
    input.placeholder = '搜索…';
    input.setAttribute('aria-label', '搜索选项');

    var list = document.createElement('ul');
    list.className = 'ssel-list';
    list.setAttribute('role', 'listbox');

    pop.appendChild(input);
    pop.appendChild(list);

    // 原生 select 视觉隐藏但保留在表单流中
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    wrap.appendChild(btn);
    wrap.appendChild(pop);
    select.classList.add('ssel-native');
    select.setAttribute('tabindex', '-1');
    select.setAttribute('aria-hidden', 'true');
    btn.setAttribute('aria-controls', 'ssel-' + (++_sselCounter));
    btn.setAttribute('aria-label', '展开下拉选项');
    list.id = btn.getAttribute('aria-controls');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-label', '搜索选项');

    var active = -1;
    var visible = [];

    function syncLabel() {
      var o = select.options[select.selectedIndex];
      btn.textContent = o ? labelOf(o) : '—';
      btn.classList.toggle('is-empty', !o || o.value === '');
    }

    function render(filter) {
      var q = (filter || '').trim().toLowerCase();
      list.innerHTML = '';
      visible = [];
      for (var i = 0; i < select.options.length; i++) {
        var o = select.options[i];
        var t = labelOf(o);
        if (q && t.toLowerCase().indexOf(q) === -1) continue;
        visible.push(i);
        var li = document.createElement('li');
        li.className = 'ssel-item';
        li.setAttribute('role', 'option');
        li.textContent = t;
        li.dataset.idx = String(i);
        if (i === select.selectedIndex) li.classList.add('is-selected');
        list.appendChild(li);
      }
      if (!visible.length) {
        var e = document.createElement('li');
        e.className = 'ssel-empty';
        e.textContent = '无匹配项';
        list.appendChild(e);

        // 允许现场新建：把搜索词作为新名称抛给页面处理
        if (select.hasAttribute('data-allow-create') && q) {
          var c = document.createElement('li');
          c.className = 'ssel-item ssel-create';
          c.setAttribute('role', 'button');
          c.textContent = '＋ 新建「' + filter.trim() + '」';
          c.addEventListener('mousedown', function (ev) {
            ev.preventDefault();
            close();
            select.dispatchEvent(new CustomEvent('ssel:create', {
              bubbles: true, detail: { query: filter.trim() }
            }));
          });
          list.appendChild(c);
        }
      }
      active = -1;
    }

    function place() {
      var r = btn.getBoundingClientRect();
      var GAP = 4, EDGE = 12, PREF = 320, MIN = 160;
      var below = window.innerHeight - r.bottom - GAP - EDGE;
      var above = r.top - GAP - EDGE;
      var h, top;
      // 下方放得下就往下弹，否则翻到上方，避免把弹层顶出视口
      if (below >= MIN || below >= above) {
        h = Math.min(PREF, Math.max(MIN, below));
        top = r.bottom + GAP;
      } else {
        h = Math.min(PREF, Math.max(MIN, above));
        top = Math.max(EDGE, r.top - GAP - h);
      }
      pop.style.position = 'fixed';
      pop.style.left = r.left + 'px';
      pop.style.width = r.width + 'px';
      pop.style.top = top + 'px';
      pop.style.maxHeight = h + 'px';
      pop.style.zIndex = '9999';
    }

    function open() {
      render('');
      input.value = '';
      pop.hidden = false;
      place();
      btn.setAttribute('aria-expanded', 'true');
      wrap.classList.add('is-open');
      input.focus();
      var sel = list.querySelector('.is-selected');
      if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: 'nearest' });
    }

    function close() {
      pop.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
      wrap.classList.remove('is-open');
    }

    function choose(idx) {
      if (idx < 0 || idx >= select.options.length) return;
      select.selectedIndex = idx;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      syncLabel();
      close();
      btn.focus();
    }

    function move(step) {
      if (!visible.length) return;
      var pos = visible.indexOf(active);
      pos = (pos === -1) ? (step > 0 ? 0 : visible.length - 1)
                         : Math.min(visible.length - 1, Math.max(0, pos + step));
      active = visible[pos];
      Array.prototype.forEach.call(list.children, function (li) {
        li.classList.toggle('is-active', li.dataset.idx === String(active));
      });
      var cur = list.querySelector('.is-active');
      if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
    }

    btn.addEventListener('click', function (e) {
      e.preventDefault();
      if (pop.hidden) open(); else close();
    });

    input.addEventListener('input', function () { render(input.value); });

    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        choose(active >= 0 ? active : (visible.length ? visible[0] : -1));
      } else if (e.key === 'Escape') { e.preventDefault(); close(); btn.focus(); }
    });

    list.addEventListener('click', function (e) {
      var li = e.target.closest('.ssel-item');
      if (!li || li.classList.contains('ssel-create')) return;   // 新建项走自己的事件
      choose(parseInt(li.dataset.idx, 10));
    });

    window.addEventListener('resize', function () { if (!pop.hidden) place(); });
    window.addEventListener('scroll', function () { if (!pop.hidden) place(); }, true);

    document.addEventListener('click', function (e) {
      if (!wrap.contains(e.target) && !pop.contains(e.target)) close();
    });

    select.addEventListener('change', syncLabel);

    // 必填校验未通过时，浏览器无法在隐藏的原生控件上提示 —— 打开弹层并聚焦搜索框
    select.addEventListener('invalid', function () {
      if (pop.hidden) open();
    });
    // 键盘 Tab 进入隐藏的原生 select 时，同步打开弹层
    select.addEventListener('focus', function () {
      if (pop.hidden) { btn.focus(); open(); }
    });

    syncLabel();
  }

  function scan(root) {
    (root || document).querySelectorAll('select').forEach(enhance);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { scan(); });
  } else {
    scan();
  }
  // 动态插入的 select（AI 预填等）也覆盖
  window.enhanceSelects = scan;
})();

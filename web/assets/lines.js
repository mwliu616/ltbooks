/* ---------------------------------------------------------------
   明细行编辑器 —— 建单 / 报价单共用
   结构：<table id="lnTable"><tbody id="lnBody">
           <tr><td class="ln-seq"></td>
               <td><input class="ln-desc" name="lineDesc[]"></td>
               <td><input class="ln-qty" name="lineQty[]" type="number"></td>
               <td><input class="ln-price" name="linePrice[]" type="number"></td>
               <td><input class="ln-tax" name="lineTax[]" type="number"></td>
               <td class="ln-amt"></td>
               <td><button class="ln-del" type="button">×</button></td></tr>
   合计：<span id="lnSubtotal"></span> <span id="lnTax"></span> <span id="lnTotal"></span>
   隐藏字段：#lnAmountInput #lnTaxInput（提交给后端的金额）
   折扣：#lnDiscount（可选，#lnDiscountRate 可选）
   --------------------------------------------------------------- */
(function () {
  var body = document.getElementById('lnBody');
  var addBtn = document.getElementById('lnAdd');
  if (!body || !addBtn) return;

  function num(el) { var v = parseFloat(el && el.value); return isFinite(v) ? v : 0; }
  function fmt(n) { return (Math.round(n * 100) / 100).toFixed(2); }

  function sync(tr) {
    var qty = num(tr.querySelector('.ln-qty'));
    var price = num(tr.querySelector('.ln-price'));
    var rate = num(tr.querySelector('.ln-tax'));
    var amt = qty * price;
    var cell = tr.querySelector('.ln-amt');
    if (cell) cell.textContent = fmt(amt);
    return { amt: amt, tax: amt * rate / 100 };
  }

  function renumber() {
    body.querySelectorAll('tr').forEach(function (tr, i) {
      var c = tr.querySelector('.ln-seq');
      if (c) c.textContent = i + 1;
    });
  }

  function recalc() {
    var sum = 0, tax = 0;
    body.querySelectorAll('tr').forEach(function (tr) {
      var v = sync(tr); sum += v.amt; tax += v.tax;
    });
    var discEl = document.getElementById('lnDiscount');
    var disc = discEl ? Math.min(Math.max(parseFloat(discEl.value) || 0, 0), sum) : 0;
    var rateEl = document.getElementById('lnDiscountRate');
    if (rateEl && sum) {
      if (document.activeElement === rateEl) {
        disc = sum * (parseFloat(rateEl.value) || 0) / 100;
        if (discEl) { discEl.value = fmt(disc); }
      } else {
        rateEl.value = (disc / sum * 100).toFixed(4).replace(/\.?0+$/, '');
      }
    }
    var net = sum - disc;
    var ratio = sum ? net / sum : 0;
    var netTax = tax * ratio;
    var el;
    if ((el = document.getElementById('lnSubtotal'))) { el.textContent = fmt(sum); }
    if ((el = document.getElementById('lnTax'))) { el.textContent = fmt(netTax); }
    if ((el = document.getElementById('lnTotal'))) { el.textContent = fmt(net + netTax); }
    if ((el = document.getElementById('lnAmountInput'))) { el.value = fmt(net); }
    if ((el = document.getElementById('lnTaxInput'))) { el.value = fmt(netTax); }
  }

  var emptyRow = body.querySelector('tr');

  function bind(tr) {
    ['ln-qty', 'ln-price', 'ln-tax'].forEach(function (cls) {
      var el = tr.querySelector('.' + cls);
      if (el) { el.addEventListener('input', recalc); }
    });
    var d = tr.querySelector('.ln-desc');
    if (d) { d.addEventListener('input', recalc); }
    var del = tr.querySelector('.ln-del');
    if (del) {
      del.addEventListener('click', function () {
        if (body.querySelectorAll('tr').length <= 1) {
          tr.querySelectorAll('input').forEach(function (i) {
            i.value = i.classList.contains('ln-qty') ? '1' : '';
          });
        } else { tr.remove(); }
        renumber(); recalc();
      });
    }
  }

  body.querySelectorAll('tr').forEach(bind);
  addBtn.addEventListener('click', function () {
    var tr = emptyRow.cloneNode(true);
    tr.querySelectorAll('input').forEach(function (i) {
      i.value = i.classList.contains('ln-qty') ? '1' : '';
    });
    var amt = tr.querySelector('.ln-amt');
    if (amt) { amt.textContent = '0.00'; }
    body.appendChild(tr); bind(tr); renumber();
    var d = tr.querySelector('.ln-desc');
    if (d) { d.focus(); }
    recalc();
  });
  ['lnDiscount', 'lnDiscountRate'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) { el.addEventListener('input', recalc); }
  });
  renumber(); recalc();

  // 供应商 / 客户下拉：选「其他」显示手填框
  var party = document.getElementById('partySel');
  var custom = document.getElementById('partyCustom');
  if (party && custom) {
    var toggle = function () {
      var c = party.value === '__custom__';
      custom.style.display = c ? '' : 'none';
      custom.required = c;
      if (c) { custom.focus(); }
    };
    party.addEventListener('change', toggle);
    toggle();
  }
})();

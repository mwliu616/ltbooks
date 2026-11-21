# LtBooks — core/pdf_reports.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""财务报表与管理报表 PDF。

版式遵循 HKFRS 惯例：实体名 / 报表名 / 期间 / 币种说明 / 分部与小计 / 附注。
所有数字来自确定性代码，PDF 只负责排版。
"""
import html
import re
from datetime import datetime
from pathlib import Path

from config import STORAGE_DIR
from .db import query
from .i18n import DEFAULT_LANG, LANGS, column, label, cell

# 当前渲染语言与科目名映射（由入口设置，避免逐函数传参）。
# 用线程局部存储：Flask 多线程下全局字典会让两个并发的 PDF 请求串语言。
import threading as _threading

_TLS = _threading.local()
_CTX_DEFAULT = {"lang": DEFAULT_LANG, "names": {}}


class _CtxProxy:
    """像 dict 一样访问，实际读写线程本地副本。"""
    def _get(self):
        if not hasattr(_TLS, "ctx"):
            _TLS.ctx = {"lang": DEFAULT_LANG, "names": {}}
        return _TLS.ctx

    def __getitem__(self, k):
        return self._get()[k]

    def __setitem__(self, k, v):
        self._get()[k] = v


_CTX = _CtxProxy()


def set_lang(lang: str, entity_id: int | None = None):
    _CTX["lang"] = lang if lang in LANGS else DEFAULT_LANG
    # 同一份报表的科目名也要跟着切：reports 模块按 _REPORT_LANG 取 name_zh_cn / name_zh_hk / name_en，
    # 不联动的话 PDF 表头是中文、科目名却是英文。
    try:
        from . import reports as _rep
        _rep.set_report_lang(_CTX["lang"])
    except Exception:
        pass
    if entity_id:
        col = {"zh_cn": "name_zh_cn", "zh_hk": "name_zh_hk", "en": "name_en"}[_CTX["lang"]]
        rows = query(f"SELECT account_code, {col} AS nm, name_zh_cn FROM accounts WHERE entity_id=%s",
                     (entity_id,))
        _CTX["names"] = {r["account_code"]: (r["nm"] or r["name_zh_cn"]) for r in rows}
    return _CTX["lang"]


_NOTE_MAP = {
    "按 HKAS 1 格式列报；税项按利得税计算表确认后入账，未确认前不预估": "note_hkas1",
    "期末现金必须与资产负债表现金一致": "note_cash_recon",
    "外币账龄按币种分列；HKD 汇总取折算列之和，不直接相加原币": "note_fx_aging",
    "不同币种不得直接相加；HKD 合计为各账户折算金额之和": "note_fx_bank",
    "正数为汇兑收益，负数为汇兑损失": "note_fx_sign",
    "按客户与币种分列；HKD 合计仅取折算列": "note_cust_bal",
    "按供应商与币种分列；HKD 合计仅取折算列": "note_vend_bal",
    "比率仅供参考；不同行业基准差异很大，不应单独作为决策依据": "note_ratios",
    "期初权益含累计未分配利润；「权益直接变动」为权益科目本期发生额": "note_equity",
    "无现金科目": "note_no_cash",
    "应评税利润为正，按两级制计税": "tax_note_profit",
    "应评税利润为负，属税务亏损，可无限期结转抵销未来年度利润": "tax_note_loss",
    "以下中间数据仅供核对，不含税额": "tax_interim_only",
    "实体两级制税率资格未确定（undetermined）；按规不得自行假定，须先确认资格": "tax_reason_undetermined",
}


def _note(text):
    """把后端固定产出中文的附注按当前语言输出；未知内容原样保留。"""
    if text is None:
        return ""
    key = _NOTE_MAP.get(str(text).strip())
    return L(key) if key else str(text)


def L(key: str) -> str:
    return label(_CTX["lang"], key)


def _nm(code, fallback=None) -> str:
    return _CTX["names"].get(code) or fallback or (code or "")

CSS = """
@page {
  size: A4; margin: 18mm 16mm 22mm;
  @bottom-center {
    content: string(run-foot);
    font-family: "IBM Plex Sans", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7.6pt; color: #555555; padding-top: 3mm;
    border-top: .5px solid #cccccc; vertical-align: top;
  }
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: "IBM Plex Sans", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888888; padding-top: 3mm;
    border-top: .5px solid #cccccc; vertical-align: top;
  }
}
@page :first { margin-top: 16mm; }
* { box-sizing: border-box; }
body { font-family: "IBM Plex Sans", "WenQuanYi Zen Hei", sans-serif;
       font-size: 9.5pt; color: #000; margin: 0; line-height: 1.45; }
.doc-head { border-bottom: 2px solid #000; padding-bottom: 8px; margin-bottom: 16px;
            text-align: center; }
.stmt-title { text-align: center; }
.stmt-title h1 { margin: 0; font-size: 14pt; font-weight: 700; letter-spacing: .5px; }
.stmt-title .period { font-size: 8.5pt; color: #444444; margin-top: 3px; }
.run-foot { string-set: run-foot content(); display: none; }
.curr-note { font-size: 8pt; color: #555555; margin: -6px 0 12px; }

table.stmt { width: 100%; border-collapse: collapse; }
table.stmt th { font-size: 8pt; color: #444444; font-weight: 600; text-align: right;
                padding: 5px 6px; border-bottom: 1.2px solid #333333; }
table.stmt th.lbl { text-align: left; }
table.stmt td { padding: 4.5px 6px; font-size: 9pt; }
table.stmt td.num { text-align: right; font-variant-numeric: tabular-nums;
                    font-family: "IBM Plex Mono", monospace; }
table.stmt tr.section td { font-weight: 700; padding-top: 12px; padding-bottom: 3px;
                           border-bottom: 1px solid #BBBBBB; }
table.stmt tr.sub td { font-weight: 600; border-top: 1px solid #BBBBBB; padding-top: 6px; }
table.stmt tr.grand td { font-weight: 700; font-size: 10pt; border-top: 2px solid #000000;
                         border-bottom: 2px double #000000; padding: 7px 6px; }
table.stmt tr.indent td.lbl { padding-left: 20px; color: #333333; }
table.stmt tr.spacer td { height: 8px; padding: 0; border: none; }

.notes { margin-top: 22px; font-size: 8.5pt; color: #333333; }
.notes h3 { font-size: 9.5pt; margin: 14px 0 5px; color: #000; }
.notes ol, .notes ul { margin: 4px 0 0; padding-left: 17px; }
.notes li { margin-bottom: 3px; line-height: 1.55; }
.notes table { width: 100%; border-collapse: collapse; margin-top: 5px; }
.notes table th { font-size: 7.5pt; text-align: left; color: #555555; padding: 3px 5px;
                  border-bottom: 1px solid #CCCCCC; }
.notes table td { font-size: 8pt; padding: 3px 5px; border-bottom: 1px solid #F2F2F2; }
.notes td.num { text-align: right; font-family: "IBM Plex Mono", monospace; }

.foot { margin-top: 24px; padding-top: 7px; border-top: 1px solid #CCCCCC;
        font-size: 7.5pt; color: #666666; line-height: 1.6; }
.page-break { page-break-before: always; }
.check { font-size: 8pt; padding: 6px 9px; border-radius: 4px; margin: 10px 0 0; }
.check.ok { background: #F2F2F2; color: #000; border: 1px solid #999; }
.check.bad { background: #E8E8E8; color: #000; border: 1.2px solid #333; }
table.plain { width: 100%; border-collapse: collapse; margin-top: 8px; }
table.plain th { font-size: 7.5pt; text-transform: uppercase; letter-spacing: .04em;
                 color: #555555; text-align: left; padding: 5px 6px;
                 background: #F2F2F2; border-bottom: 1px solid #CCCCCC; }
table.plain td { font-size: 8.5pt; padding: 5px 6px; border-bottom: 1px solid #F2F2F2; }
table.plain td.num { text-align: right; font-family: "IBM Plex Mono", monospace; }

/* 详细总分类账（QuickBooks 版式）：无竖线，仅表头一条横线 */
.gl-head { text-align: center; margin-bottom: 8px; }
.gl-head .gl-title { font-size: 13.5pt; font-weight: 700; letter-spacing: .02em; }
.gl-head .gl-basis, .gl-head .gl-period { font-size: 9pt; color: #000; margin-top: 3px; }
table.gl { width: 100%; border-collapse: collapse; }
table.gl th { font-size: 8pt; font-weight: 700; text-align: left; padding: 4px 4px;
              border-bottom: 1.1px solid #000; white-space: nowrap; }
table.gl th.num { text-align: right; }
table.gl td { font-size: 8.3pt; padding: 6px 5px; vertical-align: top; line-height: 1.5;
              border-bottom: .4px solid #e3e3e3; }
table.gl td.num { text-align: right; font-variant-numeric: tabular-nums;
                  font-family: "IBM Plex Mono", monospace; white-space: nowrap; }
table.gl td.d { white-space: nowrap; }
table.gl tr { page-break-inside: avoid; break-inside: avoid; }
table.gl tr.acct td { font-weight: 700; font-size: 9pt; padding-top: 12px; }
table.gl tr.ob td, table.gl tr.cb td { padding-top: 2px; padding-bottom: 2px; }
table.gl tr.acct, table.gl tr.ob { page-break-after: avoid; break-after: avoid; }
.gl-note { margin-top: 14px; font-size: 8.2pt; font-weight: 700; }
"""


def _e(v):
    return html.escape("" if v is None else str(v))


def _addr(entity):
    parts = [entity.get(k) for k in ("addressLine1", "addressLine2", "district", "region")]
    return ", ".join(str(x).strip() for x in parts if x)


def _n(v):
    """金额格式；None 显示破折号，不假装是 0。"""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if f < 0:
        return "(" + f"{abs(f):,.2f}" + ")"
    return f"{f:,.2f}"


def _run_footer(entity) -> str:
    """页脚：公司名 + 生成时间。页脚不印地址，避免每页重复一长串。"""
    from datetime import datetime as _dt
    name = _e(entity.get("name") or entity.get("entity_name") or "")
    stamp = _dt.now().strftime("%Y-%m-%d %H:%M")
    return f'<div class="run-foot">{name} · {_e(L("generated_at").format(time=stamp))}</div>'


def _head(entity, title, period, cur_note=True):
    note = (_currency_note(entity) if cur_note else "")
    return f"""
<div class="doc-head">
  <div class="stmt-title"><h1>{_e(title)}</h1><div class="period">{_e(period)}</div></div>
</div>
{f'<div class="curr-note">{note}</div>' if note else ''}"""


def _currency_note(entity) -> str:
    """币种说明：跟随功能货币，不写死港币。"""
    cur = entity.get("functionalCurrency") or entity.get("functional_currency") or "HKD"
    name_map = {"HKD": {"zh_cn": "港元", "zh_hk": "港元", "en": "Hong Kong Dollars"},
                "USD": {"zh_cn": "美元", "zh_hk": "美元", "en": "US Dollars"},
                "CNY": {"zh_cn": "人民币", "zh_hk": "人民幣", "en": "Renminbi"},
                "CAD": {"zh_cn": "加元", "zh_hk": "加元", "en": "Canadian Dollars"}}
    cn = name_map.get(cur, {}).get(_CTX["lang"], cur)
    txt = cn if _CTX["lang"] == "en" else f"{cn}（{cur}）"
    return L("currency_note").replace("{cur}", txt)


# ---------------------------------------------------------------- 正文翻译
_DICT = None


def _dict_for(lang):
    global _DICT
    if _DICT is None:
        import json
        from pathlib import Path
        f = Path(__file__).with_name("lang_dict.json")
        _DICT = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    return _DICT.get(lang, {})


def _tr(text):
    """按当前语言翻译一段中文（复用网页同一词库）。未命中原样返回。"""
    l = _CTX["lang"]
    if l == "zh_cn" or not isinstance(text, str):
        return text
    d = _dict_for(l)
    if not d:
        return text
    key = re.sub(r"\s+", " ", text.strip())
    v = d.get(key) or d.get(text)
    if v:
        return v
    # 含动态值的条款：按模式翻译
    m = re.match(r"^功能货币为\s*(\w+)，列报货币相同。$", key)
    if m:
        cur = m.group(1)
        if l == "en":
            return f"Functional currency is {cur}, which is also the presentation currency."
        if l == "zh_hk":
            return f"功能貨幣為 {cur}，列報貨幣相同。"
    m = re.match(r"^金额单位为港元（(\w+)），除另有注明外均四舍五入至小数点后两位。$", key)
    if m and l == "en":
        return ("Amounts are stated in Hong Kong Dollars (HKD) and, unless stated otherwise, "
                "rounded to two decimal places.")
    return text


def _foot():
    """报表页脚已按需求移除（生成说明与版权行不再印在报表上）。

    版权仍保留在 LICENSE、界面页脚与单据 PDF 中。
    """
    return ""


def _footer_css(entity) -> str:
    """页脚：公司名 + 生成时间，落在每一页底部。地址不进页脚。"""
    from datetime import datetime as _dt
    ent = entity or {}
    name = str(ent.get("name") or ent.get("entity_name") or "LEDU TECH CO., LIMITED")
    stamp = _dt.now().strftime("%Y-%m-%d %H:%M")
    text = (name + "  ·  " + L("generated_at").format(time=stamp)).replace('"', "'")
    return ('@page { @bottom-center { content: "' + text + '";'
            ' font-family: "IBM Plex Sans", "WenQuanYi Zen Hei", sans-serif;'
            ' font-size: 7.6pt; color: #555555; padding-top: 3mm;'
            ' border-top: .5px solid #cccccc; vertical-align: top; }'
            ' @bottom-right { content: counter(page) " / " counter(pages);'
            ' font-family: "IBM Plex Sans", "WenQuanYi Zen Hei", sans-serif;'
            ' font-size: 7pt; color: #888888; padding-top: 3mm;'
            ' border-top: .5px solid #cccccc; vertical-align: top; } }')


def _wrap(body, entity=None, extra_css=""):
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<style>{CSS}{_footer_css(entity)}{extra_css}</style></head><body>{body}</body></html>')


def _rows_from_section(items, indent=True):
    out = ""
    for i in items:
        cls = "indent" if indent else ""
        out += (f'<tr class="{cls}"><td class="lbl">{_e(_nm(i.get("accountCode"), i.get("accountName")))}'
                f'<span style="color:#666666;font-size:7.5pt"> · {_e(i.get("accountCode"))}</span></td>'
                f'<td class="num">{_n(i.get("amount"))}</td></tr>')
    return out


# ---------------------------------------------------------------- 单项报表
def statement_of_financial_position(fs, asof, comparative=None):
    sp = fs["statementOfFinancialPosition"]
    ent = fs["entity"]

    def block(title, cur, noncur, total):
        h = f'<tr class="section"><td class="lbl" colspan="3">{_e(title)}</td></tr>'
        if noncur["items"]:
            h += f'<tr><td class="lbl" colspan="3" style="font-weight:600;padding-top:6px">{_e(L("non_current_assets"))}</td></tr>'
            h += _rows_from_section(noncur["items"])
            h += (f'<tr class="sub"><td class="lbl">{_e(L("non_current_assets"))} — {_e(L("amount"))}</td>'
                  f'<td class="num">{_n(noncur["total"])}</td><td class="num"></td></tr>')
        h += f'<tr><td class="lbl" colspan="3" style="font-weight:600;padding-top:6px">{_e(L("current_assets"))}</td></tr>'
        h += _rows_from_section(cur["items"])
        h += (f'<tr class="sub"><td class="lbl">{_e(L("current_assets"))} — {_e(L("amount"))}</td>'
              f'<td class="num">{_n(cur["total"])}</td><td class="num"></td></tr>')
        h += (f'<tr class="grand"><td class="lbl">{_e(L("total_assets"))}</td>'
              f'<td class="num">{_n(total)}</td><td class="num"></td></tr>')
        return h

    body = _head(ent, L("statement_of_financial_position"), L("as_at").format(date=asof))
    body += (f'<table class="stmt"><thead><tr><th class="lbl">{_e(L("item"))}</th>'
             f'<th>{_e(L("current"))}</th><th>{_e(L("prior"))}</th></tr></thead><tbody>')
    body += block(L("assets"), sp["assetsCurrent"], sp["assetsNonCurrent"], sp["assetsTotal"])

    body += '<tr class="spacer"><td colspan="3"></td></tr>'
    body += f'<tr class="section"><td class="lbl" colspan="3">{_e(L("equity_liabilities"))}</td></tr>'
    body += (f'<tr class="section" style="border:none;padding-top:8px">'
             f'<td class="lbl" colspan="3" style="font-weight:600">{_e(L("equity"))}</td></tr>')
    body += _rows_from_section(sp["equity"]["items"])
    body += (f'<tr class="indent"><td class="lbl">{_e(L("profit_for_period"))} — {_e(L("cumulative"))}</td>'
             f'<td class="num">{_n(sp["equity"]["currentYearProfit"])}</td></tr>')
    body += (f'<tr class="sub"><td class="lbl">{_e(L("total_equity"))}</td>'
             f'<td class="num">{_n(sp["equity"]["total"])}</td><td class="num"></td></tr>')

    if sp["liabilitiesNonCurrent"]["items"]:
        body += (f'<tr><td class="lbl" colspan="3" style="font-weight:600;padding-top:10px">'
                 f'{_e(L("non_current_liabilities"))}</td></tr>')
        body += _rows_from_section(sp["liabilitiesNonCurrent"]["items"])
    body += (f'<tr><td class="lbl" colspan="3" style="font-weight:600;padding-top:10px">'
             f'{_e(L("current_liabilities"))}</td></tr>')
    body += _rows_from_section(sp["liabilitiesCurrent"]["items"])
    body += (f'<tr class="sub"><td class="lbl">{_e(L("total_liabilities"))}</td>'
             f'<td class="num">{_n(sp["liabilitiesTotal"])}</td><td class="num"></td></tr>')
    body += (f'<tr class="grand"><td class="lbl">{_e(L("equity_liabilities"))} — {_e(L("amount"))}</td>'
             f'<td class="num">{_n(sp["liabilitiesTotal"] + sp["equity"]["total"])}</td>'
             f'<td class="num"></td></tr>')
    body += '</tbody></table>'

    chk = sp["check"]
    body += (f'<div class="check {"ok" if chk["balanced"] else "bad"}">'
             + L("check_assets").format(a=_n(chk["assetsTotal"]),
                                        b=_n(chk["liabilitiesPlusEquity"]),
                                        d=_n(chk["difference"]))
             + f'（{_e(L("balanced") if chk["balanced"] else L("unbalanced"))}）</div>')
    body += _foot()
    return _wrap(body)


def statement_of_profit_or_loss(fs):
    p = fs["statementOfProfitOrLoss"]
    ent = fs["entity"]
    body = _head(ent, L("statement_of_profit_or_loss"),
                 L("for_period").format(date=fs["periodEnd"]))
    body += (f'<table class="stmt"><thead><tr><th class="lbl">{_e(L("item"))}</th>'
             f'<th>{_e(L("current"))}</th><th>{_e(L("prior"))}</th></tr></thead><tbody>')

    def sec(key, s, negative=False):
        lab = L(key)
        h = f'<tr class="section"><td class="lbl" colspan="3">{_e(lab)}</td></tr>'
        if s["items"]:
            h += _rows_from_section(s["items"])
        else:
            h += '<tr class="indent"><td class="lbl" style="color:#666666">—</td><td class="num">—</td><td class="num"></td></tr>'
        v = s["total"]
        val = f'({_n(abs(v))})' if negative else _n(v)
        h += (f'<tr class="sub"><td class="lbl">{_e(lab)} — {_e(L("amount"))}</td>'
              f'<td class="num">{val}</td><td class="num"></td></tr>')
        return h

    body += sec("revenue", p["revenue"])
    body += sec("cost_of_sales", p["costOfSales"], negative=True)
    body += (f'<tr class="sub"><td class="lbl"><b>{_e(L("gross_profit"))}</b></td>'
             f'<td class="num"><b>{_n(p["grossProfit"])}</b></td><td class="num"></td></tr>')
    body += sec("other_income", p["otherIncome"])
    body += sec("other_gains", p["otherGains"])
    body += sec("operating_expenses", p["operatingExpenses"], negative=True)
    body += (f'<tr class="sub"><td class="lbl"><b>{_e(L("profit_before_tax"))}</b></td>'
             f'<td class="num"><b>{_n(p["profitBeforeTax"])}</b></td><td class="num"></td></tr>')
    body += sec("finance_costs", p["financeCosts"], negative=True)
    body += sec("tax", p["taxExpense"], negative=True)
    body += (f'<tr class="grand"><td class="lbl">{_e(L("net_profit"))}</td>'
             f'<td class="num">{_n(p["netProfit"])}</td><td class="num"></td></tr>')

    body += f'<tr class="section"><td class="lbl" colspan="3">{_e(L("oci"))}</td></tr>'
    body += (f'<tr class="indent"><td class="lbl">{_e(L("fx_translation"))}</td>'
             f'<td class="num">{_n(p["otherComprehensiveIncome"])}</td><td class="num"></td></tr>')
    body += (f'<tr class="grand"><td class="lbl">{_e(L("total_comprehensive"))}</td>'
             f'<td class="num">{_n(p["totalComprehensiveIncome"])}</td><td class="num"></td></tr>')
    body += '</tbody></table>'
    body += f'<div class="check ok">{_e(_note(p["note"]))}</div>'
    body += _foot()
    return _wrap(body)


def statement_of_changes_in_equity(fs):
    eq = fs["statementOfChangesInEquity"]
    ent = fs["entity"]
    body = _head(ent, L("statement_of_changes_in_equity"),
                 L("for_period").format(date=fs["periodEnd"]))
    body += (f'<table class="stmt"><thead><tr><th class="lbl">{_e(L("item"))}</th>'
             f'<th>{_e(L("amount"))}</th></tr></thead><tbody>')
    body += (f'<tr class="section"><td class="lbl" colspan="2">{_e(L("opening_equity"))}'
             f'（{_e(eq["from"])}）</td></tr>')
    body += (f'<tr class="indent"><td class="lbl">{_e(L("account"))} — {_e(L("balance"))}</td>'
             f'<td class="num">{_n(eq["openingEquityAccounts"])}</td></tr>')
    body += (f'<tr class="indent"><td class="lbl">{_e(L("profit_for_period"))} — {_e(L("cumulative"))}</td>'
             f'<td class="num">{_n(eq["openingRetainedProfit"])}</td></tr>')
    body += (f'<tr class="sub"><td class="lbl">{_e(L("opening_equity"))}</td>'
             f'<td class="num">{_n(eq["openingEquity"])}</td></tr>')
    body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("profit_for_period"))}</td></tr>'
    body += (f'<tr class="indent"><td class="lbl">{_e(L("profit_for_period"))}</td>'
             f'<td class="num">{_n(eq["profitForPeriod"])}</td></tr>')
    body += (f'<tr class="indent"><td class="lbl">{_e(L("direct_movements"))}</td>'
             f'<td class="num">{_n(eq["equityDirectMovements"])}</td></tr>')
    body += (f'<tr class="grand"><td class="lbl">{_e(L("closing_equity"))}（{_e(eq["to"])}）</td>'
             f'<td class="num">{_n(eq["closingEquity"])}</td></tr>')
    body += '</tbody></table>'
    if eq["closingByAccount"]:
        body += f'<h3 style="font-size:9.5pt;margin:16px 0 4px">{_e(L("closing_equity"))}</h3>'
        body += (f'<table class="plain"><thead><tr><th>{_e(L("account"))}</th>'
                 f'<th>{_e(L("name"))}</th><th style="text-align:right">{_e(L("amount"))}</th></tr></thead><tbody>')
        for c in eq["closingByAccount"]:
            body += (f'<tr><td>{_e(c["code"])}</td>'
                     f'<td>{_e(_nm(c["code"], c["name"]))}</td>'
                     f'<td class="num">{_n(c["amount"])}</td></tr>')
        body += '</tbody></table>'
    body += (f'<div class="check {"ok" if eq["balanced"] else "bad"}">'
             f'{_e(L("balanced") if eq["balanced"] else L("unbalanced"))}</div>')
    body += _foot()
    return _wrap(body)


def statement_of_cash_flows(fs):
    """现金流量表（间接法）：期初 → 净利 → 调整 → 经营 → 投资 → 融资 → 期末。"""
    cf = fs["statementOfCashFlows"]
    ent = fs["entity"]
    body = _head(ent, L("statement_of_cash_flows"), L("for_period").format(date=fs["periodEnd"]))
    body += (f'<table class="stmt"><thead><tr><th class="lbl">{_e(L("item"))}</th>'
             f'<th>{_e(L("amount"))}</th></tr></thead><tbody>')
    body += (f'<tr><td class="lbl">{_e(L("opening_cash"))}</td>'
             f'<td class="num">{_n(cf.get("openingCash", 0))}</td></tr>')
    if abs(float(cf.get("openingEntryCash", 0))) >= 0.005:
        body += (f'<tr><td class="lbl">{_e(L("opening_entry_cash"))}</td>'
                 f'<td class="num">{_n(cf.get("openingEntryCash", 0))}</td></tr>')

    body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("operating"))}</td></tr>'
    body += (f'<tr class="indent"><td class="lbl">{_e(L("profit_for_period"))}</td>'
             f'<td class="num">{_n(cf.get("netProfit", 0))}</td></tr>')
    for x in cf.get("nonCash") or []:
        text = cell(_CTX["lang"], f'非现金调整：{x.get("account") or ""}')
        body += (f'<tr class="indent"><td class="lbl">{_e(text)}</td>'
                 f'<td class="num">{_n(x.get("amount", 0))}</td></tr>')
    for x in cf.get("workingCapital") or []:
        text = cell(_CTX["lang"], f'营运资金变动：{x.get("label") or ""}')
        body += (f'<tr class="indent"><td class="lbl">{_e(text)}</td>'
                 f'<td class="num">{_n(x.get("amount", 0))}</td></tr>')
    body += (f'<tr class="sub"><td class="lbl">{_e(L("operating_cash_flow"))}</td>'
             f'<td class="num">{_n(cf.get("operating", 0))}</td></tr>')

    for key, section, line in (("investing", "investing", "investing_cash_flow"),
                               ("financing", "financing", "financing_cash_flow")):
        body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L(section))}</td></tr>'
        body += (f'<tr class="indent"><td class="lbl">{_e(L(line))}</td>'
                 f'<td class="num">{_n(cf.get(key, 0))}</td></tr>')

    body += (f'<tr class="sub"><td class="lbl">{_e(L("net_change"))}</td>'
             f'<td class="num">{_n(cf["netChange"])}</td></tr>')
    body += (f'<tr class="grand"><td class="lbl">{_e(L("closing_cash"))}</td>'
             f'<td class="num">{_n(cf["closingCash"])}</td></tr>')
    body += '</tbody></table>'
    body += f'<div class="check ok">{_e(_note(cf.get("note")))}</div>'
    body += _foot()
    return _wrap(body)


def account_type_summary_pdf(data, entity, period):
    """账户类型摘要 PDF：按科目类型列借贷。"""
    body = _head(entity, L("account_type_summary"), period)
    body += (f'<table class="stmt"><thead><tr><th class="lbl">{_e(L("account_type"))}</th>'
             f'<th>{_e(L("debit"))}</th><th>{_e(L("credit"))}</th></tr></thead><tbody>')
    for g in data.get("groups") or []:
        body += f'<tr class="section"><td class="lbl" colspan="3">{_e(cell(_CTX["lang"], g["label"]))}</td></tr>'
        for it in g["items"]:
            body += (f'<tr class="indent"><td class="lbl">{_e(cell(_CTX["lang"], it["type"]))}</td>'
                     f'<td class="num">{_n(it["debit"])}</td>'
                     f'<td class="num">{_n(it["credit"])}</td></tr>')
    body += (f'<tr class="grand"><td class="lbl">{_e(L("total"))}</td>'
             f'<td class="num">{_n(data.get("debit", 0))}</td>'
             f'<td class="num">{_n(data.get("credit", 0))}</td></tr>')
    body += '</tbody></table>'
    body += _foot()
    return _wrap(body)


# ---------------------------------------------------------------- 详细总分类账
_GL_MONTHS = {
    "zh_hk": ["一月", "二月", "三月", "四月", "五月", "六月",
              "七月", "八月", "九月", "十月", "十一月", "十二月"],
    "zh_cn": ["一月", "二月", "三月", "四月", "五月", "六月",
              "七月", "八月", "九月", "十月", "十一月", "十二月"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

_GL_TEXT = {
    "zh_hk": {
        "basis": "基礎：獲利", "from_to": "從 {start} 到 {end}",
        "date": "日期", "account": "帳戶", "details": "交易明細", "type": "交易類型",
        "no": "憑證號", "ref": "參考號#", "debit": "借貸", "credit": "貸項", "amount": "金額",
        "opening": "在 {date} 期初餘額 {cur}{amt}", "opening_nd": "期初餘額 {cur}{amt}",
        "closing": "在 {date} 終期餘額 {cur}{amt}", "closing_nd": "終期餘額 {cur}{amt}",
        "note": "**金額以您的基礎貨幣顯示 {cur}",
    },
    "zh_cn": {
        "basis": "基础：获利", "from_to": "从 {start} 到 {end}",
        "date": "日期", "account": "账户", "details": "交易明细", "type": "交易类型",
        "no": "凭证号", "ref": "参考号#", "debit": "借贷", "credit": "贷项", "amount": "金额",
        "opening": "在 {date} 期初余额 {cur}{amt}", "opening_nd": "期初余额 {cur}{amt}",
        "closing": "在 {date} 终期余额 {cur}{amt}", "closing_nd": "终期余额 {cur}{amt}",
        "note": "**金额以您的基础货币显示 {cur}",
    },
    "en": {
        "basis": "Basis: Accrual", "from_to": "From {start} to {end}",
        "date": "Date", "account": "Account", "details": "Transaction detail", "type": "Type",
        "no": "Voucher No.", "ref": "Ref no.", "debit": "Debit", "credit": "Credit", "amount": "Balance",
        "opening": "Opening balance at {date} {cur}{amt}", "opening_nd": "Opening balance {cur}{amt}",
        "closing": "Closing balance at {date} {cur}{amt}", "closing_nd": "Closing balance {cur}{amt}",
        "note": "** Amounts are shown in your base currency {cur}",
    },
}

_GL_TYPES = {
    "zh_hk": {"manual": "日記帳", "journal": "日記帳", "invoice": "發票", "bill": "帳單",
              "expense": "支出", "payment": "付款", "payment_received": "收款",
              "payment_made": "付款", "settlement": "結算", "fx_reval": "匯兌重估",
              "opening": "期初", "adjustment": "調整", "reversal": "沖銷",
              "bank_line": "銀行交易", "contract_revenue": "合約收入"},
    "zh_cn": {"manual": "日记帐", "journal": "日记帐", "invoice": "发票", "bill": "账单",
              "expense": "支出", "payment": "付款", "payment_received": "收款",
              "payment_made": "付款", "settlement": "结算", "fx_reval": "汇兑重估",
              "opening": "期初", "adjustment": "调整", "reversal": "冲销",
              "bank_line": "银行交易", "contract_revenue": "合同收入"},
    "en": {"manual": "Journal", "journal": "Journal", "invoice": "Invoice", "bill": "Bill",
           "expense": "Expense", "payment": "Payment", "payment_received": "Receipt",
           "payment_made": "Payment", "settlement": "Settlement", "fx_reval": "FX Reval.",
           "opening": "Opening", "adjustment": "Adjustment", "reversal": "Reversal",
           "bank_line": "Bank Line", "contract_revenue": "Contract Rev."},
}


def _gl_date(value, lang):
    """日期统一用数字格式（2025-04-18），不显示中文月份。"""
    s = str(value or "").strip()
    return s[:10] if len(s) >= 10 else s


def _gl_amt(v):
    try:
        return f"{abs(float(v)):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _gl_bal(v):
    """余额列：正数 Dr、负数 Cr（与 QuickBooks 总账一致）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = 0.0
    return _gl_amt(f) + (" Dr" if f >= 0 else " Cr")


def _gl_txno(entry_no):
    """凭证号：保留系统单据号原样（J0001），与系统内可追溯。"""
    return str(entry_no or "").strip()


def general_ledger_detail_pdf(data, entity, start=None, end=None):
    """详细的总分类账 PDF（QuickBooks 版式）。

    表头：日期 / 账户 / 交易明细 / 交易类型 / 凭证号 / 借贷 / 贷项 / 金额；
    每个科目自带 期初余额 → 逐笔 → 终期余额，账户名逐行重复，余额带 Dr/Cr。
    """
    lang = _CTX["lang"] if _CTX["lang"] in _GL_TEXT else "zh_hk"
    T, TYPES = _GL_TEXT[lang], _GL_TYPES[lang]
    cur = entity.get("functionalCurrency") or entity.get("functional_currency") or "HKD"
    sub = T["from_to"].format(start=_gl_date(start, lang), end=_gl_date(end, lang)) if (start and end) else ""
    body = f"""
<div class="gl-head">
  <div class="gl-title">{_e(L("general_ledger_detail"))}</div>
  <div class="gl-basis">{_e(T["basis"])}</div>
  {f'<div class="gl-period">{_e(sub)}</div>' if sub else ''}
</div>
<table class="gl"><thead><tr>
  <th style="width:22mm">{_e(T["date"])}</th>
  <th style="width:36mm">{_e(T["account"])}</th>
  <th>{_e(T["details"])}</th>
  <th style="width:13mm">{_e(T["type"])}</th>
  <th style="width:17mm">{_e(T["no"])}</th>
  <th style="width:20mm" class="num">{_e(T["debit"])}</th>
  <th style="width:20mm" class="num">{_e(T["credit"])}</th>
  <th style="width:24mm" class="num">{_e(T["amount"])}</th>
</tr></thead><tbody>"""
    for acc in data.get("accounts") or []:
        name = acc.get("accountName") or acc.get("accountCode") or ""
        body += f'<tr class="acct"><td colspan="8">{_e(name)}</td></tr>'
        if start:
            body += (f'<tr class="ob"><td colspan="8">'
                     f'{_e(T["opening"].format(date=_gl_date(start, lang), cur=cur, amt=_gl_amt(acc.get("opening"))))}'
                     f'</td></tr>')
        else:
            body += (f'<tr class="ob"><td colspan="8">'
                     f'{_e(T["opening_nd"].format(cur=cur, amt=_gl_amt(acc.get("opening"))))}</td></tr>')
        for ln in acc.get("lines") or []:
            body += ('<tr>'
                     f'<td class="d">{_e(_gl_date(ln.get("date"), lang))}</td>'
                     f'<td>{_e(name)}</td>'
                     f'<td>{_e(cell(lang, str(ln.get("description") or "")))}</td>'
                     f'<td>{_e(TYPES.get(ln.get("sourceType"), TYPES["manual"]))}</td>'
                     f'<td>{_e(_gl_txno(ln.get("entryNo")))}</td>'
                     f'<td class="num">{_gl_amt(ln.get("debit")) if ln.get("debit") else ""}</td>'
                     f'<td class="num">{_gl_amt(ln.get("credit")) if ln.get("credit") else ""}</td>'
                     f'<td class="num">{_e(_gl_bal(ln.get("balance")))}</td>'
                     '</tr>')
        if end:
            body += (f'<tr class="cb"><td colspan="8">'
                     f'{_e(T["closing"].format(date=_gl_date(end, lang), cur=cur, amt=_gl_amt(acc.get("closing"))))}'
                     f'</td></tr>')
        else:
            body += (f'<tr class="cb"><td colspan="8">'
                     f'{_e(T["closing_nd"].format(cur=cur, amt=_gl_amt(acc.get("closing"))))}</td></tr>')
    body += '</tbody></table>'
    if data.get("accounts"):
        body += f'<div class="gl-note">{_e(T["note"].format(cur=cur))}</div>'
    body += _foot()
    # A4 竖向：8 列按固定列宽排开，余下宽度给交易明细
    extra = ('@page { size: A4 portrait; margin: 14mm 9mm 18mm; }'
             '@page :first { margin-top: 12mm; }'
             'table.gl { table-layout: fixed; }'
             'table.gl th { font-size: 7.6pt; }'
             'table.gl td { font-size: 8pt; padding-left: 4px; padding-right: 4px; }')
    return _wrap(body, entity, extra)


def notes_page(fs):
    n = fs["notes"]
    ent = fs["entity"]
    body = _head(ent, L("notes"), L("for_period").format(date=fs["periodEnd"]))
    body += '<div class="notes">'
    body += f'<h3>1. {_e(L("basis_of_preparation"))}</h3><ul>'
    for b in n["basis"]:
        body += f'<li>{_e(_tr(b))}</li>'
    body += '</ul>'
    body += f'<h3>2. {_e(L("significant_policies"))}</h3><ul>'
    for p_ in n["policies"]:
        body += f'<li>{_e(_tr(p_))}</li>'
    body += '</ul>'
    rp = n.get("relatedParties") or []
    if rp:
        body += f'<h3>3. {_e(L("related_party_title"))}</h3>'
        body += (f'<div style="font-size:8.4pt;line-height:1.7;color:#333">'
                 f'{_e(L("related_party_note"))}</div>')
        body += (f'<table><thead><tr><th>{_e(L("account"))}</th><th>{_e(L("nature"))}</th>'
                 f'<th style="text-align:right">{_e(L("balance_hkd"))}</th>'
                 '</tr></thead><tbody>')
        for x in rp:
            kind = L("liability") if x["category"] == "liability" else (L("equity") if x["category"] == "equity" else L("asset"))
            body += (f'<tr><td>{_e(x["accountCode"])}</td>'
                     f'<td>{kind} · {_e(cell(_CTX["lang"], str(x["description"]))[:40])}</td>'
                     f'<td class="num">{_n(abs(x["balance"]))}</td></tr>')
        body += '</tbody></table>'

    if n.get("fxRates"):
        body += f'<h3>4. {_e(L("currency"))}</h3>'
        body += (f'<table><thead><tr><th>{_e(L("date"))}</th><th>{_e(L("currency"))}</th>'
                 f'<th style="text-align:right">{_e(L("amount"))}</th></tr></thead><tbody>')
        for r in n["fxRates"][:40]:
            body += (f'<tr><td>{_e(r["date"])}</td><td>{_e(r["pair"])}</td>'
                     f'<td class="num">{r["rate"]:.4f}</td></tr>')
        body += '</tbody></table>'
    body += '</div>'
    body += _foot()
    return _wrap(body)



def full_package(fs, extra_pages=None):
    """完整报表包：封面 + 四张主表 +（总账、试算表）+ 附注。"""
    ent = fs["entity"]
    cover = _head(ent, L("financial_statements"),
                  L("period_range").format(start=fs['periodStart'], end=fs['periodEnd']))
    cover += ('<div style="margin-top:20px;text-align:center">'
              '<div style="margin-top:36px;text-align:left;max-width:340px;margin-left:auto;margin-right:auto;'
              'font-size:9pt;color:#333333;line-height:2">'
              f'1. {L("statement_of_financial_position")}<br>2. {L("statement_of_profit_or_loss")}<br>'
              f'3. {L("statement_of_changes_in_equity")}<br>'
              f'4. {L("statement_of_cash_flows")}<br>5. {L("notes")}</div></div>')
    cover += ('<div class="check ok" style="margin-top:46px">'
              f'{_e(L("cross_check"))} '
              f'{_e(L("total_assets"))} {_n(fs["statementOfFinancialPosition"]["assetsTotal"])} = '
              f'{_e(L("equity_liabilities"))} {_n(fs["statementOfFinancialPosition"]["liabilitiesTotal"] + fs["statementOfFinancialPosition"]["equity"]["total"])}; '
              f'{_e(L("profit_for_period"))} {_n(fs["statementOfProfitOrLoss"]["netProfit"])}; '
              f'{_e(L("closing_equity"))} {_n(fs["statementOfChangesInEquity"]["closingEquity"])}</div>')
    cover += _foot()

    pages = [
        statement_of_financial_position(fs, fs["periodEnd"]),
        statement_of_profit_or_loss(fs),
        statement_of_changes_in_equity(fs),
        statement_of_cash_flows(fs),
    ]
    # 总账与试算表默认并入报表包：审计要能一路追到明细
    pages += list(extra_pages or [])
    pages.append(notes_page(fs))

    # 各分页由 _wrap 包过，取 body 内容再拼；封面是裸片段，直接用
    joined = ""
    for p in pages:
        inner = p.split("<body>", 1)[1].rsplit("</body>", 1)[0]
        joined += f'<div class="page-break">{inner}</div>'
    return _wrap(cover + joined)


# ---------------------------------------------------------------- 管理报表
def generic_report(title, subtitle, columns, rows, footer_note="", entity=None):
    """任意管理报表 → PDF。columns = [{'label','num'}]"""
    ent = entity or {}
    subtitle = str(subtitle or "").replace(
        "　·　上年 ", "　·　" + column(_CTX["lang"], "上年") + " ")
    co_name = _e(ent.get("entity_name") or ent.get("name") or "")
    co_addr = _e(_addr({
        "addressLine1": ent.get("address_line1") or ent.get("addressLine1"),
        "addressLine2": ent.get("address_line2") or ent.get("addressLine2"),
        "district": ent.get("district"), "region": ent.get("region"),
    }))
    body = f"""
<div class="doc-head">
  <div class="stmt-title"><h1>{_e(title)}</h1>
    <div class="period">{_e(subtitle)}</div></div>
</div>
<div class="curr-note">{_e(_currency_note(ent))}</div>
<table class="plain"><thead><tr>
{''.join(f'<th style="text-align:{"right" if c.get("num") else "left"}">{_e(column(_CTX["lang"], c["label"]))}</th>' for c in columns)}
</tr></thead><tbody>
"""
    if not rows:
        body += f'<tr><td colspan="{len(columns)}" style="text-align:center;color:#666666;padding:30px">{_e(L("no_data"))}</td></tr>'
    for r in rows:
        cells = ""
        for i, c in enumerate(columns):
            v = r[i] if i < len(r) else ""
            cls = ' class="num"' if c.get("num") else ""
            if not c.get("num"):
                try:
                    from .i18n import cell as _cell
                    v = _cell(_CTX["lang"], v)
                except Exception:
                    pass
            cells += f'<td{cls}>{_e(v)}</td>'
        body += f"<tr>{cells}</tr>"
    body += "</tbody></table>"
    if footer_note:
        # 脚注由后端固定产出中文，按当前语言输出；未收录的原文保留
        from .i18n import cell as _cell
        body += f'<div class="notes"><p>{_e(_cell(_CTX["lang"], _note(footer_note)))}</p></div>'
    body += _foot()
    return _wrap(body)


def render(html_text, out_name):
    from weasyprint import HTML
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(STORAGE_DIR) / out_name
    HTML(string=html_text).write_pdf(str(path))
    return path


def profits_tax_pdf(entity, r):
    """利得税计算表 PDF（按 BIR51 结构）。"""
    ent = {"name": entity.get("entity_name"), "code": entity.get("entity_code"),
           "addressLine1": entity.get("address_line1"),
           "addressLine2": entity.get("address_line2"),
           "district": entity.get("district"), "region": entity.get("region"),
           "framework": entity.get("reporting_framework")}
    body = _head(ent, L("profits_tax_title"),
                 L("tax_year_period").format(year=r['yearOfAssessment'], period=r['period']), cur_note=False)
    body += f'<div class="curr-note">{_e(L("tax_currency_note"))}</div>'
    body += (f'<table class="stmt"><thead><tr><th class="lbl">{_e(L("item"))}</th>'
             f'<th>{_e(L("amount"))}</th></tr></thead><tbody>')

    body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("accounting_profit"))}</td></tr>'
    body += (f'<tr><td class="lbl">{_e(L("profit_before_tax_accounting"))}</td>'
             f'<td class="num">{_n(r["accountingProfit"])}</td></tr>')

    body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("add_nondeductible"))}</td></tr>'
    if r["addBacks"]:
        for x in r["addBacks"]:
            note = f' <span style="color:#666666;font-size:7.5pt">（{_e(x.get("basis_note") or "")}）</span>' if x.get("basis_note") else ""
            body += (f'<tr class="indent"><td class="lbl">{_e(x["item_name"])}{note}</td>'
                     f'<td class="num">{_n(x["amount"])}</td></tr>')
    else:
        body += f'<tr class="indent"><td class="lbl" style="color:#666666">{_e(L("no_adjustments"))}</td><td class="num">—</td></tr>'
    body += f'<tr class="sub"><td class="lbl">{_e(L("total_add_back"))}</td><td class="num">{_n(r["totalAddBack"])}</td></tr>'

    body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("less_nontaxable"))}</td></tr>'
    if r["deducts"]:
        for x in r["deducts"]:
            body += (f'<tr class="indent"><td class="lbl">{_e(x["item_name"])}</td>'
                     f'<td class="num">({_n(x["amount"])})</td></tr>')
    else:
        body += f'<tr class="indent"><td class="lbl" style="color:#666666">{_e(L("no_adjustments"))}</td><td class="num">—</td></tr>'
    body += f'<tr class="sub"><td class="lbl">{_e(L("total_deduct"))}</td><td class="num">({_n(r["totalDeduct"])})</td></tr>'

    body += (f'<tr class="sub"><td class="lbl">{_e(L("adjusted_assessable"))}</td>'
             f'<td class="num">{_n(r["adjustedAssessable"])}</td></tr>')

    body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("less_capital_allowances"))}</td></tr>'
    if r["capitalAllowances"]:
        for x in r["capitalAllowances"]:
            body += (f'<tr class="indent"><td class="lbl">{_e(x["item_name"])}</td>'
                     f'<td class="num">({_n(x["amount"])})</td></tr>')
    else:
        body += f'<tr class="indent"><td class="lbl" style="color:#666666">{_e(L("none_paren"))}</td><td class="num">—</td></tr>'
    body += (f'<tr class="sub"><td class="lbl">{_e(L("total_deduct"))}</td>'
             f'<td class="num">({_n(r["totalCapitalAllowance"])})</td></tr>')
    body += (f'<tr class="grand"><td class="lbl">{_e(L("assessable_profit"))}</td>'
             f'<td class="num">{_n(r["assessableProfit"])}</td></tr>')

    if r["computed"]:
        body += f'<tr class="section"><td class="lbl" colspan="2">{_e(L("profits_tax_payable"))}</td></tr>'
        body += (f'<tr class="indent"><td class="lbl">{_e(L("tier1_profit").format(cap=_n(r["tier1Cap"]), rate=f"{r['tier1Rate']*100:.4g}"))}</td>'
                 f'<td class="num">{_n(r["tier1Profit"])}</td></tr>')
        body += (f'<tr class="indent"><td class="lbl">{_e(L("tier2_profit").format(rate=f"{r['tier2Rate']*100:.4g}"))}</td>'
                 f'<td class="num">{_n(r["tier2Profit"])}</td></tr>')
        body += (f'<tr class="sub"><td class="lbl">{_e(L("profits_tax_payable"))}</td>'
                 f'<td class="num">{_n(r["taxPayable"])}</td></tr>')
        if r["provisionalTaxPaid"]:
            body += (f'<tr class="indent"><td class="lbl">{_e(L("less_provisional"))}</td>'
                     f'<td class="num">({_n(r["provisionalTaxPaid"])})</td></tr>')
            body += (f'<tr class="grand"><td class="lbl">{_e(L("balance_payable"))}</td>'
                     f'<td class="num">{_n(r["balancePayable"])}</td></tr>')
    body += '</tbody></table>'

    status = r["twoTierStatus"]
    label = {"nominated": L("two_tier_nominated_status"),
             "not_nominated": L("two_tier_not_nominated_status"),
             "undetermined": L("two_tier_undetermined")}.get(status, status)
    cls = "ok" if r["computed"] else "bad"
    body += f'<div class="check {cls}">{_e(L("two_tier_eligibility").format(label=label))}{_e(_note(r.get("note")))}</div>'
    if not r["computed"]:
        body += f'<div class="check bad">{_e(_note(r.get("reason")))}</div>'
    body += _foot()
    return _wrap(body)

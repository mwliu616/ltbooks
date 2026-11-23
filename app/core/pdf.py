# LtBooks — core/pdf.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""PDF 生成：发票/账单正式打印件。用 WeasyPrint 渲染 HTML，中文字体用 Noto CJK。"""
import html
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path

from config import STORAGE_DIR, WEB_ASSETS_DIR

BASE_CSS = """
@page {
  size: A4; margin: 16mm 14mm;
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888; padding-bottom: 4mm;
    vertical-align: bottom;
  }
}
/* 底部预留 56mm 给收款信息 + 公司页脚，页脚固定贴在纸张底边上方 10mm。 */
@page invpage {
  size: A4; margin: 16mm 14mm 56mm 14mm;
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
    font-size: 6.6pt; color: #999; padding-bottom: 10mm;
    vertical-align: bottom;
  }
}
body.invpage { page: invpage; }
* { box-sizing: border-box; }
body { display:flex; flex-direction:column; min-height:250mm; font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
       font-size: 10.5pt; color: #222; margin: 0; }
/* 三列：左公司资料 · 中标题（1fr / auto / 1fr 时中列正好在页心）· 右留白配平 */
.head { display: block; border-bottom: 1.5px solid #000; padding-bottom: 9px; margin-bottom: 16px; }
/* 标题：整行居中（宽度占满，text-align 才真的在页心） */
.head .doc-title { display: block; width: 100%; text-align: center; }
.head .doc-title h1 { text-align: center; }
/* 单号与状态：靠右，排在标题下一行 */
.head .doc-meta-right { display: flex; justify-content: flex-end; align-items: center;
                        gap: 3mm; margin-top: 1.5mm; }
.head .doc-meta-right .dno { font-size: 10pt; color: #444; }
/* 公司信息放页脚 */
.doc-foot { margin-top: 8mm; padding-top: 2.2mm; border-top: .6px solid #000;
            font-size: 6.6pt; color: #444; line-height: 1.45; }
.doc-foot .df-name { font-size: 8pt; color: #000; font-weight: 700; letter-spacing: .01em; }
.doc-foot .df-line { white-space: nowrap; }
.doc-foot .df-note { color: #888; margin-top: .6mm; }
.brandrow { display: flex; align-items: flex-start; gap: 2.4mm; margin-bottom: 1.5mm; }
/* 抬头三行（公司名 / 地址 / 编码）：总高 13mm，Logo 与这个高度一致 */
.hdr-txt { display: block; min-width: 0; }
.hdr-txt .brand { font-size: 12pt; font-weight: 700; color: #000;
                  line-height: 1.1; letter-spacing: .01em; }
.hdr-txt .brand { display: block; white-space: nowrap; }
.hdr-txt .sub { display: block; white-space: nowrap; }   /* 地址一行打印，避免与下一行挤在一起 */
.hdr-txt .sub { font-size: 6.6pt; color: #666; line-height: 1.25; margin-top: 0;
                  letter-spacing: -.002em; }
.logo { height: 10.5mm; width: auto; max-width: 22mm; object-fit: contain; flex: 0 0 auto;
        align-self: flex-start; }   /* 与抬头三行文字等高 */
.brandsub { font-size: 7pt; color: #666; letter-spacing: .1em; }
.doc-title { text-align: center; }
.doc-title h1 { margin: 0; font-size: 13pt; letter-spacing: 1px; text-align: center; }
/* 抬头联系方式：一行三项，字号与地址一致 */
.hdr-txt .contact { display: block; white-space: nowrap; font-size: 6.6pt; color: #444;
                    line-height: 1.3; letter-spacing: 0; margin-top: .4mm; }
.hdr-txt .contact b { font-weight: 400; color: #888; }
.meta { display: flex; gap: 24px; margin-bottom: 16px; }
.meta .col { flex: 1; }
.meta .label { font-size: 8pt; color: #888; text-transform: uppercase; letter-spacing: .5px; }
.meta .value { font-size: 10.5pt; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; margin-top: 6px; }
th { background: #F2F2F2; font-size: 8.5pt; color: #555; text-align: left;
     padding: 6px 8px; border-bottom: 1px solid #DDE3EA; }
td { padding: 6px 8px; border-bottom: 1px solid #EEF1F4; font-size: 9.5pt; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.totals { width: 46%; margin-left: auto; margin-top: 10px; }
.totals td { border: none; padding: 4px 8px; }
.totals .grand td { border-top: 1.5px solid #333; font-weight: 700; font-size: 11pt; padding-top: 7px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 9px; font-size: 8pt;
         border: 1px solid; }
.badge.draft { color: #333; border-color: #999; background: #F2F2F2; }
.badge.posted { color: #000; border-color: #000; background: #EDEDED; }
/* 固定在纸张底边上方 10mm（bottom 的参照是页面内容区，负值抵消下边距）。 */
.bottombar { position: fixed; left: 0; right: 0; bottom: -46mm; }
.paybox { padding-top:8px; border-top:1px solid #DDE3EA; }
.ptitle { font-size:7pt; font-weight:700; color:#000; letter-spacing:.06em;
          text-transform:uppercase; margin-bottom:3px; }
.paytable { width:100%; border-collapse:collapse; }
.paytable td { border:none; padding:1px 0; font-size:7pt; line-height:1.35; vertical-align:top; }
.paytable td.pk { color:#555; width:74px; padding-right:8px; white-space:nowrap; }
.paytable td.pv { color:#000; font-weight:600; }
.paytable td.gap { width:14px; }
.foot { margin-top: 6px; padding-top: 6px; border-top: 1px solid #DDE3EA;
        font-size: 8pt; color: #777; line-height: 1.6; }
.wm { position: fixed; top: 42%; left: 8%; font-size: 62pt; color: rgba(0,0,0,0.055);
      transform: rotate(-24deg); font-weight: 400; letter-spacing: 8px; }
.wm-void { color: rgba(0,0,0,0.075); letter-spacing: 6px; }
"""


# ---------------------------------------------------------------- 本地化
_LANG_DICT = None


def _lang_dict(lang):
    global _LANG_DICT
    if _LANG_DICT is None:
        import json
        from pathlib import Path
        f = Path(__file__).with_name("lang_dict.json")
        _LANG_DICT = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    return _LANG_DICT.get(lang, {})


def localize(html, lang="en"):
    """单据 PDF 的三语化：只替换文本节点，保护 script/style。"""
    if lang == "zh_cn":
        return html
    import re
    d = _lang_dict(lang)
    if not d:
        return html
    stash = []

    def prot(m):
        stash.append(m.group(0))
        return f"\x01B{len(stash)-1}\x01"

    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", prot, html, flags=re.S | re.I)

    def rep(m):
        raw, txt = m.group(1), m.group(1).strip()
        if not txt or not re.search(r"[\u4e00-\u9fff]", txt):
            return m.group(0)
        key = re.sub(r"\s+", " ", txt)
        v = d.get(key) or d.get(txt)
        if v:
            return ">" + v + "<"
        # 动态拼接：LEDU-HK · 功能货币 HKD
        mm = re.match(r"^(LEDU-HK)\s+·\s+功能货币\s+(\w+)$", key)
        if mm:
            label = "功能貨幣" if lang == "zh_hk" else "Functional Currency"
            return ">" + f"LEDU-HK · {label} {mm.group(2)}" + "<"
        # 动态拼接：生成时间 … · 会计记录按规保存不少于 7 年。
        mm = re.match(r"^生成时间\s+(.+?)\s+·\s+会计记录按规保存不少于 7 年。$", key)
        if mm:
            return ">" + f"Generated at {mm.group(1)} · Accounting records are retained for at least 7 years." + "<"
        # 动态拼接：生成时间 <时间>（页脚现在只有这一项）
        mm = re.match(r"^生成时间\s+(\d{4}-\d{2}-\d{2}.*)$", key)
        if mm:
            label = "生成時間" if lang == "zh_hk" else "Generated at"
            return ">" + f"{label} {mm.group(1)}" + "<"
        # 动态拼接：本文件由 … 生成 · <时间>
        mm = re.match(r"^本文件由\s+(.+?)\s+生成\s+·\s+(\d{4}-\d{2}-\d{2}.*)$", key)
        if mm:
            return ">" + f"Generated by {mm.group(1)} · {mm.group(2)}" + "<"
        # 版权行：保留前缀，只翻译「·」之后的许可说明
        if key.startswith("©"):
            parts = key.split(" · ", 1)
            if len(parts) == 2:
                tail = d.get(parts[1]) or d.get(parts[1].strip())
                if tail:
                    return ">" + parts[0] + " · " + tail + "<"
            return m.group(0)
        return m.group(0)

    html = re.sub(r">([^<>]+)<", rep, html)
    for i, blk in enumerate(stash):
        html = html.replace(f"\x01B{i}\x01", blk)
    return html


def _e(v):
    return html.escape("" if v is None else str(v))


# 单据明细里的标准业务描述。用户可以自由填写，因此不能做整句翻译；
# 只对系统示例/标准明细中的固定业务词组做替换，单号、数量与自填部分保持原样。
_DOC_PHRASES = {
    "顾问服务": ("顧問服務", "Consulting services"),
    "系统维护服务": ("系統維護服務", "System maintenance services"),
    "云端订阅服务": ("雲端訂閱服務", "Cloud subscription services"),
    "设备销售": ("設備銷售", "Equipment sales"),
    "技术支援服务": ("技術支援服務", "Technical support services"),
    "软件开发服务": ("軟件開發服務", "Software development services"),
    "项目报价": ("項目報價", "Project quotation"),
    "季度租金": ("季度租金", "Quarterly rent"),
    "外判服务": ("外判服務", "Outsourced services"),
    "法律及公司秘书服务": ("法律及公司秘書服務", "Legal and company secretarial services"),
    "办公用品采购": ("辦公用品採購", "Office supplies purchase"),
    "年度办公室保险": ("年度辦公室保險", "Annual office insurance"),
    "设备采购": ("設備採購", "Equipment purchase"),
    "服务调整退款": ("服務調整退款", "Refund for service adjustment"),
}


def _doc_text(value, lang):
    """按 PDF 语言转换标准明细词组，兼容早期以繁体录入的同义词组。"""
    out = "" if value is None else str(value)
    for cn, (hk, en) in _DOC_PHRASES.items():
        target = en if lang == "en" else (hk if lang == "zh_hk" else cn)
        if lang == "zh_cn":
            out = out.replace(hk, cn)
        else:
            out = out.replace(cn, target).replace(hk, target)
    return out


def _address(entity):
    parts = []
    for k in ("address_line1", "address_line2", "district", "region"):
        v = entity.get(k)
        if v:
            parts.append(str(v).strip())
    return ", ".join(parts)


_LOGO_CACHE = None


def _logo_uri():
    """公司 Logo 的 data URI（内嵌，保证 PDF 自带图，不依赖外部路径）。

    用户上传过自定义 Logo 时优先使用；每次调用都检查文件，上传后无需重启。
    """
    global _LOGO_CACHE
    from pathlib import Path
    for cand in (WEB_ASSETS_DIR / "logo-custom-192.png",
                 WEB_ASSETS_DIR / "logo-192.png",
                 WEB_ASSETS_DIR / "logo-custom-64.png",
                 WEB_ASSETS_DIR / "logo-64.png"):
        p_ = Path(cand)
        if p_.is_file():
            import base64
            return "data:image/png;base64," + base64.b64encode(p_.read_bytes()).decode()
    return ""
    for cand in ():
        p = Path(cand)
        if p.is_file():
            import base64
            _LOGO_CACHE = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
            return _LOGO_CACHE
    _LOGO_CACHE = ""
    return _LOGO_CACHE


def _entity_name_pair(entity, lang):
    """按语言返回（主名称, 副名称）。中文语境下主名为中文名、副名为英文注册名。"""
    en = str(entity.get("entity_name") or entity.get("legal_name") or "")
    zh = str(entity.get("legal_name_zh") or "")
    if zh and lang == "zh_hk":
        try:
            from opencc import OpenCC
            zh = OpenCC("s2hk").convert(zh)
        except Exception:
            pass
    if lang in ("zh_cn", "zh_hk") and zh:
        return zh, en
    return en, ""


def _payment_box(bank, lang="en"):
    """收款信息：置于页脚之上的底部区。

    用表格而非 flex 排布 —— flex 在 PDF 渲染引擎里会撑出多余行高，
    表格的行高完全由内容决定，紧凑且对齐稳定。
    """
    if not bank:
        return ""
    LB = _SD_LABELS.get(lang, _SD_LABELS["en"])
    holder = bank.get("account_holder")
    bank_line = " · ".join(x for x in (bank.get("bank_name"), bank.get("bank_code")) if x)
    swift = bank.get("swift_code")
    acct = bank.get("account_number")
    addr = bank.get("bank_address")
    if not any([holder, bank_line, swift, acct, addr]):
        return ""

    def cell_pk(v):
        return f'<td class="pk">{_e(v)}</td>'

    def cell_pv(v):
        return f'<td class="pv">{_e(v)}</td>'

    r1 = ""
    if holder or acct:
        r1 = ("<tr>" + (cell_pk(LB["account_holder"]) + cell_pv(holder) if holder else '<td class="pk"></td><td class="pv"></td>')
              + '<td class="gap"></td>'
              + (cell_pk(LB["account_number"]) + cell_pv(acct) if acct else '<td class="pk"></td><td class="pv"></td>')
              + "</tr>")
    r2 = ""
    if bank_line or swift:
        r2 = ("<tr>" + (cell_pk(LB["bank_name"]) + cell_pv(bank_line) if bank_line else '<td class="pk"></td><td class="pv"></td>')
              + '<td class="gap"></td>'
              + (cell_pk("SWIFT") + cell_pv(swift) if swift else '<td class="pk"></td><td class="pv"></td>')
              + "</tr>")
    r3 = ""
    if addr:
        r3 = f'<tr>{cell_pk(LB["bank_address"])}<td class="pv" colspan="4">{_e(addr)}</td></tr>'

    return ('<div class="paybox"><div class="ptitle">' + _e(LB["payment_account"]) + '</div>'
            f'<table class="paytable">{r1}{r2}{r3}</table></div>')


def _rate(v):
    """汇率显示：外币→功能货币（≥1）两位小数，反向汇率（<1）四位。

    与「汇率」页面的口径一致，避免 PDF 上出现 1.0000000000 这种十位小数。
    """
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    if x == 0:
        return "0.00"
    return f"{x:,.2f}" if abs(x) >= 1 else f"{x:.4f}"


def _money(v, ccy=""):
    try:
        s = f"{float(v):,.2f}"
    except (TypeError, ValueError):
        s = "—"
    return f"{s} {ccy}".strip()


def _decimal(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _real_rate(v):
    rate = _decimal(v)
    return rate if rate is not None and rate > 0 else None


def _functional_gross(original, *parts):
    """仅在折算字段完整且不是非零单据的零值占位时返回含税折算额。"""
    values = [_decimal(v) for v in parts]
    if any(v is None for v in values):
        return None
    total = sum(values, Decimal(0))
    original_value = _decimal(original)
    if original_value is not None and original_value != 0 and total == 0:
        return None
    return total


# 单据水印：草稿未过账、已作废的单据必须有明显标识，避免被误当正式单据使用
_WM_TEXT = {
    "draft": {"zh_cn": "草稿",     "zh_hk": "草稿",     "en": "DRAFT"},
    "void":  {"zh_cn": "已作废",   "zh_hk": "已作廢",   "en": "VOID"},
}



def _qty(v):
    """数量：去掉多余的零，最多保留 4 位小数。"""
    if v is None:
        return "—"
    try:
        d = float(v)
    except (TypeError, ValueError):
        return "—"
    txt = f"{d:.4f}".rstrip("0").rstrip(".")
    return txt or "0"


def _pct(v):
    """税率：显示为百分比，空值给破折号。"""
    if v is None:
        return "—"
    try:
        d = float(v)
    except (TypeError, ValueError):
        return "—"
    txt = f"{d:.4f}".rstrip("0").rstrip(".")
    return f"{txt}%"

def _watermark(status, lang):
    key = "draft" if str(status) == "draft" else ("void" if str(status) == "void" else None)
    if not key:
        return ""
    txt = _WM_TEXT[key].get(lang) or _WM_TEXT[key]["en"]
    return f"<div class='wm wm-{key}'>{txt}</div>"




def _entity_line(entity: dict, lang: str = "en") -> str:
    """抬头第三行：公司代号 · 商业登记号 · 功能货币（有才打印）。"""
    cur_label = {"en": "Functional currency", "zh_hk": "功能貨幣",
                 "zh_cn": "功能货币"}.get(lang, "Functional currency")
    bits = []
    code = str(entity.get("entity_code") or "").strip()
    if code:
        bits.append(code)
    br = str(entity.get("br_number") or "").strip()
    if br:
        bits.append("BR " + br)
    cur = str(entity.get("functional_currency") or "").strip()
    if cur:
        bits.append(f"{cur_label} {cur}")
    return " · ".join(bits)


def _doc_word(kind: str, lang: str = "en") -> str:
    """单据标题：英文大写，中文按语言给出正确写法。"""
    words = {
        "invoice": ("INVOICE", "發 票", "发 票"),
        "bill":    ("BILL", "賬 單", "账 单"),
        "quote":   ("QUOTATION", "報 價 單", "报 价 单"),
        "credit":  ("CREDIT NOTE", "貸 記 單", "贷 记 单"),
        "order_sales":    ("SALES ORDER", "銷 售 訂 單", "销 售 订 单"),
        "order_purchase": ("PURCHASE ORDER", "採 購 訂 單", "采 购 订 单"),
    }
    en, hk, cn = words.get(kind, (kind.upper(), kind.upper(), kind.upper()))
    return en if lang == "en" else (hk if lang == "zh_hk" else cn)



def _legal_name(entity: dict, lang: str = "en") -> str:
    """页脚用的法定全名：中文语境优先中文注册名，其余用英文注册名。"""
    if lang in ("zh_hk", "zh_cn"):
        zh = str(entity.get("legal_name_zh") or "").strip()
        if zh:
            return zh
    return str(entity.get("legal_name") or entity.get("entity_name") or "").strip()


def _br_line(entity: dict) -> str:
    br = str(entity.get("br_number") or "").strip()
    return f"BR {br}" if br else ""

def _gen_note(lang: str = "en") -> str:
    """页脚的那句说明：金额由代码计算、校验不等于授权过账。"""
    if lang == "zh_hk":
        return "金額由確定性代碼計算 · 校驗結果不構成過賬授權"
    if lang == "zh_cn":
        return "金额由确定性代码计算 · 校验结果不构成过账授权"
    return "Amounts are computed by deterministic code; validation is not authorisation to post."

def _contact_line(entity: dict, lang: str = "en") -> str:
    """抬头里的联系方式：网址 · 邮箱 · 电话，缺哪项就不打印哪项。"""
    labels = {"en": ("Email", "Tel", "Web"), "zh_hk": ("電郵", "電話", "網址"),
              "zh_cn": ("邮箱", "电话", "网址")}.get(lang, ("Email", "Tel", "Web"))
    parts = []
    for key, lab in zip(("email", "phone", "website"), labels):
        val = str(entity.get(key) or "").strip()
        if val:
            parts.append(f'<b>{lab}</b> {_e(val)}')
    return " · ".join(parts)

def invoice_html(inv, entity, files=None, bank=None, lang="en"):
    LB = _SD_LABELS.get(lang, _SD_LABELS["en"])
    status = str(inv.get("status") or "draft")
    badge = "posted" if status == "posted" else "draft"
    _badge_cn = {"posted": "已過賬", "draft": "草稿", "void": "已作廢"}
    _badge_cn_cn = {"posted": "已过账", "draft": "草稿", "void": "已作废"}
    _badge_en = {"posted": "POSTED", "draft": "DRAFT", "void": "VOID"}
    badge_text = (_badge_en if lang == "en"
                  else (_badge_cn if lang == "zh_hk" else _badge_cn_cn)).get(status, status)
    gross = inv.get("gross_original")
    amount = inv.get("amount_original")
    tax = inv.get("tax_original")
    ccy = inv.get("currency") or ""

    # 有明细行就按行打印，没有明细时退回单行汇总，保证老单据仍能出 PDF
    inv_lines = inv.get("lines") or []
    if inv_lines:
        lines_html = "".join(
            f"<tr><td>{_e(_doc_text(ln.get('description') or '', lang))}"
            + (f"<span style='color:#666;font-size:8pt'> · {_e(ln.get('item_code'))}</span>"
               if ln.get("item_code") else "")
            + f"</td>"
            f"<td class='num'>{_qty(ln.get('quantity'))}</td>"
            f"<td class='num'>{_money(ln.get('unit_price'), ccy)}</td>"
            f"<td class='num'>{_money(ln.get('amount'), ccy)}</td>"
            f"<td class='num'>{_pct(ln.get('tax_rate'))}</td>"
            f"<td class='num'>{_money(ln.get('tax_amount'), ccy)}</td></tr>"
            for ln in inv_lines)
    else:
        lines_html = (f"<tr><td>{_e(LB['goods_services'])}</td><td class='num'>—</td>"
                      f"<td class='num'>—</td><td class='num'>{_money(amount, ccy)}</td>"
                      f"<td class='num'>—</td><td class='num'>{_money(tax, ccy)}</td></tr>")

    watermark = _watermark(status, lang)
    files_html = ""
    if files:
        items = "".join(
            f"<tr><td>{_e(f.get('file_name'))}</td><td class='num'>{int(f.get('file_size') or 0):,} B</td>"
            f"<td style='font-family:monospace;font-size:7.5pt'>{_e(str(f.get('sha256_hash'))[:24])}…</td></tr>"
            for f in files[:8])
        files_html = (f"<h4 style='font-size:9pt;margin:18px 0 4px'>{_e(LB['attachments'])}</h4>"
                      f"<table><thead><tr><th>{_e(LB['file'])}</th><th class='num'>{_e(LB['size'])}</th><th>SHA-256</th></tr></thead>"
                      f"<tbody>{items}</tbody></table>")

    functional_ccy = entity.get("functional_currency") or ""
    is_foreign = bool(functional_ccy and ccy != functional_ccy)
    fx_rate = _real_rate(inv.get("fx_rate"))
    gross_functional = _functional_gross(
        gross, inv.get("amount_functional"), inv.get("tax_functional"))
    rate_text = _rate(fx_rate) if fx_rate is not None else "—"
    if fx_rate is not None and inv.get("fx_rate_date"):
        rate_text += f" ({_e(inv.get('fx_rate_date'))})"
    fx_rows = ""
    if is_foreign:
        fx_rows = (
            f'<tr><td style="font-size:9pt;color:#666">{_e(LB["fx"])}</td>'
            f'<td class="num" style="font-size:9pt;color:#666">'
            f'{_money(gross_functional, functional_ccy)}</td></tr>'
            f'<tr><td style="font-size:9pt;color:#666">{_e(LB["rate"])}</td>'
            f'<td class="num" style="font-size:9pt;color:#666">{rate_text}</td></tr>'
        )

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{BASE_CSS}</style></head><body class="invpage">
{watermark}
<div class="head">
  <div class="doc-title"><h1>{_e(_doc_word('invoice', lang))}</h1></div>
  <div class="doc-meta-right">
    <span class="dno">{_e(inv.get('invoice_no'))}</span>
    <span class="badge {badge}">{_e(badge_text)}</span>
  </div>
</div>

<div class="meta">
  <div class="col">
    <div class="label">{_e(LB['customer'])}</div>
    <div class="value">{_e(inv.get('supplier_name'))}</div>
  </div>
  <div class="col">
    <div class="label">{_e(LB['invoice_date'])}</div>
    <div class="value">{_e(inv.get('invoice_date'))}</div>
  </div>
  <div class="col">
    <div class="label">{_e(LB['revenue_date'])}</div>
    <div class="value">{_e(inv.get('revenue_recognition_date'))}</div>
  </div>
  <div class="col">
    <div class="label">{_e(LB['currency'])}</div>
    <div class="value">{_e(ccy)}</div>
  </div>
</div>

<table>
  <thead><tr><th>{_e(LB['item'])}</th><th class="num" style="width:12%">{_e(LB['qty'])}</th>
  <th class="num" style="width:16%">{_e(LB['unit'])}</th><th class="num" style="width:18%">{_e(LB['line_total'])}</th>
  <th class="num" style="width:10%">{_e(LB['tax_rate'])}</th><th class="num" style="width:16%">{_e(LB['tax'])}</th></tr></thead>
  <tbody>{lines_html}</tbody>
</table>

<table class="totals">
  <tr><td>{_e(LB['net'])}</td><td class="num">{_money(amount, ccy)}</td></tr>
  <tr><td>{_e(LB['tax'])}</td><td class="num">{_money(tax, ccy)}</td></tr>
  <tr class="grand"><td>{_e(LB['original_total'] if is_foreign else LB['gross'])}</td><td class="num">{_money(gross, ccy)}</td></tr>
  {fx_rows}
</table>

{files_html}

<div class="bottombar">
  {_payment_box(bank, lang)}
  <div class="doc-foot">
    <div class="df-name">{_e(_legal_name(entity, lang))}</div>
    <div class="df-line">{_e(_br_line(entity))}</div>
    <div class="df-line">{_contact_line(entity, lang)}</div>
    <div class="df-line">{_e(_address(entity))}</div>
    <div class="df-note">{_e(_gen_note(lang))} {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
  </div>
</div>
</body></html>"""


def bill_html(bill, entity, lang="en"):
    LB = _SD_LABELS.get(lang, _SD_LABELS["en"])
    ccy = bill.get("currency") or ""
    watermark = _watermark(bill.get("status"), lang)
    # 明细行：有就逐行打印，没有退回单行汇总
    b_lines = bill.get("lines") or []
    if b_lines:
        bill_rows = "".join(
            f"<tr><td>{_e(_doc_text(ln.get('description') or '', lang))}"
            + (f"<span style='color:#666;font-size:8pt'> · {_e(ln.get('item_code'))}</span>"
               if ln.get("item_code") else "")
            + f"</td>"
            f"<td class='num'>{_qty(ln.get('quantity'))}</td>"
            f"<td class='num'>{_money(ln.get('unit_price'), ccy)}</td>"
            f"<td class='num'>{_money(ln.get('amount'), ccy)}</td>"
            f"<td class='num'>{_pct(ln.get('tax_rate'))}</td>"
            f"<td class='num'>{_money(ln.get('tax_amount'), ccy)}</td></tr>"
            for ln in b_lines)
    else:
        bill_rows = (f"<tr><td>{_e(LB['purchase'])}</td><td class='num'>—</td><td class='num'>—</td>"
                     f"<td class='num'>{_money(bill.get('amount'), ccy)}</td>"
                     f"<td class='num'>—</td>"
                     f"<td class='num'>{_money(bill.get('tax_amount'), ccy)}</td></tr>")
    functional_ccy = entity.get("functional_currency") or ""
    is_foreign = bool(functional_ccy and ccy != functional_ccy)
    fx_rate = _real_rate(bill.get("fx_rate"))
    tax_original = _decimal(bill.get("tax_amount"))
    tax_functional = tax_original * fx_rate if tax_original is not None and fx_rate is not None else None
    gross_functional = _functional_gross(
        bill.get("gross_original"), bill.get("amount_functional"), tax_functional)
    rate_text = _rate(fx_rate) if fx_rate is not None else "—"
    if fx_rate is not None and bill.get("fx_rate_date"):
        rate_text += f" ({_e(bill.get('fx_rate_date'))})"
    fx_rows = ""
    if is_foreign:
        fx_rows = (
            f'<tr><td style="font-size:9pt;color:#666">{_e(LB["fx"])}</td>'
            f'<td class="num" style="font-size:9pt;color:#666">'
            f'{_money(gross_functional, functional_ccy)}</td></tr>'
            f'<tr><td style="font-size:9pt;color:#666">{_e(LB["rate"])}</td>'
            f'<td class="num" style="font-size:9pt;color:#666">{rate_text}</td></tr>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{BASE_CSS}
@page {{ size: A4; margin: 16mm 14mm 38mm 14mm;
  @bottom-right {{ content: counter(page) " / " counter(pages);
    font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888; padding-bottom: 10mm;
    vertical-align: bottom; }} }}
.doc-foot {{ position: fixed; left: 0; right: 0; bottom: -28mm; margin-top: 0; }}
</style></head><body>
{watermark}
<div class="head">
  <div class="doc-title"><h1>{_e(_doc_word('bill', lang))}</h1></div>
  <div class="doc-meta-right"><span class="dno">{_e(bill.get('bill_no'))}</span></div>
</div>

<div class="meta">
  <div class="col"><div class="label">{_e(LB['vendor'])}</div><div class="value">{_e(bill.get('vendor_name'))}</div></div>
  <div class="col"><div class="label">{_e(LB['date'])}</div><div class="value">{_e(bill.get('date'))}</div></div>
  <div class="col"><div class="label">{_e(LB['due_date'])}</div><div class="value">{_e(bill.get('due_date'))}</div></div>
  <div class="col"><div class="label">{_e(LB['currency'])}</div><div class="value">{_e(ccy)}</div></div>
</div>
<table><thead><tr><th>{_e(LB['item'])}</th><th class="num" style="width:12%">{_e(LB['qty'])}</th>
<th class="num" style="width:16%">{_e(LB['unit'])}</th><th class="num" style="width:18%">{_e(LB['line_total'])}</th>
<th class="num" style="width:10%">{_e(LB['tax_rate'])}</th><th class="num" style="width:16%">{_e(LB['tax'])}</th></tr></thead>
<tbody>{bill_rows}</tbody></table>
<table class="totals">
  <tr><td>{_e(LB['net'])}</td><td class="num">{_money(bill.get('amount'), ccy)}</td></tr>
  <tr><td>{_e(LB['tax'])}</td><td class="num">{_money(bill.get('tax_amount'), ccy)}</td></tr>
  <tr class="grand"><td>{_e(LB['original_total'] if is_foreign else LB['total'])}</td><td class="num">{_money(bill.get('gross_original'), ccy)}</td></tr>
  {fx_rows}
</table>
<div class="doc-foot">
  <div class="df-name">{_e(_legal_name(entity, lang))}</div>
  <div class="df-line">{_e(_br_line(entity))}</div>
  <div class="df-line">{_contact_line(entity, lang)}</div>
  <div class="df-line">{_e(_address(entity))}</div>
  <div class="df-note">{_e(_gen_note(lang))} {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
</div>
</body></html>"""


def merge_documents(docs, page_name: str = "invpage") -> str:
    """把多份单据 HTML 拼成一份，一次渲染：字体只子集化一次，几十张单也不会各等一次。

    每份单据的内容包进 .docpage，显式分页；最后一份不分页，免得尾部多一张空白页。
    """
    import re as _re
    bodies = []
    head = ""
    for h in docs:
        if not head:
            head = h.split("<body", 1)[0]
        m = _re.split(r"<body[^>]*>", h, maxsplit=1)
        inner = m[1].rsplit("</body>", 1)[0] if len(m) > 1 else h
        bodies.append(inner)
    extra = (f"@page {page_name} {{ size: A4; margin: 16mm 14mm 56mm 14mm;\n"
             f"  @bottom-right {{ content: counter(page) \" / \" counter(pages);\n"
             f"    font-family: \"Liberation Serif\", \"WenQuanYi Zen Hei\", sans-serif;\n"
             f"    font-size: 6.6pt; color: #999; padding-bottom: 10mm;\n"
             f"    vertical-align: bottom; }} }}\n"
             f".docpage {{ page: {page_name}; break-after: page; display: flex; "
             "flex-direction: column; min-height: 250mm; padding: 0; }\n"
             ".docpage:last-child { break-after: auto; }\n")
    head = head.replace("</head>", f"<style>{extra}</style></head>")
    out = "".join(f'<div class="docpage">{b}</div>' for b in bodies)
    return head + "<body>" + out + "</body></html>"


def render(html_text, out_name, split_css=True):
    """渲染成 PDF。split_css=False 时不再包一层 <style>（调用方自带完整 HTML）。"""
    from weasyprint import HTML
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = Path(STORAGE_DIR) / out_name
    HTML(string=html_text).write_pdf(str(path))
    return path


# ---------------------------------------------------------------- 公司抬头纸

LETTERHEAD_CSS = """
@page {
  size: A4; margin: 0 0 12mm;
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888; padding-bottom: 3mm; padding-right: 20mm;
    vertical-align: bottom;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: "Liberation Sans", "WenQuanYi Zen Hei", sans-serif; color: #000; }

.sheet { width: 210mm; height: 285mm; position: relative;
         padding: 16mm 20mm 2mm; display: flex; flex-direction: column; }

/* 水印：居中淡色 Logo，压在文字之下 */
.wm { position: absolute; left: 0; right: 0; top: 92mm;
      display: flex; justify-content: center; }
.wm img { width: 105mm; height: 105mm; object-fit: contain; opacity: .028; }

/* 抬头：左 Logo + 名称，右联系块 */
.head { display: flex; justify-content: space-between; align-items: flex-start;
        gap: 10mm; position: relative; z-index: 1; }
.brand { display: flex; align-items: center; gap: 4mm; min-width: 0; }
.brand .txt { display: flex; flex-direction: column; justify-content: flex-start;
                line-height: 1.1; }
.brand img { height: 12mm; width: auto; max-width: 24mm; object-fit: contain;
             flex: 0 0 auto; align-self: flex-start; }   /* 与右侧三行文字等高 */
.brand .txt { min-width: 0; }
.brand .co { font-family: 'Liberation Serif', 'Playfair Display', serif;
               font-size: 10pt; font-weight: 600; letter-spacing: .05em;
               line-height: 1.05; white-space: nowrap; }
.brand .co-en { font-family: 'Playfair Display', serif; font-size: 11pt;
                font-weight: 500; letter-spacing: .03em;
                margin-top: .8mm; white-space: nowrap; }
.brand .tag { font-size: 6.6pt; color: #555; letter-spacing: .02em;
              margin-top: .7mm; white-space: nowrap; }
.brand .en { font-size: 6.4pt; color: #555; letter-spacing: .14em;
             text-transform: uppercase; margin-top: .7mm; white-space: nowrap; }

.meta { text-align: right; font-size: 7.8pt; line-height: 1.85; color: #222;
        flex: 0 1 72mm; max-width: 72mm; }
.meta .k { color: #666; margin-right: 1.5mm; }

.rule { border-top: 1.8px solid #000; margin-top: 4mm; position: relative; z-index: 1; }
.foot { position: relative; z-index: 1; border-top: .6px solid #000; padding-top: 2.4mm;
        display: flex; flex-direction: column; align-items: flex-start;
        gap: .9mm; font-size: 6.8pt; color: #333; line-height: 1.4; }
.foot > div { white-space: nowrap; text-align: left; }
/* 网址 / 邮箱 / 电话 排一行，间距一致，靠左对齐 */
.foot-row { display: flex; align-items: baseline; gap: 7mm; flex-wrap: nowrap; }
.foot-row > span { white-space: nowrap; }
.foot .k { color: #666; }
.foot .k { color: #777; margin-right: 1.5mm; }
.body { flex: 1; position: relative; z-index: 1; }
"""


_LH_LABELS = {
    "en":    {"addr": "Address", "email": "Email", "web": "Website", "tel": "Tel"},
    "zh_cn": {"addr": "地址", "email": "邮箱", "web": "网址", "tel": "电话"},
    "zh_hk": {"addr": "地址", "email": "電郵", "web": "網址", "tel": "電話"},
}

# 报价单 / 贷记单 / 订单的固定表头与元信息标签（三语分开写，避免简繁混排）
_SD_LABELS = {
    "en": {
        "item": "Item", "qty": "Qty", "unit": "Unit price", "amount": "Amount",
        "line_total": "Line total", "total": "Total", "gross": "Gross total",
        "original_total": "Total (original currency)", "net": "Net amount",
        "tax": "Tax", "tax_rate": "Tax rate", "currency": "Currency",
        "customer": "Customer", "vendor": "Vendor", "date": "DATE",
        "invoice_date": "Invoice date", "revenue_date": "Revenue recognition date",
        "due_date": "Due date", "goods_services": "Goods/services", "purchase": "Purchase",
        "attachments": "Attachments", "file": "File", "size": "Size",
        "fx": "In functional currency", "rate": "FX rate",
        "payment_account": "Payment account", "account_holder": "Account holder",
        "account_number": "Account number", "bank_name": "Bank", "bank_address": "Bank address",
    },
    "zh_cn": {
        "item": "项目", "qty": "数量", "unit": "单价", "amount": "金额",
        "line_total": "合价", "total": "合计", "gross": "价税合计",
        "original_total": "原币合计", "net": "不含税金额",
        "tax": "税额", "tax_rate": "税率", "currency": "币种",
        "customer": "客户", "vendor": "供应商", "date": "日期",
        "invoice_date": "发票日期", "revenue_date": "收入确认日",
        "due_date": "到期日", "goods_services": "货物/服务", "purchase": "采购",
        "attachments": "附件", "file": "文件", "size": "大小",
        "fx": "折合功能货币", "rate": "汇率",
        "payment_account": "收款账户", "account_holder": "收款人",
        "account_number": "账户号码", "bank_name": "开户银行", "bank_address": "银行地址",
    },
    "zh_hk": {
        "item": "項目", "qty": "數量", "unit": "單價", "amount": "金額",
        "line_total": "合價", "total": "合計", "gross": "價稅合計",
        "original_total": "原幣合計", "net": "不含稅金額",
        "tax": "稅額", "tax_rate": "稅率", "currency": "幣種",
        "customer": "客戶", "vendor": "供應商", "date": "日期",
        "invoice_date": "發票日期", "revenue_date": "收入確認日",
        "due_date": "到期日", "goods_services": "貨物/服務", "purchase": "採購",
        "attachments": "附件", "file": "文件", "size": "大小",
        "fx": "折合功能貨幣", "rate": "匯率",
        "payment_account": "收款賬戶", "account_holder": "收款人",
        "account_number": "賬戶號碼", "bank_name": "開戶銀行", "bank_address": "銀行地址",
    },
}



def simple_doc_html(kind: str, doc: dict, entity: dict, *, lines=None, lang="en") -> str:
    """报价单 / 贷记单 / 订单：与发票同一套抬头（标题居中 + 公司联系方式），
    只是元信息与表格不同。明细由调用方给（description/quantity/unitPrice/amount）。"""
    from .i18n import column

    lines = lines or []
    ccy = str(doc.get("currency") or entity.get("functional_currency") or "HKD")
    no = str(doc.get("no") or "")
    date = str(doc.get("date") or "")
    party_label = column(lang, str(doc.get("partyLabel") or ""))
    party = str(doc.get("party") or "")
    extra = doc.get("meta") or []          # [(label, value), ...]
    LB = _SD_LABELS.get(lang, _SD_LABELS["en"])

    rows = ""
    total = 0.0
    for i, ln in enumerate(lines, start=1):
        amt = float(ln.get("amount") or 0)
        total += amt
        rows += (f"<tr><td>{i}</td><td>{_e(_doc_text(ln.get('description') or '', lang))}</td>"
                 f"<td class='num'>{_qty(ln.get('quantity'))}</td>"
                 f"<td class='num'>{_money(ln.get('unitPrice'), ccy)}</td>"
                 f"<td class='num'>{_money(amt, ccy)}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='5' style='color:#888'>—</td></tr>"

    meta_html = (f'<div class="col"><div class="label">{_e(party_label)}</div>'
                 f'<div class="value">{_e(party)}</div></div>'
                 f'<div class="col"><div class="label">{_e(LB["date"])}</div>'
                 f'<div class="value">{_e(date)}</div></div>')
    for lab, val in extra:
        if val:
            meta_html += (f'<div class="col"><div class="label">{_e(column(lang, str(lab)))}</div>'
                          f'<div class="value">{_e(_doc_text(str(val), lang))}</div></div>')

    total_value = doc.get("total") if doc.get("total") is not None else total
    functional_ccy = str(doc.get("functional_currency") or entity.get("functional_currency") or "")
    is_foreign = bool(functional_ccy and ccy != functional_ccy)
    fx_rate = _real_rate(doc.get("fx_rate"))
    gross_functional = _functional_gross(total_value, doc.get("amount_functional"))
    if kind in ("order_sales", "order_purchase") and gross_functional is None:
        # 老订单的外币占位值为 rate=1 / functional=0，不能冒充真实折算。
        fx_rate = None
    rate_text = _rate(fx_rate) if fx_rate is not None else "—"
    if fx_rate is not None and doc.get("fx_rate_date"):
        rate_text += f" ({_e(doc.get('fx_rate_date'))})"
    fx_rows = ""
    if is_foreign:
        fx_rows = (
            f'<tr><td style="font-size:9pt;color:#666">{_e(LB["fx"])}</td>'
            f'<td class="num" style="font-size:9pt;color:#666">'
            f'{_money(gross_functional, functional_ccy)}</td></tr>'
            f'<tr><td style="font-size:9pt;color:#666">{_e(LB["rate"])}</td>'
            f'<td class="num" style="font-size:9pt;color:#666">{rate_text}</td></tr>'
        )

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{BASE_CSS}
@page {{ size: A4; margin: 16mm 14mm 38mm 14mm;
  @bottom-right {{ content: counter(page) " / " counter(pages);
    font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888; padding-bottom: 10mm;
    vertical-align: bottom; }} }}
.doc-foot {{ position: fixed; left: 0; right: 0; bottom: -28mm; margin-top: 0; }}
</style></head><body>
<div class="head">
  <div class="doc-title"><h1>{_e(_doc_word(kind, lang))}</h1></div>
  <div class="doc-meta-right"><span class="dno">{_e(no)}</span></div>
</div>
<div class="meta">{meta_html}</div>
<table><thead><tr><th style="width:6%">#</th><th>{_e(LB["item"])}</th>
<th class="num" style="width:12%">{_e(LB["qty"])}</th>
<th class="num" style="width:18%">{_e(LB["unit"])}</th>
<th class="num" style="width:20%">{_e(LB["amount"])}</th></tr></thead>
<tbody>{rows}</tbody></table>
<table class="totals">
  <tr class="grand"><td>{_e(LB["original_total"] if is_foreign else LB["total"])}</td>
      <td class="num">{_money(total_value, ccy)}</td></tr>
  {fx_rows}
</table>
<div class="doc-foot">
  <div class="df-name">{_e(_legal_name(entity, lang))}</div>
  <div class="df-line">{_e(_br_line(entity))}</div>
  <div class="df-line">{_contact_line(entity, lang)}</div>
  <div class="df-line">{_e(_address(entity))}</div>
  <div class="df-note">{_e(_gen_note(lang))}</div>
</div>
</body></html>"""

def letterhead_html(entity, lang="en"):
    """公司抬头纸：左 Logo + 名称、右联系信息、粗横线、居中淡色水印。

    Logo 保留彩色，其余全部黑白。
    """
    L = _LH_LABELS.get(lang, _LH_LABELS["en"])
    # 页眉固定三行，与文档语言无关：
    #   繁體中文名 / 英文公司名 / 业务标语
    name_en = _e(entity.get("entity_name") or entity.get("legal_name") or "")
    name_zh_raw = str(entity.get("legal_name_zh") or "")
    name_zh = ""
    if name_zh_raw:
        try:
            from opencc import OpenCC
            name_zh = _e(OpenCC("s2hk").convert(name_zh_raw))
        except Exception:
            name_zh = _e(name_zh_raw)
    tagline = "Ledu Tech: Leading Technology, Diversified Services"
    addr = ", ".join(x for x in [entity.get("address_line1"), entity.get("address_line2"),
                                 entity.get("district"), entity.get("region")] if x)
    site = _e(entity.get("website") or "")
    tel = _e(entity.get("phone") or "")
    mail = _e(entity.get("email") or "")

    # 页脚：地址一行；网址 / 邮箱 / 电话 三个排一行，靠左
    contact = []
    if site:
        contact.append(f'<span><span class="k">{L["web"]}：</span>{site}</span>')
    if mail:
        contact.append(f'<span><span class="k">{L["email"]}：</span>{mail}</span>')
    if tel:
        contact.append(f'<span><span class="k">{L["tel"]}：</span>{tel}</span>')
    foot_rows = []
    if addr:
        foot_rows.append(f'<div class="foot-addr"><span class="k">{L["addr"]}：</span>{_e(addr)}</div>')
    if contact:
        foot_rows.append('<div class="foot-row">' + "".join(contact) + '</div>')

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{LETTERHEAD_CSS}</style></head><body>
<div class="sheet">
  <div class="wm"><img src="{_logo_uri()}"></div>

  <div class="head">
    <div class="brand">
      <img src="{_logo_uri()}">
      <div class="txt">
        {f'<div class="co">{name_zh}</div>' if name_zh else ''}
        <div class="co-en">{name_en}</div>
        <div class="tag">{tagline}</div>
      </div>
    </div>
  </div>
  <div class="rule"></div>
  <div class="body"></div>

  <div class="foot">{''.join(foot_rows)}</div>
</div>
</body></html>"""


# ---------------------------------------------------------------- 记账凭证

VOUCHER_I18N = {
    "zh_cn": {
        "title": "记账凭证", "date": "日期", "source": "来源", "atts": "附单据",
        "line": "行", "account": "会计科目", "desc": "摘要",
        "debit": "借方金额", "credit": "贷方金额", "total": "合计",
        "words": "金额大写", "prepared": "制单", "reviewed": "审核",
        "posted": "记账", "checked": "复核", "sheet": "张",
    },
    "zh_hk": {
        "title": "記賬憑證", "date": "日期", "source": "來源", "atts": "附單據",
        "line": "行", "account": "會計科目", "desc": "摘要",
        "debit": "借方金額", "credit": "貸方金額", "total": "合計",
        "words": "金額大寫", "prepared": "製單", "reviewed": "審核",
        "posted": "記賬", "checked": "覆核", "sheet": "張",
    },
    "en": {
        "title": "ACCOUNTING VOUCHER", "date": "Date", "source": "Source",
        "atts": "Attachments", "line": "No.", "account": "Account", "desc": "Description",
        "debit": "Debit", "credit": "Credit", "total": "Total",
        "words": "Amount in words", "prepared": "Prepared", "reviewed": "Reviewed",
        "posted": "Posted", "checked": "Checked", "sheet": "",
    },
}


def _num_words_en(amount: float) -> str:
    """英文金额大写：One Thousand Two Hundred and 50/100 only."""
    ones = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def below_thousand(n: int) -> str:
        out = []
        if n >= 100:
            out.append(ones[n // 100] + " Hundred")
            n %= 100
            if n:
                out.append("and")
        if n >= 20:
            out.append(tens[n // 10] + ("-" + ones[n % 10] if n % 10 else ""))
        elif n:
            out.append(ones[n])
        return " ".join(out)

    n = int(round(abs(amount) * 100))
    yuan, cent = divmod(n, 100)
    if yuan == 0:
        words = "Zero"
    else:
        parts, scale = [], ["", " Thousand", " Million", " Billion"]
        i = 0
        while yuan > 0:
            chunk = yuan % 1000
            if chunk:
                parts.insert(0, below_thousand(chunk) + scale[i])
            yuan //= 1000; i += 1
        words = " ".join(parts)
    if cent:
        words += " and %02d/100" % cent
    else:
        words += " only"
    return ("Minus " if amount < 0 else "") + words


VOUCHER_CSS = """
@page {
  size: A4 portrait; margin: 14mm 14mm 12mm;
  @bottom-right {
    content: counter(page) " / " counter(pages);
    font-family: "Liberation Sans", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888; padding-bottom: 3mm;
    vertical-align: bottom;
  }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: "Liberation Sans", "WenQuanYi Zen Hei", sans-serif;
       color: #111; font-size: 10.5pt; }
.v { page-break-after: always; }
.v:last-child { page-break-after: auto; }
.vh { display: flex; justify-content: space-between; align-items: flex-end;
      border-bottom: 1pt solid #333; padding-bottom: 3mm; margin-bottom: 3mm; }
.vh .co { font-size: 11pt; font-weight: bold; }
.vh .ttl { font-size: 17pt; letter-spacing: .35em; font-weight: bold; text-align: center;
           flex: 1; white-space: nowrap; }
.vh .ttl.en { font-size: 14pt; letter-spacing: .12em; }
.vh .no { font-size: 9.5pt; text-align: right; min-width: 46mm; line-height: 1.6; }
.meta { display: flex; justify-content: space-between; gap: 6mm; margin-bottom: 2mm;
        font-size: 9.5pt; }
table.lines { width: 100%; border-collapse: collapse; table-layout: fixed; }
table.lines th, table.lines td { border: .6pt solid #555; padding: 1.6mm 2mm; vertical-align: top; }
table.lines th { background: #f1f3f6; font-weight: bold; text-align: center; font-size: 9.5pt; }
table.lines td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
table.lines td.acct { font-size: 9.5pt; }
table.lines tr.total td { font-weight: bold; background: #fafafa; }
.sign { display: flex; justify-content: space-between; margin-top: 6mm; font-size: 9.5pt; }
.sign span { border-bottom: .6pt solid #999; min-width: 34mm; display: inline-block;
             padding-bottom: .5mm; }
.attach-note { margin-top: 4mm; font-size: 9pt; color: #444; }
.page-att { page-break-after: always; text-align: center; }
.page-att:last-child { page-break-after: auto; }
.page-att img { max-width: 100%; max-height: 255mm; object-fit: contain; }
.page-att .cap { font-size: 9pt; color: #555; margin-top: 2mm; }
"""


def _cn_upper(amount: float) -> str:
    """金额大写（港币/人民币通用写法），凭证底部用。"""
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["", "拾", "佰", "仟"]
    big = ["", "万", "亿"]
    n = int(round(abs(amount) * 100))
    if n == 0:
        return "零元整"
    yuan, cent = divmod(n, 100)
    s = ""
    if yuan:
        grp, gi = [], 0
        while yuan > 0:
            grp.append(yuan % 10000); yuan //= 10000; gi += 1
        parts = []
        for idx in range(len(grp) - 1, -1, -1):
            seg = grp[idx]
            if seg == 0:
                if parts and not parts[-1].endswith("零"):
                    parts.append("零")
                continue
            seg_s, zero, started = "", False, False
            for pos in range(3, -1, -1):
                d = (seg // (10 ** pos)) % 10
                if d == 0:
                    if started:
                        zero = True
                else:
                    if zero:
                        seg_s += "零"
                        zero = False
                    started = True
                    seg_s += digits[d] + units[pos]
            # 该段不足四位（如 0032）时，段前要补「零」
            if seg < 1000 and parts:
                seg_s = "零" + seg_s
            parts.append(seg_s + big[idx])
        s = "".join(parts).rstrip("零") + "元"
    if cent:
        jiao, fen = divmod(cent, 10)
        if jiao:
            s += digits[jiao] + "角"
        if fen:
            s += digits[fen] + "分"
    else:
        s += "整"
    return ("负" if amount < 0 else "") + s


def _esc(v) -> str:
    """HTML 转义（本模块内部用，避免与调用方的 e() 混淆）。"""
    return html.escape(str(v if v is not None else ""))


def voucher_html(entry, lines, entity, attachments=None, lang="zh_cn"):
    """一张记账凭证 + 其附件，逐页输出（附件每张一页）。"""
    from .pdf_reports import set_lang          # 复用报表的语言切换
    from .i18n import cell                     # 系统生成的凭证摘要按导出语言显示
    set_lang(lang or "zh_cn", entity.get("entity_id"))
    atts = attachments or []
    co = entity.get("entity_name") or ""
    date_s = str(entry.get("entry_date") or "")[:10]
    no = entry.get("entry_no") or ""
    src = entry.get("source_type") or ""
    desc = entry.get("description") or ""
    total_d = Decimal(str(entry.get("total_debit") or 0))
    total_c = Decimal(str(entry.get("total_credit") or 0))

    # 科目名与界面文案都按当前语言取
    _lang = (lang or "zh_cn").lower()
    if _lang not in VOUCHER_I18N:
        _lang = "zh_cn"
    T = VOUCHER_I18N[_lang]
    src = cell(_lang, src)
    _col = {"en": "name_en", "zh_hk": "name_zh_hk"}.get(_lang, "name_zh_cn")
    rows = []
    for ln in lines:
        code = str(ln.get("account_code") or "")
        name = ln.get(_col) or ln.get("account_name") or code
        rows.append(
            "<tr>"
            f"<td>{_esc(ln.get('line_no') or '')}</td>"
            f"<td class='acct'>{_esc(code)} {_esc(name)}</td>"
            f"<td>{_esc(cell(_lang, str(ln.get('description') or desc)))}</td>"
            f"<td class='num'>{_money(ln.get('debit')) if float(ln.get('debit') or 0) else ''}</td>"
            f"<td class='num'>{_money(ln.get('credit')) if float(ln.get('credit') or 0) else ''}</td>"
            "</tr>")

    html = [f"<html><head><meta charset='utf-8'><style>{VOUCHER_CSS}</style></head><body>"]
    html.append("<div class='v'>")
    html.append("<div class='vh'>")
    html.append(f"<div class='co'>{_esc(co)}</div>")
    html.append(f"<div class='ttl{' en' if _lang == 'en' else ''}'>{T['title']}</div>")
    html.append(f"<div class='no'>{_esc(no)}<br/>{_esc(date_s)}</div>")
    html.append("</div>")
    html.append("<div class='meta'>")
    html.append(f"<div><b>{T['date']}</b> {_esc(date_s)}　<b>{T['source']}</b> {_esc(src)}</div>")
    html.append(f"<div><b>{T['atts']}</b> {len(atts)} {T['sheet']}</div>")
    html.append("</div>")
    html.append("<table class='lines'><colgroup>"
                "<col style='width:8mm'><col style='width:58mm'><col>"
                "<col style='width:30mm'><col style='width:30mm'></colgroup>")
    html.append(f"<thead><tr><th>{T['line']}</th><th>{T['account']}</th><th>{T['desc']}</th>"
                f"<th>{T['debit']}</th><th>{T['credit']}</th></tr></thead><tbody>")
    html.extend(rows)
    html.append(f"<tr class='total'><td colspan='3' style='text-align:right'>{T['total']}</td>"
                f"<td class='num'>{_money(total_d)}</td>"
                f"<td class='num'>{_money(total_c)}</td></tr>")
    html.append("</tbody></table>")
    if _lang == "en":
        _words = _num_words_en(float(total_d))
    else:
        _words = _cn_upper(float(total_d))
        if _lang == "zh_hk":
            _words = _words.translate(str.maketrans({
                "贰": "貳", "叁": "參", "陆": "陸", "万": "萬", "亿": "億", "负": "負",
            }))
    _colon = ": " if _lang == "en" else "："
    html.append(f"<div class='attach-note'>{T['words']}{_colon}{_esc(_words)}</div>")
    html.append("<div class='sign'>"
                f"<div>{T['prepared']}　<span></span></div>"
                f"<div>{T['reviewed']}　<span></span></div>"
                f"<div>{T['posted']}　<span></span></div>"
                f"<div>{T['checked']}　<span></span></div></div>")
    html.append("</div>")

    for i, a in enumerate(atts, 1):
        src_uri = a.get("dataUri") or a.get("url")
        if not src_uri:
            continue
        html.append("<div class='page-att'>")
        html.append(f"<img src='{src_uri}'/>")
        _cap = ("Attachment" if _lang == "en" else ("附件" if _lang == "zh_cn" else "附件"))
        html.append(f"<div class='cap'>{_cap} {i}/{len(atts)} · {_esc(a.get('file_name') or '')}</div>")
        html.append("</div>")
    html.append("</body></html>")
    return "".join(html)


# ---------------------------------------------------------------- 付款单 / 收款单

_PAY_I18N = {
    "en": {
        "made": "PAYMENT VOUCHER", "received": "RECEIPT VOUCHER",
        "no": "No.", "date": "Date", "vendor": "Vendor", "customer": "Customer",
        "currency": "Currency", "amount": "Amount", "functional": "In functional currency",
        "rate": "FX rate", "bank": "Bank account", "entry": "Journal entry",
        "status": "Status", "docs": "Settled documents", "doc_no": "Document",
        "doc_date": "Document date", "doc_total": "Document total",
        "settled": "Settled now", "settled_total": "Settled to date",
        "fx_diff": "FX difference", "total": "Total",
        "payee_bank": "Payee bank details", "bank_name": "Bank",
        "account_name": "Account name", "account_no": "Account number",
        "swift": "SWIFT / BIC", "bank_address": "Bank address",
        "none": "No documents settled",
        "draft": "Draft", "posted": "Posted", "void": "Void", "reversed": "Reversed",
    },
    "zh_hk": {
        "made": "付 款 單", "received": "收 款 單",
        "no": "編號", "date": "日期", "vendor": "供應商", "customer": "客戶",
        "currency": "幣種", "amount": "金額", "functional": "折合功能貨幣",
        "rate": "匯率", "bank": "銀行賬戶", "entry": "記賬憑證",
        "status": "狀態", "docs": "核銷明細", "doc_no": "單據號",
        "doc_date": "單據日期", "doc_total": "單據金額",
        "settled": "本次核銷", "settled_total": "累計已核銷",
        "fx_diff": "匯兌差額", "total": "合計",
        "payee_bank": "收款銀行資料", "bank_name": "開戶銀行",
        "account_name": "賬戶名稱", "account_no": "銀行賬號",
        "swift": "SWIFT / BIC", "bank_address": "銀行地址",
        "none": "這張付款單沒有核銷任何單據",
        "draft": "草稿", "posted": "已記賬", "void": "已作廢", "reversed": "已沖銷",
    },
    "zh_cn": {
        "made": "付 款 单", "received": "收 款 单",
        "no": "编号", "date": "日期", "vendor": "供应商", "customer": "客户",
        "currency": "币种", "amount": "金额", "functional": "折合功能货币",
        "rate": "汇率", "bank": "银行账户", "entry": "记账凭证",
        "status": "状态", "docs": "核销明细", "doc_no": "单据号",
        "doc_date": "单据日期", "doc_total": "单据金额",
        "settled": "本次核销", "settled_total": "累计已核销",
        "fx_diff": "汇兑差额", "total": "合计",
        "payee_bank": "收款银行信息", "bank_name": "开户银行",
        "account_name": "账户名称", "account_no": "银行账号",
        "swift": "SWIFT / BIC", "bank_address": "银行地址",
        "none": "这张付款单没有核销任何单据",
        "draft": "草稿", "posted": "已记账", "void": "已作废", "reversed": "已冲销",
    },
}

_PAY_CSS = """
@page { size: A4; margin: 16mm 14mm 38mm 14mm;
  @bottom-right { content: counter(page) " / " counter(pages);
    font-family: "Liberation Serif", "WenQuanYi Zen Hei", sans-serif;
    font-size: 7pt; color: #888; padding-bottom: 10mm;
    vertical-align: bottom; } }
.doc-foot { position: fixed; left: 0; right: 0; bottom: -28mm; margin-top: 0; }
.kvt { margin: 0 0 4px; }
.kvt td { border: none; padding: 3px 8px 3px 0; font-size: 9.5pt; vertical-align: top; }
.kvt td.k { color: #888; width: 24mm; white-space: nowrap; font-size: 8.5pt; }
.kvt td.v { font-weight: 600; padding-right: 18px; }
.bankbox { border: 1px solid #DDE3EA; background: #FAFBFC; padding: 8px 10px; margin-top: 14px; }
.bankbox .bt { font-size: 8pt; font-weight: 700; color: #555; letter-spacing: .06em;
               text-transform: uppercase; margin-bottom: 5px; }
.bankbox table { margin-top: 0; }
.bankbox td { border: none; padding: 2px 6px 2px 0; font-size: 9.5pt; vertical-align: top; }
.bankbox td.k { color: #888; width: 26mm; white-space: nowrap; font-size: 8.5pt; }
.bankbox td.v { font-weight: 600; padding-right: 18px; }
.muted { color: #888; }
"""


def payment_voucher_html(payment, docs, entity, party_bank=None, lang="zh_cn"):
    """付款单 / 收款单 PDF：单据信息 + 金额 + 核销明细。

    付款单在核销明细下方打印供应商的收款银行信息，供汇款或复核使用；
    收款单没有收款方银行资料，区块省略。
    """
    _lang = (lang or "zh_cn").lower()
    if _lang not in _PAY_I18N:
        _lang = "zh_cn"
    T = _PAY_I18N[_lang]
    is_made = str(payment.get("direction") or "received") == "made"
    ccy = str(payment.get("currency") or "")
    func = str(entity.get("functional_currency") or "")
    status = str(payment.get("status") or "")
    no = str(payment.get("paymentNo") or "")
    date_s = str(payment.get("date") or "")[:10]

    def kv(k, v_html, colspan=""):
        span = f" colspan='{colspan}'" if colspan else ""
        return (f"<td class='k'>{_e(k)}</td>"
                f"<td class='v'{span}>{v_html}</td>")

    rate_txt = _rate(payment.get("fxRate"))
    if payment.get("fxRateDate"):
        rate_txt += (f" ({_e(payment.get('fxRateDate'))})" if _lang == "en"
                     else f"（{_e(payment.get('fxRateDate'))}）")

    bank = payment.get("bank") or {}
    bank_txt = ""
    if bank:
        bits = [str(x) for x in (bank.get("name"), bank.get("account")) if x]
        bank_txt = _e(" · ".join(bits))

    rows = [
        "<tr>" + kv(T["vendor"] if is_made else T["customer"], _e(payment.get("party") or "—"))
        + kv(T["date"], _e(date_s)) + "</tr>",
        "<tr>" + kv(T["currency"], _e(ccy))
        + kv(T["rate"], _e(rate_txt)) + "</tr>",
        "<tr>" + kv(T["bank"], bank_txt or "<span class='muted'>—</span>")
        + kv(T["status"], _e(T.get(status, status))) + "</tr>",
        "<tr>" + kv(T["entry"], _e((payment.get("entry") or {}).get("entryNo") or "—"),
                    colspan="3") + "</tr>",
    ]

    fx_rows = ""
    if payment.get("settlementFxDiff"):
        fx_rows = (f"<tr><td>{_e(T['fx_diff'])}</td>"
                   f"<td class='num'>{_money(payment.get('settlementFxDiff'), func)}</td></tr>")

    doc_rows = ""
    for x in (docs or []):
        doc_rows += (
            "<tr>"
            f"<td>{_e(x.get('docNo') or '')}</td>"
            f"<td>{_e(x.get('docDate') or '')}</td>"
            f"<td class='num'>{_money(x.get('documentTotal'), x.get('currency') or ccy)}</td>"
            f"<td class='num'><b>{_money(x.get('settledOriginal'), x.get('currency') or ccy)}</b></td>"
            f"<td class='num'>{_money(x.get('documentSettled'), x.get('currency') or ccy)}</td>"
            f"<td class='num'>{_money(x.get('fxDiff'), func)}</td>"
            "</tr>")
    if not doc_rows:
        doc_rows = f"<tr><td colspan='6' class='muted'>{_e(T['none'])}</td></tr>"

    bank_html = ""
    if is_made and party_bank:
        pairs = [
            (T["bank_name"], party_bank.get("bank_name")),
            (T["account_name"], party_bank.get("bank_account_name")),
            (T["account_no"], party_bank.get("bank_account_no")),
            (T["swift"], party_bank.get("bank_swift")),
        ]
        bank_rows = ""
        for i in range(0, len(pairs), 2):
            left = pairs[i]
            right = pairs[i + 1] if i + 1 < len(pairs) else ("", "")
            bank_rows += "<tr>" + kv(left[0], _e(left[1] or "—")) + kv(right[0], _e(right[1] or "—")) + "</tr>"
        addr = party_bank.get("bank_address")
        if addr:
            bank_rows += "<tr>" + kv(T["bank_address"], _e(addr), colspan="3") + "</tr>"
        if any(v for _, v in pairs) or addr:
            bank_html = (f"<div class='bankbox'><div class='bt'>{_e(T['payee_bank'])}</div>"
                         f"<table>{bank_rows}</table></div>")

    foot = (
        f"<div class='doc-foot'>"
        f"<div class='df-name'>{_e(_legal_name(entity, _lang))}</div>"
        f"<div class='df-line'>{_e(_br_line(entity))}</div>"
        f"<div class='df-line'>{_contact_line(entity, _lang)}</div>"
        f"<div class='df-line'>{_e(_address(entity))}</div>"
        f"<div class='df-note'>{_e(_gen_note(_lang))} {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>"
        f"</div>")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{BASE_CSS}{_PAY_CSS}</style></head><body>
{_watermark(status, _lang)}
<div class="head">
  <div class="doc-title"><h1>{_e(T['made' if is_made else 'received'])}</h1></div>
  <div class="doc-meta-right"><span class="dno">{_e(no)} · {_e(date_s)}</span></div>
</div>
<table class="kvt"><tbody>{''.join(rows)}</tbody></table>
<table class="totals">
  <tr><td>{_e(T['amount'])}</td><td class="num">{_money(payment.get('amount'), ccy)}</td></tr>
  {fx_rows}
  <tr class="grand"><td>{_e(T['functional'])}</td>
      <td class="num">{_money(payment.get('amountFunctional'), func)}</td></tr>
</table>
<table><thead><tr><th>{_e(T['doc_no'])}</th><th>{_e(T['doc_date'])}</th>
<th class="num">{_e(T['doc_total'])}</th><th class="num">{_e(T['settled'])}</th>
<th class="num">{_e(T['settled_total'])}</th><th class="num">{_e(T['fx_diff'])}</th></tr></thead>
<tbody>{doc_rows}</tbody></table>
{bank_html}
{foot}
</body></html>"""

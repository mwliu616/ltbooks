# LtBooks — core/doc_analyze.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""单据分析：判断采购 / 销售、单据类型，并给出科目建议。

设计原则
--------
1. **确定性优先**：方向、科目、借贷方向都由代码规则给出，不交给模型自由发挥；
   模型只负责把结论讲给人听。
2. **可解释**：每个结论都带 reasons / basis / confidence，低置信必须提示人工确认。
3. **可学习**：人在反馈接口里改正一次，就写进 extract_samples；
   同一往来单位同一字段改到 2 次，固化成 extract_rules，下次直接命中。
4. **不写账**：只产出建议与预览，入账仍走建单/过账流程。

对外只暴露 analyze() 与 learning 相关的薄封装。
"""
from __future__ import annotations

import re
from typing import Iterable

from .db import query, query_one
from .agents import extractor_learning as exl

DISCLAIMER = "AI-assisted, subject to human review"

SALE_HINTS = ("銷售", "销售", "開票", "开票", "銷貨", "销货", "客戶", "客户",
              "customer", "client", "invoice to", "bill to", "service fee",
              "服務收入", "服务收入")
PURCHASE_HINTS = ("採購", "采购", "供應商", "供应商", "supplier", "vendor", "供貨", "供货",
                  "請款", "请款", "purchase", "buyer", "bill from", "賬單", "账单",
                  "發票", "发票", "稅務發票", "税务发票")
CREDIT_HINTS = ("credit note", "credit memo", "貸項", "贷项", "紅字", "红字", "退款單", "退款单")
QUOTE_HINTS = ("quotation", "quote", "報價", "报价", "估價", "估价")
EXPENSE_HINTS = ("expense claim", "報銷", "报销", "petty cash", "零用金")

# 关键词 → 科目名称片段。命中后按名称去科目表里找，不硬编码科目代码，
# 换一套科目表也能用。
ACCOUNT_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("租金", "rent", "lease"), "租金"),
    (("管理費", "管理费", "management fee"), "管理費"),
    (("水電", "水电", "電費", "电费", "utility", "utilities"), "水電費"),
    (("差餉", "差饷", "rates and government"), "差餉"),
    (("審計", "审计", "audit", "核數", "核数"), "核數"),
    (("法律", "legal", "律師", "律师", "諮詢", "咨询", "consult"), "法律"),
    (("銀行手續費", "银行手续费", "bank charge", "手續費", "手续费"), "銀行手續費"),
    (("it ", "it服務", "it服务", "software", "軟件", "软件", "saas", "hosting",
      "server", "subscription", "系統維護", "系统维护"), "IT"),
    (("差旅", "travel", "機票", "机票", "酒店", "hotel"), "差旅"),
    (("應酬", "应酬", "entertainment", "餐飲", "餐饮"), "應酬"),
    (("交通", "transport", "的士", "taxi", "uber", "車費", "车费"), "交通"),
    (("辦公", "办公", "office", "文具", "stationery", "打印"), "辦公"),
    (("通訊", "通讯", "電話", "电话", "telecom", "寬頻", "宽带"), "通訊"),
    (("電腦", "电脑", "computer", "硬件", "hardware", "設備", "设备", "equipment"), "電腦及軟件"),
    (("維修", "维修", "repair", "保養", "保养"), "維修"),
    (("保險", "保险", "insurance"), "保險"),
    (("商業登記", "商业登记", "business registration"), "商業登記"),
    (("折舊", "折旧", "depreciation"), "折舊"),
    (("攤銷", "摊销", "amortisation", "amortization"), "攤銷"),
    (("利息", "interest"), "利息"),
]

SERVICE_HINTS = ("服務", "服务", "service", "consult", "顧問", "顾问", "設計", "设计")

STATUS_OK = ("active",)


# ---------------------------------------------------------------- 基础工具
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(s or "").lower())


def _entity_names(entity_id: int) -> list[str]:
    r = query_one("""SELECT entity_name, legal_name, legal_name_zh FROM entities
                      WHERE entity_id=%s""", (entity_id,)) or {}
    return [str(x) for x in (r.get("entity_name"), r.get("legal_name"), r.get("legal_name_zh")) if x]


def _known_parties(entity_id: int) -> list[dict]:
    rows = query("""SELECT customer_id AS id, customer_name AS name, 'customer' AS kind
                      FROM customers WHERE entity_id=%s
                    UNION ALL
                    SELECT vendor_id AS id, vendor_name AS name, 'vendor' AS kind
                      FROM vendors WHERE entity_id=%s""", (entity_id, entity_id))
    return [dict(r) for r in rows if r.get("name")]


def _match_party(entity_id: int, text: str, given: str = "") -> dict:
    """优先用户给的名称；否则在文本里找已知客户/供应商（取最长命中）。"""
    parties = _known_parties(entity_id)
    if given:
        key = _norm(given)
        for p in parties:
            if _norm(p["name"]) == key:
                return {**p, "matched": "exact"}
        for p in parties:
            nk = _norm(p["name"])
            # 双向包含：OCR 常多带/少带 Ltd、有限公司等后缀
            if len(nk) >= 4 and (nk in key or key in nk):
                return {**p, "matched": "fuzzy"}
        return {"id": None, "name": str(given), "kind": "unknown", "matched": "user"}

    norm = _norm(text)
    best = None
    for p in parties:
        k = _norm(p["name"])
        if len(k) >= 2 and k in norm and (best is None or len(k) > len(best["key"])):
            best = {**p, "matched": "text", "key": k}
    return best or {"id": None, "name": "", "kind": "unknown", "matched": "none"}


def _rules_map(entity_id: int, party: str) -> dict:
    """该往来单位已固化的规则。同一字段出现多个值时不硬套，交给人工。"""
    out: dict = {}
    if not party:
        return out
    for r in exl.rules_for(entity_id, party):
        f, v = str(r["field"]), str(r["value"])
        if f in out and str(out[f]["value"]) != v:
            out[f] = {"value": None, "ambiguous": True, "samples": r["samples"]}
        elif f not in out:
            out[f] = {"value": v, "samples": r["samples"], "ruleId": r["rule_id"]}
    return out


def _account_by_name(term: str, categories: Iterable[str], entity_id: int) -> dict | None:
    cats = tuple(categories)
    holes = ",".join(["%s"] * len(cats))
    like = f"%{term}%"
    r = query_one(f"""SELECT account_code, name_zh_hk, name_en, category
                        FROM accounts
                       WHERE entity_id=%s AND is_active=1 AND category IN ({holes})
                         AND (name_zh_hk LIKE %s OR name_en LIKE %s)
                       ORDER BY FIELD(category,'expense','cogs','asset','revenue'), account_code
                       LIMIT 1""", (entity_id, *cats, like, like))
    return dict(r) if r else None


def _keyword_account(text: str, entity_id: int, direction: str) -> dict | None:
    low = str(text or "").lower()
    if direction == "sale":
        if any(k in low for k in SERVICE_HINTS):
            r = _account_by_name("服務收入", ("revenue",), entity_id)
            if r:
                return {**r, "basis": "关键词：服务类收入"}
        r = _account_by_name("主營業務收入", ("revenue",), entity_id)
        return {**r, "basis": "销售收入默认科目"} if r else None

    for words, term in ACCOUNT_KEYWORDS:
        if any(w in low for w in words):
            r = _account_by_name(term, ("expense", "cogs"), entity_id)
            if r:
                return {**r, "basis": f"关键词命中「{term}」"}
    return None


def _party_history(entity_id: int, party: str, direction: str) -> list[dict]:
    if not party:
        return []
    like = f"%{party}%"
    side = "l.credit > 0" if direction == "sale" else "l.debit > 0"
    cats = ("revenue",) if direction == "sale" else ("expense", "cogs")
    holes = ",".join(["%s"] * len(cats))
    rows = query(f"""SELECT l.account_code, a.name_zh_hk AS account_name, COUNT(*) AS n
                       FROM journal_lines l
                       JOIN journal_entries e ON e.entry_id=l.entry_id
                       JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=%s
                       LEFT JOIN invoices i ON i.invoice_id=e.source_id AND e.source_type='invoice'
                       LEFT JOIN bills b ON b.bill_id=e.source_id AND e.source_type='bill'
                      WHERE e.entity_id=%s AND e.status='posted' AND {side}
                        AND a.category IN ({holes})
                        AND (i.supplier_name LIKE %s OR b.vendor_name LIKE %s)
                      GROUP BY l.account_code, a.name_zh_hk
                      ORDER BY n DESC LIMIT 5""",
                   (entity_id, entity_id, *cats, like, like))
    return [dict(r) for r in rows]


_SKIP_LINE = re.compile(r"^\s*(total|subtotal|amount\s*due|balance|tax|vat|gst|"
                        r"合計|合计|小計|小计|稅額|税额|總額|总额)", re.I)


def _text_lines(text: str) -> list[dict]:
    """没有结构化明细时，从原文里挑出带金额的行，作为科目建议的载体。"""
    out, seen = [], set()
    for ln in str(text or "").splitlines():
        s = ln.strip()
        if not s or len(s) > 300 or _SKIP_LINE.match(s):
            continue
        if not re.search(r"\d[\d,]*\.\d{2}", s):
            continue
        key = _norm(s)
        if key in seen:
            continue
        seen.add(key)
        m = re.search(r"(\d[\d,]*\.\d{2})", s)
        try:
            amt = float(m.group(1).replace(",", ""))
        except ValueError:
            amt = None
        out.append({"description": s, "amount": amt})
    return out[:20]


# ---------------------------------------------------------------- 方向与类型
def _direction(text: str, party: dict, entity_id: int, learned: dict) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    if learned.get("value") in ("purchase", "sale"):
        label = "采购" if learned["value"] == "purchase" else "销售"
        return learned["value"], "high", [
            f"学习规则命中：该往来单位历史上被确认为「{label}」（{learned.get('samples', 0)} 次样本）"]

    score = {"sale": 0, "purchase": 0}
    kind = party.get("kind")
    if kind == "customer":
        score["sale"] += 8
        reasons.append(f"客户档案命中：{party.get('name')}")
    elif kind == "vendor":
        score["purchase"] += 8
        reasons.append(f"供应商档案命中：{party.get('name')}")

    low = str(text or "").lower()
    if not kind or kind == "unknown":
        # 只有认不出往来单位时，才靠「本公司是开票方还是受票方」判断
        own_hit = False
        for name in _entity_names(entity_id):
            raw = name.lower()
            if raw and raw in low:
                own_hit = True
                before = low[:low.index(raw)][-60:]
                if re.search(r"(bill\s*to|ship\s*to|buyer|受票方|買方|买方|客户|客戶)"
                             r"\s*[:：]?\s*$", before):
                    score["purchase"] += 3
                    reasons.append("单据受票方为本公司")
                else:
                    score["sale"] += 3
                    reasons.append("本公司为开票方")
                break
        if not own_hit:
            reasons.append("单据未出现本公司名称，方向按关键词判断")

    for kw in SALE_HINTS:
        if kw in low:
            score["sale"] += 1
    for kw in PURCHASE_HINTS:
        if kw in low:
            score["purchase"] += 1

    if any(k in low for k in CREDIT_HINTS):
        score["sale"] += 1
        reasons.append("出现贷记单字样")

    if score["sale"] >= score["purchase"] + 2:
        return "sale", ("high" if score["sale"] >= 5 else "medium"), reasons
    if score["purchase"] >= score["sale"] + 2:
        return "purchase", ("high" if score["purchase"] >= 5 else "medium"), reasons
    reasons.append(f"方向证据不足（销售 {score['sale']} / 采购 {score['purchase']}）")
    return "unknown", "low", reasons


def _doc_type(text: str, direction: str) -> str:
    low = str(text or "").lower()
    if any(k in low for k in CREDIT_HINTS):
        return "credit_note"
    if any(k in low for k in QUOTE_HINTS):
        return "quote"
    if any(k in low for k in EXPENSE_HINTS):
        return "expense"
    if direction == "sale":
        return "invoice"
    if direction == "purchase":
        return "bill"
    return "unknown"


# ---------------------------------------------------------------- 支出性质
_REIMBURSE_STRONG = (
    "报销", "報銷", "reimburse", "expense claim", "垫付", "墊付", "垫支", "代垫", "代墊",
    "员工支付", "員工支付", "员工付款", "員工付款", "个人支付", "個人支付", "个人卡", "個人卡",
    "其他应付款—员工", "其他应付款-员工", "其他應付款—員工", "其他應付款-員工",
)
_COMPANY_DIRECT_STRONG = (
    "公司直接支出", "公司支付", "公司付款", "对公支付", "對公支付", "公司卡", "企业卡", "企業卡",
    "直接支付供应商", "直接支付供應商", "corporate card", "company paid", "paid by company",
)
_ORG_HINTS = (
    "有限公司", "公司", "集团", "集團", "事务所", "事務所", "银行", "銀行", "政府", "大学", "大學",
    "医院", "醫院", "limited", "ltd", "inc", "llc", "corp", "company", "co.", "gmbh", "pte", "plc",
)
_PERSON_TITLE_HINTS = ("先生", "女士", "小姐", "员工", "員工", "职员", "職員", "本人")
_REIMBURSE_ACCOUNT_HINTS = (
    "差旅", "交通", "应酬", "應酬", "餐饮", "餐飲", "住宿", "机票", "機票",
    "travel", "transport", "entertainment", "meal", "accommodation", "hotel",
)


def _nature_result(nature: str, confidence: str, why: str, applicable: bool = True) -> dict:
    labels = {"company": "公司直接支出", "reimburse": "个人报销", "": "未确定"}
    return {
        "nature": nature,
        "label": labels[nature],
        "confidence": confidence,
        "why": why,
        "applicable": applicable,
        "needsConfirmation": applicable and nature not in ("company", "reimburse"),
    }


def _expense_nature(text: str, party_info: dict, doc_type: str,
                    accounts: list[dict], extracted: dict) -> dict:
    """保守判断公司直付/员工报销；普通发票字样本身不算公司直付证据。"""
    action_type = str(extracted.get("actionType") or "")
    applicable = action_type in ("create_bill", "create_expense") or (
        not action_type and doc_type in ("bill", "expense"))
    if not applicable or action_type == "create_invoice":
        return _nature_result("", "not_applicable", "销售及非费用单据不需要判断支出性质", False)

    party = str(party_info.get("name") or "").strip()
    account_text = " ".join(
        f"{a.get('accountName') or ''} {a.get('basis') or ''}"
        for a in accounts if a.get("confidence") != "low"
    )
    blob = " ".join((str(text or ""), party, account_text)).lower()
    if any(w in blob for w in _REIMBURSE_STRONG):
        return _nature_result("reimburse", "high", "OCR/单据内容出现报销、垫付或员工个人支付依据")
    if any(w in blob for w in _COMPANY_DIRECT_STRONG):
        return _nature_result("company", "high", "OCR/单据内容出现公司直接付款依据")

    # 已建档供应商是确定的公司往来证据；但若原文明确说员工垫付，上面已优先返回报销。
    if party_info.get("kind") == "vendor":
        return _nature_result("company", "high", "往来单位匹配到供应商档案，按公司直接支出处理")

    low_party = party.lower()
    org_party = bool(party) and any(w in low_party for w in _ORG_HINTS)
    titled_person = bool(party) and any(w in party for w in _PERSON_TITLE_HINTS)
    plain_person = bool(party) and not org_party and (
        bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", party))
        or bool(re.fullmatch(r"[A-Za-z]+(?:\s+[A-Za-z]+){1,2}", party))
    )
    reimbursable_account = any(w in account_text.lower() for w in _REIMBURSE_ACCOUNT_HINTS)
    if titled_person or (plain_person and reimbursable_account):
        return _nature_result("reimburse", "medium", "往来单位像个人，并结合费用单据/科目判断为员工报销")
    if org_party:
        return _nature_result("company", "medium", "往来单位具有机构/公司特征，按公司直接支出处理")

    return _nature_result("", "low", "往来单位、OCR 与科目建议均不足以可靠判断支出性质")


# ---------------------------------------------------------------- 科目建议
def _suggest_for_line(entity_id: int, line: dict, direction: str, *,
                      history: list[dict], learned: dict, party: str = "") -> dict:
    desc = str(line.get("description") or line.get("desc") or "")
    # 行内容常常把往来单位也带进来（"… Alpha Office Solutions"），
    # 先剔掉单位名再匹配关键词，免得 "Office" 被当成办公费。
    kw_text = desc
    if party:
        kw_text = re.sub(re.escape(party), " ", kw_text, flags=re.I)
    kw = _keyword_account(kw_text, entity_id, direction)
    hist = history[0] if history else None
    learned_code = learned.get("accountCode", {}).get("value") if learned else None

    primary = None
    basis = ""
    conf = "low"
    alts: list[dict] = []
    learned_acct = None
    if learned_code:
        a = query_one("""SELECT account_code, name_zh_hk FROM accounts
                          WHERE entity_id=%s AND account_code=%s""", (entity_id, learned_code))
        if a:
            learned_acct = dict(a)

    if kw:
        # 行内关键词最具体：它和该单位习惯一致就升为高置信，不一致就并列提示
        primary, basis, conf = kw, kw["basis"], "medium"
        if learned_acct and str(learned_acct["account_code"]) == str(kw["account_code"]):
            basis, conf = f"{kw['basis']} + 学习规则", "high"
    elif learned_acct:
        # 人工确认过两次的单位习惯，优先于统计出来的历史频次
        primary = learned_acct
        basis = f"学习规则：该单位固定科目（{learned['accountCode'].get('samples', 0)} 次）"
        conf = "high"

    if hist and (not primary or str(hist["account_code"]) == str(primary["account_code"])):
        primary = {"account_code": hist["account_code"], "name_zh_hk": hist["account_name"]}
        basis = f"关键词 + 该单位历史 {hist['n']} 笔" if kw else f"该单位历史 {hist['n']} 笔"
        conf = "high"
        hist = None

    if not primary and hist:
        primary = {"account_code": hist["account_code"], "name_zh_hk": hist["account_name"]}
        basis, conf = f"该单位历史 {hist['n']} 笔", "medium"

    if not primary:
        fallback = _account_by_name("辦公費用", ("expense",), entity_id) if direction != "sale" \
            else _account_by_name("主營業務收入", ("revenue",), entity_id)
        if fallback:
            primary = fallback
            basis, conf = "无关键词与历史，使用默认科目", "low"

    for h in history[1:4]:
        alts.append({"accountCode": h["account_code"], "accountName": h["account_name"],
                     "basis": f"该单位历史 {h['n']} 笔"})
    if kw and hist and primary and str(hist["account_code"]) != str(primary["account_code"]):
        alts.append({"accountCode": hist["account_code"], "accountName": hist["account_name"],
                     "basis": f"该单位历史 {hist['n']} 笔，与关键词不一致"})
    if learned_acct and primary and str(primary.get("account_code")) != str(learned_acct["account_code"]):
        alts.append({"accountCode": learned_acct["account_code"], "accountName": learned_acct["name_zh_hk"],
                     "basis": "学习规则记录的另一科目"})

    return {
        "line": desc[:160] or "（未识别明细）",
        "accountCode": str(primary["account_code"]) if primary else "",
        "accountName": str(primary.get("name_zh_hk") or "") if primary else "",
        "side": "credit" if direction == "sale" else "debit",
        "confidence": conf,
        "basis": basis,
        "alternatives": alts,
    }


def analyze(text: str, *, entity_id: int = 1, party: str = "", lines: list | None = None,
            extracted: dict | None = None) -> dict:
    """分析一张单据：方向、类型、科目建议、分录预览。"""
    text = str(text or "")
    ext = dict(extracted or {})
    party_info = _match_party(entity_id, text, party or str(ext.get("partyName") or ext.get("supplierName") or ""))
    learned = _rules_map(entity_id, str(party_info.get("name") or ""))

    direction, dir_conf, reasons = _direction(text, party_info, entity_id, learned.get("direction") or {})
    doc_type = _doc_type(text, direction)
    if learned.get("direction", {}).get("value") and doc_type in ("invoice", "bill", "unknown"):
        doc_type = ("invoice" if direction == "sale" else "bill") if direction in ("sale", "purchase") else doc_type

    explicit_lines = list(lines or ext.get("lines") or [])
    raw_lines = explicit_lines or _text_lines(text)
    implicit = not explicit_lines
    if not raw_lines:
        raw_lines = [{"description": (text.strip()[:160] or "（无文本）"), "amount": None}]

    history = _party_history(entity_id, str(party_info.get("name") or ""), direction)
    accounts, seen = [], set()
    for ln in raw_lines[:20]:
        a = _suggest_for_line(entity_id, ln, direction, history=history, learned=learned,
                              party=str(party_info.get("name") or ""))
        key = (a["line"].lower(), a["accountCode"])
        if key in seen:
            continue
        seen.add(key)
        accounts.append(a)
    if not accounts:
        accounts = [_suggest_for_line(entity_id, {"description": text[:160]},
                                      direction, history=history, learned=learned,
                                      party=str(party_info.get("name") or ""))]

    amount = None
    for k in ("grossOriginal", "amountOriginal", "amount"):
        v = ext.get(k)
        if v not in (None, ""):
            try:
                amount = float(v)
                break
            except (TypeError, ValueError):
                pass
    if amount is None:
        amts = [ln.get("amount") for ln in raw_lines if isinstance(ln.get("amount"), (int, float))]
        if amts:
            amount = float(sum(amts))
        else:
            m = re.search(r"(?:total|amount\s*due|合計|合计|總額|总额)[^\d]{0,12}([\d,]+\.\d{2})",
                          text, re.I)
            if m:
                try:
                    amount = float(m.group(1).replace(",", ""))
                except ValueError:
                    pass

    nature = _expense_nature(text, party_info, doc_type, accounts, ext)

    warnings: list[str] = []
    if nature["needsConfirmation"]:
        warnings.append("无法可靠判断是公司直接支出还是个人报销，请人工选择")
    if not party_info.get("name"):
        warnings.append("未匹配到客户/供应商档案，方向仅按文本关键词判断")
    if direction == "unknown":
        warnings.append("无法确定是采购还是销售，请人工选择")
    if not amount:
        warnings.append("未取到金额，科目建议仍可用，但无法生成分录预览")
    if any(a["confidence"] == "low" for a in accounts):
        warnings.append("存在低置信科目建议，过账前请人工确认")

    journal = None
    if amount and direction in ("sale", "purchase") and accounts:
        tax = 0.0
        try:
            tax = float(ext.get("taxOriginal") or 0)
        except (TypeError, ValueError):
            tax = 0.0
        net = amount - tax if tax > 0 else amount

        # 分录金额：结构化明细且各行金额能对上总额时才逐行拆；否则只挂一行，
        # 避免从文本里抓到的多行金额把总额翻倍。
        line_amts = []
        if not implicit:
            vals = [float(ln["amount"]) for ln in raw_lines[:len(accounts)]
                    if isinstance(ln.get("amount"), (int, float))]
            if len(vals) == len(accounts) and abs(sum(vals) - net) < 0.01:
                line_amts = vals
        if line_amts:
            acct_side = [{"accountCode": a["accountCode"], "accountName": a["accountName"],
                          "amount": round(v, 2)} for a, v in zip(accounts, line_amts)]
        else:
            acct_side = [{"accountCode": accounts[0]["accountCode"],
                          "accountName": accounts[0]["accountName"], "amount": round(net, 2)}]

        if direction == "sale":
            credit = acct_side
            if tax > 0:
                credit.append({"accountCode": "2150", "accountName": "應付稅項", "amount": round(tax, 2)})
            journal = {"debit": [{"accountCode": "1130", "accountName": "應收賬款",
                                  "amount": round(amount, 2)}], "credit": credit}
        else:
            journal = {"debit": acct_side,
                       "credit": [{"accountCode": "2110", "accountName": "應付賬款",
                                   "amount": round(amount, 2)}]}

    overall = "high"
    if dir_conf == "low" or direction == "unknown":
        overall = "low"
    elif dir_conf == "medium" or any(a["confidence"] != "high" for a in accounts):
        overall = "medium"

    rules_applied = [
        {"field": f, "value": v["value"], "samples": v.get("samples"), "ruleId": v.get("ruleId")}
        for f, v in learned.items() if v.get("value") and f in ("direction", "accountCode")
    ]

    return {
        "direction": direction,
        "directionLabel": {"sale": "销售", "purchase": "采购", "unknown": "未确定"}[direction],
        "docType": doc_type,
        "docTypeLabel": {"invoice": "销售发票", "bill": "采购账单", "expense": "费用报销",
                         "credit_note": "贷记单", "quote": "报价单", "unknown": "未识别"}.get(doc_type, doc_type),
        "partyName": party_info.get("name") or "",
        "partyKind": party_info.get("kind") or "unknown",
        "partyMatch": party_info.get("matched"),
        "expenseNature": nature["nature"],
        "expenseNatureLabel": nature["label"],
        "expenseNatureConfidence": nature["confidence"],
        "expenseNatureWhy": nature["why"],
        "expenseNatureApplicable": nature["applicable"],
        "expenseNatureNeedsConfirmation": nature["needsConfirmation"],
        "confidence": overall,
        "reasons": reasons,
        "accounts": accounts,
        "journalPreview": journal,
        "amount": round(amount, 2) if amount else None,
        "rulesApplied": rules_applied,
        "warnings": warnings,
        "needReview": overall != "high" or nature["needsConfirmation"],
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- 学习
def record_feedback(entity_id: int, text: str, corrected: dict, *, actor: str = "user",
                    predicted: dict | None = None, party: str = "", doc_kind: str = "") -> dict:
    """人改正一次 → 写样本 → 够格就固化。predicted 不传就先跑一遍分析。"""
    if predicted is None:
        got = analyze(text, entity_id=entity_id, party=party)
        predicted = {
            "partyName": got.get("partyName"),
            "direction": got.get("direction"),
            "accountCode": ",".join(sorted({a["accountCode"] for a in got.get("accounts") or [] if a["accountCode"]})),
        }
    payload = {
        "partyName": corrected.get("partyName") or predicted.get("partyName") or party,
        "direction": corrected.get("direction") or predicted.get("direction"),
        "accountCode": corrected.get("accountCode") or predicted.get("accountCode"),
    }
    kind = doc_kind or ("invoice" if predicted.get("direction") == "sale" else "bill")
    rec = exl.record_correction(entity_id, predicted, payload, actor=actor,
                                doc_kind=kind, raw_excerpt=text[:2000])
    promoted = exl.promote(entity_id)
    return {"recorded": rec, "promoted": promoted}

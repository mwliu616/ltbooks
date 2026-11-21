# LtBooks — core/agents/actions.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""AI 待确认动作：智能体只能「提案」，写入必须由人点确认。

为什么要有这一层
----------------
D-01 规定：没有任何智能体能执行写操作。但「AI 帮我录入一张发票」如果完全不让它
碰数据，人就还得把识别结果手抄一遍，等于没帮上忙。

所以把它拆成两步：

    智能体 → 提案（写 ai_actions 一行，不碰任何业务表）
    人 → 点确认（以登录用户身份执行 service 层的建单函数）→ 才真正入库

- 提案里的 payload 是**结构化字段**，不是自然语言；确认卡片显示的 summary
  是确定性代码算出来的（匹配了哪个供应商、金额对不对、是不是重复），
  不是模型说的。
- 确认时必须带登录用户名，审计链记的是这个人；智能体名字只出现在 created_by。
- 提案可以拒绝，拒绝后什么都不写。
"""
from __future__ import annotations

import json
import re

from ..db import query, query_one, transaction
from ..service import append_audit

# 可提案的动作类型。确认后各自调用既有 service 函数，不另写一套记账逻辑。
ACTION_TYPES = {
    "create_bill": "采购发票",
    "create_invoice": "销售发票",
    "create_expense": "费用",
    "post_document": "记账",
    "import_bank_statement": "银行对账单",
    "import_opening": "上年结转（期初余额）",
}

_PARTY_TABLE = {
    "create_bill": ("vendors", "vendor_id", "vendor_name"),
    "create_invoice": ("customers", "customer_id", "customer_name"),
    "create_expense": (None, None, None),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def match_party(kind: str, name: str, entity_id: int = 1) -> dict:
    """把单据上的往来单位对上档案里的客户/供应商。

    只做「精确 → 忽略大小写 → 包含」三档，不猜；对不上就说对不上，
    让确认卡片显示「将在确认后按新名称建单」。
    """
    table, id_col, name_col = _PARTY_TABLE.get(kind, (None, None, None))
    needle = _norm(name)
    if not table or not needle:
        return {"matched": False, "name": needle, "partyId": None, "candidates": []}

    rows = query(f"""SELECT {id_col} AS id, {name_col} AS name, vendor_code AS code
                       FROM {table} WHERE entity_id=%s""", (entity_id,)) \
        if kind == "create_bill" else \
        query(f"""SELECT {id_col} AS id, {name_col} AS name, customer_code AS code
                    FROM {table} WHERE entity_id=%s""", (entity_id,))

    low = needle.lower()
    exact = [r for r in rows if _norm(r["name"]).lower() == low]
    if exact:
        r = exact[0]
        return {"matched": True, "level": "exact", "name": r["name"],
                "partyId": int(r["id"]), "code": r["code"], "candidates": []}
    loose = [r for r in rows
             if low in _norm(r["name"]).lower() or _norm(r["name"]).lower() in low]
    if len(loose) == 1:
        r = loose[0]
        return {"matched": True, "level": "fuzzy", "name": r["name"],
                "partyId": int(r["id"]), "code": r["code"], "candidates": []}
    # 档案里没有，但这个名称在历史单据里用过 —— 说清楚，别让人以为从来没见过
    hist_table = "bills" if kind == "create_bill" else "invoices"
    hist_col = "vendor_name" if kind == "create_bill" else "supplier_name"
    h = query_one(f"""SELECT COUNT(*) AS n FROM {hist_table}
                       WHERE entity_id=%s AND {hist_col}=%s""", (entity_id, needle))
    uses = int((h or {}).get("n") or 0)
    return {"matched": False, "level": "none", "name": needle, "partyId": None,
            "historyUses": uses,
            "candidates": [{"id": int(r["id"]), "name": r["name"], "code": r["code"]}
                           for r in loose[:5]]}


# 票据内容 → 费用科目的关键词表。命中即用，命中不了才退回历史/默认。
# 这是「看一眼发票就知道这笔是什么钱」的规则层，不依赖模型。
_ACCT_KEYWORDS = [
    (("秘书", "公司秘書", "公司秘书", "secretary", "company secretarial"), ("公司秘書", "秘书")),
    (("核数", "核數", "audit"), ("核數", "审计")),
    (("律师", "律師", "法律", "legal", "notary", "公证"), ("法律",)),
    (("租金", "rent", "lease"), ("租金",)),
    (("差饷", "差餉", "地租", "rates"), ("差餉", "差饷")),
    (("管理费", "管理費", "management fee"), ("管理費", "管理费")),
    (("水电", "水電", "电费", "電費", "水费", "utilities"), ("水電", "水电")),
    (("银行手续费", "銀行手續費", "bank charge", "bank fee"), ("银行手续费", "銀行手續費")),
    (("利息", "interest"), ("利息",)),
    (("差旅", "机票", "機票", "hotel", "travel", "住宿"), ("差旅",)),
    (("应酬", "應酬", "招待", "entertainment", "餐"), ("應酬", "应酬")),
    (("交通", "的士", "taxi", "uber", "地铁", "地鐵", "transport"), ("交通",)),
    (("办公", "辦公", "文具", "stationery", "office"), ("办公费用", "辦公費用")),
    (("电话", "電話", "通讯", "通訊", "telecom", "mobile", "宽频", "寬頻"), ("通訊", "通讯")),
    (("软件", "軟件", "订阅", "訂閱", "software", "saas", "cloud", "aws", "microsoft"), ("IT 服务费", "IT 服務費", "電腦")),
    (("广告", "廣告", "推广", "推廣", "marketing", "advertis"), ("广告", "廣告")),
    (("保险", "保險", "insurance"), ("保險", "保险")),
    (("维修", "維修", "保养", "保養", "repair"), ("維修", "维修")),
    (("培训", "培訓", "training", "课程", "課程"), ("培训", "培訓")),
    (("运输", "運輸", "快递", "快遞", "物流", "courier", "shipping"), ("运输", "運輸")),
    (("薪酬", "薪金", "工资", "工資", "salary", "payroll"), ("薪金", "薪酬")),
    (("强积金", "強積金", "mpf"), ("强积金", "強積金")),
]


def _guess_by_text(text: str, entity_id: int) -> dict | None:
    """按票据文字猜费用科目：关键词 → 科目名片段 → 账套里真实存在的科目。"""
    blob = (text or "").lower()
    if not blob.strip():
        return None
    rows = query("""SELECT account_code, account_name, name_zh_hk, name_en
                      FROM accounts
                     WHERE entity_id=%s AND is_active=1 AND category IN ('expense','cogs')""",
                 (entity_id,))
    for words, name_frags in _ACCT_KEYWORDS:
        if not any(w.lower() in blob for w in words):
            continue
        for frag in name_frags:
            for r in rows:
                names = " ".join(str(r.get(k) or "") for k in ("account_name", "name_zh_hk", "name_en"))
                if frag in names:
                    return {"code": str(r["account_code"]),
                            "why": f"按票据内容命中「{words[0]}」"}
    return None


# ------------------------------------------------------------------ 支出性质
# 「这张单是员工先垫钱、公司再还他」还是「公司直接付给供应商」——
# 两者借贷不同：报销的贷方是「其他应付款—员工」，直接支出是银行或应付账款。
_REIMBURSE_WORDS = ("报销", "報銷", "垫付", "墊付", "垫支", "個人墊付", "个人垫付",
                    "员工", "員工", "本人", "自付", "代垫", "代墊", "reimburse", "expense claim")
_COMPANY_WORDS = ("invoice", "發票", "发票", "账单", "bill", "收据", "receipt",
                  "公司", "有限公司", "ltd", "limited", "co.", "inc", "gmbh")
_PERSON_HINTS = ("先生", "女士", "小姐", "同学", "本人", "员工", "員工")
_ORG_WORDS = ("公司", "有限公司", "集团", "集團", "事务所", "事務所", "银行", "銀行",
              "政府", "大学", "大學", "医院", "醫院", "limited", "ltd", "inc", "llc",
              "corp", "company", "co.", "gmbh", "pte", "plc")
_COMPANY_PAID_WORDS = ("公司直接支出", "公司支付", "公司付款", "对公支付", "對公支付",
                       "公司卡", "企业卡", "企業卡", "corporate card", "company paid",
                       "paid by company")


def _classify_expense_nature(text: str, party: str, payload: dict) -> dict:
    """保守判断公司直付/员工报销；证据不足时返回空值，绝不默认公司支出。"""
    blob = " ".join(str(x) for x in (text or "", party or "",
                                     payload.get("directionWhy") or "") if x).lower()

    # 明确的报销/垫付证据优先于供应商档案，避免把员工代垫错误记成应付供应商。
    if any(w.lower() in blob for w in _REIMBURSE_WORDS):
        return {"nature": "reimburse", "creditCode": "2173",
                "why": "单据出现报销/垫付字样，按员工垫付处理"}
    if any(w in blob for w in ("个人卡", "個人卡", "现金支付", "現金支付", "自付")):
        return {"nature": "reimburse", "creditCode": "2173",
                "why": "单据显示个人卡/现金支付，按员工垫付处理"}
    if any(w in blob for w in _COMPANY_PAID_WORDS):
        return {"nature": "company", "creditCode": "",
                "why": "单据出现公司直接付款依据"}

    p = (party or "").strip()
    org_party = bool(p) and any(w in p.lower() for w in _ORG_WORDS)
    titled_person = bool(p) and any(h in p for h in _PERSON_HINTS)
    chinese_person = bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", p))
    english_person = bool(re.fullmatch(r"[A-Za-z]+(?:\s+[A-Za-z]+){1,2}", p))
    reimbursable = any(w in blob for w in (
        "差旅", "交通", "应酬", "應酬", "餐饮", "餐飲", "住宿", "机票", "機票",
        "travel", "transport", "entertainment", "meal", "hotel"))
    looks_person = bool(p) and not org_party and (
        titled_person or chinese_person or (english_person and reimbursable))
    if looks_person:
        return {"nature": "reimburse", "creditCode": "2173",
                "why": f"往来单位「{p}」像个人，按员工垫付处理"}
    if payload.get("partyId"):
        return {"nature": "company", "creditCode": "",
                "why": "往来单位匹配到供应商档案，按公司直接支出处理"}
    if p and any(w in p.lower() for w in _ORG_WORDS):
        return {"nature": "company", "creditCode": "",
                "why": "往来单位具有机构/公司特征，按公司直接支出处理"}
    return {"nature": "", "creditCode": "",
            "why": "现有证据不足以可靠判断支出性质，需人工选择"}


def _suggest_account(kind: str, party: str, entity_id: int = 1, text: str = "") -> dict:
    """按票据内容 → 学习映射 → 该供应商上次科目 → 默认，逐级回退。"""
    if kind == "create_invoice":
        return {"code": "4100", "why": "销售收入默认科目"}
    # 0) 票据内容（最贴近这张单本身）
    hit = _guess_by_text(text, entity_id)
    if hit:
        return hit
    # 1) 学到的映射（map:supplier=xxx）
    from . import learning
    for r in learning.active_rules(entity_id):
        key = str(r["scene_key"])
        if key.startswith("map:") and _norm(party) and _norm(party).lower() in key.lower():
            code = str(r["learned"]).split()[0] if r["learned"] else ""
            if re.fullmatch(r"\d{3,6}", code):
                return {"code": code, "why": f"按历史习惯（{r['samples']} 次一致）"}
    # 2) 该供应商最近一次账单用的科目
    if kind in ("create_bill", "create_expense"):
        row = query_one("""SELECT expense_account_code FROM bills
                            WHERE entity_id=%s AND vendor_name=%s
                              AND expense_account_code IS NOT NULL
                            ORDER BY bill_id DESC LIMIT 1""", (entity_id, party))
        if row and row["expense_account_code"]:
            return {"code": str(row["expense_account_code"]), "why": "该供应商上次入账用的科目"}
    return {"code": "6200", "why": "默认费用科目"}


def _dup_check(kind: str, party: str, doc_no: str, date: str, gross: float,
               entity_id: int = 1) -> list:
    """查重：同号同主体 / 同主体同日同额。命中就放进风险提示，但不拦。"""
    out = []
    table = "bills" if kind in ("create_bill", "create_expense") else "invoices"
    no_col = "bill_no" if table == "bills" else "invoice_no"
    party_col = "vendor_name" if table == "bills" else "supplier_name"
    date_col = "date" if table == "bills" else "invoice_date"
    if doc_no:
        r = query_one(f"""SELECT {no_col} AS no FROM {table}
                           WHERE entity_id=%s AND {party_col}=%s AND {no_col}=%s LIMIT 1""",
                      (entity_id, party, doc_no))
        if r:
            out.append(f"已经有一张 {r['no']}（同一往来单位同一单号），确认前请核对是否重复")
    if date and gross:
        r = query_one(f"""SELECT {no_col} AS no FROM {table}
                           WHERE entity_id=%s AND {party_col}=%s AND {date_col}=%s
                             AND gross_original=%s LIMIT 1""",
                      (entity_id, party, date, gross))
        if r:
            out.append(f"同一天同一金额已有一张 {r['no']}，可能是同一笔单据的重复录入")
    return out


def build_summary(kind: str, payload: dict, entity_id: int = 1) -> dict:
    """确认卡片的内容。全部由确定性代码算，模型只负责把结果说成人话。"""
    if kind == "import_opening":
        rows_in = payload.get("rows") or []
        dr = round(sum(float(r.get("debit") or 0) for r in rows_in), 2)
        cr = round(sum(float(r.get("credit") or 0) for r in rows_in), 2)
        # 卡片按 description / amount 渲染明细；借/贷方向写进描述里
        preview = [{
            "description": f"{r.get('code') or ''} {r.get('name') or ''} "
                           + ("借" if float(r.get("debit") or 0) else "贷"),
            "amount": float(r.get("debit") or 0) or float(r.get("credit") or 0),
        } for r in rows_in[:14]]
        risks = []
        if abs(dr - cr) > 0.005:
            risks.append(f"借方合计 {dr:,.2f} ≠ 贷方合计 {cr:,.2f}，差 {dr - cr:,.2f}；不平不能入账")
        bad = [r for r in rows_in if not r.get("matched")]
        if bad:
            risks.append(f"{len(bad)} 个科目在账套里找不到（如 {bad[0].get('code')}），确认前请先在科目表里建好")
        return {
            "rows": [
                {"k": "单据类型", "v": "上年结转 · 期初余额"},
                {"k": "期初日期", "v": payload.get("openingDate") or ""},
                {"k": "科目数", "v": str(len(rows_in))},
                {"k": "借方合计", "v": f"{dr:,.2f}"},
                {"k": "贷方合计", "v": f"{cr:,.2f}"},
                {"k": "差额", "v": f"{dr - cr:,.2f}"},
            ],
            "lines": preview[:14],
            "match": {},
            "account": {},
            "asks": [],
            "risks": risks,
            "needsFunctional": False,
            "afterConfirm": "生成一条「上年结转」分录（source=opening），不平会被拒绝",
        }
    party = _norm(payload.get("partyName") or payload.get("party") or "")
    date = str(payload.get("date") or "")
    ccy = str(payload.get("currency") or "HKD").upper()
    amount = _money(payload.get("amountOriginal") or payload.get("amount"))
    tax = _money(payload.get("taxOriginal") or payload.get("taxAmount"))
    gross = round(amount + tax, 2)
    doc_no = _norm(payload.get("docNo") or payload.get("invoiceNo") or "")

    match = match_party(kind, party, entity_id) if kind != "post_document" else {
        "matched": False, "name": party}
    acct = _suggest_account(kind, match.get("name") or party, entity_id)
    risks = _dup_check(kind, match.get("name") or party, doc_no, date, gross, entity_id) \
        if kind != "post_document" else []
    learned = payload.get("learned") or []
    if learned:
        for x in learned:
            risks.append(f"已按学到的规则修正 {x.get('label') or x.get('field')}："
                         f"「{x.get('from')}」→「{x.get('to')}」"
                         f"（同一供应商 {x.get('samples')} 次一致）")
    conf = str(payload.get("confidence") or "")
    if conf == "low":
        risks.append("识别置信度低，请逐项核对原件")
    for w in (payload.get("warnings") or []):
        risks.append(str(w)[:160])

    rows = [
        {"k": "单据类型", "v": ACTION_TYPES.get(kind, kind)},
        {"k": "往来单位", "v": match.get("name") or party or "—"},
        {"k": "日期", "v": date or "—"},
        {"k": "币种", "v": ccy},
        {"k": "金额（不含税）", "v": f"{amount:,.2f}"},
        {"k": "税额", "v": f"{tax:,.2f}"},
        {"k": "合计", "v": f"{gross:,.2f}", "strong": True},
    ]
    if doc_no:
        rows.insert(1, {"k": "对方单号", "v": doc_no})
    why = str(payload.get("directionWhy") or "")
    if why:
        rows.insert(1, {"k": "识别依据", "v": why, "i18n": "why"})
    if kind in ("create_bill", "create_expense"):
        _nat = str(payload.get("expenseNature") or "")
        if _nat:
            _lab = "个人报销（先记其他应付款—员工）" if _nat == "reimburse" else "公司直接支出"
            rows.append({"k": "支出性质", "v": _lab, "i18n": "why"})

    if kind != "post_document":
        _lns = payload.get("lines") or []
        _accts = []
        for _ln in _lns:
            _c = str(_ln.get("accountCode") or "").strip()
            if _c and _c not in _accts:
                _accts.append(_c)
        if len(_accts) > 1:
            rows.append({"k": "费用/收入科目",
                         "v": " + ".join(_accts) + " · 按明细行拆分", "i18n": "why"})
        else:
            rows.append({"k": "费用/收入科目",
                         "v": f"{acct['code']} · {acct['why']}", "i18n": "why"})

    # 拿不准的地方不要只写在风险里，要明确问人。只问真的会影响入账的。
    asks = []
    if kind != "post_document":
        if not match.get("matched"):
            opts = [{"v": "use", "t": "按这个名称建单", "rec": True}]
            for c in (match.get("candidates") or [])[:5]:
                opts.append({"v": f"pick:{c['id']}", "t": f"用档案里的 {c['name']}"})
            opts.append({"v": "skip", "t": "先不建，我再核对"})
            asks.append({"key": "party", "q": "这个往来单位不在档案里，怎么处理？",
                         "options": opts})
        if payload.get("directionNeedsConfirmation"):
            # 只有角色证据冲突/缺失才问方向；未建档本身不是方向不明的理由。
            asks.append({"key": "direction", "q": "这张是采购还是销售？",
                         "options": [{"v": "bill", "t": "采购发票（我方付钱）"},
                                     {"v": "invoice", "t": "销售发票（我方收钱）"}]})
        func_ccy = "HKD"
        if ccy != func_ccy:
            # 外币单据：折算金额要人确认，不让系统自己挑汇率
            rate_hint = ""
            try:
                from ..db import query_one as _q1
                r = _q1("""SELECT rate FROM fx_rates WHERE from_ccy=%s AND to_ccy=%s
                            AND rate_date<=%s ORDER BY rate_date DESC LIMIT 1""",
                        (ccy, func_ccy, date or "2100-01-01"))
                if r and r.get("rate"):
                    rate_hint = f"按最近汇率 {float(r['rate']):.4f} ≈ HKD {amount * float(r['rate']):,.2f}"
            except Exception:
                rate_hint = ""
            if rate_hint:
                opts = [{"v": "rate", "t": "按系统汇率折算", "n": rate_hint, "rec": True},
                        {"v": "manual", "t": "我填港币金额"},
                        {"v": "hkd", "t": "币种识别错了，其实是 HKD"}]
            else:
                # 那天没有汇率：默认就让人填港币金额，别让他选一条走不通的路
                opts = [{"v": "manual", "t": "我填港币金额", "n": "那天没有可用汇率", "rec": True},
                        {"v": "rate", "t": "先按系统汇率试试", "n": "可能仍然缺"},
                        {"v": "hkd", "t": "币种识别错了，其实是 HKD"}]
            asks.append({"key": "fx", "ccy": ccy,
                         "q": "识别到外币，不是港币——折算金额怎么定？",
                         "options": opts})

        if amount <= 0:
            asks.append({"key": "amountMissing", "q": "没读到金额，请在下面「金额」里填上再确认",
                         "options": []})
        if tax == 0 and not payload.get("taxOriginal"):
            asks.append({"key": "tax", "q": "没读到税额，按 0 处理吗？",
                         "options": [{"v": "zero", "t": "按 0（不含税）", "rec": True},
                                     {"v": "keep", "t": "我填一个税额"}]})

    return {
        "rows": rows,
        "match": match,
        "account": acct,
        "asks": asks,
        "needsFunctional": (ccy != "HKD"),
        "risks": risks,
        "lines": payload.get("lines") or [],
        "afterConfirm": ("建一张草稿单据，不入账；草稿仍需复核后才能记账"
                         if kind != "post_document"
                         else "对勾选的草稿执行 提交复核 → 批准 → 记账"),
    }


def propose(entity_id: int, action_type: str, payload: dict, *,
            actor: str = "agent", run_id: int | None = None,
            source_file: str | None = None, actor_role: str = "agent",
            source_path: str | None = None, source_name: str | None = None) -> dict:
    """登记一个提案。这里只写 ai_actions，不碰业务表。"""
    if action_type not in ACTION_TYPES:
        raise ValueError(f"不支持的动作类型：{action_type}")
    payload = dict(payload or {})
    if source_path:
        payload["_sourceFile"] = source_path          # 确认后挂成附件
        payload["_sourceName"] = source_name or ""
    if action_type in ("create_bill", "create_invoice", "create_expense"):
        party = _norm(payload.get("partyName") or payload.get("party"))
        if not party:
            raise ValueError("往来单位不能为空")
        if _money(payload.get("amountOriginal") or payload.get("amount")) <= 0 \
                and not payload.get("lines") and not payload.get("_incomplete"):
            raise ValueError("金额必须大于 0（或提供明细行）")
        payload["partyName"] = party
        m = match_party(action_type, party, entity_id)
        if m.get("partyId"):
            payload["partyId"] = m["partyId"]
        if action_type != "create_invoice":
            _blob = " ".join(str(x) for x in (
                payload.get("directionWhy") or "",
                payload.get("docText") or payload.get("text") or "",
                payload.get("docNo") or "",
                " ".join(str((ln or {}).get("description") or "")
                         for ln in (payload.get("lines") or [])),
                party or "",
            ) if x)
            _hit = _suggest_account(action_type, m.get("name") or party, entity_id, _blob)
            payload.setdefault("expenseAccountCode", _hit["code"])
            payload["_acctWhy"] = _hit["why"]
            # 支出性质：个人报销 / 公司直接支出，决定贷方科目
            _nature = _classify_expense_nature(_blob, party, payload)
            payload.setdefault("expenseNature", _nature["nature"])
            payload.setdefault("_natureWhy", _nature["why"])
            if _nature["creditCode"] and not payload.get("creditAccountCode"):
                payload["_suggestedCredit"] = _nature["creditCode"]
            # 明细行：逐行按内容判科目（一张单多个费用科目就拆成多条借方）
            _lines = payload.get("lines") or []
            if _lines:
                for _ln in _lines:
                    if _ln.get("accountCode"):
                        continue
                    _txt = " ".join(str(x) for x in (
                        _ln.get("description") or "", _blob) if x)
                    _lhit = _suggest_account(action_type, m.get("name") or party, entity_id, _txt)
                    _ln["accountCode"] = _lhit["code"]
                payload["lines"] = _lines
    elif action_type == "post_document":
        docs = payload.get("docs") or []
        if not docs:
            raise ValueError("没有选择要记账的单据")

    summary = build_summary(action_type, payload, entity_id)
    title = _title(action_type, payload, summary)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO ai_actions
                (entity_id, run_id, action_type, title, summary, payload, status,
                 created_by, source_file)
                VALUES (%s,%s,%s,%s,%s,%s,'proposed',%s,%s)""",
                        (entity_id, run_id, action_type, title,
                         json.dumps(summary, ensure_ascii=False),
                         json.dumps(payload, ensure_ascii=False, default=str),
                         actor, source_file))
            aid = cur.lastrowid
        append_audit(conn, {"entity_id": entity_id, "actor": actor,
                            "actor_role": actor_role, "action": "ai_action.propose",
                            "object_type": "ai_actions", "object_id": str(aid),
                            "detail": {"type": action_type, "title": title}})
    return {"actionId": aid, "title": title, "summary": summary,
            "actionType": action_type, "status": "proposed"}


def _title(kind: str, payload: dict, summary: dict) -> str:
    party = (summary.get("match") or {}).get("name") or _norm(payload.get("partyName"))
    if kind == "import_bank_statement":
        if bank_executor is None:
            raise RuntimeError("对账单导入通道未注入")
        return bank_executor({**p, "actor": actor})

    if kind == "import_opening":
        rows_in = payload.get("rows") or []
        return (f"上年结转 · 期初余额 · {len(rows_in)} 个科目 · "
                f"{payload.get('openingDate') or ''}")
    if kind == "post_document":
        docs = payload.get("docs") or []
        return f"记账 {len(docs)} 张草稿"
    gross = 0.0
    for r in summary.get("rows") or []:
        if r.get("k") == "合计":
            try:
                gross = float(str(r["v"]).replace(",", ""))
            except ValueError:
                gross = 0.0
    return f"{ACTION_TYPES.get(kind, kind)} · {party} · {gross:,.2f} {payload.get('currency') or 'HKD'}"


def propose_opening(entity_id: int, parsed: dict, *, actor: str = "user",
                    opening_date: str = "", source_file: str | None = None,
                    source_path: str | None = None, source_name: str | None = None) -> dict:
    """上年末科目余额表 → 待确认提案；确认后生成一条 source=opening 的分录。"""
    from datetime import date as _d
    rows = parsed.get("rows") or []
    totals = parsed.get("totals") or {}
    if not rows:
        raise ValueError("没读到科目行")
    od = opening_date or f"{_d.today().year}-01-01"
    payload = {"rows": rows, "openingDate": od,
               "description": "上年结转 · 期初余额"}
    return propose(entity_id, "import_opening", payload, actor=actor,
                   source_file=source_file, source_path=source_path,
                   source_name=source_name)


def propose_bank_statement(entity_id: int, *, rows: list, header: dict, sha: str,
                           account: dict, warnings: list, actor: str = "user",
                           source_file: str | None = None) -> dict:
    """对账单 → 待确认提案：确认后一次性导入流水并自动核销高置信匹配。"""
    amounts = [float(r.get("amount") or 0) for r in rows]
    debits = round(sum(-a for a in amounts if a < 0), 2)
    credits = round(sum(a for a in amounts if a > 0), 2)
    # 电子表格类对账单常没有表头合计：按明细补出来，并明说是推算的，
    # 不能让人以为做了余额勾稽。
    header = dict(header or {})
    warn = list(warnings or [])
    if header.get("totalDebits") is None or header.get("totalCredits") is None:
        header["totalDebits"] = debits
        header["totalCredits"] = credits
        warn.append("文件没有表头借贷合计，已按明细汇总")
    if header.get("openingBalance") is None:
        header["openingBalance"] = 0.0
        warn.append("文件没有期初余额，按 0 起算（不影响流水本身）")
    if header.get("closingBalance") is None:
        header["closingBalance"] = round(float(header["openingBalance"]) + credits - debits, 2)
        warn.append(f"文件没有期末余额，按「期初 + 存入 − 支出」推算为 {header['closingBalance']:,.2f}")
    warnings = warn
    dates = [str(r.get("date")) for r in rows if r.get("date")]
    period = f"{min(dates)} ~ {max(dates)}" if dates else ""
    acct_label = f"{account.get('name')} ({account.get('currency')})"
    summary = {
        "rows": [
            {"k": "文件类型", "v": "银行对账单（不是发票）"},
            {"k": "账户", "v": acct_label},
            {"k": "账户号", "v": account.get("account_number_masked") or ""},
            {"k": "期间", "v": period},
            {"k": "笔数", "v": str(len(rows))},
            {"k": "支出合计", "v": f"{debits:,.2f}", "num": True},
            {"k": "存入合计", "v": f"{credits:,.2f}", "num": True},
            {"k": "期末余额", "v": f"{float(header.get('closingBalance') or 0):,.2f}", "num": True},
        ],
        "match": {"matched": True, "name": acct_label, "level": "exact",
                  "code": str(account.get("account_id"))},
        "risks": list(warnings or []),
        "lines": [{"description": f"{r.get('date')} · {r.get('description')}",
                   "amount": float(r.get("amount") or 0)} for r in rows[:12]],
        "afterConfirm": ("导入这些流水，并把 P1/P2（同币种、金额一致、日期接近）的匹配自动核销；"
                         "其余的留在「待对账」，可以让我继续逐笔对"),
        "accountId": account.get("account_id"),
    }
    payload = {"bankAccountId": account.get("account_id"), "header": header,
               "lines": rows, "sha256": sha, "fileName": source_file or ""}
    title = f"银行对账单 · {acct_label} · {len(rows)} 笔 · 支出 {debits:,.2f} / 存入 {credits:,.2f}"
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO ai_actions
                (entity_id, action_type, title, summary, payload, status, created_by, source_file)
                VALUES (%s,'import_bank_statement',%s,%s,%s,'proposed',%s,%s)""",
                        (entity_id, title, json.dumps(summary, ensure_ascii=False),
                         json.dumps(payload, ensure_ascii=False, default=str),
                         actor, source_file))
            aid = cur.lastrowid
        append_audit(conn, {"entity_id": entity_id, "actor": actor, "actor_role": "system",
                            "action": "ai_action.propose", "object_type": "ai_actions",
                            "object_id": str(aid),
                            "detail": {"type": "import_bank_statement", "rows": len(rows)}})
    return {"actionId": aid, "title": title, "summary": summary,
            "actionType": "import_bank_statement", "status": "proposed"}


def get(action_id: int, entity_id: int = 1) -> dict | None:
    r = query_one("""SELECT * FROM ai_actions WHERE action_id=%s AND entity_id=%s""",
                  (action_id, entity_id))
    if not r:
        return None
    d = dict(r)
    for k in ("summary", "payload", "result"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                pass
    return d


def pending(entity_id: int = 1, limit: int = 20) -> list:
    rows = query("""SELECT action_id, action_type, title, summary, created_at, created_by,
                           source_file
                      FROM ai_actions WHERE entity_id=%s AND status='proposed'
                      ORDER BY action_id DESC LIMIT %s""", (entity_id, limit))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["summary"] = json.loads(d["summary"])
        except (TypeError, ValueError):
            d["summary"] = {}
        d["created_at"] = d["created_at"].isoformat(sep=" ", timespec="minutes") \
            if hasattr(d["created_at"], "isoformat") else str(d["created_at"])
        out.append(d)
    return out


def cancel(action_id: int, actor: str, entity_id: int = 1, role: str = "user") -> dict:
    row = get(action_id, entity_id)
    if not row:
        raise ValueError("提案不存在")
    if row["status"] != "proposed":
        raise ValueError(f"该提案已是 {row['status']}，不能再放弃")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE ai_actions SET status='cancelled', confirmed_by=%s,
                                  decided_at=NOW(3) WHERE action_id=%s""", (actor, action_id))
        append_audit(conn, {"entity_id": entity_id, "actor": actor, "actor_role": role,
                            "action": "ai_action.cancel", "object_type": "ai_actions",
                            "object_id": str(action_id),
                            "detail": {"title": row["title"]}})
    return {"actionId": action_id, "status": "cancelled"}


def confirm(action_id: int, actor: str, entity_id: int = 1,
            role: str = "admin", post_executor=None, bank_executor=None,
            options: dict | None = None) -> dict:
    """人工确认后才真正写业务表。执行者是登录用户，不是智能体。"""
    row = get(action_id, entity_id)
    if not row:
        raise ValueError("提案不存在")
    if row["status"] != "proposed":
        raise ValueError(f"该提案已是 {row['status']}，不能重复确认")

    payload = dict(row["payload"]) if isinstance(row["payload"], dict) else {}
    kind = row["action_type"]
    _need_amount = payload.get("_incomplete") == "amount"
    # 卡片上可以改的选项（选错银行账户 / 识别错字段）
    for k in ("bankAccountId",):
        if options and options.get(k) not in (None, "", 0, "0"):
            payload[k] = int(options[k])
    # 手工改选科目：识别/建议科目不对时，人可以直接点选
    _acct = (options or {}).get("accountCode")
    if _acct not in (None, "", 0, "0"):
        code = str(_acct).strip()
        if kind in ("create_bill", "create_expense", "create_invoice"):
            _acct_row = query_one(
                "SELECT account_code FROM accounts WHERE entity_id=%s AND account_code=%s AND is_active=1",
                (entity_id, code))
            if not _acct_row:
                raise ValueError(f"科目 {code} 不存在或已停用")
            payload["expenseAccountCode"] = code

    # 支出性质：人行里改过的优先
    _nat = str((options or {}).get("expenseNature") or "").strip()
    if _nat in ("company", "reimburse"):
        payload["expenseNature"] = _nat

    # 贷方（付款方式）：ap = 先挂应付；bank:<id> = 当场从该银行账户付款
    _credit = str((options or {}).get("creditKey") or "ap").strip()
    if _credit.startswith("bank:"):
        try:
            _bid = int(_credit.split(":", 1)[1])
        except (ValueError, IndexError):
            _bid = 0
        if _bid > 0:
            payload["payNowBankId"] = _bid

    original = dict(payload)
    ans = options.get("answers") if options and isinstance(options.get("answers"), dict) else {}
    if ans:
        _dir = ans.get("direction")
        if _dir in ("bill", "invoice"):
            payload["_direction"] = _dir
        effective_kind = kind
        if payload.get("_direction") == "invoice" and kind == "create_bill":
            effective_kind = "create_invoice"
        elif payload.get("_direction") == "bill" and kind == "create_invoice":
            effective_kind = "create_bill"
        if _dir in ("bill", "invoice"):
            # 改购销方向也要改往来单位：销售是受票方，采购是开票方。
            source_name = str(payload.get("_customerName" if _dir == "invoice"
                                          else "_supplierName") or "").strip()
            if source_name:
                payload["partyName"] = source_name
            payload.pop("partyId", None)
            matched = match_party(effective_kind, str(payload.get("partyName") or ""), entity_id)
            if matched.get("partyId"):
                payload["partyId"] = matched["partyId"]

        _ap = ans.get("party")
        if _ap == "skip":
            raise ValueError("已按你的选择先不建单；核对完再导入一次即可")
        if isinstance(_ap, str) and _ap.startswith("pick:"):
            pid = int(_ap.split(":", 1)[1] or 0)
            party_row = query_one("""SELECT customer_id AS id, customer_name AS name FROM customers
                                      WHERE customer_id=%s AND entity_id=%s""", (pid, entity_id)) \
                if effective_kind == "create_invoice" else \
                query_one("""SELECT vendor_id AS id, vendor_name AS name FROM vendors
                             WHERE vendor_id=%s AND entity_id=%s""", (pid, entity_id))
            if party_row:
                payload["partyId"] = int(party_row["id"])
                payload["partyName"] = party_row["name"]
        _fx = ans.get("fx")
        if _fx == "hkd":
            payload["currency"] = "HKD"
            payload.pop("amountFunctionalOverride", None)
        elif _fx == "manual":
            val = (options.get("fields") or {}).get("amountFunctional")
            try:
                fv = float(val)
            except (TypeError, ValueError):
                fv = 0
            if fv <= 0:
                raise ValueError("你选择了「我填港币金额」，但还没填折算金额")
            payload["amountFunctionalOverride"] = fv
        if ans.get("tax") == "keep" and options.get("fields", {}).get("taxOriginal") in (None, ""):
            raise ValueError("你选择了「我填一个税额」，但税额还是空的")

    if options and isinstance(options.get("fields"), dict):
        for k in ("partyName", "date", "docNo", "currency",
                  "amountOriginal", "taxOriginal"):
            v = options["fields"].get(k)
            if v in (None, ""):
                continue
            payload[k] = float(v) if k in ("amountOriginal", "taxOriginal") else str(v).strip()
    if _need_amount and float(payload.get("amountOriginal") or 0) <= 0:
        raise ValueError("金额还是 0：请在卡片的「金额」里填上，再点确认")

    effective_kind = kind
    if payload.get("_direction") == "invoice" and kind == "create_bill":
        effective_kind = "create_invoice"
    elif payload.get("_direction") == "bill" and kind == "create_invoice":
        effective_kind = "create_bill"
    if payload.get("directionNeedsConfirmation") and not payload.get("_direction"):
        raise ValueError("购销方向证据不足，请在确认卡片中选择采购或销售")
    if effective_kind in ("create_bill", "create_expense") \
            and payload.get("expenseNature") not in ("company", "reimburse"):
        raise ValueError("支出性质证据不足，请选择公司直接支出或个人报销")
    if str(payload.get("partyName") or "") != str(original.get("partyName") or "") \
            and effective_kind in ("create_bill", "create_invoice", "create_expense"):
        # 名称被改正后，不能继续沿用改名前匹配到的档案 ID。
        if not str(ans.get("party") or "").startswith("pick:"):
            payload.pop("partyId", None)
            matched = match_party(effective_kind, str(payload.get("partyName") or ""), entity_id)
            if matched.get("partyId"):
                payload["partyId"] = matched["partyId"]
    result: dict
    try:
        result = _execute(kind, payload, actor, role, entity_id, post_executor, bank_executor)
    except Exception as ex:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE ai_actions SET status='failed', confirmed_by=%s,
                                      decided_at=NOW(3), result=%s
                                WHERE action_id=%s""",
                            (actor, json.dumps({"error": str(ex)}, ensure_ascii=False),
                             action_id))
        raise ValueError(f"执行失败：{ex}")

    # 人改过的字段 → 记成纠正样本，喂给票据识别的学习回路
    correction = {"recorded": False}
    try:
        from . import extractor_learning as exl
        if original.get("_sourceFile"):
            correction = exl.record_correction(
                entity_id, original, payload, actor=actor,
                doc_kind="bill" if effective_kind == "create_bill" else
                         ("invoice" if effective_kind == "create_invoice" else "expense"),
                raw_excerpt=str(original.get("sourceNote") or "")[:2000])
    except Exception as ex:      # 学习失败不能影响建单
        correction = {"recorded": False, "error": str(ex)}

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE ai_actions SET status='confirmed', confirmed_by=%s,
                                  decided_at=NOW(3), result=%s
                            WHERE action_id=%s""",
                        (actor, json.dumps(result, ensure_ascii=False, default=str),
                         action_id))
        append_audit(conn, {"entity_id": entity_id, "actor": actor, "actor_role": role,
                            "action": "ai_action.confirm", "object_type": "ai_actions",
                            "object_id": str(action_id),
                            "detail": {"type": kind, "title": row["title"],
                                       "result": result}})
    return {"actionId": action_id, "status": "confirmed", "result": result,
            "correction": correction}


def _attach(kind: str, p: dict, res: dict, actor: str) -> dict:
    """把导入时留下的原件挂到刚建好的单据上（附件表与界面手工上传同一张）。"""
    src = str(p.get("_sourceFile") or "").strip()
    if not src:
        return res
    from .tools_write import _BOUND
    fn = _BOUND.get("register_attachment")
    if fn is None:
        res["attachment"] = {"ok": False, "error": "附件通道未就绪"}
        return res
    doc_id = int(res.get("docId") or 0)
    try:
        got = fn(src,
                 invoice_id=doc_id if kind == "create_invoice" else None,
                 bill_id=doc_id if kind == "create_bill" else None,
                 expense_id=doc_id if kind == "create_expense" else None,
                 actor=actor, file_name=str(p.get("_sourceName") or "") or None)
        res["attachment"] = {"ok": True, **got}
        # 过账后凭证也要能看到同一份原件：再挂一条到日记账
        _entry = int(res.get("entryId") or 0) or int((res.get("post") or {}).get("entryId") or 0)
        if _entry:
            try:
                fn(src, actor=actor, file_name=str(p.get("_sourceName") or "") or None,
                   journal_id=_entry)
            except Exception:
                pass
    except Exception as ex:
        # 附件挂不上不该把单据一起丢掉：单据已建成，把失败原因报出来
        res["attachment"] = {"ok": False, "error": str(ex)}
    return res


def _execute(kind: str, p: dict, actor: str, role: str, entity_id: int,
             post_executor=None, bank_executor=None) -> dict:
    # 卡片上人改判了方向（采购 ⇄ 销售）：这里统一换类型，各分支不用各写一遍
    if p.get("_direction") in ("bill", "invoice"):
        want = p["_direction"]
        if kind == "create_bill" and want == "invoice":
            kind = "create_invoice"
        elif kind == "create_invoice" and want == "bill":
            kind = "create_bill"
    if kind == "import_opening":
        from .tools_write import _BOUND
        lines = [{"accountCode": r.get("code"), "debit": float(r.get("debit") or 0)}
                 if float(r.get("debit") or 0) else
                 {"accountCode": r.get("code"), "credit": float(r.get("credit") or 0)}
                 for r in (p.get("rows") or []) if r.get("code")]
        fn = _BOUND.get("post_opening")
        if fn is None:
            raise RuntimeError("分录通道未注入")
        res = fn(p.get("openingDate"), p.get("description") or "上年结转 · 期初余额",
                 lines, actor)
        return {"docType": "opening", "docId": res.get("entryId"),
                "docNo": res.get("entryNo"), "href": "?p=journal",
                "entryNo": res.get("entryNo"),
                "status": res.get("status") or "posted"}

    from ..service import create_bill, create_invoice, create_expense

    if kind == "create_bill":
        res = create_bill({
            "vendorName": p.get("partyName"),
            "vendorId": p.get("partyId"),
            "vendorInvoiceNo": p.get("docNo") or None,
            "date": p.get("date"),
            "dueDate": p.get("dueDate") or None,
            "currency": p.get("currency") or "HKD",
            "amount": float(p.get("amountOriginal") or 0),
            "taxAmount": float(p.get("taxOriginal") or 0),
            "expenseAccountCode": p.get("expenseAccountCode") or "6200",
            # 个人报销的贷方是「其他应付款—员工」，不是应付账款
            "payableAccountCode": ("2173" if str(p.get("expenseNature") or "") == "reimburse"
                                   else None),
            "lines": p.get("lines") or [],
            "amountFunctionalOverride": p.get("amountFunctionalOverride"),
            "actor": actor,
        }, actor)
        # 选了「立即付款」：同一笔确认里再记一笔付款，结清这张账单
        _pay = None
        _bid = int(p.get("payNowBankId") or 0)
        if _bid > 0:
            try:
                from api import payment_create_core
                _gross = float(p.get("amountOriginal") or 0) + float(p.get("taxOriginal") or 0)
                _pay = payment_create_core({
                    "direction": "made",
                    "amount": _gross,
                    "currency": p.get("currency") or "HKD",
                    "date": p.get("date"),
                    "bankAccountId": _bid,
                    "allocations": [{"docId": res.get("billId"), "amount": _gross}],
                    "actor": actor,
                })
            except Exception as _ex:
                _pay = {"error": str(_ex)[:120]}
        _out = {"docType": "bill", "docId": res.get("billId"),
                "docNo": res.get("billNo"),
                "href": f"?p=bill-view&id={res.get('billId')}"}
        if _pay is not None:
            _out["payment"] = _pay
        return _attach(kind, p, _out, actor)

    if kind == "create_invoice":
        res = create_invoice({
            "supplierName": p.get("partyName"),
            "customerId": p.get("partyId"),
            "invoiceDate": p.get("date"),
            "dueDate": p.get("dueDate") or None,
            "currency": p.get("currency") or "HKD",
            "amountOriginal": float(p.get("amountOriginal") or 0),
            "taxOriginal": float(p.get("taxOriginal") or 0),
            "lines": p.get("lines") or [],
            "amountFunctionalOverride": p.get("amountFunctionalOverride"),
            "performanceObligationStatus": "fulfilled",
            "recognitionPattern": "point_in_time",
            "actor": actor,
        }, actor)
        return _attach(kind, p, {
            "docType": "invoice", "docId": res.get("invoiceId"),
            "docNo": res.get("invoiceNo"),
            "href": f"?p=invoice-view&id={res.get('invoiceId')}"}, actor)

    if kind == "create_expense":
        res = create_expense({
            "category": p.get("partyName"),
            "date": p.get("date"),
            "currency": p.get("currency") or "HKD",
            "amount": float(p.get("amountOriginal") or 0),
            "taxAmount": float(p.get("taxOriginal") or 0),
            "actor": actor,
        }, actor)
        return _attach(kind, p, {
            "docType": "expense", "docId": res.get("expenseId"),
            "docNo": res.get("expenseNo"), "href": "?p=expenses"}, actor)

    if kind == "import_bank_statement":
        if bank_executor is None:
            raise RuntimeError("对账单导入通道未注入")
        return bank_executor({**p, "actor": actor})

    if kind == "post_document":
        # 记账复用 api 层的 one_click_post（内部补齐提交复核与批准）。
        # 这里用注入的方式拿它，避免 core 反向依赖 api。
        if post_executor is None:
            raise RuntimeError("记账执行器未注入，无法执行")
        docs = (p.get("docs") or [])[:50]
        res = []
        for d in docs:
            r = post_executor(str(d.get("kind") or "invoice"),
                              int(d.get("docId") or 0), actor, role)
            res.append({"kind": d.get("kind"), "docId": d.get("docId"),
                        "ok": bool(r.get("ok")), "entryNo": r.get("entryNo"),
                        "error": r.get("error")})
        ok = sum(1 for x in res if x["ok"])
        return {"docs": len(res), "ok": ok, "failed": len(res) - ok, "results": res}

    raise ValueError(f"不支持的动作类型：{kind}")

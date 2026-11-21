# LtBooks — core/agents/extractor_learning.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""票据识别的学习回路：人改一次，系统记住一次。

为什么需要
----------
`core/ai.py` 的提取靠大模型读文本，同一个供应商的单据它每次可能取成不同的名字
（VISION 有时带中文全称、有时不带），单号、税额也会读错。这类错误不是「再多想一会儿」
能修好的，只能靠人改一次、系统记住。

两条学习，一条确定性、一条提示性：

1. **规则（确定性）**——同一供应商同一字段被改成同一个值达阈值 → 生成 `extract_rules`，
   识别之后由 `apply_rules()` 直接改写。不依赖模型是否记得，也不会时好时坏。
2. **提示（few-shot）**——最近几条纠正塞进提取提示，让模型先看到「上次这个供应商
   的单号读错了、正确的是什么」，减少第一次就错。

边界：只学「这家供应商的单据长什么样」（名称、币种、税额习惯、单号格式），
不学任何判断口径（该不该入账、税率合不合法），也与 learning.py 的白名单一致。
"""
from __future__ import annotations

import json
import re
from collections import Counter

from ..db import query, query_one, transaction

PROMOTE_AFTER = 2          # 同一字段被改成同一个值 2 次就固化
HINTS_LIMIT = 3            # 提示里最多塞 3 条历史纠正

# 只学这几样：都是「字段长相」，不涉及判断
LEARNABLE_FIELDS = {
    "partyName": "往来单位名称",
    "currency": "币种",
    "taxOriginal": "税额",
    "docNo": "对方单号",
    "amountOriginal": "不含税金额",
    "date": "日期",
    # 单据分析：同一往来单位的方向与常用科目也该越用越准
    "direction": "单据方向",
    "accountCode": "常用科目",
}

_FIELD_ALIASES = {
    "supplierName": "partyName",
    "customerName": "partyName",
    "invoiceNo": "docNo",
    "invoiceDate": "date",
    "taxAmount": "taxOriginal",
    "amount": "amountOriginal",
}


def vendor_key(name: str) -> str:
    """归一化开票方：去掉标点、空白、大小写与中英混排差异，用于分组。"""
    s = str(name or "").lower()
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", s)
    return s[:120] or "unknown"


def _alias(field: str) -> str:
    return _FIELD_ALIASES.get(field, field)


def _norm_val(field: str, v) -> str:
    if v is None:
        return ""
    if field in ("amountOriginal", "taxOriginal"):
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return str(v)
    if field == "accountCode":
        # 可能是 "6200"、也可能是 [{accountCode:...}] 或 ["6200","6600"]
        if isinstance(v, (list, tuple, set)):
            codes = []
            for x in v:
                if isinstance(x, dict):
                    x = x.get("accountCode") or x.get("code")
                if x not in (None, ""):
                    codes.append(str(x).strip())
            return ",".join(sorted(set(codes)))
        return str(v).strip()
    if field == "direction":
        return str(v).strip().lower()
    return str(v).strip()


def record_correction(entity_id: int, predicted: dict, corrected: dict, *,
                      actor: str, doc_kind: str = "bill",
                      raw_excerpt: str = "") -> dict:
    """记一条纠正样本。只记真的改了东西的那些字段。"""
    changed = []
    for k in LEARNABLE_FIELDS:
        before = _norm_val(k, predicted.get(k))
        after = _norm_val(k, corrected.get(k))
        if after == "" or before == after:
            continue
        changed.append({"field": k, "from": before, "to": after})
    # 没改也记一条：连续多次「确认就是这个值」同样说明这个字段稳定，
    # 只是它不能单独作为固化的理由（promote 要求至少有一次真实纠正）。
    if not changed and not vendor_key(corrected.get("supplierName") or predicted.get("supplierName")
                                      or corrected.get("partyName") or predicted.get("partyName")):
        return {"recorded": False, "changed": []}

    vk = vendor_key(corrected.get("supplierName") or predicted.get("supplierName")
                    or corrected.get("partyName") or predicted.get("partyName") or "")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO extract_samples
                (entity_id, vendor_key, doc_kind, predicted, corrected, changed, raw_excerpt, actor)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (entity_id, vk, doc_kind,
                         json.dumps(predicted, ensure_ascii=False, default=str)[:20000],
                         json.dumps(corrected, ensure_ascii=False, default=str)[:20000],
                         json.dumps(changed, ensure_ascii=False),
                         (raw_excerpt or "")[:2000], actor))
            sid = cur.lastrowid
    return {"recorded": True, "sampleId": sid, "vendorKey": vk, "changed": changed}


def promote(entity_id: int = 1) -> list:
    """把「同一供应商同一字段、改成同一个值」的重复纠正固化成规则。"""
    rows = query("""SELECT vendor_key, changed, corrected FROM extract_samples
                     WHERE entity_id=%s ORDER BY sample_id DESC LIMIT 500""", (entity_id,))
    seen = Counter()        # (vendor, field, 确认后的值) → 出现次数
    fixed = Counter()       # 同上 → 其中被人工改过的次数
    for r in rows:
        try:
            changed = json.loads(r["changed"]) if isinstance(r["changed"], str) else (r["changed"] or [])
            corrected = json.loads(r["corrected"]) if isinstance(r["corrected"], str) else (r["corrected"] or {})
        except (TypeError, ValueError):
            continue
        changed_fields = {_alias(c.get("field")) for c in changed}
        for f in LEARNABLE_FIELDS:
            val = _norm_val(f, corrected.get(f))
            if not val:
                continue
            seen[(r["vendor_key"], f, val)] += 1
            if f in changed_fields:
                fixed[(r["vendor_key"], f, val)] += 1

    made = []
    for (vk, field, value), n in seen.items():
        # 稳定 + 至少被人纠正过一次，才固化成规则
        if n < PROMOTE_AFTER or fixed[(vk, field, value)] < 1 or vk == "unknown" or not value:
            continue
        exist = query_one("""SELECT rule_id, status, samples FROM extract_rules
                              WHERE entity_id=%s AND vendor_key=%s AND field=%s AND value=%s""",
                          (entity_id, vk, field, value))
        if exist:
            if exist["samples"] != n:
                with transaction() as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE extract_rules SET samples=%s WHERE rule_id=%s",
                                    (n, exist["rule_id"]))
            continue
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO extract_rules
                    (entity_id, vendor_key, field, value, mode, samples, status)
                    VALUES (%s,%s,%s,%s,'set',%s,'active')""",
                            (entity_id, vk, field, value[:200], n))
                rid = cur.lastrowid
        made.append({"ruleId": rid, "vendorKey": vk, "field": field,
                     "value": value, "samples": n})
    return made


def guess_vendor(text: str, entity_id: int = 1) -> str:
    """从原文里猜开票方，用来取它的 few-shot 与规则。

    只做「已知名字是否出现在文本里」这种确定性判断，猜不出就返回空——
    猜错比不猜更糟，会让别的供应商的规则套到这张单上。
    """
    from ..db import query as _q
    norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").lower())
    if not norm:
        return ""
    cands = set()
    for r in _q("""SELECT vendor_name AS n FROM vendors WHERE entity_id=%s""", (entity_id,)):
        if r["n"]:
            cands.add(str(r["n"]))
    for r in _q("""SELECT DISTINCT vendor_key AS n FROM extract_samples WHERE entity_id=%s""",
                (entity_id,)):
        if r["n"] and r["n"] != "unknown":
            cands.add(str(r["n"]))
    best = ""
    for name in cands:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", name.lower())
        if len(key) >= 6 and key in norm and len(key) > len(best):
            best = name
    return best


def rules_for(entity_id: int = 1, vendor: str = "", status: str = "active") -> list:
    vk = vendor_key(vendor) if vendor else ""
    if vk:
        return [dict(r) for r in query(
            """SELECT rule_id, vendor_key, field, value, samples, status
                 FROM extract_rules WHERE entity_id=%s AND status=%s AND vendor_key=%s
                ORDER BY samples DESC""", (entity_id, status, vk))]
    return [dict(r) for r in query(
        """SELECT rule_id, vendor_key, field, value, samples, status
             FROM extract_rules WHERE entity_id=%s AND status=%s
            ORDER BY samples DESC LIMIT 200""", (entity_id, status))]


def apply_rules(data: dict, entity_id: int = 1) -> dict:
    """识别之后先套规则再给人看：同一供应商的名称/币种/税额不该每次都不一样。"""
    out = dict(data or {})
    vendor = str(out.get("partyName") or out.get("supplierName") or "")
    if not vendor:
        return out
    applied = []
    for r in rules_for(entity_id, vendor):
        f = str(r["field"])
        if f not in LEARNABLE_FIELDS:
            continue
        # 提取结果里开票方叫 supplierName，规则里统一叫 partyName
        before = out.get(f)
        if before in (None, "") and f == "partyName":
            before = out.get("supplierName")
        new_val = None
        if f in ("amountOriginal", "taxOriginal"):
            try:
                new_val = float(r["value"])
            except (TypeError, ValueError):
                continue
        else:
            new_val = str(r["value"])
        if before is not None and _norm_val(f, before) == _norm_val(f, new_val):
            continue                      # 已经是这个值，就别报告「修正」
        out[f] = new_val
        applied.append({"field": f, "label": LEARNABLE_FIELDS[f],
                        "from": before if before not in (None, "") else "（未取到）",
                        "to": out[f],
                        "ruleId": r["rule_id"], "samples": r["samples"]})
    if applied:
        out["_rulesApplied"] = applied
    return out


def hints_text(entity_id: int = 1, vendor: str = "") -> str:
    """给提取提示的 few-shot：上次这个供应商哪里读错了、正确的是什么。"""
    vk = vendor_key(vendor) if vendor else ""
    if not vk or vk == "unknown":
        return ""
    rows = query("""SELECT changed FROM extract_samples
                     WHERE entity_id=%s AND vendor_key=%s
                     ORDER BY sample_id DESC LIMIT %s""",
                 (entity_id, vk, HINTS_LIMIT))
    lines = []
    for r in rows:
        try:
            changed = json.loads(r["changed"]) if isinstance(r["changed"], str) else (r["changed"] or [])
        except (TypeError, ValueError):
            continue
        for c in changed:
            f = _alias(c.get("field"))
            if f in LEARNABLE_FIELDS:
                lines.append(f"- {LEARNABLE_FIELDS[f]}：读成「{c.get('from')}」，应为「{c.get('to')}」")
    if not lines:
        return ""
    return "【这家供应商的历史纠正，优先按正确值输出】\n" + "\n".join(lines[:6])


def summary(entity_id: int = 1) -> dict:
    s = query_one("""SELECT COUNT(*) n FROM extract_samples WHERE entity_id=%s""", (entity_id,))
    r = query_one("""SELECT SUM(status='active') act, COUNT(*) total FROM extract_rules
                      WHERE entity_id=%s""", (entity_id,))
    # 最近 30 天纠正次数最多的字段
    top = query("""SELECT changed FROM extract_samples WHERE entity_id=%s
                    ORDER BY sample_id DESC LIMIT 100""", (entity_id,))
    cnt = Counter()
    for row in top:
        try:
            changed = json.loads(row["changed"]) if isinstance(row["changed"], str) else (row["changed"] or [])
        except (TypeError, ValueError):
            continue
        for c in changed:
            cnt[_alias(c.get("field"))] += 1
    return {"samples": int((s or {}).get("n") or 0),
            "rules": {"active": int((r or {}).get("act") or 0),
                      "total": int((r or {}).get("total") or 0)},
            "topFields": [{"field": f, "count": n} for f, n in cnt.most_common(5)]}

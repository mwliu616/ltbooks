# LtBooks — core/bankrec.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""银行对账引擎：导入算术校验 + P1–P4 匹配 + 跨币种折算 + 汇率异常。"""
import re
from .money import convert, days_between, dec, sum_money, within_tolerance

DISCLAIMER = "AI-assisted, subject to human review"


def validate_statement(data):
    cur = str(data.get("currency") or "HKD").upper()
    op = dec(data.get("openingBalance", 0))
    cl = dec(data.get("closingBalance", 0))
    dr = dec(data.get("totalDebits", 0))
    cr = dec(data.get("totalCredits", 0))
    bad = [n for n, v in (("openingBalance", op), ("closingBalance", cl),
                          ("totalDebits", dr), ("totalCredits", cr)) if v is None]
    if bad:
        return {"ok": False, "currency": cur, "problems": bad,
                "message": "；".join(f"{b} 非法" for b in bad), "difference": None}

    expected = op + cr - dr
    diff = cl - expected
    detail = []

    lines = data.get("lines")
    if isinstance(lines, list) and lines:
        ld = dec(0)
        lc = dec(0)
        bad_line = False
        for ln in lines:
            a = dec((ln or {}).get("amount"))
            if a is None:
                bad_line = True
                break
            if a < 0:
                ld += -a
            else:
                lc += a
        if bad_line:
            detail.append("明细含非法金额")
        else:
            if ld != dr:
                detail.append(f"明细借方 {ld} ≠ 表头 {dr}")
            if lc != cr:
                detail.append(f"明细贷方 {lc} ≠ 表头 {cr}")

    ok = diff == 0 and not detail
    return {
        "ok": ok, "currency": cur,
        "openingBalance": float(op), "closingBalance": float(cl),
        "totalDebits": float(dr), "totalCredits": float(cr),
        "expectedClosing": float(expected), "difference": float(diff),
        "detailProblems": detail,
        "message": "算术校验通过" if ok else (
            "；".join(detail) if detail else
            f"算术校验失败：期初 {op} + 贷方 {cr} − 借方 {dr} = {expected}，与期末 {cl} 相差 {diff}"),
    }


def _norm_name(v):
    if not isinstance(v, str):
        return ""
    s = re.sub(r"[\s\-_.,;:()\[\]{}'\"`/\\]+", "", v.lower())
    return re.sub(r"(limited|ltd\.?|company|co\.?|corporation|corp\.?|inc\.?|llc)$", "", s).strip()


def name_similarity(a, b):
    x, y = _norm_name(a), _norm_name(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    if len(x) < 2 or len(y) < 2:
        return 0.0
    def grams(s):
        m = {}
        for i in range(len(s) - 1):
            g = s[i:i + 2]
            m[g] = m.get(g, 0) + 1
        return m
    bx, by = grams(x), grams(y)
    hit = sum(min(n, by.get(g, 0)) for g, n in bx.items())
    total = (len(x) - 1) + (len(y) - 1)
    return 0.0 if total == 0 else (2.0 * hit) / total


def reference_matches(bank_ref, doc_no):
    if not isinstance(bank_ref, str) or not isinstance(doc_no, str):
        return False
    ref = bank_ref.upper()
    if not re.search(r"INV-|INVOICE|BILL-|PAY-", ref):
        return False
    def digits(s):
        return "".join(re.findall(r"[A-Z0-9]+", s))
    doc = digits(doc_no.upper().replace(" ", ""))
    if len(doc) < 4:
        return False
    return doc in digits(ref)


def match_bank_lines(bank_lines, documents, policy, rates,
                     tolerance_percent=1.0, tolerance_absolute=5.0):
    cross = (policy or {}).get("cross_currency_match") or {}
    tol_pct = float(cross.get("tolerance_percent", tolerance_percent))
    tol_abs = dec(cross.get("tolerance_absolute", tolerance_absolute))

    matches, pending, unmatched = [], [], []
    claimed, consumed = set(), set()
    ordered = sorted(bank_lines, key=lambda l: (str(l.get("txn_date") or ""), l.get("lineId") or 0))

    for line in ordered:
        lid = line.get("lineId")
        if lid in consumed:
            continue
        lccy = str(line.get("currency") or "").upper()
        cents = dec(line.get("amount_original"))
        if cents is None:
            pending.append({"lineId": lid, "pendingKind": "bank_match", "reason": "流水金额非法"})
            continue
        abs_line = abs(cents)
        cands = []

        for doc in documents:
            did = doc.get("docId")
            if did in claimed:
                continue
            dccy = str(doc.get("currency") or "").upper()
            out = dec(doc.get("outstanding_original"))
            if out is None:
                continue
            gap = days_between(doc.get("txn_date"), line.get("txn_date"))
            if gap is None:
                continue

            same = lccy == dccy
            cmp_amount = abs_line
            conv = None

            if not same:
                need_date = line.get("txn_date")
                row = next((r for r in rates or [] if r
                            and str(r.get("from_ccy", "")).upper() == lccy
                            and str(r.get("to_ccy", "")).upper() == dccy
                            and str(r.get("rate_date"))[:10] == str(need_date)[:10]), None)
                if not row or dec(row.get("rate", 0)) <= 0:
                    pending.append({
                        "lineId": lid, "docId": did, "pendingKind": "fx_missing",
                        "reason": f"跨币种匹配需要 {lccy}→{dccy} 在 {need_date} 的汇率，未取得；不得静默核销",
                        "lineCurrency": lccy, "docCurrency": dccy,
                    })
                    continue
                converted = convert(abs_line, row["rate"])
                if converted is None:
                    continue
                cmp_amount = converted
                conv = {"rate": float(row["rate"]), "rateDate": str(row["rate_date"])[:10],
                        "from": lccy, "to": dccy, "convertedAmount": float(converted)}

            diff = abs(cmp_amount - out)
            pct = 0.0 if out == 0 else float(diff / out) * 100
            score = name_similarity(line.get("counterparty_name"), doc.get("counterparty_name"))
            ref_hit = reference_matches(line.get("bank_ref"), doc.get("doc_no"))
            exact = diff == 0

            rule = conf = None
            if ref_hit and exact and abs(gap) <= 7 and same:
                rule, conf = "P1", "high"
            elif exact and score >= 0.8 and abs(gap) <= 30:
                rule, conf = "P2", "high"
            elif (pct <= tol_pct or diff <= tol_abs or score >= 0.7) and abs(gap) <= 45:
                rule, conf = "P3", "medium"
            else:
                continue

            if not same:
                within = within_tolerance(cmp_amount, out, tol_abs)
                if within is False and pct > tol_pct:
                    rule, conf = "P3", "low"
                elif conf == "high":
                    conf = "medium"

            cands.append({
                "docId": did, "docType": doc.get("docType"), "docNo": doc.get("doc_no"),
                "docCurrency": dccy, "outstandingOriginal": float(out), "dateGap": gap,
                "nameScore": round(score, 3), "refHit": ref_hit, "amountExact": exact,
                "compareAmount": float(cmp_amount), "difference": float(diff),
                "differencePercent": round(pct, 3),
                "rule": rule, "confidence": conf, "sameCurrency": same, "conversion": conv,
            })

        if not cands:
            unmatched.append({"lineId": lid, "txnDate": line.get("txn_date"),
                              "amountOriginal": float(cents), "currency": lccy,
                              "counterparty": line.get("counterparty_name"),
                              "reason": "无满足 P1–P3 的候选单据"})
            continue

        rank = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        cr = {"high": 0, "medium": 1, "low": 2}
        cands.sort(key=lambda c: (rank[c["rule"]], cr[c["confidence"]],
                                  c["difference"], abs(c["dateGap"]), str(c["docId"])))
        best = cands[0]
        auto = (best["rule"] in ("P1", "P2") and best["confidence"] == "high"
                and best["sameCurrency"] and best["difference"] == 0)

        if auto:
            matches.append({"lineId": lid, "docId": best["docId"], "rule": best["rule"],
                            "confidence": best["confidence"], "autoMatch": True,
                            "sameCurrency": True, "candidate": best,
                            "alternateCount": len(cands) - 1})
            claimed.add(best["docId"])
            consumed.add(lid)
        else:
            pending.append({
                "lineId": lid, "docId": best["docId"], "rule": best["rule"],
                "confidence": best["confidence"], "autoMatch": False,
                "sameCurrency": best["sameCurrency"], "pendingKind": "bank_match",
                "reason": _pending_reason(best, len(cands) - 1),
                "candidate": best, "alternatives": cands[1:4],
            })

    return {
        "matches": matches, "pending": pending, "unmatched": unmatched,
        "stats": {"bankLineCount": len(bank_lines), "documentCount": len(documents),
                  "autoMatched": len(matches), "pendingReview": len(pending),
                  "unmatched": len(unmatched),
                  "crossCurrencyPending": sum(1 for p in pending if p.get("sameCurrency") is False)},
        "note": "仅 P1/P2 且 high、同币种、金额精确才自动核销；其余一律人工复核",
        "disclaimer": DISCLAIMER,
    }


def _pending_reason(c, alt):
    parts = []
    if not c["sameCurrency"]:
        cv = c.get("conversion") or {}
        parts.append(f"跨币种（{cv.get('from')}→{cv.get('to')} @ {cv.get('rate')}，折算后 {c['compareAmount']}），折算路径须人工确认")
    if c["rule"] == "P3":
        parts.append("P3 容差匹配不自动核销")
    if c["difference"] != 0:
        parts.append(f"金额差异 {c['difference']}（{c['differencePercent']}%）")
    if alt > 0:
        parts.append(f"另有 {alt} 个候选，存在歧义")
    return "；".join(parts) if parts else "未达自动核销门槛"


def detect_rate_anomalies(rates, window_days=30, threshold_percent=5.0):
    groups = {}
    for r in rates or []:
        if not r or dec(r.get("rate", 0)) is None or dec(r.get("rate", 0)) <= 0:
            continue
        key = f"{str(r.get('from_ccy','')).upper()}->{str(r.get('to_ccy','')).upper()}"
        groups.setdefault(key, []).append(r)

    out = []
    for pair, rows in groups.items():
        rows.sort(key=lambda r: str(r.get("rate_date")))
        for i, cur in enumerate(rows):
            win = [r for r in rows[max(0, i - window_days):i]
                   if (days_between(r.get("rate_date"), cur.get("rate_date")) or 999) <= window_days]
            if len(win) < 5:
                continue
            mean = sum(float(dec(r["rate"])) for r in win) / len(win)
            if mean == 0:
                continue
            dev = (float(dec(cur["rate"])) - mean) / mean * 100
            if abs(dev) > threshold_percent:
                out.append({"pair": pair, "rateDate": str(cur["rate_date"])[:10],
                            "rate": float(dec(cur["rate"])), "windowMean": round(mean, 8),
                            "deviationPercent": round(dev, 3), "thresholdPercent": threshold_percent,
                            "sampleSize": len(win), "pendingKind": "fx_rate_anomaly",
                            "reason": f"汇率 {float(dec(cur['rate']))} 偏离近 {window_days} 天均值 {round(mean,8)} 达 {round(dev,3)}%，超过阈值 {threshold_percent}%"})
    return {"anomalies": out, "windowDays": window_days, "thresholdPercent": threshold_percent,
            "note": "异常仅为风险提示，不自动拒绝付款或冻结交易", "disclaimer": DISCLAIMER}

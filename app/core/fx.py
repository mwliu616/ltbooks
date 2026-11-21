# LtBooks — core/fx.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""汇率解析与期末重估。
绑定日由 rules/fx_policy.yml 决定；找不到汇率转待复核，绝不估算。
货币性项目缺省参与重估（宁可多做，不可漏做）。"""
from .money import convert, dec, parse_date, period_end_date

MISSING = object()


def normalize_policy(raw):
    p = raw or {}
    binding = p.get("rate_binding") or {}
    fb = p.get("fallback") or {}
    monetary = p.get("monetary_items") or {}
    rev = p.get("revaluation") or {}

    def basis(entry, dflt):
        if isinstance(entry, dict):
            return entry.get("basis", dflt)
        if isinstance(entry, str) and entry:
            return entry
        return dflt

    def flag(camel, snake):
        if monetary.get(camel) is False or monetary.get(snake) is False:
            return False
        return True

    return {
        "functional": p.get("functional_currency") or "HKD",
        "default_rate_basis": p.get("default_rate_basis") or "revenue_recognition_date",
        "advance_payment_rate": p.get("advance_payment_rate") is True,
        "fallback_enabled": p.get("fallback_to_prior_business_day") is not False,
        "fallback_tag": fb.get("source_tag") or p.get("fallback_source_tag") or "ECB:fallback",
        "fallback_days": fb.get("max_lookback_days") or p.get("fallback_max_lookback_days") or 5,
        "on_missing": p.get("on_missing") or "pending_review",
        "pending_kind": p.get("pending_kind") or "fx_missing",
        "binding": {
            "revenue": basis(binding.get("revenue"), "revenue_recognition_date"),
            "purchase": basis(binding.get("purchase"), "bill_date"),
            "payment": basis(binding.get("payment"), "payment_date"),
            "bank_line": basis(binding.get("bank_line"), "txn_date"),
            "revaluation": basis(binding.get("revaluation"), "period_end_date"),
        },
        "monetary": {
            "trade_receivables": flag("tradeReceivables", "trade_receivables"),
            "trade_receivables_fx": flag("tradeReceivablesFx", "trade_receivables_fx"),
            "trade_payables": flag("tradePayables", "trade_payables"),
            "trade_payables_fx": flag("tradePayablesFx", "trade_payables_fx"),
            "foreign_bank_accounts": flag("foreignBankAccounts", "foreign_bank_accounts"),
            "contract_assets": flag("contractAssets", "contract_assets"),
            "prepayments": flag("prepayments", "prepayments"),
        },
        "reval": {
            "enabled": rev.get("enabled") is not False,
            "source_type": rev.get("entry_source_type") or "fx_reval",
            "gain_realised": rev.get("gain_loss_account_realised") or "4410",
            "gain_unrealised": rev.get("gain_loss_account_unrealised") or "4420",
            "mark_tax": rev.get("mark_tax_adjustment") is True,
        },
        "cross": p.get("cross_currency_match") or {},
    }


def lookup_rate(rates, rate_date, from_ccy, to_ccy, policy):
    f = (from_ccy or "").upper()
    t = (to_ccy or "").upper()
    if f == t:
        return {"ok": True, "rate": 1.0, "rateDate": rate_date, "source": "identity", "isFallback": False}

    target = parse_date(rate_date)
    if target is None:
        return {"ok": False, "code": "RATE_MISSING",
                "reason": f"汇率日期无法解析：{rate_date}",
                "pendingKind": policy["pending_kind"]}

    rows = []
    for r in rates or []:
        if not r:
            continue
        if str(r.get("from_ccy", "")).upper() != f or str(r.get("to_ccy", "")).upper() != t:
            continue
        rate = dec(r.get("rate"))
        rd = parse_date(r.get("rate_date"))
        if rate is None or rate <= 0 or rd is None:
            continue
        rows.append((rd, rate, r.get("source") or "ECB"))
    rows.sort(key=lambda x: x[0], reverse=True)

    for rd, rate, src in rows:
        if rd == target:
            return {"ok": True, "rate": float(rate), "rateDate": rd.isoformat(),
                    "source": src, "isFallback": False}

    if policy["fallback_enabled"]:
        # 先找之前的（次优），再找之后的：银行实际汇率常常晚几天才入账，
        # 例如 12 日的发票、15 日的信用卡结算。窗口内取最近一条，
        # 并把实际使用的汇率日期一并返回，报表上能看出用的是哪天的价。
        for rd, rate, src in rows:
            if rd < target and (target - rd).days <= policy["fallback_days"]:
                return {"ok": True, "rate": float(rate), "rateDate": rd.isoformat(),
                        "source": policy["fallback_tag"], "isFallback": True}
        for rd, rate, src in sorted(rows, key=lambda x: x[0]):
            if rd > target and (rd - target).days <= policy["fallback_days"]:
                return {"ok": True, "rate": float(rate), "rateDate": rd.isoformat(),
                        "source": policy["fallback_tag"], "isFallback": True}

    return {"ok": False, "code": "RATE_MISSING",
            "reason": f"找不到 {f}→{t} 在 {rate_date} 的汇率（回退窗口 {policy['fallback_days']} 天）",
            "pendingKind": policy["pending_kind"]}


def resolve_rate_date(policy, kind, dates):
    m = {
        "revenue": ("revenue", dates.get("revenueRecognitionDate")),
        "purchase": ("purchase", dates.get("billDate")),
        "payment": ("payment", dates.get("paymentDate")),
        "bank_line": ("bank_line", dates.get("txnDate")),
        "revaluation": ("revaluation", dates.get("periodEnd") or period_end_date(dates.get("period"))),
    }
    if kind not in m:
        return {"rateDate": None, "basis": "unknown", "note": f"未知汇率类型 {kind}"}
    key, value = m[kind]
    basis = policy["binding"].get(key, policy["default_rate_basis"])
    return {"rateDate": value, "basis": basis,
            "note": f"按政策绑定到 {basis}" if value else f"按政策须使用 {basis}，但该日期缺失；不得改用其他日期"}


_SCOPE = {
    "trade_receivable": "trade_receivables",
    "trade_receivable_fx": "trade_receivables_fx",
    "trade_payable": "trade_payables",
    "trade_payable_fx": "trade_payables_fx",
    "foreign_bank_account": "foreign_bank_accounts",
    "contract_asset": "contract_assets",
    "prepayment": "prepayments",
}


def revalue_items(policy_raw, period, period_end, rates, items):
    policy = normalize_policy(policy_raw)
    functional = policy["functional"]
    period_end = period_end or period_end_date(period)
    blockers, revalued, pending, skipped = [], [], [], []
    total = dec(0)

    if period_end is None:
        blockers.append("期末日期无法确定")

    for item in items or []:
        kind = str(item.get("kind", ""))
        ccy = str(item.get("currency") or functional).upper()

        scope_key = _SCOPE.get(kind)
        if scope_key is None or not policy["monetary"].get(scope_key, True):
            skipped.append({"kind": kind, "refId": item.get("refId"), "reason": "不在重估范围（政策显式关闭）"})
            continue
        if ccy == functional:
            skipped.append({"kind": kind, "refId": item.get("refId"), "reason": f"{ccy} 即功能货币，无需重估"})
            continue

        bal = dec(item.get("balanceOriginal"))
        carry = dec(item.get("carryingFunctional", 0))
        if bal is None:
            blockers.append(f"{kind} {item.get('refId')} 原币余额非法")
            continue
        if carry is None:
            blockers.append(f"{kind} {item.get('refId')} 账面功能货币余额非法")
            continue

        look = lookup_rate(rates, period_end, ccy, functional, policy)
        if not look["ok"]:
            pending.append({"kind": kind, "refId": item.get("refId"),
                            "accountCode": item.get("accountCode"), "currency": ccy,
                            "balanceOriginal": float(bal), "reason": look["reason"],
                            "pendingKind": look["pendingKind"], "requiredRateDate": period_end})
            continue

        new_val = convert(bal, look["rate"])
        diff = new_val - carry
        revalued.append({
            "kind": kind, "refId": item.get("refId"), "accountCode": item.get("accountCode"),
            "currency": ccy, "balanceOriginal": float(bal),
            "carryingFunctional": float(carry), "revaluedFunctional": float(new_val),
            "differenceFunctional": float(diff),
            "rate": look["rate"], "rateDate": look["rateDate"],
            "rateSource": look["source"], "isFallback": look["isFallback"],
        })
        total += diff

    entries = []
    for r in revalued:
        diff = dec(r["differenceFunctional"])
        if diff == 0:
            continue
        if not r["accountCode"]:
            blockers.append(f"{r['kind']} {r['refId']} 缺 accountCode，无法生成重估分录")
            continue
        is_asset = r["kind"].startswith("trade_receivable") or r["kind"] in ("foreign_bank_account", "contract_asset")
        gl = policy["reval"]["gain_unrealised"]
        amt = abs(diff)
        # 分录必须一借一贷：科目侧与损益侧的借贷方向永远相反。
        # 之前把损益侧写死成「收益必贷、亏损必借」，负债类重估就会两边同向，
        # 分录不平（试算表当场失衡）。
        acct_debit = (diff > 0) == is_asset
        lines = [
            {"accountCode": r["accountCode"],
             "debit": float(amt) if acct_debit else 0.0,
             "credit": 0.0 if acct_debit else float(amt), "ccy": r["currency"],
             "amountOriginal": r["balanceOriginal"], "rate": r["rate"], "rateDate": r["rateDate"]},
            {"accountCode": gl,
             "debit": 0.0 if acct_debit else float(amt),
             "credit": float(amt) if acct_debit else 0.0, "ccy": functional,
             "amountOriginal": 0.0, "rate": 1.0, "rateDate": r["rateDate"]},
        ]
        entries.append({
            "sourceType": policy["reval"]["source_type"],
            "sourceId": r["refId"],
            "entryDate": period_end,
            "description": f"期末重估 {r['kind']} #{r['refId']} {r['currency']} @ {r['rate']}（{r['rateDate']}）",
            "lines": lines,
            "totalDebit": float(amt), "totalCredit": float(amt),
            "markTaxAdjustment": policy["reval"]["mark_tax"],
        })

    return {
        "period": period, "periodEnd": period_end, "functionalCurrency": functional,
        "revalued": revalued, "entries": entries, "pending": pending, "skipped": skipped,
        "blockers": blockers, "totalGainLossFunctional": float(total),
        "complete": not blockers and not pending,
        "note": f"有 {len(pending)} 项因汇率缺失未计入合计；合计仅为已重估部分" if pending else "所有范围内项目均已重估",
        "disclaimer": "AI-assisted, subject to human review",
    }

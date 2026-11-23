# LtBooks — api.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""LtBooks Ver 1.0 — Python 后端 API（Flask）。
所有写操作在事务内，全部参数化；金额由确定性代码计算。"""
import hashlib
import hmac
import io
import json
import re
import uuid
from pathlib import Path
from datetime import date, timedelta

from werkzeug.exceptions import HTTPException
from flask import Flask, jsonify, request, send_file

from config import (API_HOST, API_PORT, API_TOKEN, STORAGE_DIR, UPLOAD_DIR,
                    WEB_ASSETS_DIR)
from core import auth as authcore
from core import bankrec, reports
from core import backup as backupcore
from core.audit import verify_chain
from core.agent import check_entry
from core.db import DbError, describe_error, query, query_one, transaction
import os as _os
import time as _time
# 业务时区：香港。数据库仍以 UTC 存时间戳，但「今天」按香港本地日算
_os.environ["TZ"] = "Asia/Hong_Kong"
try:
    _time.tzset()
except Exception:
    pass

from core.money import convert, dec, quantize_money, retention_until
from core.numbering import next_no
from core.service import (add_pending, append_audit, create_bill, create_expense,
                         mark_reconciled,
                          create_invoice, load_audit_chain, load_entity,
                          post_bill, post_invoice, reverse_entry, run_revaluation)
from jsonenc import Encoder

app = Flask(__name__)

# 报表口径：已过账 + 已冲销
POSTED_SQL = "e.status IN ('posted','reversed')"
app.json_encoder = Encoder
app.json.sort_keys = False


def J(payload, status=200):
    return app.response_class(json.dumps(payload, cls=Encoder, ensure_ascii=False),
                              status=status, mimetype="application/json; charset=utf-8")


# 写权限的角色集合。cashier 也要能建单、登记收付款、做银行匹配，
# 否则出纳账号登进来什么都点不了（文档里的权限矩阵一直这么写，代码却没给）。
WRITE_ROLES = ("admin", "accountant", "cashier")


def is_admin() -> bool:
    """管理员是「超级个体」账号：所有权限，包括批准自己录入的单据。

    一人公司的现实：老板既是录单人也是审批人。这里不做任何限制，
    但每一次动作都写审计链，事后能查出「谁批了自己录的单」。
    """
    return current_role() == "admin"


@app.before_request
def _guard():
    """内部调用守卫。

    /api/ 经 nginx 暴露在公网，所以不能信任任何客户端头部。
    只有持有内部令牌的调用方（PHP 前端）提供 X-Ledu-Role 才被采信，
    否则一律视为未认证，写操作直接拒绝。
    """
    if request.path == "/health":
        return None
    token = request.headers.get("X-Ledu-Token", "")
    if not API_TOKEN or not hmac.compare_digest(token, API_TOKEN):
        return J({"error": "unauthorized",
                  "message": "缺少或错误的内部令牌；该接口仅供前端服务调用"}, 401)
    return None


def current_role() -> str:
    return request.headers.get("X-Ledu-Role", "")


def require_writer():
    role = current_role()
    if role == "admin" or role in WRITE_ROLES:
        return
    raise PermissionError("当前角色为只读，不能执行写操作")


@app.errorhandler(PermissionError)
def _perm_err(e):
    return J({"error": "forbidden", "message": str(e)}, 403)


@app.errorhandler(DbError)
def _db_err(e):
    return J({"error": e.kind, "message": e.message, "constraint": e.constraint}, 400)


@app.errorhandler(backupcore.BackupError)
def _backup_err(e):
    """备份错误只记录到服务日志，避免把服务器绝对路径返回给浏览器。"""
    app.logger.warning("Backup operation rejected: %s", e)
    message = str(e)
    if message != "另一项备份或恢复操作正在进行，请稍后重试":
        message = ("备份或恢复未通过校验，未继续执行。请检查备份包完整性、"
                   "可用磁盘空间和数据库工具；详细原因已写入服务日志。")
    return J({"error": "backup_error", "message": message}, 400)


@app.errorhandler(ValueError)
def _val_err(e):
    if str(e) == "confirmation_required":
        return J({"error": "confirmation_required",
                  "message": "请明确确认恢复会覆盖当前数据"}, 400)
    message = str(e)
    if request.path.endswith("/pdf") or request.path.endswith(".pdf"):
        from core.i18n import pdf_error
        message = pdf_error(str(request.args.get("lang") or "zh_cn"), message)
    return J({"error": "bad_request", "message": message}, 400)


@app.errorhandler(HTTPException)
def _http_err(e):
    """404/405 等协议错误保留真实状态码，不要伪装成 500。"""
    return J({"error": e.name.lower().replace(" ", "_"), "message": e.description}, e.code)


@app.errorhandler(Exception)
def _any_err(e):
    import traceback
    traceback.print_exc()
    # 不把内部异常/SQL 细节回传给前端，避免泄露表结构与实现细节。
    return J({"error": "internal_error",
              "message": "服务器内部错误，请稍后重试；如持续出现请联系管理员。"}, 500)


def _to_hk(text):
    """中文名称统一以繁体落库：繁体是香港公司注册的中文法定写法。

    输入简体时自动转换，已是繁体时原样返回（s2hk 幂等）。
    """
    t = str(text or "").strip()
    if not t:
        return t
    try:
        from opencc import OpenCC
        return OpenCC("s2hk").convert(t)
    except Exception:
        return t


# ---------------------------------------------------------------- 列表分页
def page_args(default_limit=200, max_limit=2000):
    """统一解析列表分页参数：limit=0 表示全部（受 max_limit 约束）。"""
    try:
        limit = int(request.args.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    if limit <= 0:
        limit = max_limit
    return min(limit, max_limit), offset


def search_clause(q, cols, args):
    """把关键词转成 LIKE 条件，并把参数追加进 args。返回 SQL 片段或空串。"""
    q = str(q or "").strip()
    if not q:
        return ""
    like = f"%{q}%"
    parts = []
    for c in cols:
        parts.append(f"{c} LIKE %s")
        args.append(like)
    return " AND (" + " OR ".join(parts) + ")"


def entity_or_404():
    e = load_entity()
    if not e:
        raise ValueError("没有启用的实体")
    return e


# ------------------------------------------------------------------ 只读
@app.get("/health")
def health():
    return J({"ok": True, "service": "ltbooks-api", "version": "1.0.0"})


@app.post("/auth/login")
def auth_login():
    p = request.get_json(force=True) or {}
    ok, data = authcore.login(
        str(p.get("username", "")).strip(),
        str(p.get("password", "")),
        request.headers.get("X-Real-IP"),
        request.headers.get("User-Agent"))
    if not ok:
        return J(data, 401)
    try:
        authcore.purge_expired()      # 顺手清掉过期会话，省掉外部 cron
    except Exception:
        pass
    with transaction() as conn:
        append_audit(conn, {"entity_id": entity_or_404()["entity_id"],
                            "actor": data["user"]["username"],
                            "actor_role": data["user"]["role"],
                            "action": "auth.login", "object_type": "users",
                            "object_id": str(data["user"]["id"]),
                            "detail": {"username": data["user"]["username"],
                                       "role": data["user"]["role"]}})
    return J(data)


@app.post("/auth/logout")
def auth_logout():
    p = request.get_json(force=True) or {}
    sid = str(p.get("sessionId", ""))
    if sid:
        authcore.delete_session(sid)
    return J({"ok": True})


@app.get("/auth/me")
def auth_me():
    sid = request.headers.get("X-Ledu-Session", "")
    row = authcore.resolve_session(sid)
    if not row:
        return J({"error": "unauthorized", "message": "会话已失效，请重新登录"}, 401)
    authcore.touch_session(sid)
    return J({"user": {"id": row["user_id"], "username": row["username"],
                       "displayName": row["display_name"], "role": row["role"],
                       "mustChange": bool(row["must_change"])},
              "csrfToken": row["csrf_token"]})


@app.post("/auth/change-password")
def auth_change_password():
    sid = request.headers.get("X-Ledu-Session", "")
    row = authcore.resolve_session(sid)
    if not row:
        return J({"error": "unauthorized", "message": "会话已失效"}, 401)
    p = request.get_json(force=True) or {}
    old, new = str(p.get("oldPassword", "")), str(p.get("newPassword", ""))
    u = authcore.get_user(row["username"])
    if not authcore.verify_password(old, u["password_hash"]):
        return J({"error": "bad_request", "message": "原口令不正确"}, 400)
    authcore.change_password(u["user_id"], new)
    with transaction() as conn:
        append_audit(conn, {"entity_id": entity_or_404()["entity_id"],
                            "actor": u["username"], "actor_role": u["role"],
                            "action": "auth.change_password", "object_type": "users",
                            "object_id": str(u["user_id"]), "detail": None})
    return J({"ok": True, "note": "口令已更新"})


@app.get("/admin/users")
def admin_users():
    if not is_admin():
        raise PermissionError("仅管理员可查看用户列表")
    rows = authcore.list_users()
    return J({"users": [dict(r, last_login_at=r["last_login_at"].isoformat(sep=" ", timespec="milliseconds") if r["last_login_at"] else None,
                             created_at=r["created_at"].isoformat(sep=" ", timespec="milliseconds")) for r in rows]})


@app.post("/admin/users")
def admin_create_user():
    if not is_admin():
        raise PermissionError("仅管理员可新建用户")
    p = request.get_json(force=True) or {}
    uid = authcore.create_user(str(p.get("username", "")).strip(),
                               str(p.get("displayName", "")).strip() or str(p.get("username", "")),
                               str(p.get("password", "")),
                               str(p.get("role", "accountant")))
    with transaction() as conn:
        append_audit(conn, {"entity_id": entity_or_404()["entity_id"],
                            "actor": request.headers.get("X-Ledu-User", "admin"),
                            "actor_role": "admin", "action": "user.create",
                            "object_type": "users", "object_id": str(uid),
                            "detail": {"username": p.get("username"), "role": p.get("role")}})
    return J({"userId": uid})


@app.route("/admin/users/<int:uid>", methods=["PATCH"])
def admin_update_user(uid):
    if not is_admin():
        raise PermissionError("仅管理员可编辑用户")
    p = request.get_json(force=True) or {}
    operator = request.headers.get("X-Ledu-User", "")
    u = authcore.get_user_by_id(uid)
    if not u:
        raise ValueError("用户不存在")
    authcore.update_user(uid,
                         str(p.get("displayName", "")).strip(),
                         str(p.get("role", u["role"])),
                         str(p.get("status", u["status"])),
                         operator=operator)
    with transaction() as conn:
        append_audit(conn, {"entity_id": entity_or_404()["entity_id"],
                            "actor": operator or "admin", "actor_role": "admin",
                            "action": "user.update", "object_type": "users",
                            "object_id": str(uid),
                            "detail": {"username": u["username"],
                                       "role": p.get("role"), "status": p.get("status")}})
    return J({"ok": True})


@app.route("/admin/users/<int:uid>", methods=["DELETE"])
def admin_delete_user(uid):
    if not is_admin():
        raise PermissionError("仅管理员可删除用户")
    operator = request.headers.get("X-Ledu-User", "")
    username = authcore.delete_user(uid, operator=operator)
    with transaction() as conn:
        append_audit(conn, {"entity_id": entity_or_404()["entity_id"],
                            "actor": operator or "admin", "actor_role": "admin",
                            "action": "user.delete", "object_type": "users",
                            "object_id": str(uid), "detail": {"username": username}})
    return J({"ok": True})


@app.get("/overview")
def overview():
    e = load_entity()
    if not e:
        return J({"configured": False, "reason": "没有启用的实体"})
    c = query_one("""SELECT
        (SELECT COUNT(*) FROM invoices) AS invoices,
        (SELECT COUNT(*) FROM bills) AS bills,
        (SELECT COUNT(*) FROM expenses) AS expenses,
        (SELECT COUNT(*) FROM bank_accounts WHERE status='active') AS bank_accounts,
        (SELECT COUNT(*) FROM pending_review WHERE status='open') AS open_reviews,
        (SELECT COUNT(*) FROM journal_entries WHERE status='posted') AS posted_entries,
        0 AS _unused""")
    # 应收/应付必须按币种分列：不同币种的原币金额相加没有意义
    def outstanding(table, date_col, gross_functional):
        """按币种列出未结金额。gross_functional 是「含税功能货币金额」表达式：
        invoices 拆了净额与税额两列，bills 只有一列，不能共用同一段 SQL。"""
        rows = query(f"""SELECT currency,
                                SUM(gross_original - settled_original) AS original,
                                SUM(CASE WHEN gross_original > 0
                                         THEN (gross_original - settled_original) / gross_original
                                              * ({gross_functional})
                                         ELSE 0 END) AS functional
                           FROM {table}
                          WHERE entity_id=%s AND status='posted'
                            AND (gross_original - settled_original) > 0
                          GROUP BY currency ORDER BY currency""", (e["entity_id"],))
        return [{"currency": r["currency"],
                 "original": float(dec(r["original"])),
                 "functional": float(dec(r["functional"]))} for r in rows]

    ar = outstanding("invoices", "invoice_date", "amount_functional + COALESCE(tax_functional, 0)")
    ap = outstanding("bills", "date", "amount_functional + COALESCE(tax_amount, 0) * COALESCE(fx_rate, 1)")

    # 总账口径的应收/应付：和资产负债表同一套科目，用来说明
    # 「单据口径 0、但账上还有余额」的差异（例如期初带进来的应收）
    def gl_side(cats):
        rows = query("""SELECT COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
                          FROM journal_lines l
                          JOIN journal_entries e ON e.entry_id=l.entry_id
                          JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
                         WHERE e.entity_id=%s AND e.status IN ('posted','reversed')
                           AND a.fs_line_item IN (%s)"""
                      % ("%s", ",".join(["%s"] * len(cats))),
                      tuple([e["entity_id"]] + list(cats)))
        r = rows[0] if rows else None
        return float(dec(r["dr"]) - dec(r["cr"])) if r else 0.0

    gl_ar = gl_side(("TRADE_RECEIVABLES", "OTHER_RECEIVABLES", "PREPAYMENTS"))
    gl_ap = -gl_side(("TRADE_PAYABLES", "OTHER_PAYABLES"))

    return J({
        "configured": True,
        "arByCurrency": ar,
        "apByCurrency": ap,
        "arFunctional": float(sum((dec(x["functional"]) for x in ar), dec(0))),
        "apFunctional": float(sum((dec(x["functional"]) for x in ap), dec(0))),
        "arGlBalance": gl_ar,
        "apGlBalance": gl_ap,
        "arOriginal": None,
        "apOriginal": None,
        "entity": {
            "id": e["entity_id"], "code": e["entity_code"], "name": e["entity_name"],
            "legalName": e.get("legal_name"), "brNumber": e.get("br_number"),
            "addressLine1": e.get("address_line1"), "addressLine2": e.get("address_line2"),
            "district": e.get("district"), "region": e.get("region"),
            "phone": e.get("phone"), "email": e.get("email"), "website": e.get("website"),
            "functionalCurrency": e["functional_currency"],
            "twoTierStatus": e["two_tier_status"],
            "reportingFramework": e["reporting_framework"],
            "fiscalYearEnd": e.get("fiscal_year_end_mmdd"),
        },
        "counts": {k: int(c[k]) for k in ("invoices", "bills", "expenses", "bank_accounts",
                                          "open_reviews", "posted_entries")},
        "disclaimer": "AI-assisted, subject to human review",
    })


@app.get("/accounts")
def accounts():
    e = entity_or_404()
    return J({"accounts": query(
        """SELECT account_code, account_name, category, fs_line_item, normal_balance,
                  parent_account_code, contra_reclass_target
             FROM accounts WHERE entity_id=%s AND is_active=1 ORDER BY account_code""",
        (e["entity_id"],))})


# ---------------------------------------------------------------- 报价单
def _document_fx(entity: dict, currency: str, on_date, gross_original) -> dict:
    """按单据日期解析真实汇率并计算含税功能货币金额。

    同币种采用 1:1；外币仅从 fx_rates 取价，并沿用系统汇率回退政策。
    找不到汇率时拒绝生成可能误导客户或供应商的折算金额，绝不按 1 估算。
    """
    ccy = str(currency or "").upper()
    functional = str(entity["functional_currency"]).upper()
    if ccy == functional:
        return {"amount_functional": convert(gross_original, 1),
                "fx_rate": dec(1),
                "fx_rate_date": on_date.isoformat() if hasattr(on_date, "isoformat") else on_date}

    from core.fx import lookup_rate, normalize_policy
    from core.service import load_rules
    policy = normalize_policy(load_rules()["fx_policy"])
    # 查询窗口必须覆盖政策允许的完整前后回退天数，不能另写一个 10 天上限。
    days = max(0, int(policy["fallback_days"]))
    rates = query("""SELECT rate_date, from_ccy, to_ccy, rate, source
                       FROM fx_rates
                      WHERE from_ccy=%s AND to_ccy=%s
                        AND rate_date BETWEEN DATE_SUB(%s, INTERVAL %s DAY)
                                          AND DATE_ADD(%s, INTERVAL %s DAY)
                      ORDER BY rate_date DESC""",
                  (ccy, functional, on_date, days, on_date, days))
    look = lookup_rate([dict(r) for r in rates], on_date, ccy, functional, policy)
    if not look.get("ok"):
        raise ValueError(look["reason"] + "；外币单据缺少真实汇率，不得估算")
    return {"amount_functional": convert(gross_original, look["rate"]),
            "fx_rate": dec(look["rate"]), "fx_rate_date": look["rateDate"]}


def _quote_serialize(rows, ids=None):
    out = []
    for r in rows:
        d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
        for k in ("amount_original", "tax_original", "discount_original", "gross_original",
                  "amount_functional", "fx_rate"):
            if d.get(k) is not None:
                d[k] = float(dec(d[k]))
        out.append(d)
    return out


@app.get("/quotes")
def quotes_list():
    e = entity_or_404()
    limit, offset = page_args(default_limit=25)
    q = str(request.args.get("q") or "").strip()
    st = str(request.args.get("status") or "").strip()
    cond, args = ["entity_id=%s"], [e["entity_id"]]
    if st and st != "all":
        cond.append("status=%s"); args.append(st)
    if q:
        cond.append("(quote_no LIKE %s OR customer_name LIKE %s OR subject LIKE %s OR reference LIKE %s OR salesperson LIKE %s)")
        args += [f"%{q}%"] * 5
    where = " AND ".join(cond)
    total = int(query_one(f"SELECT COUNT(*) n FROM quotes WHERE {where}", tuple(args))["n"])
    rows = query(f"""SELECT quote_id, quote_no, customer_name, subject, reference, salesperson,
                            quote_date, valid_until, currency,
                            amount_original, tax_original, discount_original, gross_original,
                            status, contract_id, converted_invoice_id
                       FROM quotes WHERE {where}
                      ORDER BY quote_id DESC LIMIT %s OFFSET %s""",
                 tuple(args + [limit, offset]))
    return J({"quotes": _quote_serialize(rows), "total": total,
              "limit": limit, "offset": offset})


@app.get("/quotes/<int:quote_id>")
def quote_detail(quote_id):
    e = entity_or_404()
    r = query_one("SELECT * FROM quotes WHERE quote_id=%s AND entity_id=%s",
                  (quote_id, e["entity_id"]))
    if not r:
        raise ValueError("报价单不存在")
    d = _quote_serialize([r])[0]
    d["functional_currency"] = e["functional_currency"]
    lines = query("""SELECT line_no, description, unit, quantity, unit_price, amount,
                            tax_rate, tax_amount, notes
                       FROM quote_lines WHERE quote_id=%s ORDER BY line_no""", (quote_id,))
    d["lines"] = [{**dict(x),
                   "quantity": float(dec(x["quantity"])),
                   "unit_price": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "tax_rate": float(dec(x["tax_rate"])) if x["tax_rate"] is not None else None,
                   "tax_amount": float(dec(x["tax_amount"]))} for x in lines]
    return J(d)


def _allocate_doc_no(conn, entity_id, doc_date, kind, supplied, table, column):
    """系统预览号要真正推进序号；自定义号保留，但必须先检查实际占用。"""
    from core.numbering import next_no, peek_no
    supplied = str(supplied or "").strip()
    if supplied and supplied != peek_no(conn, entity_id, doc_date, kind):
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {table} WHERE entity_id=%s AND {column}=%s LIMIT 1",
                        (entity_id, supplied))
            if cur.fetchone():
                raise ValueError("单据编号已存在，请使用自动编号或另填编号")
        return supplied
    for _ in range(500):
        candidate = next_no(conn, entity_id, doc_date, kind)
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {table} WHERE entity_id=%s AND {column}=%s LIMIT 1",
                        (entity_id, candidate))
            if not cur.fetchone():
                return candidate
    raise ValueError("无法分配单据编号，请手工指定")


@app.post("/quotes")
@app.post("/quotes/<int:quote_id>/update")
def quote_create(quote_id=None):
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    existing = None
    if quote_id is not None:
        existing = query_one("SELECT * FROM quotes WHERE quote_id=%s AND entity_id=%s",
                             (quote_id, e["entity_id"]))
        if not existing:
            raise ValueError("报价单不存在")
        if existing["status"] != "draft":
            raise ValueError("只有草稿状态的报价单可以编辑")
    cust = str(p.get("customerName") or "").strip()
    if not cust:
        raise ValueError("客户名称不能为空")
    qdate = p.get("quoteDate") or date.today().isoformat()
    ccy = str(p.get("currency") or "HKD").upper()

    lines = []
    for i, ln in enumerate(p.get("lines") or [], start=1):
        desc = str(ln.get("description") or "").strip()
        if not desc:
            continue
        qty = dec(ln.get("quantity")) if ln.get("quantity") not in (None, "") else dec(1)
        price = dec(ln.get("unitPrice")) if ln.get("unitPrice") not in (None, "") else dec(0)
        discount_rate = dec(ln.get("discountRate")) if ln.get("discountRate") not in (None, "") else dec(0)
        if qty is None or price is None or discount_rate is None:
            raise ValueError(f"第 {i} 行数量、单价或折扣非法")
        if discount_rate < 0 or discount_rate > 100:
            raise ValueError(f"第 {i} 行折扣必须在 0 到 100 之间")
        amt = quantize_money(qty * price * (1 - discount_rate / 100))[0]
        rate = dec(ln.get("taxRate")) if ln.get("taxRate") not in (None, "") else None
        tax = quantize_money(amt * (rate or 0) / 100)[0] if rate else dec(0)
        lines.append((i, desc[:400], (str(ln.get("unit") or "").strip() or None),
                      qty, price, amt, rate, tax, (str(ln.get("notes") or "").strip() or None)))

    if lines:
        amount = sum((l[5] for l in lines), dec(0))
        tax = sum((l[7] for l in lines), dec(0))
    else:
        amount = quantize_money(p.get("amountOriginal") or 0)[0]
        tax = quantize_money(p.get("taxOriginal") or 0)[0]
    discount = dec(p.get("discountOriginal") or 0) or dec(0)
    if discount < 0 or discount > amount:
        raise ValueError("折扣必须在 0 与金额之间")
    net = amount - discount
    ratio = (net / amount) if amount else dec(0)
    tax = quantize_money(tax * ratio)[0]
    gross = net + tax
    fx = _document_fx(e, ccy, qdate, gross)
    customer_id = p.get("customerId") or (
        existing["customer_id"] if existing and cust == existing["customer_name"] else None)
    contract_id = p.get("contractId") or (existing["contract_id"] if existing else None)

    actor = p.get("actor", "system")
    with transaction() as conn:
        with conn.cursor() as cur:
            if existing:
                cur.execute("SELECT status, quote_no FROM quotes WHERE quote_id=%s AND entity_id=%s FOR UPDATE",
                            (quote_id, e["entity_id"]))
                locked = cur.fetchone()
                if not locked or locked["status"] != "draft":
                    raise ValueError("只有草稿状态的报价单可以编辑")
                no = locked["quote_no"]
                qid = quote_id
                cur.execute("""UPDATE quotes SET customer_id=%s, customer_name=%s, subject=%s,
                    reference=%s, salesperson=%s, quote_date=%s, valid_until=%s, currency=%s,
                    amount_original=%s, tax_original=%s, discount_original=%s, gross_original=%s,
                    amount_functional=%s, fx_rate=%s, fx_rate_date=%s, contract_id=%s,
                    terms=%s, notes=%s WHERE quote_id=%s AND entity_id=%s""",
                    (customer_id, cust, str(p.get("subject") or "")[:200] or None,
                     str(p.get("reference") or "")[:100] or None,
                     str(p.get("salesperson") or "")[:100] or None,
                     qdate, p.get("validUntil") or None, ccy, amount, tax, discount, gross,
                     fx["amount_functional"], fx["fx_rate"], fx["fx_rate_date"], contract_id,
                     str(p.get("terms") or "")[:600] or None,
                     str(p.get("notes") or "")[:600] or None, quote_id, e["entity_id"]))
                cur.execute("DELETE FROM quote_lines WHERE quote_id=%s", (quote_id,))
            else:
                no = _allocate_doc_no(conn, e["entity_id"], qdate, "quote",
                                      p.get("quoteNo"), "quotes", "quote_no")
                cur.execute("""INSERT INTO quotes
                    (entity_id, quote_no, customer_id, customer_name, subject, reference, salesperson,
                     quote_date, valid_until, currency, amount_original, tax_original, discount_original,
                     gross_original, amount_functional, fx_rate, fx_rate_date,
                     contract_id, terms, notes, status, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,'draft',%s)""",
                    (e["entity_id"], no, customer_id, cust,
                     str(p.get("subject") or "")[:200] or None,
                     str(p.get("reference") or "")[:100] or None,
                     str(p.get("salesperson") or "")[:100] or None,
                     qdate, p.get("validUntil") or None, ccy, amount, tax, discount, gross,
                     fx["amount_functional"], fx["fx_rate"], fx["fx_rate_date"], contract_id,
                     str(p.get("terms") or "")[:600] or None,
                     str(p.get("notes") or "")[:600] or None, actor))
                qid = cur.lastrowid
            for l in lines:
                cur.execute("""INSERT INTO quote_lines
                    (entity_id, quote_id, line_no, description, unit, quantity, unit_price,
                     amount, tax_rate, tax_amount, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (e["entity_id"], qid) + l)
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "quote.update" if existing else "quote.create",
                            "object_type": "quotes", "object_id": str(qid),
                            "detail": {"quote_no": no, "customer": cust, "gross": float(gross)}})
    return J({"quoteId": qid, "quoteNo": no, "grossOriginal": float(gross), "status": "draft"})


@app.post("/quotes/<int:quote_id>/status")
def quote_set_status(quote_id):
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    st = str(p.get("status") or "").strip()
    if st not in ("draft", "sent", "accepted", "declined", "expired", "converted"):
        raise ValueError("状态不合法")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE quotes SET status=%s
                            WHERE quote_id=%s AND entity_id=%s""",
                        (st, quote_id, e["entity_id"]))
            if cur.rowcount == 0:
                raise ValueError("报价单不存在")
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "quote.status", "object_type": "quotes",
                            "object_id": str(quote_id), "detail": {"status": st}})
    return J({"quoteId": quote_id, "status": st})


@app.post("/quotes/<int:quote_id>/to-invoice")
def quote_to_invoice(quote_id):
    """报价单转销售发票（转出后报价单标记 converted）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    q = query_one("SELECT * FROM quotes WHERE quote_id=%s AND entity_id=%s",
                  (quote_id, e["entity_id"]))
    if not q:
        raise ValueError("报价单不存在")
    if q["converted_invoice_id"]:
        raise ValueError("该报价单已转过发票")
    lines = query("""SELECT description, unit, quantity, unit_price, amount, tax_rate, tax_amount
                       FROM quote_lines WHERE quote_id=%s ORDER BY line_no""", (quote_id,))
    payload = {
        "supplierName": q["customer_name"],
        "customerId": q.get("customer_id"),
        "invoiceDate": date.today().isoformat(),
        "currency": q["currency"],
        "contractId": q.get("contract_id"),
        "discountOriginal": float(dec(q["discount_original"] or 0)),
        "performanceObligationStatus": "fulfilled",
        "recognitionPattern": "point_in_time",
        "lines": [{"description": x["description"], "unit": x["unit"],
                   "quantity": float(dec(x["quantity"])), "unitPrice": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "discountRate": float((1 - dec(x["amount"]) / (dec(x["quantity"]) * dec(x["unit_price"]))) * 100)
                       if dec(x["quantity"]) and dec(x["unit_price"]) else 0,
                   "taxRate": float(dec(x["tax_rate"])) if x["tax_rate"] is not None else None}
                  for x in lines],
        "actor": p.get("actor", "system"),
    }
    res = create_invoice(payload, p.get("actor", "system"))
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE quotes SET status='converted', converted_invoice_id=%s
                            WHERE quote_id=%s""", (res["invoiceId"], quote_id))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "quote.convert", "object_type": "quotes",
                            "object_id": str(quote_id),
                            "detail": {"invoiceId": res["invoiceId"]}})
    return J({"quoteId": quote_id, "invoiceId": res["invoiceId"],
              "invoiceNo": res.get("invoiceNo"), "status": "converted"})


def _has_kind(conn, kind):
    from core.numbering import KINDS
    return kind in KINDS


# ---------------------------------------------------------------- 贷记单
@app.get("/credit-notes")
def credit_notes_list():
    e = entity_or_404()
    limit, offset = page_args(default_limit=25)
    q = str(request.args.get("q") or "").strip()
    cond, args = ["entity_id=%s"], [e["entity_id"]]
    if q:
        cond.append("(credit_no LIKE %s OR party_name LIKE %s)")
        args += [f"%{q}%", f"%{q}%"]
    where = " AND ".join(cond)
    total = int(query_one(f"SELECT COUNT(*) n FROM credit_notes WHERE {where}", tuple(args))["n"])
    rows = query(f"""SELECT credit_id, credit_no, credit_type, party_name, credit_date, currency,
                            amount_original, tax_original, gross_original, reason, status,
                            source_invoice_id, source_bill_id
                       FROM credit_notes WHERE {where}
                      ORDER BY credit_id DESC LIMIT %s OFFSET %s""",
                 tuple(args + [limit, offset]))
    out = [{**{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()},
            "amount_original": float(dec(r["amount_original"])),
            "tax_original": float(dec(r["tax_original"])),
            "gross_original": float(dec(r["gross_original"]))} for r in rows]
    return J({"creditNotes": out, "total": total, "limit": limit, "offset": offset})


def _credit_note_source(entity: dict, kind: str, currency: str,
                        invoice_id=None, bill_id=None):
    """校验贷记单关联原单的类型、归属和币种，防止跨币种直接冲减原币余额。"""
    if invoice_id and bill_id:
        raise ValueError("贷记单只能关联一张原发票或原账单")
    if (kind == "customer" and bill_id) or (kind == "vendor" and invoice_id):
        raise ValueError("客户贷记单只能关联发票，供应商贷记单只能关联账单")
    source_id = invoice_id if kind == "customer" else bill_id
    if not source_id:
        return None
    table = "invoices" if kind == "customer" else "bills"
    id_column = "invoice_id" if kind == "customer" else "bill_id"
    source = query_one(
        f"SELECT {id_column} AS id, currency FROM {table} "
        f"WHERE {id_column}=%s AND entity_id=%s",
        (source_id, entity["entity_id"]),
    )
    if not source:
        raise ValueError("关联原单不存在或不属于当前公司")
    if str(source["currency"]).upper() != str(currency).upper():
        raise ValueError("贷记单与关联原单必须使用相同币种，禁止跨币种直接核销")
    return source


@app.post("/credit-notes")
@app.post("/credit-notes/<int:credit_id>/update")
def credit_note_create(credit_id=None):
    """新建或修改贷记单草稿；已过账、已核销单据保持不可变。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    existing = None
    if credit_id is not None:
        existing = query_one("SELECT * FROM credit_notes WHERE credit_id=%s AND entity_id=%s",
                             (credit_id, e["entity_id"]))
        if not existing:
            raise ValueError("贷记单不存在")
        if existing["status"] != "draft":
            raise ValueError("只有草稿状态的贷记单可以编辑")
    party = str(p.get("partyName") or "").strip()
    if not party:
        raise ValueError("往来单位不能为空")
    kind = str(p.get("creditType") or "customer")
    if kind not in ("customer", "vendor"):
        raise ValueError("类型只能是 customer 或 vendor")
    amount = quantize_money(p.get("amountOriginal") or 0)[0]
    tax = quantize_money(p.get("taxOriginal") or 0)[0]
    if amount is None or amount <= 0:
        raise ValueError("金额必须大于 0")
    if tax is None or tax < 0:
        raise ValueError("税额不能小于 0")
    cdate = p.get("creditDate") or date.today().isoformat()
    ccy = str(p.get("currency") or "HKD").upper()
    _credit_note_source(e, kind, ccy, p.get("sourceInvoiceId"), p.get("sourceBillId"))
    gross = amount + tax
    fx = _document_fx(e, ccy, cdate, gross)
    actor = p.get("actor", "system")
    with transaction() as conn:
        with conn.cursor() as cur:
            if existing:
                cur.execute("SELECT status, credit_no FROM credit_notes WHERE credit_id=%s AND entity_id=%s FOR UPDATE",
                            (credit_id, e["entity_id"]))
                locked = cur.fetchone()
                if not locked or locked["status"] != "draft":
                    raise ValueError("只有草稿状态的贷记单可以编辑")
                no = locked["credit_no"]
                cid = credit_id
                cur.execute("""UPDATE credit_notes SET credit_type=%s, party_name=%s, credit_date=%s,
                    currency=%s, amount_original=%s, tax_original=%s, gross_original=%s,
                    amount_functional=%s, fx_rate=%s, fx_rate_date=%s, reason=%s,
                    source_invoice_id=%s, source_bill_id=%s, revenue_account_code=%s
                    WHERE credit_id=%s AND entity_id=%s""",
                    (kind, party, cdate, ccy, amount, tax, gross,
                     fx["amount_functional"], fx["fx_rate"], fx["fx_rate_date"],
                     str(p.get("reason") or "")[:400] or None,
                     p.get("sourceInvoiceId"), p.get("sourceBillId"),
                     p.get("revenueAccountCode") or None, credit_id, e["entity_id"]))
            else:
                no = _allocate_doc_no(conn, e["entity_id"], cdate, "credit",
                                      p.get("creditNo"), "credit_notes", "credit_no")
                cur.execute("""INSERT INTO credit_notes
                    (entity_id, credit_no, credit_type, party_name, credit_date, currency,
                     amount_original, tax_original, gross_original,
                     amount_functional, fx_rate, fx_rate_date, reason,
                     source_invoice_id, source_bill_id, revenue_account_code, status, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                    (e["entity_id"], no, kind, party, cdate, ccy,
                     amount, tax, gross, fx["amount_functional"], fx["fx_rate"], fx["fx_rate_date"],
                     str(p.get("reason") or "")[:400] or None,
                     p.get("sourceInvoiceId"), p.get("sourceBillId"),
                     p.get("revenueAccountCode") or None, actor))
                cid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "credit_note.update" if existing else "credit_note.create",
                            "object_type": "credit_notes", "object_id": str(cid),
                            "detail": {"credit_no": no, "party": party, "amount": float(gross)}})
    return J({"creditId": cid, "creditNo": no, "status": "draft"})


@app.post("/credit-notes/<int:credit_id>/post")
def credit_note_post(credit_id):
    """贷记单过账：生成一张红字凭证（借收入 / 贷应收，或反向）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    actor = p.get("actor", "system")
    c = query_one("SELECT * FROM credit_notes WHERE credit_id=%s AND entity_id=%s",
                  (credit_id, e["entity_id"]))
    if not c:
        raise ValueError("贷记单不存在")
    if c["status"] != "draft":
        raise ValueError("只有草稿状态的贷记单可以过账")
    # 必须在生成凭证前复核原单；否则类型或币种错误会先入账再失败。
    _credit_note_source(e, c["credit_type"], c["currency"],
                        c.get("source_invoice_id"), c.get("source_bill_id"))
    total_original = dec(c["gross_original"])
    tax_original = dec(c["tax_original"] or 0)
    if c["currency"] == e["functional_currency"]:
        total, tax = total_original, tax_original
    else:
        # 手工分录通道只接受功能货币金额；外币原币直接入账会夸大或缩小损益。
        if not c.get("fx_rate") or c.get("amount_functional") is None:
            raise ValueError("外币贷记单缺少真实汇率或折算金额，禁止过账")
        total = dec(c["amount_functional"])
        tax = convert(tax_original, c["fx_rate"])
    net = total - tax
    is_cust = c["credit_type"] == "customer"
    # 客户贷记：借 收入(净额) + 借 销项税 / 贷 应收(含税)；
    # 供应商贷记：借 应付(含税) / 贷 费用(净额) + 贷 进项税。
    rev_acct = c.get("revenue_account_code") or ("4100" if is_cust else "6200")
    if is_cust:
        lines = [{"accountCode": rev_acct, "debit": float(net)},
                 {"accountCode": "1130", "credit": float(total)}]
        if tax > 0:
            lines.append({"accountCode": "2140", "debit": float(tax)})
    else:
        lines = [{"accountCode": "2110", "debit": float(total)},
                 {"accountCode": rev_acct, "credit": float(net)}]
        if tax > 0:
            lines.append({"accountCode": "1160", "credit": float(tax)})
    # 红字凭证走既有手工凭证通道：借贷平衡、科目存在、期间未锁定都由它保证
    _resp = journal_create_core({
        "entryDate": str(c["credit_date"]),
        "description": f"{c['credit_no']} · {c['party_name']}",
        "currency": c["currency"],
        "lines": lines,
        "actor": actor,
    })
    entry = json.loads(_resp.get_data(as_text=True)) if hasattr(_resp, "get_data") else (_resp or {})
    applied = None
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE credit_notes SET status='posted' WHERE credit_id=%s""",
                        (credit_id,))
            # 关联了原单的，过账时按原币金额冲减未收/未付余额。
            if c.get("source_invoice_id") and is_cust:
                cur.execute("""SELECT gross_original, settled_original FROM invoices
                                WHERE invoice_id=%s AND entity_id=%s""",
                            (c["source_invoice_id"], e["entity_id"]))
                inv = cur.fetchone()
                if inv:
                    cap = dec(inv["gross_original"]) - dec(inv["settled_original"])
                    use = min(total_original, cap) if cap > 0 else dec(0)
                    cur.execute("""UPDATE invoices SET settled_original = settled_original + %s
                                    WHERE invoice_id=%s""", (float(use), c["source_invoice_id"]))
                    applied = {"doc": "invoice", "id": c["source_invoice_id"], "amount": float(use)}
            elif c.get("source_bill_id") and not is_cust:
                cur.execute("""SELECT gross_original, settled_original FROM bills
                                WHERE bill_id=%s AND entity_id=%s""",
                            (c["source_bill_id"], e["entity_id"]))
                bl = cur.fetchone()
                if bl:
                    cap = dec(bl["gross_original"]) - dec(bl["settled_original"])
                    use = min(total_original, cap) if cap > 0 else dec(0)
                    cur.execute("""UPDATE bills SET settled_original = settled_original + %s
                                    WHERE bill_id=%s""", (float(use), c["source_bill_id"]))
                    applied = {"doc": "bill", "id": c["source_bill_id"], "amount": float(use)}
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "credit_note.post", "object_type": "credit_notes",
                            "object_id": str(credit_id),
                            "detail": {"entryId": entry.get("entryId"),
                                       "amountOriginal": float(total_original),
                                       "amountFunctional": float(total),
                                       "currency": c["currency"], "applied": applied}})
    return J({"creditId": credit_id, "status": "posted",
              "entryId": entry.get("entryId"), "entryNo": entry.get("entryNo"),
              "applied": applied})


# ---------------------------------------------------------------- 循环交易
@app.get("/recurring")
def recurring_list():
    e = entity_or_404()
    rows = query("""SELECT rule_id, name, doc_kind, party_name, currency, amount_original,
                           tax_original, description, expense_account_code, revenue_account_code,
                           frequency, start_date, end_date, next_run, last_run, runs_count,
                           auto_post, status
                      FROM recurring_rules WHERE entity_id=%s
                     ORDER BY status='active' DESC, next_run""", (e["entity_id"],))
    out = []
    for r in rows:
        d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
        d["amount_original"] = float(dec(r["amount_original"]))
        d["tax_original"] = float(dec(r["tax_original"]))
        out.append(d)
    return J({"rules": out, "total": len(out)})


def _next_run_date(d, freq):
    from datetime import timedelta
    if freq == "monthly":
        y, m = d.year, d.month + 1
        if m > 12:
            y, m = y + 1, 1
        return date(y, m, min(d.day, 28))
    if freq == "quarterly":
        y, m = d.year, d.month + 3
        while m > 12:
            y, m = y + 1, m - 12
        return date(y, m, min(d.day, 28))
    return date(d.year + 1, d.month, min(d.day, 28))


@app.post("/recurring")
@app.post("/recurring/<int:rule_id>/update")
def recurring_create(rule_id=None):
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    name = str(p.get("name") or "").strip()
    party = str(p.get("partyName") or "").strip()
    if not name or not party:
        raise ValueError("名称与往来单位不能为空")
    kind = str(p.get("docKind") or "invoice")
    if kind not in ("invoice", "bill", "expense"):
        raise ValueError("单据类型不合法")
    freq = str(p.get("frequency") or "monthly")
    if freq not in ("monthly", "quarterly", "yearly"):
        raise ValueError("频率不合法")
    start = p.get("startDate") or date.today().isoformat()
    auto_post = 1 if p.get("autoPost") else 0
    if kind == "expense" and auto_post:
        raise ValueError("费用规则只能生成草稿，不支持自动记账")
    actor = p.get("actor", "system")
    with transaction() as conn:
        with conn.cursor() as cur:
            existing = None
            if rule_id is not None:
                cur.execute("""SELECT * FROM recurring_rules
                                WHERE rule_id=%s AND entity_id=%s FOR UPDATE""",
                            (rule_id, e["entity_id"]))
                existing = cur.fetchone()
                if not existing:
                    raise ValueError("规则不存在")
            values = (name, kind, party, str(p.get("currency") or "HKD").upper(),
                      quantize_money(p.get("amountOriginal") or 0)[0],
                      quantize_money(p.get("taxOriginal") or 0)[0],
                      (str(p.get("description") or "")[:400] or None),
                      p.get("expenseAccountCode"), p.get("revenueAccountCode"), freq,
                      start, p.get("endDate"), auto_post)
            if existing:
                # 已执行过的规则保留下次执行日，避免编辑金额等资料时重复建单。
                next_run = start if int(existing["runs_count"] or 0) == 0 else existing["next_run"]
                cur.execute("""UPDATE recurring_rules SET name=%s, doc_kind=%s, party_name=%s,
                    currency=%s, amount_original=%s, tax_original=%s, description=%s,
                    expense_account_code=%s, revenue_account_code=%s, frequency=%s,
                    start_date=%s, end_date=%s, auto_post=%s, next_run=%s
                  WHERE rule_id=%s AND entity_id=%s""",
                    values + (next_run, rule_id, e["entity_id"]))
                rid = rule_id
            else:
                cur.execute("""INSERT INTO recurring_rules
                    (entity_id, name, doc_kind, party_name, currency, amount_original, tax_original,
                     description, expense_account_code, revenue_account_code, frequency,
                     start_date, end_date, auto_post, next_run, status, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)""",
                    (e["entity_id"],) + values + (start, actor))
                rid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "recurring.update" if existing else "recurring.create",
                            "object_type": "recurring_rules", "object_id": str(rid),
                            "detail": {"name": name, "kind": kind, "frequency": freq}})
    return J({"ruleId": rid, "status": existing["status"] if existing else "active"})


@app.post("/recurring/<int:rule_id>/run")
def recurring_run(rule_id):
    """执行一条循环交易：按规则建一张草稿（可自动记账）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    actor = p.get("actor", "system")
    r = query_one("SELECT * FROM recurring_rules WHERE rule_id=%s AND entity_id=%s",
                  (rule_id, e["entity_id"]))
    if not r:
        raise ValueError("规则不存在")
    if r["status"] != "active":
        raise ValueError("规则已暂停或结束")
    run_date = str(r["next_run"])
    created = None
    if r["doc_kind"] == "invoice":
        created = create_invoice({
            "supplierName": r["party_name"], "invoiceDate": run_date,
            "subject": r["description"] or r["name"], "currency": r["currency"],
            "amountOriginal": float(dec(r["amount_original"])),
            "taxOriginal": float(dec(r["tax_original"])),
            "performanceObligationStatus": "fulfilled",
            "recognitionPattern": "point_in_time",
            "actor": actor,
        }, actor)
        doc_no = created.get("invoiceNo")
        doc_id = created.get("invoiceId")
    else:
        created = create_bill({
            "vendorName": r["party_name"], "date": run_date,
            "subject": r["description"] or r["name"], "currency": r["currency"],
            "amount": float(dec(r["amount_original"])),
            "taxAmount": float(dec(r["tax_original"])),
            "expenseAccountCode": r.get("expense_account_code") or "6200",
            "actor": actor,
        }, actor) if r["doc_kind"] == "bill" else create_expense({
            "category": r["party_name"], "date": run_date, "currency": r["currency"],
            "amount": float(dec(r["amount_original"])),
            "taxAmount": float(dec(r["tax_original"])),
            "expenseAccountCode": r.get("expense_account_code") or "6600",
            "notes": r["description"], "actor": actor,
        }, actor)
        doc_no = created.get("billNo") or created.get("expenseNo")
        doc_id = created.get("billId") or created.get("expenseId")
    post_result = None
    if r["auto_post"] and r["doc_kind"] in ("invoice", "bill"):
        post_result = one_click_post(r["doc_kind"], int(doc_id or 0), actor,
                                     str(p.get("role") or "admin"))
    _base = r["next_run"]
    _base = _base if isinstance(_base, date) else date.fromisoformat(str(_base))
    nxt = _next_run_date(_base, r["frequency"])
    ended = r["end_date"] and nxt > r["end_date"]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE recurring_rules
                              SET last_run=%s, next_run=%s, runs_count=runs_count+1,
                                  status=%s
                            WHERE rule_id=%s""",
                        (r["next_run"], nxt, "ended" if ended else "active", rule_id))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "recurring.run", "object_type": "recurring_rules",
                            "object_id": str(rule_id),
                            "detail": {"rule": r["name"], "docNo": doc_no, "date": run_date}})
    return J({"ruleId": rule_id, "docNo": doc_no, "docId": doc_id,
              "nextRun": nxt.isoformat(), "status": "ended" if ended else "active",
              "postResult": post_result})


@app.post("/recurring/<int:rule_id>/status")
def recurring_status(rule_id):
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    st = str(p.get("status") or "paused")
    if st not in ("active", "paused", "ended"):
        raise ValueError("状态不合法")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE recurring_rules SET status=%s
                            WHERE rule_id=%s AND entity_id=%s""",
                        (st, rule_id, e["entity_id"]))
    return J({"ruleId": rule_id, "status": st})


# ---------------------------------------------------------------- 月结工作台
CLOSE_STEPS = [
    ("recon",    "银行对账完成"),
    ("ar_ap",    "应收应付核对"),
    ("fx",       "汇率补齐"),
    ("revalue",  "外币重估"),
    ("accrual",  "计提与调整"),
    ("lock",     "锁账并出报表"),
]


@app.get("/period-close")
def period_close_state():
    """月结流水线状态：六步，各步完成情况 + 可自动/需人工标注。"""
    e = entity_or_404()
    period = str(request.args.get("period") or date.today().strftime("%Y-%m"))
    rows = query("""SELECT step_key, status, detail, finished_at, actor
                      FROM period_close_runs WHERE entity_id=%s AND period=%s""",
                 (e["entity_id"], period))
    # 每步的可量化现状：前端按当前语言自行组织句子，避免把中文句子写死在库里
    def _params(key):
        if key == "recon":
            n = int(query_one("""SELECT COUNT(*) c FROM bank_lines
                                  WHERE entity_id=%s AND match_status='unmatched'""",
                              (e["entity_id"],))["c"])
            return {"unmatched": n}
        if key == "ar_ap":
            inv = query_one("""SELECT COUNT(*) c, COALESCE(SUM(gross_original-settled_original),0) s
                                 FROM invoices WHERE entity_id=%s AND status='posted'
                                  AND (gross_original-settled_original)>0""", (e["entity_id"],))
            bill = query_one("""SELECT COUNT(*) c, COALESCE(SUM(gross_original-settled_original),0) s
                                  FROM bills WHERE entity_id=%s AND status='posted'
                                   AND (gross_original-settled_original)>0""", (e["entity_id"],))
            return {"arCount": int(inv["c"]), "arAmount": float(dec(inv["s"])),
                    "apCount": int(bill["c"]), "apAmount": float(dec(bill["s"]))}
        if key == "fx":
            n = int(query_one("""SELECT COUNT(*) c FROM fx_rates
                                  WHERE rate_date >= %s AND source='ECB'""",
                              (f"{period}-01",))["c"])
            return {"ecbRows": n}
        return None

    by = {r["step_key"]: r for r in rows}
    steps = []
    for key, name in CLOSE_STEPS:
        r = by.get(key)
        steps.append({
            "key": key, "name": name,
            "status": (r or {}).get("status") or "pending",
            "detail": (r or {}).get("detail"),
            "params": _params(key),
            "finishedAt": (r["finished_at"].isoformat(sep=" ", timespec="minutes")
                           if r and r.get("finished_at") else None),
            "auto": key in ("recon", "fx", "revalue"),
        })
    done = sum(1 for s in steps if s["status"] == "done")
    return J({"period": period, "steps": steps, "done": done, "total": len(steps)})


def _mark_step(conn, entity_id, period, key, name, status, detail, actor):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO period_close_runs
            (entity_id, period, step_key, step_name, status, detail, actor, finished_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(3))
            ON DUPLICATE KEY UPDATE status=VALUES(status), detail=VALUES(detail),
                                    actor=VALUES(actor), finished_at=NOW(3)""",
            (entity_id, period, key, name, status, detail, actor))


@app.post("/period-close/run")
def period_close_run():
    """执行一个月结步骤。key=all 时只跑可自动的三步。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    period = str(p.get("period") or date.today().strftime("%Y-%m"))
    actor = p.get("actor", "system")
    want = str(p.get("step") or "all")

    result = []
    keys = [k for k, _ in CLOSE_STEPS] if want == "all" else [want]
    auto = {"recon", "fx", "revalue"}
    if want == "all":
        keys = [k for k in keys if k in auto]

    for key in keys:
        name = dict(CLOSE_STEPS).get(key)
        if not name:
            continue
        status, detail = "done", ""
        if key == "recon":
            n = int(query_one("""SELECT COUNT(*) c FROM bank_lines
                                  WHERE entity_id=%s AND match_status='unmatched'""",
                              (e["entity_id"],))["c"])
            detail = f"未匹配流水 {n} 笔" + ("（需人工处理）" if n else "，全部匹配")
            status = "failed" if n else "done"
        elif key == "ar_ap":
            inv = query_one("""SELECT COUNT(*) c, COALESCE(SUM(gross_original-settled_original),0) s
                                 FROM invoices WHERE entity_id=%s AND status='posted'
                                  AND (gross_original-settled_original)>0""", (e["entity_id"],))
            bill = query_one("""SELECT COUNT(*) c, COALESCE(SUM(gross_original-settled_original),0) s
                                  FROM bills WHERE entity_id=%s AND status='posted'
                                   AND (gross_original-settled_original)>0""", (e["entity_id"],))
            detail = (f"未收 {int(inv['c'])} 张 / {float(dec(inv['s'])):,.2f}；"
                      f"未付 {int(bill['c'])} 张 / {float(dec(bill['s'])):,.2f}")
        elif key == "fx":
            n = int(query_one("""SELECT COUNT(*) c FROM fx_rates
                                  WHERE rate_date >= %s AND source='ECB'""",
                              (f"{period}-01",))["c"])
            detail = f"本月已抓取 {n} 条 ECB 汇率"
            status = "done" if n else "failed"
            if not n:
                detail += "（无数据，请检查汇率更新任务）"
        elif key == "revalue":
            detail = "外币重估：请在汇率页确认本月是否有外币余额需要重估"
        elif key == "accrual":
            detail = "计提与调整：请确认折旧、应计费用、预付款摊销是否已入账"
        elif key == "lock":
            detail = "锁账：确认无误后锁定期间，锁后不可直接修改"
        with transaction() as conn:
            _mark_step(conn, e["entity_id"], period, key, name, status, detail, actor)
            append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                                "action": "period_close.step", "object_type": "period_close_runs",
                                "object_id": f"{period}:{key}",
                                "detail": {"status": status, "detail": detail}})
        result.append({"key": key, "name": name, "status": status, "detail": detail})

    return J({"period": period, "ran": result})


# ---------------------------------------------------------------- 报表汇总
@app.get("/reports/summary")
def reports_summary():
    """报表中心统一取数：给定期间，一次返回三表关键数 + 与上期对比。

    损益数字直接取 `reports.profit_and_loss()`，与损益表、利得税页同一口径；
    不再自己按科目类别重算 —— 否则报表中心的「收入」会与损益表差一个汇兑科目。
    """
    e = entity_or_404()
    eid = e["entity_id"]
    period = str(request.args.get("period") or date.today().strftime("%Y-%m"))

    def _month_range(p):
        y, m = int(p[:4]), int(p[5:7])
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        return start, end

    start, end = _month_range(period)
    prev_y, prev_m = (start.year - 1, 12) if start.month == 1 else (start.year, start.month - 1)
    prev_p = f"{prev_y:04d}-{prev_m:02d}"
    p_start, p_end = _month_range(prev_p)

    def block(s: date, t_exclusive: date) -> dict:
        # profit_and_loss 用「> from 且 <= to」：端点各让一天，保证首尾都算进去
        pl = reports.profit_and_loss(eid, (s - timedelta(days=1)).isoformat(),
                                     (t_exclusive - timedelta(days=1)).isoformat())
        return {
            "revenue": round(float(pl["revenue"]["total"]), 2),
            "cogs": round(float(pl["costOfSales"]["total"]), 2),
            "grossProfit": round(float(pl["grossProfit"]), 2),
            "otherIncome": round(float(pl["otherIncome"]["total"]), 2),
            "otherGains": round(float(pl["otherGains"]["total"]), 2),
            "expense": round(float(pl["operatingExpenses"]["total"]), 2),
            "finance": round(float(pl["financeCosts"]["total"]), 2),
            "netProfit": round(float(pl["profitBeforeTax"]), 2),
        }

    cur = block(start, end)
    prev = block(p_start, p_end)

    bs = reports.balance_sheet(eid, (end - timedelta(days=1)).isoformat())
    tb = reports.trial_balance(eid)
    return J({
        "period": period, "prevPeriod": prev_p,
        "pnl": {"current": cur, "previous": prev,
                "delta": {k: round(cur[k] - prev[k], 2) for k in cur}},
        "balance": {
            "assets": bs["assets"]["total"], "liabilities": bs["liabilities"]["total"],
            "equity": bs["equity"]["total"],
            "balanced": bs["check"]["balanced"], "difference": bs["check"]["difference"],
        },
        "trialBalance": {"balanced": tb["balanced"], "difference": tb["difference"]},
    })


def profit_tax_data(e, year: str = "") -> dict:
    """香港利得税计算表的数据。

    会计数字来自损益表（课税年度 4/1–3/31），税额由 core.tax 按两级制计算；
    资格未确定（undetermined）时**不计算税额**，这是规矩，不是遗漏。
    """
    from core import tax
    from core.reports import profit_and_loss

    y = str(year or "").strip()
    if not re.match(r"^\d{4}/\d{2}$", y):
        t = date.today()
        yy = t.year if t.month >= 4 else t.year - 1
        y = f"{yy}/{str(yy + 1)[2:]}"
    y0 = int(y[:4])
    start, end = date(y0, 4, 1), date(y0 + 1, 3, 31)
    period = end.strftime("%Y-%m")          # 2027-03 → 课税年度 2026/27

    pl = profit_and_loss(e["entity_id"], start.isoformat(), end.isoformat())
    # 必须把课税年度传下去：否则 compute 会用「全部历史」当会计利润，
    # 与上面按基期算出来的 pl 对不上（跨年时直接算错税）。
    tp = tax.compute(e, period, ya=y)
    status = str(tp.get("twoTierStatus") or "undetermined")
    rates = {"nominated": "8.25% / 16.5%", "not_nominated": "16.5%",
             "undetermined": "—"}.get(status, "—")
    return {
        "period": period,
        "yearOfAssessment": y,
        "start": start.isoformat(), "end": end.isoformat(),
        "revenue": float(pl["revenue"]["total"]),
        "costOfSales": float(pl["costOfSales"]["total"]),
        "grossProfit": float(pl["grossProfit"]),
        "otherIncome": float(pl["otherIncome"]["total"]),
        "otherGains": float(pl["otherGains"]["total"]),
        "operatingExpenses": float(pl["operatingExpenses"]["total"]),
        "financeCosts": float(pl["financeCosts"]["total"]),
        "accountingProfit": float(tp.get("accountingProfit") or 0),
        "assessableProfit": float(tp.get("assessableProfit") or 0),
        "twoTierStatus": status,
        "rate": rates,
        "taxPayable": tp.get("taxPayable"),
        "computed": bool(tp.get("computed")),
        "reason": tp.get("reason") or "",
        "addBacks": tp.get("addBacks") or [],
        "deducts": tp.get("deducts") or [],
        "capitalAllowances": tp.get("capitalAllowances") or [],
        "basis": "已过账与已冲销分录，按 entry_date 归期，港币本位",
    }


@app.get("/tax/profit-tax")
def tax_profit_tax():
    """香港利得税计算表：课税年度 4/1–3/31，两级制。"""
    e = entity_or_404()
    return J(profit_tax_data(e, str(request.args.get("year") or "")))


# ---------------------------------------------------------------- 待处理队列
@app.get("/workbench/todo")
def workbench_todo():
    """今天要处理什么：识别待确认、待记账、逾期未收、待核销、缺附件。"""
    e = entity_or_404()
    eid = e["entity_id"]
    items = []

    # 1) 草稿（待确认 / 待提交）
    for r in query("""SELECT invoice_id id, invoice_no no, supplier_name party, invoice_date d,
                             gross_original amt, currency ccy, status, created_at
                        FROM invoices WHERE entity_id=%s AND status='draft'
                       ORDER BY invoice_id DESC LIMIT 50""", (eid,)):
        items.append({"kind": "invoice_draft", "label": "销售发票草稿", "id": r["id"],
                      "docNo": r["no"], "party": r["party"], "date": str(r["d"]),
                      "amount": float(dec(r["amt"])), "currency": r["ccy"],
                      "action": "提交记账", "href": f"?p=invoice-view&id={r['id']}"})
    for r in query("""SELECT bill_id id, bill_no no, vendor_name party, date d,
                             gross_original amt, currency ccy, status
                        FROM bills WHERE entity_id=%s AND status='draft'
                       ORDER BY bill_id DESC LIMIT 50""", (eid,)):
        items.append({"kind": "bill_draft", "label": "采购发票草稿", "id": r["id"],
                      "docNo": r["no"], "party": r["party"], "date": str(r["d"]),
                      "amount": float(dec(r["amt"])), "currency": r["ccy"],
                      "action": "提交记账", "href": f"?p=bill-view&id={r['id']}"})

    # 2) 逾期待收
    for r in query("""SELECT invoice_id id, invoice_no no, supplier_name party, invoice_date d,
                             due_date dd, (gross_original-settled_original) amt, currency ccy,
                             DATEDIFF(CURDATE(), due_date) overdue_days,
                             CASE WHEN DATEDIFF(CURDATE(), due_date) <= 30 THEN '1-30'
                                  WHEN DATEDIFF(CURDATE(), due_date) <= 60 THEN '31-60'
                                  WHEN DATEDIFF(CURDATE(), due_date) <= 90 THEN '61-90'
                                  ELSE '91+' END aging_bucket
                        FROM invoices WHERE entity_id=%s AND status='posted'
                         AND (gross_original-settled_original)>0
                         AND due_date IS NOT NULL AND due_date < CURDATE()
                       ORDER BY due_date LIMIT 30""", (eid,)):
        items.append({"kind": "overdue_ar", "label": "逾期未收", "id": r["id"],
                      "docNo": r["no"], "party": r["party"], "date": str(r["d"]),
                      "dueDate": str(r["dd"]), "amount": float(dec(r["amt"])), "currency": r["ccy"],
                      "daysOverdue": int(r["overdue_days"]), "agingBucket": r["aging_bucket"],
                      "action": "去催收 / 核销", "href": f"?p=invoice-view&id={r['id']}"})

    # 3) 待处理（校验阻断等）：同时给真实单号，AI 工作台才能继续查明细，
    # 不把 invoices#123 这类数据库内部引用当成可查询单号。
    for r in query("""SELECT pr.review_id id, pr.kind, pr.reason, pr.severity,
                             pr.ref_table, pr.ref_id, pr.created_at,
                             CASE pr.ref_table WHEN 'invoices' THEN i.invoice_no
                                               WHEN 'bills' THEN b.bill_no END doc_no,
                             COALESCE(i.supplier_name, b.vendor_name, '') party_name,
                             COALESCE(i.invoice_date, b.date, DATE(pr.created_at)) doc_date,
                             COALESCE(i.gross_original, b.gross_original) amt,
                             COALESCE(i.currency, b.currency) ccy
                        FROM pending_review pr
                        LEFT JOIN invoices i ON pr.ref_table='invoices'
                           AND i.invoice_id=pr.ref_id AND i.entity_id=pr.entity_id
                        LEFT JOIN bills b ON pr.ref_table='bills'
                           AND b.bill_id=pr.ref_id AND b.entity_id=pr.entity_id
                       WHERE pr.entity_id=%s AND pr.status='open'
                      ORDER BY FIELD(pr.severity,'blocker','warning','info'), pr.review_id DESC
                      LIMIT 50""", (eid,)):
        href = "?p=pending"
        if r["ref_table"] == "invoices":
            href = f"?p=invoice-view&id={r['ref_id']}"
        elif r["ref_table"] == "bills":
            href = f"?p=bill-view&id={r['ref_id']}"
        item = {"kind": "pending_review", "label": f"待处理 · {r['kind']}",
                "id": r["id"], "docNo": r["doc_no"] or f"{r['ref_table']}#{r['ref_id']}",
                "party": r["party_name"], "reason": r["reason"] or "",
                "date": str(r["doc_date"])[:10], "severity": r["severity"],
                "action": "去处理", "href": href}
        if r["amt"] is not None:
            item["amount"] = float(dec(r["amt"]))
            item["currency"] = r["ccy"]
        items.append(item)

    # 4) 未匹配流水
    n_line = int(query_one("""SELECT COUNT(*) c FROM bank_lines
                               WHERE entity_id=%s AND match_status='unmatched'""", (eid,))["c"])
    if n_line:
        items.append({"kind": "bank_unmatched", "label": "银行流水未匹配", "id": 0,
                      "docNo": f"{n_line} 笔", "party": "在 AI 工作台逐笔读取并匹配",
                      "date": date.today().isoformat(), "action": "在这里对账", "href": "?p=reconcile"})

    # 5) 未核销收付款
    n_recv = int(query_one("""SELECT COUNT(*) c FROM payments_received p
                               WHERE p.entity_id=%s AND NOT EXISTS
                                 (SELECT 1 FROM settlements s WHERE s.payment_id=p.payment_id
                                   AND s.direction='received')""", (eid,))["c"])
    if n_recv:
        items.append({"kind": "unsettled_receipt", "label": "收款未核销", "id": 0,
                      "docNo": f"{n_recv} 笔", "party": "登记收款后尚未冲抵发票",
                      "date": date.today().isoformat(), "action": "去核销", "href": "?p=receipts"})

    # 汇总
    summary = {
        "total": len(items),
        "draft": sum(1 for x in items if x["kind"].endswith("_draft")),
        "overdue": sum(1 for x in items if x["kind"] == "overdue_ar"),
        "pending": sum(1 for x in items if x["kind"] == "pending_review"),
        "bank": n_line, "unsettled": n_recv,
    }
    return J({"items": items, "summary": summary, "today": date.today().isoformat()})


# ---------------------------------------------------------------- 快速建单
@app.post("/fast/create")
def fast_create():
    """快速建单：识别结果或手填 → 建草稿；可选立即记账（管理员）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    kind = str(p.get("kind") or "bill")
    if kind not in ("invoice", "bill", "expense"):
        raise ValueError("单据类型不合法")
    actor = p.get("actor", "system")

    if kind == "invoice":
        res = create_invoice({
            "supplierName": p.get("party"), "customerId": p.get("partyId"),
            "invoiceDate": p.get("date") or date.today().isoformat(),
            "dueDate": p.get("dueDate"),
            "currency": str(p.get("currency") or "HKD"),
            "lines": p.get("lines") or [],
            "amountOriginal": p.get("amountOriginal") or 0,
            "taxOriginal": p.get("taxOriginal") or 0,
            "discountOriginal": p.get("discountOriginal") or 0,
            "contractId": p.get("contractId"),
            "performanceObligationStatus": "fulfilled",
            "recognitionPattern": "point_in_time",
            "actor": actor,
        }, actor)
        doc_id, doc_no = res.get("invoiceId"), res.get("invoiceNo")
        doc_type = "invoice"
    elif kind == "bill":
        res = create_bill({
            "vendorName": p.get("party"), "date": p.get("date") or date.today().isoformat(),
            "dueDate": p.get("dueDate"), "currency": str(p.get("currency") or "HKD"),
            "lines": p.get("lines") or [],
            "amount": p.get("amountOriginal") or 0,
            "taxAmount": p.get("taxOriginal") or 0,
            "discountOriginal": p.get("discountOriginal") or 0,
            "expenseAccountCode": p.get("expenseAccountCode") or "6200",
            "actor": actor,
        }, actor)
        doc_id, doc_no = res.get("billId"), res.get("billNo")
        doc_type = "bill"
    else:
        res = create_expense({
            "category": p.get("party"), "date": p.get("date") or date.today().isoformat(),
            "projectName": p.get("projectName"), "notes": p.get("notes"),
            "currency": str(p.get("currency") or "HKD"),
            "amount": p.get("amountOriginal") or 0,
            "taxAmount": p.get("taxOriginal") or 0,
            "expenseAccountCode": p.get("expenseAccountCode") or "6600",
            "actor": actor,
        }, actor)
        doc_id, doc_no = res.get("expenseId"), res.get("expenseNo")
        doc_type = "expense"

    out = {"kind": doc_type, "docId": doc_id, "docNo": doc_no,
           "canPost": bool(res.get("canPost")), "status": "draft",
           "checks": res.get("checks"), "agentCheck": res.get("agentCheck")}

    # 立即记账：仍受 D-01 约束——必须显式传 post=true（来自人工确认弹窗）
    if p.get("post"):
        out["postResult"] = one_click_post(doc_type, int(doc_id or 0), actor,
                                            str(p.get("role") or "admin"))
    return J(out)


def one_click_post(doc_type, doc_id, actor, role="admin"):
    """一键记账：草稿 → 提交复核 → 批准 → 过账，一步完成。

    仍遵守 D-01：本函数只在人工点过确认之后被调用（由 /fast/post 触发），
    它不替代确认，只把确认之后的四步机械动作串起来。
    """
    if not doc_id:
        return {"ok": False, "error": "单据 ID 缺失"}
    table = {"invoice": ("invoices", "invoice"), "bill": ("bills", "bill")}.get(doc_type)
    if not table:
        return {"ok": False, "error": "该类型不支持一键记账"}
    tbl, key = table
    row = query_one(f"SELECT status, review_status, created_by FROM {tbl} WHERE {key}_id=%s",
                    (doc_id,))
    if not row:
        return {"ok": False, "error": "单据不存在"}
    if row["status"] != "draft":
        return {"ok": True, "status": row["status"], "steps": ["已是终态，无需处理"]}

    steps = []
    e = entity_or_404()
    payload = {"actor": actor, "role": role}

    # 1) 提交复核
    if (row.get("review_status") or "draft") == "draft":
        try:
            _submit_review_core(tbl, key, doc_id, e["entity_id"], actor)
            steps.append("提交复核")
        except Exception as ex:
            steps.append(f"提交复核跳过（{ex}）")
    # 2) 批准（role=admin 时允许一人完成）
    try:
        _approve_core(tbl, key, doc_id, e["entity_id"], actor, role, None)
        steps.append("批准")
    except Exception as ex:
        steps.append(f"批准跳过（{ex}）")
    # 3) 过账
    try:
        from core.service import post_invoice, post_bill
        r = post_invoice(doc_id, actor) if doc_type == "invoice" else post_bill(doc_id, actor)
        steps.append("记账")
        return {"ok": True, "entryNo": r.get("entryNo"), "entryId": r.get("entryId"),
                "status": "posted", "steps": steps}
    except Exception as ex:
        return {"ok": False, "error": str(ex), "steps": steps}


def _submit_review_core(tbl, key, doc_id, entity_id, actor):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {tbl} SET review_status='pending' WHERE {key}_id=%s", (doc_id,))
        append_audit(conn, {"entity_id": entity_id, "actor": actor,
                            "action": f"{key}.submit_review", "object_type": tbl,
                            "object_id": str(doc_id), "detail": {"via": "one_click_post"}})


def _approve_core(tbl, key, doc_id, entity_id, actor, role, note):
    d = query_one(f"SELECT status, review_status, created_by FROM {tbl} WHERE {key}_id=%s",
                  (doc_id,))
    if not d:
        raise ValueError("单据不存在")
    if d["review_status"] == "approved":
        return
    same = str(d["created_by"] or "").strip().lower() == str(actor or "").strip().lower()
    if same and role != "admin":
        raise ValueError("不能复核自己录入的单据（四眼原则）")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""UPDATE {tbl} SET review_status='approved', approved_by=%s,
                                              approved_at=NOW(3), approval_note=%s
                             WHERE {key}_id=%s""", (actor, note, doc_id))
        append_audit(conn, {"entity_id": entity_id, "actor": actor,
                            "action": f"{key}.approve", "object_type": tbl,
                            "object_id": str(doc_id),
                            "detail": {"via": "one_click_post", "note": note}})


@app.post("/fast/post")
def fast_post():
    """一键记账：对已有草稿执行（前端弹窗确认后调用）。"""
    require_writer()
    entity_or_404()
    p = request.get_json(force=True) or {}
    kind = str(p.get("kind") or "invoice")
    doc_id = int(p.get("docId") or 0)
    actor = p.get("actor", "system")
    if doc_id <= 0:
        raise ValueError("单据 ID 非法")
    return J(one_click_post(kind, doc_id, actor, str(p.get("role") or "admin")))


# ---------------------------------------------------------------- 一键批量记账
@app.post("/fast/post-batch")
def fast_post_batch():
    """批量记账：勾选多条草稿一次过账，逐条返回结果。"""
    require_writer()
    entity_or_404()
    p = request.get_json(force=True) or {}
    actor = p.get("actor", "system")
    docs = p.get("docs") or []
    if not docs:
        raise ValueError("没有选择单据")
    results = []
    for d in docs[:50]:
        kind = str(d.get("kind") or "invoice")
        did = int(d.get("docId") or 0)
        r = one_click_post(kind, did, actor, str(p.get("role") or "admin"))
        results.append({"kind": kind, "docId": did, "ok": r.get("ok"),
                        "entryNo": r.get("entryNo"), "error": r.get("error")})
    ok = sum(1 for x in results if x["ok"])
    return J({"total": len(results), "ok": ok, "failed": len(results) - ok, "results": results})


@app.get("/invoices")
def invoices():
    """销售发票列表。支持 limit / offset / q / status 分页筛选。"""
    e = entity_or_404()
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    if limit <= 0:
        limit = 2000
    limit = min(limit, 2000)

    cond = ["i.entity_id=%s"]
    args = [e["entity_id"]]
    st = str(request.args.get("status") or "").strip()
    if st and st != "all":
        cond.append("i.status=%s")
        args.append(st)
    q = str(request.args.get("q") or "").strip()
    if q:
        cond.append("(i.invoice_no LIKE %s OR i.supplier_name LIKE %s)")
        args += [f"%{q}%", f"%{q}%"]
    where = " AND ".join(cond)
    total = int(query_one(f"SELECT COUNT(*) n FROM invoices i WHERE {where}", tuple(args))["n"])

    rows = query(
        f"""SELECT i.invoice_id, i.invoice_no, i.supplier_name, i.invoice_date, i.due_date,
                  i.subject, i.order_number, i.payment_terms, i.salesperson, i.settled_original,
                  i.revenue_recognition_date, i.currency, i.amount_original, i.tax_original,
                  i.gross_original, i.tax_rate_implied, i.amount_functional, i.fx_rate,
                  i.fx_rate_date, i.performance_obligation_status, i.revenue_account_code,
                  i.status, i.review_status, i.approved_by, i.approved_at, i.approval_note,
                  i.created_by, i.created_at,
                  (SELECT COUNT(*) FROM pending_review p WHERE p.ref_table='invoices'
                     AND p.ref_id=i.invoice_id AND p.status='open' AND p.severity='blocker') AS blockers,
                  (SELECT COUNT(*) FROM pending_review p WHERE p.ref_table='invoices'
                     AND p.ref_id=i.invoice_id AND p.status='open' AND p.severity='warning') AS warnings
             FROM invoices i WHERE {where} ORDER BY i.invoice_id DESC LIMIT %s OFFSET %s""",
        tuple(args + [limit, offset]))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("amount_original", "tax_original", "gross_original", "tax_rate_implied",
                  "amount_functional", "fx_rate", "settled_original"):
            if d.get(k) is not None:
                d[k] = float(dec(d[k]))
        d["created_at"] = d["created_at"].isoformat(sep=" ", timespec="milliseconds")
        blocked, warns = int(r["blockers"]), int(r["warnings"])
        d["canPost"] = r["status"] == "draft" and blocked == 0
        d["checkStatus"] = "FAIL" if blocked else ("REVIEW" if warns else "PASS")
        out.append(d)
    return J({"invoices": out, "total": total, "limit": limit, "offset": offset})


@app.get("/bills")
def bills():
    """采购发票列表。支持 limit / offset / q / status 分页筛选。"""
    e = entity_or_404()
    limit, offset = page_args()
    cond = ["b.entity_id=%s"]
    args = [e["entity_id"]]
    st = str(request.args.get("status") or "").strip()
    if st and st != "all":
        cond.append("b.status=%s")
        args.append(st)
    cond.append("1=1")
    where = " AND ".join(cond[:-1])
    where += search_clause(request.args.get("q"),
                           ["b.bill_no", "b.vendor_name", "b.vendor_invoice_no"], args)
    if st and st != "all":
        where = where  # status 已并入 args 顺序
    total = int(query_one(f"SELECT COUNT(*) n FROM bills b WHERE {where}", tuple(args))["n"])
    rows = query(
        f"""SELECT b.bill_id, b.bill_no, b.vendor_invoice_no, b.vendor_name, b.date, b.due_date,
                  b.subject, b.order_number, b.payment_terms, b.settled_original, b.currency,
                  b.amount, b.tax_amount, b.gross_original, b.amount_functional, b.fx_rate,
                  b.expense_account_code, b.status, b.review_status, b.approved_by,
                  b.approved_at, b.approval_note, b.created_by, b.created_at,
                  (SELECT COUNT(*) FROM pending_review p WHERE p.ref_table='bills'
                     AND p.ref_id=b.bill_id AND p.status='open' AND p.severity='blocker') AS blockers,
                  (SELECT COUNT(*) FROM pending_review p WHERE p.ref_table='bills'
                     AND p.ref_id=b.bill_id AND p.status='open' AND p.severity='warning') AS warnings
             FROM bills b WHERE {where} ORDER BY b.bill_id DESC LIMIT %s OFFSET %s""",
        tuple(args + [limit, offset]))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("amount", "tax_amount", "gross_original", "amount_functional", "fx_rate"):
            if d.get(k) is not None:
                d[k] = float(dec(d[k]))
        d["date"] = d["date"].isoformat()
        d["due_date"] = d["due_date"].isoformat() if d["due_date"] else None
        d["created_at"] = d["created_at"].isoformat(sep=" ", timespec="milliseconds")
        blocked, warns = int(d.pop("blockers", 0)), int(d.pop("warnings", 0))
        d["canPost"] = d["status"] == "draft" and blocked == 0
        d["checkStatus"] = "FAIL" if blocked else ("REVIEW" if warns else "PASS")
        out.append(d)
    return J({"bills": out, "total": total, "limit": limit, "offset": offset})


@app.get("/expenses/<int:expense_id>")
def expense_detail(expense_id):
    e = entity_or_404()
    r = query_one("SELECT * FROM expenses WHERE expense_id=%s AND entity_id=%s",
                  (expense_id, e["entity_id"]))
    if not r:
        raise ValueError("费用单不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    for k in ("amount", "tax_amount", "amount_functional"):
        if d.get(k) is not None:
            d[k] = float(dec(d[k]))
    d["attachments"] = [dict(x) for x in query(
        """SELECT file_id, file_name, file_type, file_size, sha256_hash, created_at AS uploaded_at
             FROM doc_files WHERE doc_type='expense' AND doc_id=%s ORDER BY file_id""", (expense_id,))]
    for a in d["attachments"]:
        a["uploaded_at"] = a["uploaded_at"].isoformat(sep=" ", timespec="minutes") if a.get("uploaded_at") else None
    return J(d)


@app.get("/credit-notes/<int:credit_id>")
def credit_note_detail(credit_id):
    e = entity_or_404()
    r = query_one("SELECT * FROM credit_notes WHERE credit_id=%s AND entity_id=%s",
                  (credit_id, e["entity_id"]))
    if not r:
        raise ValueError("贷记单不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    for k in ("amount_original", "tax_original", "gross_original", "amount_functional", "fx_rate"):
        if d.get(k) is not None:
            d[k] = float(dec(d[k]))
    d["functional_currency"] = e["functional_currency"]
    d["source_invoice_no"] = None
    d["source_bill_no"] = None
    if r.get("source_invoice_id"):
        source = query_one("SELECT invoice_no FROM invoices WHERE invoice_id=%s AND entity_id=%s",
                           (r["source_invoice_id"], e["entity_id"]))
        d["source_invoice_no"] = source["invoice_no"] if source else None
    if r.get("source_bill_id"):
        source = query_one("SELECT bill_no FROM bills WHERE bill_id=%s AND entity_id=%s",
                           (r["source_bill_id"], e["entity_id"]))
        d["source_bill_no"] = source["bill_no"] if source else None
    d["journal"] = None
    je = query_one("""SELECT entry_id, entry_no, entry_date, status FROM journal_entries
                       WHERE entity_id=%s AND source_type='manual' AND source_id=%s
                       ORDER BY entry_id DESC LIMIT 1""", (e["entity_id"], credit_id))
    if je:
        d["journal"] = {**dict(je), "entry_date": je["entry_date"].isoformat()}
    return J(d)


@app.get("/expenses")
def expenses():
    e = entity_or_404()
    limit, offset = page_args()
    cond = ["entity_id=%s"]
    args = [e["entity_id"]]
    st = str(request.args.get("status") or "").strip()
    if st and st != "all":
        cond.append("status=%s")
        args.append(st)
    where = " AND ".join(cond) + search_clause(
        request.args.get("q"), ["expense_no", "category", "project_name", "notes"], args)
    total = int(query_one(f"SELECT COUNT(*) n FROM expenses WHERE {where}", tuple(args))["n"])
    rows = query(
        f"""SELECT expense_id, expense_no, category, project_name, notes, reviewed_by, date, currency,
                  amount, tax_amount, amount_functional, status, created_by, created_at
             FROM expenses WHERE {where} ORDER BY expense_id DESC LIMIT %s OFFSET %s""",
        tuple(args + [limit, offset]))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("amount", "tax_amount", "amount_functional"):
            if d.get(k) is not None:
                d[k] = float(dec(d[k]))
        d["date"] = d["date"].isoformat()
        d["created_at"] = d["created_at"].isoformat(sep=" ", timespec="milliseconds")
        out.append(d)
    return J({"expenses": out, "total": total, "limit": limit, "offset": offset})


@app.get("/pending-review")
def pending_review():
    e = entity_or_404()
    kind = request.args.get("kind")
    sql = """SELECT review_id, kind, ref_table, ref_id, reason, severity, status, payload, created_at
               FROM pending_review WHERE entity_id=%s AND status='open'"""
    params = [e["entity_id"]]
    if kind:
        sql += " AND kind=%s"
        params.append(kind)
    sql += " ORDER BY severity='blocker' DESC, created_at DESC LIMIT 200"
    rows = query(sql, tuple(params))
    out = []
    for r in rows:
        d = dict(r)
        if isinstance(d["payload"], str):
            try:
                d["payload"] = json.loads(d["payload"])
            except Exception:
                d["payload"] = None
        d["created_at"] = d["created_at"].isoformat(sep=" ", timespec="milliseconds")
        out.append(d)
    return J({"reviews": out})


def subaccounts(eid: int):
    """112x 银行子科目及占用情况，供新建账户时人工选择。"""
    rows = query(
        """SELECT a.account_code, a.account_name, a.name_en,
                  (SELECT COUNT(*) FROM bank_accounts b
                    WHERE b.entity_id=a.entity_id AND b.account_code=a.account_code) AS used
             FROM accounts a
            WHERE a.entity_id=%s AND a.parent_account_code='1120'
            ORDER BY a.account_code""", (eid,))
    out = []
    for r in rows:
        m = re.search(r"—\s*([A-Z]{3})(?:\s+\d+)?$", r["name_en"] or "")
        out.append({"accountCode": r["account_code"], "name": r["account_name"],
                    "nameEn": r["name_en"], "currency": m.group(1) if m else None,
                    "used": bool(r["used"])})
    return out


@app.get("/bank-accounts")
def bank_accounts():
    e = entity_or_404()
    bb = reports.bank_balances(e["entity_id"])
    rows = query(
        """SELECT b.account_id, b.name, b.account_holder, b.currency, b.account_code, b.bank_name,
                  b.bank_code, b.swift_code, b.bank_address, b.branch, b.account_number,
                  b.account_number_masked, b.is_credit_card, b.is_primary_receiving,
                  b.opening_balance, b.current_balance, b.current_balance_functional,
                  b.last_reval_rate, b.last_reval_date, b.status,
                  a.account_name, a.name_en AS account_name_en
             FROM bank_accounts b
             LEFT JOIN accounts a
               ON a.entity_id=b.entity_id AND a.account_code=b.account_code
            WHERE b.entity_id=%s AND b.status='active'
            ORDER BY (b.currency = %s) DESC, b.currency, b.account_id""",
                 (e["entity_id"], e["functional_currency"]))
    # 余额统一取总账：current_balance 只在导流水时维护，期初结转与手工分录不动它，
    # 直接返回会和 /reports/bank-balances 对不上。
    gl_bal = {a["account_id"]: (a["current_balance"], a["current_balance_functional"])
              for g in bb["groups"] for a in g["accounts"]}
    out = []
    for r in rows:
        d = dict(r)
        for k in ("opening_balance", "current_balance", "current_balance_functional", "last_reval_rate"):
            d[k] = float(dec(d[k])) if d.get(k) is not None else None
        d["last_reval_date"] = d["last_reval_date"].isoformat() if d["last_reval_date"] else None
        if d["account_id"] in gl_bal:
            d["current_balance"], d["current_balance_functional"] = gl_bal[d["account_id"]]
        out.append(d)
    return J({"accounts": out, "groups": bb["groups"], "hkdTotal": bb["hkdTotal"], "note": bb["note"],
              "subaccounts": subaccounts(e["entity_id"])})


@app.post("/bank-accounts")
def bank_account_create():
    """新建银行账户：必要时自动建立 112x 银行科目，并为期初余额生成期初分录。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    name = str(p.get("name") or "").strip()
    ccy = str(p.get("currency") or "").upper().strip()
    if not name:
        raise ValueError("账户名称不能为空")
    if not re.fullmatch(r"[A-Z]{3}", ccy):
        raise ValueError("币种代码必须是 3 位英文字母，例如 USD")
    opening, _ = quantize_money(p.get("openingBalance") or 0)
    if opening is None or opening < 0:
        raise ValueError("期初余额必须是不小于 0 的数值")

    eid = e["entity_id"]
    functional = str(e["functional_currency"]).upper()
    today = date.today()
    if opening and ccy != functional:
        fx = _document_fx(e, ccy, today, opening)
        opening_fx = fx["amount_functional"]
        rate, rate_date = fx["fx_rate"], fx["fx_rate_date"]
    else:
        opening_fx = convert(opening, 1)
        rate, rate_date = dec(1), today.isoformat()

    actor = p.get("actor", "system")
    with transaction() as conn:
        with conn.cursor() as cur:
            # 人工指定科目时优先采用；否则复用该币种下空闲的银行科目，都没有才新建
            sel = str(p.get("accountCode") or "").strip()
            code = None
            if sel:
                cur.execute("""SELECT a.account_code, a.name_en FROM accounts a
                                WHERE a.entity_id=%s AND a.account_code=%s
                                  AND a.parent_account_code='1120'""", (eid, sel))
                srow = cur.fetchone()
                if not srow:
                    raise ValueError("所选会计科目不是本实体 1120 下的银行子科目")
                m = re.search(r"—\s*([A-Z]{3})(?:\s+\d+)?$", srow["name_en"] or "")
                if m and m.group(1) != ccy:
                    raise ValueError(f"所选科目 {sel} 属于 {m.group(1)}，与所选币种 {ccy} 不一致")
                cur.execute("""SELECT account_id FROM bank_accounts
                                WHERE entity_id=%s AND account_code=%s LIMIT 1""",
                            (eid, sel))
                if cur.fetchone():
                    raise ValueError("该会计科目已被其他银行账户占用，请另选或留空自动新建")
                code = sel
            if not code:
                cur.execute("""SELECT a.account_code FROM accounts a
                                LEFT JOIN bank_accounts b
                                  ON b.entity_id=a.entity_id AND b.account_code=a.account_code
                                WHERE a.entity_id=%s AND a.parent_account_code='1120'
                                  AND a.name_en LIKE %s AND b.account_id IS NULL
                                ORDER BY a.account_code LIMIT 1""",
                            (eid, f"Bank Account — {ccy}%"))
            row = cur.fetchone() if not code else None
            if not code:
                code = row["account_code"] if row else None
            if not code:
                cur.execute("""SELECT account_code FROM accounts
                                WHERE entity_id=%s FOR UPDATE""", (eid,))
                used = {r["account_code"] for r in cur.fetchall()}
                for n in range(1121, 1200):
                    if str(n) not in used:
                        code = str(n)
                        break
                if not code:
                    raise ValueError("112x 银行科目已用尽，请先整理会计科目")
                cur.execute("""SELECT COUNT(*) AS n FROM accounts
                                WHERE entity_id=%s AND parent_account_code='1120'
                                  AND name_en LIKE %s""",
                            (eid, f"Bank Account — {ccy}%"))
                seq = int(cur.fetchone()["n"]) + 1
                suffix = f" {seq}" if seq > 1 else ""
                cur.execute("""INSERT INTO accounts
                    (account_code, entity_id, account_name, name_zh_cn, name_zh_hk,
                     name_en, category, fs_line_item, normal_balance, parent_account_code, is_active)
                    VALUES (%s,%s,%s,%s,%s,%s,'asset','CASH_EQUIVALENTS','debit','1120',1)""",
                    (code, eid, f"银行账户 — {ccy}{suffix}", f"银行账户 — {ccy}{suffix}",
                     f"銀行賬戶 — {ccy}{suffix}", f"Bank Account — {ccy}{suffix}"))

            cur.execute("""SELECT account_id FROM bank_accounts
                            WHERE entity_id=%s AND is_primary_receiving=1
                              AND status='active' LIMIT 1""", (eid,))
            primary = 0 if cur.fetchone() else 1

            acct_no = str(p.get("accountNumber") or "").strip() or None
            masked = ("****" + acct_no[-3:]) if acct_no else None
            cur.execute("""INSERT INTO bank_accounts
                (entity_id, name, account_holder, currency, account_code, bank_name,
                 bank_code, swift_code, account_number, account_number_masked,
                 is_credit_card, is_primary_receiving, opening_balance,
                 opening_balance_functional, current_balance, current_balance_functional, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')""",
                        (eid, name,
                         str(p.get("accountHolder") or "").strip() or e.get("legal_name") or e["entity_name"],
                         ccy, code, str(p.get("bankName") or "").strip() or None,
                         str(p.get("bankCode") or "").strip() or None,
                         str(p.get("swiftCode") or "").strip() or None,
                         acct_no, masked, 1 if p.get("isCreditCard") else 0, primary,
                         opening, opening_fx, opening, opening_fx))
            acct_id = cur.lastrowid

            if opening_fx:
                from core.numbering import next_no as _next_no
                entry_no = _next_no(conn, eid, today.isoformat(), "journal")
                cur.execute("""INSERT INTO journal_entries
                    (entity_id, entry_no, entry_date, source_type, description, status,
                     total_debit, total_credit, created_by, retention_until)
                    VALUES (%s,%s,%s,'opening',%s,'draft',%s,%s,%s,
                            DATE_ADD(%s, INTERVAL 7 YEAR))""",
                            (eid, entry_no, today.isoformat(), f"期初余额 — {name}",
                             opening_fx, opening_fx, actor, today.isoformat()))
                entry_id = cur.lastrowid
                cur.execute("""INSERT INTO journal_lines
                    (entry_id, line_no, account_code, description, debit, credit, ccy,
                     amount_original, rate, rate_date)
                    VALUES (%s,1,%s,%s,%s,0,%s,%s,%s,%s)""",
                            (entry_id, code, f"期初余额 — {name}", opening_fx,
                             ccy, opening, rate, rate_date))
                cur.execute("""INSERT INTO journal_lines
                    (entry_id, line_no, account_code, description, debit, credit, ccy,
                     amount_original, rate, rate_date)
                    VALUES (%s,2,'3200',%s,0,%s,%s,%s,1,%s)""",
                            (entry_id, f"期初余额 — {name}", opening_fx,
                             functional, opening_fx, rate_date))
                cur.execute("""UPDATE journal_entries
                    SET status='posted', posted_by=%s, posted_at=NOW(3)
                    WHERE entry_id=%s""", (actor, entry_id))

        append_audit(conn, {"entity_id": eid, "actor": actor,
                            "action": "bank_account.create", "object_type": "bank_accounts",
                            "object_id": str(acct_id),
                            "detail": {"name": name, "currency": ccy, "accountCode": code,
                                       "opening": float(opening),
                                       "openingFunctional": float(opening_fx)}})
    return J({"ok": True, "accountId": acct_id, "accountCode": code, "currency": ccy,
              "openingBalanceFunctional": float(opening_fx)})


@app.get("/bank-lines")
def bank_lines():
    e = entity_or_404()
    where = "entity_id=%s"
    params = [e["entity_id"]]
    if request.args.get("accountId"):
        where += " AND bank_account_id=%s"
        params.append(int(request.args["accountId"]))
    status = str(request.args.get("status") or "")
    if status == "unmatched":
        where += " AND match_status<>'matched'"
    elif status:
        where += " AND match_status=%s"
        params.append(status)
    try:
        limit = int(request.args.get("limit", 300))
    except (TypeError, ValueError):
        limit = 300
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    limit = 2000 if limit <= 0 else min(limit, 2000)
    summary = query_one(f"""SELECT COUNT(*) AS total,
                                   COALESCE(SUM(CASE WHEN amount_original>0 THEN amount_original ELSE 0 END),0) AS amount_in,
                                   COALESCE(SUM(CASE WHEN amount_original<0 THEN amount_original ELSE 0 END),0) AS amount_out
                              FROM bank_lines WHERE {where}""", tuple(params))
    rows = query(f"""SELECT line_id, bank_account_id, bank_ref, txn_date, amount_original, currency,
                            counterparty_name, amount_functional, fx_rate, fx_rate_date,
                            match_status, match_rule, match_confidence, matched_type, matched_id,
                            matched_currency, matched_amount_at_rate, match_rate, match_rate_date
                       FROM bank_lines WHERE {where}
                      ORDER BY txn_date DESC, line_id DESC LIMIT %s OFFSET %s""",
                 tuple(params + [limit, offset]))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("amount_original", "amount_functional", "fx_rate", "matched_amount_at_rate", "match_rate"):
            d[k] = float(dec(d[k])) if d.get(k) is not None else None
        for k in ("txn_date", "fx_rate_date", "match_rate_date"):
            d[k] = d[k].isoformat() if d[k] else None
        out.append(d)
    return J({"lines": out, "total": int(summary["total"]),
              "amountIn": float(dec(summary["amount_in"])),
              "amountOut": float(dec(summary["amount_out"])),
              "limit": limit, "offset": offset})


@app.get("/fx/rates")
def fx_rates():
    limit = int(request.args.get("limit", 200))
    rows = query("""SELECT rate_date, from_ccy, to_ccy, rate, source, is_fallback FROM fx_rates
                     ORDER BY rate_date DESC, from_ccy LIMIT %s""", (limit,))
    return J({"rates": [dict(r, rate=float(dec(r["rate"])),
                           rate_date=r["rate_date"].isoformat(),
                           is_fallback=bool(r["is_fallback"])) for r in rows]})


@app.get("/journal")
def journal():
    """分录列表。支持 limit / offset / q 分页，返回总数供翻页。

    limit=0 表示不限（上限 2000 条，避免一次拉爆），默认 200 保持旧行为。
    """
    e = entity_or_404()
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    if limit <= 0:
        limit = 2000
    limit = min(limit, 2000)

    q = str(request.args.get("q") or "").strip()
    where = "entity_id=%s"
    args = [e["entity_id"]]
    if q:
        where += " AND (entry_no LIKE %s OR description LIKE %s OR source_type LIKE %s)"
        like = f"%{q}%"
        args += [like, like, like]

    total = int(query_one(f"SELECT COUNT(*) n FROM journal_entries WHERE {where}", tuple(args))["n"])
    rows = query(
        f"""SELECT entry_id, entry_no, entry_date, period, source_type, description, status,
                  total_debit, total_credit, created_by, posted_by,
                  reversal_of_entry_id, reversed_by_entry_id,
                  (SELECT COUNT(*) FROM doc_files f
                    WHERE f.entity_id=journal_entries.entity_id
                      AND f.doc_type='journal' AND f.doc_id=journal_entries.entry_id) AS file_count
             FROM journal_entries WHERE {where} ORDER BY entry_id DESC LIMIT %s OFFSET %s""",
        tuple(args + [limit, offset]))
    out = []
    for r in rows:
        d = dict(r)
        d["entry_date"] = d["entry_date"].isoformat()
        d["total_debit"] = float(dec(d["total_debit"]))
        d["total_credit"] = float(dec(d["total_credit"]))
        d["file_count"] = int(d.get("file_count") or 0)
        out.append(d)
    return J({"entries": out, "total": total, "limit": limit, "offset": offset})


@app.get("/journal/<int:entry_id>")
def journal_detail(entry_id):
    je = query_one("SELECT * FROM journal_entries WHERE entry_id=%s", (entry_id,))
    if not je:
        raise ValueError("分录不存在")
    lines = query("SELECT * FROM journal_lines WHERE entry_id=%s ORDER BY line_no", (entry_id,))
    d = dict(je)
    d["entry_date"] = d["entry_date"].isoformat()
    d["period"] = d.get("period")
    for k in ("total_debit", "total_credit"):
        d[k] = float(dec(d[k]))
    for k in ("posted_at", "created_at", "updated_at"):
        if d.get(k):
            d[k] = d[k].isoformat(sep=" ", timespec="milliseconds")
    ld = []
    for l in lines:
        x = dict(l)
        for k in ("debit", "credit", "amount_original", "rate"):
            x[k] = float(dec(x[k]))
        x["rate_date"] = x["rate_date"].isoformat() if x["rate_date"] else None
        ld.append(x)
    return J({"entry": d, "lines": ld})


@app.get("/audit/chain")
def audit_chain():
    e = entity_or_404()
    limit = int(request.args.get("limit", 200))
    return J({"chain": load_audit_chain(e["entity_id"], limit)})


@app.get("/audit/verify")
def audit_verify():
    e = entity_or_404()
    v = verify_chain(load_audit_chain(e["entity_id"]))
    return J(dict(v, entityId=e["entity_id"]))


@app.get("/reports/trial-balance")
def r_tb():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    return J(reports.trial_balance(entity_or_404()["entity_id"],
                                   request.args.get("asOf") or None))


@app.get("/reports/pnl")
def r_pnl():
    """损益表。支持 ?from=&to= 限定期间；不传则为全部历史。"""
    e = entity_or_404()
    start = request.args.get("from")
    end = request.args.get("to")
    return J(reports.profit_and_loss(e["entity_id"], start, end))


@app.get("/reports/account-types")
def r_account_types():
    """帳戶類型摘要：按科目类型汇总本期借贷（含资产负债类，不只看损益）。"""
    e = entity_or_404()
    return J(reports.account_type_summary(e["entity_id"],
                                          request.args.get("from"),
                                          request.args.get("to")))


@app.get("/reports/general-ledger-detail")
def r_gl_detail():
    """詳細的總分類帳：期初余额 + 逐笔流水 + 结余。"""
    e = entity_or_404()
    from core.pdf_reports import set_lang as _set_lang
    _set_lang(request.args.get("lang") or "zh_cn", e["entity_id"])
    return J(reports.general_ledger_detail(e["entity_id"],
                                           request.args.get("from"),
                                           request.args.get("to"),
                                           request.args.get("account") or None))


# ---------------------------------------------------------------- 银行规则（按摘要关键词自动指定对方科目）
@app.get("/bank-rules")
def bank_rules_list():
    e = entity_or_404()
    try:
        limit = int(request.args.get("limit", 300))
    except (TypeError, ValueError):
        limit = 300
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    limit = 2000 if limit <= 0 else min(limit, 2000)
    total = int(query_one("SELECT COUNT(*) AS n FROM bank_rules WHERE entity_id=%s",
                          (e["entity_id"],))["n"])
    rows = query("""SELECT rule_id, name, match_field, match_text, txn_kind, counter_account,
                           tax_rate, auto_post, hits, status, created_at
                      FROM bank_rules WHERE entity_id=%s ORDER BY rule_id DESC
                      LIMIT %s OFFSET %s""", (e["entity_id"], limit, offset))
    out = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
           for r in rows]
    return J({"rules": out, "total": total, "limit": limit, "offset": offset})


@app.post("/bank-rules")
def bank_rules_create():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    name = str(p.get("name") or "").strip()
    text = str(p.get("matchText") or "").strip()
    acct = str(p.get("counterAccount") or "").strip()
    if not name or not text or not acct:
        raise ValueError("规则名称、匹配文字、对方科目都要填")
    field = str(p.get("matchField") or "any")
    if field not in ("any", "description", "reference"):
        raise ValueError("匹配字段只能是 any / description / reference")
    kind = str(p.get("txnKind") or "any")
    if kind not in ("any", "in", "out"):
        raise ValueError("收支方向只能是 any / in / out")
    if not query_one("SELECT 1 AS x FROM accounts WHERE entity_id=%s AND account_code=%s",
                     (e["entity_id"], acct)):
        raise ValueError("对方科目不存在")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO bank_rules
                (entity_id, name, match_field, match_text, txn_kind, counter_account,
                 tax_rate, auto_post, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (e["entity_id"], name[:120], field, text[:200], kind, acct,
                 p.get("taxRate") or None, 1 if p.get("autoPost") else 0,
                 p.get("actor", "system")))
            rid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "bank_rule.create", "object_type": "bank_rules",
                            "object_id": str(rid), "detail": {"name": name}})
    return J({"ruleId": rid, "status": "active"})


@app.post("/bank-rules/<int:rule_id>/delete")
def bank_rules_delete(rule_id):
    require_writer()
    e = entity_or_404()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bank_rules WHERE rule_id=%s AND entity_id=%s",
                        (rule_id, e["entity_id"]))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": "system",
                            "action": "bank_rule.delete", "object_type": "bank_rules",
                            "object_id": str(rule_id), "detail": {}})
    return J({"ruleId": rule_id, "status": "deleted"})


@app.post("/bank-rules/apply")
def bank_rules_apply():
    """把规则套到未匹配的流水上，返回命中清单（不自动过账，由人确认）。"""
    require_writer()
    e = entity_or_404()
    rules = query("""SELECT * FROM bank_rules WHERE entity_id=%s AND status='active'
                      ORDER BY rule_id""", (e["entity_id"],))
    lines = query("""SELECT * FROM bank_lines WHERE entity_id=%s AND match_status='unmatched'
                      ORDER BY txn_date""", (e["entity_id"],))
    hits = []
    for ln in lines:
        desc = str(ln["counterparty_name"] or "")
        for r in rules:
            kind = r["txn_kind"]
            amt = dec(ln["amount_original"])
            if kind == "in" and amt <= 0:
                continue
            if kind == "out" and amt >= 0:
                continue
            if r["match_text"] and r["match_text"].lower() not in desc.lower():
                continue
            hits.append({"lineId": ln["line_id"], "date": ln["txn_date"].isoformat(),
                         "amount": float(amt), "description": desc[:80],
                         "ruleId": r["rule_id"], "ruleName": r["name"],
                         "account": r["counter_account"]})
            break
    return J({"hits": hits, "total": len(hits), "rules": len(rules)})


# ---------------------------------------------------------------- 转账（两个银行账户之间）
@app.post("/bank/transfer")
def bank_transfer():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    from_id = int(p.get("fromId") or 0)
    to_id = int(p.get("toId") or 0)
    amt = quantize_money(p.get("amount") or 0)[0]
    if not from_id or not to_id or from_id == to_id:
        raise ValueError("请选择两个不同的银行账户")
    if amt is None or amt <= 0:
        raise ValueError("转账金额必须大于 0")
    a = query_one("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                  (from_id, e["entity_id"]))
    b = query_one("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                  (to_id, e["entity_id"]))
    if not a or not b:
        raise ValueError("银行账户不存在")
    if a["currency"] != b["currency"]:
        raise ValueError("跨币种转账请先做一笔外币兑换分录，这里只处理同币种")
    d = str(p.get("date") or date.today().isoformat())
    res = journal_create_core({
        "entryDate": d,
        "description": f"转账 {a['name']} → {b['name']}",
        "currency": a["currency"],
        "lines": [{"accountCode": b["account_code"], "debit": float(amt)},
                  {"accountCode": a["account_code"], "credit": float(amt)}],
        "actor": p.get("actor", "system"),
    })
    body = res.get_json() if hasattr(res, "get_json") else res
    return J({"entryId": body.get("entryId"), "entryNo": body.get("entryNo"),
              "from": a["name"], "to": b["name"], "amount": float(amt)})


# ---------------------------------------------------------------- 期初余额
@app.get("/opening-balances")
def opening_balances():
    """期初余额：每个科目的期初（第一条分录之前的累计），可据此判断是否已导入。"""
    e = entity_or_404()
    rows = query("""SELECT a.account_code, a.account_name, a.category, a.normal_balance,
                           COALESCE(SUM(l.debit),0) AS dr, COALESCE(SUM(l.credit),0) AS cr
                      FROM accounts a
                      JOIN journal_lines l ON l.account_code=a.account_code
                      JOIN journal_entries en ON en.entry_id=l.entry_id
                           AND en.entity_id=a.entity_id AND en.status IN ('posted','reversed')
                     WHERE a.entity_id=%s AND a.is_active=1
                     GROUP BY a.account_code, a.account_name, a.category, a.normal_balance
                     HAVING dr<>0 OR cr<>0
                     ORDER BY a.account_code""", (e["entity_id"],))
    out = [{"accountCode": r["account_code"], "accountName": r["account_name"],
            "category": r["category"], "balance": float(dec(r["dr"]) - dec(r["cr"]))}
           for r in rows]
    op = query("""SELECT e.entry_id, e.entry_no, e.entry_date, e.total_debit
                    FROM journal_entries e
                   WHERE e.entity_id=%s AND e.source_type='opening' AND e.status='posted'
                   ORDER BY e.entry_date""", (e["entity_id"],))
    return J({"accounts": out, "openingEntries": [
        {"entryNo": r["entry_no"], "date": r["entry_date"].isoformat(),
         "amount": float(dec(r["total_debit"]))} for r in op]})


# ---------------------------------------------------------------- 通用附件（各类单据均可挂附件）
DOC_TYPES = {"invoice", "bill", "expense", "quote", "order", "credit_note",
             "payment", "journal", "vendor", "customer"}


@app.post("/doc-files")
def doc_files_register():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    t = str(p.get("docType") or "").strip()
    if t not in DOC_TYPES:
        raise ValueError("附件类型不合法")
    did = int(p.get("docId") or 0)
    name = str(p.get("fileName") or "").strip()[:255]
    path = str(p.get("storagePath") or "").strip()
    sha = str(p.get("sha256") or "").strip().lower()
    size = int(p.get("fileSize") or 0)
    if not did or not name or not path:
        raise ValueError("缺少单据 ID / 文件名 / 存储路径")
    if len(sha) != 64:
        raise ValueError("SHA-256 必须是 64 位十六进制")
    if size <= 0:
        raise ValueError("文件大小必须大于 0")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (e["entity_id"], t, did, name, p.get("fileType") or None, size,
                 sha, path, p.get("actor", "system")))
            fid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "doc_file.attach", "object_type": "doc_files",
                            "object_id": str(fid),
                            "detail": {"docType": t, "docId": did, "name": name}})
    return J({"fileId": fid, "docType": t, "docId": did})


@app.get("/doc-files")
def doc_files_list():
    e = entity_or_404()
    t = str(request.args.get("type") or "").strip()
    did = int(request.args.get("id") or 0)
    cond, args = ["entity_id=%s"], [e["entity_id"]]
    if t:
        cond.append("doc_type=%s"); args.append(t)
    if did:
        cond.append("doc_id=%s"); args.append(did)
    rows = query(f"""SELECT file_id, doc_type, doc_id, file_name, file_type, file_size,
                            sha256_hash, created_at
                       FROM doc_files WHERE {' AND '.join(cond)}
                      ORDER BY file_id DESC""", tuple(args))
    out = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
           for r in rows]
    return J({"files": out, "total": len(out)})


@app.post("/doc-files/<int:file_id>/delete")
def doc_files_delete(file_id):
    require_writer()
    e = entity_or_404()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM doc_files WHERE file_id=%s AND entity_id=%s",
                        (file_id, e["entity_id"]))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": "system",
                            "action": "doc_file.delete", "object_type": "doc_files",
                            "object_id": str(file_id), "detail": {}})
    return J({"fileId": file_id, "status": "deleted"})


@app.get("/doc-files/<int:file_id>/raw")
def doc_file_raw(file_id):
    """按登记路径回源文件（只允许 storage 下的文件）。"""
    from flask import send_file as _send
    e = entity_or_404()
    r = query_one("""SELECT * FROM doc_files WHERE file_id=%s AND entity_id=%s""",
                  (file_id, e["entity_id"]))
    if not r:
        raise ValueError("附件不存在")
    path = Path(str(r["storage_path"]))
    if not path.is_file():
        raise ValueError("文件已不在磁盘上")
    resolved = path.resolve()
    allowed = (STORAGE_DIR.resolve(), UPLOAD_DIR.resolve())
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise ValueError("附件路径不在允许范围")
    _is_pdf = path.name.lower().endswith(".pdf")
    return _send(str(resolved),
                 mimetype="application/pdf" if _is_pdf else None,
                 as_attachment=not _is_pdf, download_name=str(r["file_name"]))


def _voucher_attachments(entity_id, entry_id):
    """取凭证附件。

    图片转成 data URI 直接嵌进 HTML；PDF 附件单独返回路径，
    渲染完成后按顺序把它的每一页并进最终 PDF（附件顺序 = 登记顺序）。
    """
    import base64, os
    rows = query("""SELECT file_id, file_name, file_type, storage_path
                      FROM doc_files
                     WHERE entity_id=%s AND doc_type='journal' AND doc_id=%s
                     ORDER BY file_id""", (entity_id, entry_id))
    out = []
    for r in rows:
        path = str(r.get("storage_path") or "")
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            out.append({"file_name": r["file_name"], "pdfPath": path})
            continue
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}[ext]
        with open(path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        out.append({"file_name": r["file_name"], "dataUri": f"data:{mime};base64,{b64}"})
    return out


def _merge_voucher_pages(pages):
    """把多份 voucher_html 合成一份文档：CSS 取第一份，正文依次拼接。"""
    import re as _re
    css = ""
    bodies = []
    for p_ in pages:
        m = _re.search(r"<style>(.*?)</style>", p_, _re.S)
        if m and not css:
            css = m.group(1)
        b = _re.search(r"<body>(.*)</body>", p_, _re.S)
        bodies.append(b.group(1) if b else p_)
    return ("<html><head><meta charset='utf-8'><style>" + css + "</style></head><body>"
            + "".join(bodies) + "</body></html>")


def _voucher_pdf(entry_ids, lang="zh_cn", entity=None):
    """把若干凭证渲染成一个 PDF：一张凭证一页，后面跟它的附件页。

    附件顺序：每张凭证自己的附件按登记顺序紧跟其后；
    PDF 附件在渲染完成后按同样顺序把页并进去。
    """
    from core.pdf import voucher_html, render
    e = entity or entity_or_404()
    eid = e["entity_id"]
    parts = []
    pdf_plan = []          # [(在 parts 里的序号, 附件列表)] 供合并阶段使用
    for entry_id in entry_ids:
        je = query_one("SELECT * FROM journal_entries WHERE entry_id=%s AND entity_id=%s",
                       (entry_id, eid))
        if not je:
            continue
        lines = query("""SELECT l.*, a.account_name, a.name_zh_cn, a.name_zh_hk, a.name_en
                           FROM journal_lines l
                           LEFT JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=%s
                          WHERE l.entry_id=%s ORDER BY l.line_no""", (eid, entry_id))
        atts = _voucher_attachments(eid, entry_id)
        pdf_only = [a for a in atts if a.get("pdfPath")]
        parts.append(voucher_html(dict(je), [dict(x) for x in lines], e,
                                  [a for a in atts if not a.get("pdfPath")], lang))
        if pdf_only:
            pdf_plan.append((len(parts) - 1, pdf_only))
    if not parts:
        raise ValueError("没有可打印的凭证")
    stamp = date.today().strftime("%Y%m%d")
    out = f"vouchers-{stamp}-{len(parts)}.pdf"
    base = render(_merge_voucher_pages(parts), out)
    if not pdf_plan:
        return base

    # 把 PDF 附件并进去：要知道基础 PDF 里「每张凭证」占了几页，
    # 所以这里用 pypdf 重新拆页，按凭证顺序插入附件页。
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(base))
    total = len(reader.pages)
    # 每个凭证块的页数：图片附件页数已知（voucher_html 里每张一页），
    # 这里按「凭证页 1 + 图片附件数」倒推
    per_entry_pages = []
    for idx, chunk in enumerate(parts):
        imgs = chunk.count("class='page-att'")
        per_entry_pages.append(1 + imgs)
    writer = PdfWriter()
    cursor = 0
    plan_by_index = {i: atts for i, atts in pdf_plan}
    for idx, cnt in enumerate(per_entry_pages):
        for _ in range(cnt):
            if cursor < total:
                writer.add_page(reader.pages[cursor]); cursor += 1
        for att in plan_by_index.get(idx, []):
            try:
                ar = PdfReader(str(att["pdfPath"]))
                for pg in ar.pages:
                    writer.add_page(pg)
            except Exception:
                continue
    while cursor < total:
        writer.add_page(reader.pages[cursor]); cursor += 1
    with open(str(base), "wb") as fh:
        writer.write(fh)
    return base


@app.get("/journal/<int:entry_id>/voucher.pdf")
def journal_voucher_pdf(entry_id):
    """单张凭证 PDF（含附件）。"""
    from flask import send_file as _send
    e = entity_or_404()
    path = _voucher_pdf([entry_id], request.args.get("lang") or "zh_cn", e)
    return _send(str(path), mimetype="application/pdf", as_attachment=False,
                 download_name=path.name)


@app.get("/journal/vouchers.pdf")
def journal_vouchers_pdf():
    """批量凭证 PDF：按凭证号顺序，一张凭证一页 + 该凭证的附件页。"""
    from flask import send_file as _send
    e = entity_or_404()
    ids = [x for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    if ids:
        entry_ids = [int(x) for x in ids]
    else:
        where, args = ["je.entity_id=%s", "je.status IN ('posted','reversed')"], [e["entity_id"]]
        if request.args.get("from"):
            where.append("je.entry_date >= %s"); args.append(request.args["from"])
        if request.args.get("to"):
            where.append("je.entry_date <= %s"); args.append(request.args["to"])
        if request.args.get("q"):
            where.append("(je.entry_no LIKE %s OR je.description LIKE %s)")
            kw = f"%{request.args['q']}%"; args += [kw, kw]
        rows = query(f"""SELECT je.entry_id FROM journal_entries je
                          WHERE {' AND '.join(where)}
                          ORDER BY je.entry_date, je.entry_no
                          LIMIT 500""", tuple(args))
        entry_ids = [int(r["entry_id"]) for r in rows]
    path = _voucher_pdf(entry_ids, request.args.get("lang") or "zh_cn", e)
    return _send(str(path), mimetype="application/pdf", as_attachment=False,
                 download_name=path.name)


@app.get("/reports/balance-sheet")
def r_bs():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    return J(reports.balance_sheet(entity_or_404()["entity_id"]))


@app.get("/reports/cash-flow")
def r_cf():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    return J(reports.cash_flow(entity_or_404()["entity_id"],
                               request.args.get("from"), request.args.get("to")))


@app.get("/reports/aging")
def r_aging():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    # asOf：账龄是时点表，按截止日算（跟随报表期间选择器）
    return J(reports.aging(entity_or_404()["entity_id"],
                           request.args.get("side", "receivable"),
                           request.args.get("asOf")))


def _analysis_options(source=None):
    """分析接口与智能体共用白名单参数；AI 只能由调用方显式开启。"""
    source = request.args if source is None else source
    lang = str(source.get("lang") or "zh_cn").strip()
    if lang not in ("zh_cn", "zh_hk", "en"):
        raise ValueError("lang 仅支持 zh_cn/zh_hk/en")
    return {
        "period": str(source.get("period") or "this_month").strip(),
        "month": str(source.get("month") or "").strip(),
        "year": str(source.get("year") or "").strip(),
        "start": str(source.get("from") or "").strip(),
        "end": str(source.get("to") or "").strip(),
        "lang": lang,
        "use_ai": str(source.get("ai") or "0").strip().lower() in ("1", "true", "yes"),
    }


def _build_analysis(source=None):
    from core import financial_analysis
    return financial_analysis.build_report(entity_or_404(), **_analysis_options(source))


def _analysis_export_file(report, fmt):
    """生成受控文件并追加业务审计；不在日志中记录 AI 配置或上游内容。"""
    from core import financial_analysis
    fmt = str(fmt or "pdf").lower()
    if fmt not in ("pdf", "docx"):
        raise ValueError("format 仅支持 pdf/docx")
    path = financial_analysis.export_report(report, fmt, STORAGE_DIR)
    with transaction() as conn:
        append_audit(conn, {
            "entity_id": report["entity"]["id"],
            "actor": request.headers.get("X-Ledu-User", "system"),
            "actor_role": current_role(),
            "action": "financial_analysis.export",
            "object_type": "financial_analysis",
            "object_id": path.name,
            "detail": {"format": fmt, "lang": report["lang"],
                       "periodType": report["period"]["type"],
                       "from": report["period"]["start"], "to": report["period"]["end"],
                       "reconciled": report["reconciled"], "bytes": path.stat().st_size},
        })
    return path


@app.get("/reports/analysis")
def r_analysis():
    return J(_build_analysis())


@app.get("/reports/analysis/export")
def r_analysis_export():
    report = _build_analysis()
    fmt = str(request.args.get("format") or "pdf").lower()
    path = _analysis_export_file(report, fmt)
    mimetype = ("application/pdf" if fmt == "pdf" else
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return send_file(str(path), mimetype=mimetype, as_attachment=(fmt == "docx"),
                     download_name=path.name, max_age=0)


@app.get("/reports/bank-balances")
def r_bank():
    return J(reports.bank_balances(entity_or_404()["entity_id"]))


@app.get("/reports/fx")
def r_fx():
    return J(reports.fx_gain_loss(entity_or_404()["entity_id"]))


# ------------------------------------------------------------------ 写入
@app.post("/invoices")
def post_new_invoice():
    require_writer()
    p = request.get_json(force=True) or {}
    return J(create_invoice(p, p.get("actor", "accountant")))


@app.post("/invoices/<int:invoice_id>/update")
def update_draft_invoice(invoice_id):
    """更新一张草稿发票；编号不变，已过账发票由服务层拒绝。"""
    require_writer()
    p = request.get_json(force=True) or {}
    return J(create_invoice(p, p.get("actor", "accountant"), invoice_id=invoice_id))


@app.post("/invoices/<int:invoice_id>/post")
def do_post_invoice(invoice_id):
    require_writer()
    p = request.get_json(force=True) or {}
    return J(post_invoice(invoice_id, p.get("actor", "accountant")))


@app.post("/bills")
def post_new_bill():
    require_writer()
    p = request.get_json(force=True) or {}
    return J(create_bill(p, p.get("actor", "accountant")))


@app.post("/bills/<int:bill_id>/update")
def update_draft_bill(bill_id):
    """更新草稿采购发票；服务层保留编号并拒绝已过账单据。"""
    require_writer()
    p = request.get_json(force=True) or {}
    return J(create_bill(p, p.get("actor", "accountant"), bill_id=bill_id))


@app.post("/expenses")
def post_new_expense():
    require_writer()
    p = request.get_json(force=True) or {}
    return J(create_expense(p, p.get("actor", "accountant")))


@app.post("/expenses/<int:expense_id>/update")
def update_draft_expense(expense_id):
    """更新草稿费用；服务层保留编号并拒绝已过账单据。"""
    require_writer()
    p = request.get_json(force=True) or {}
    return J(create_expense(p, p.get("actor", "accountant"), expense_id=expense_id))


# ------------------------------------------------------------------ 草稿删除
_DRAFT_DELETE_KINDS = {
    "quote": {"table": "quotes", "id": "quote_id", "no": "quote_no",
              "label": "报价单", "docType": "quote",
              "details": [("quote_lines", "quote_id")]},
    "invoice": {"table": "invoices", "id": "invoice_id", "no": "invoice_no",
                "label": "销售发票", "docType": "invoice",
                "details": [("invoice_lines", "invoice_id")]},
    "bill": {"table": "bills", "id": "bill_id", "no": "bill_no",
             "label": "采购发票", "docType": "bill",
             "details": [("bill_lines", "bill_id")]},
    "expense": {"table": "expenses", "id": "expense_id", "no": "expense_no",
                "label": "费用单", "docType": "expense", "details": []},
    "credit_note": {"table": "credit_notes", "id": "credit_id", "no": "credit_no",
                    "label": "贷记单", "docType": "credit_note", "details": []},
    "order": {"table": "orders", "id": "order_id", "no": "order_no",
              "label": "订单", "docType": "order",
              "details": [("order_lines", "order_id")]},
    "payment_received": {"table": "payments_received", "id": "payment_id", "no": "payment_no",
                         "label": "收款单", "docType": "payment", "details": []},
    "payment_made": {"table": "payments_made", "id": "payment_id", "no": "payment_no",
                     "label": "付款单", "docType": "payment", "details": []},
    "journal": {"table": "journal_entries", "id": "entry_id", "no": "entry_no",
                "label": "日记账分录", "docType": "journal",
                "details": [("journal_lines", "entry_id")]},
}


@app.post("/drafts/<kind>/<int:doc_id>/delete")
def draft_delete(kind, doc_id):
    """删除当前实体的草稿；所有表名、列名均来自白名单。"""
    require_writer()
    cfg = _DRAFT_DELETE_KINDS.get(kind)
    if not cfg:
        raise ValueError("不支持删除该类型单据")
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    actor = p.get("actor", "system")
    table, id_col = cfg["table"], cfg["id"]

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE {id_col}=%s AND entity_id=%s FOR UPDATE",
                (doc_id, e["entity_id"]))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"{cfg['label']}不存在")
            if row["status"] != "draft":
                raise ValueError(f"只有草稿状态的{cfg['label']}可以删除")

            if kind in ("invoice", "bill"):
                source_col = "invoice_id" if kind == "invoice" else "bill_id"
                cur.execute(f"SELECT COUNT(*) n FROM settlements WHERE {source_col}=%s", (doc_id,))
                if cur.fetchone()["n"]:
                    raise ValueError("该单据已有收付款核销记录，不能删除；请先处理核销关系")
                credit_col = "source_invoice_id" if kind == "invoice" else "source_bill_id"
                cur.execute(f"""SELECT COUNT(*) n FROM credit_notes
                                 WHERE entity_id=%s AND {credit_col}=%s AND status<>'draft'""",
                            (e["entity_id"], doc_id))
                if cur.fetchone()["n"]:
                    raise ValueError("该单据已被非草稿贷记单引用，不能删除")
                cur.execute(f"""UPDATE credit_notes SET {credit_col}=NULL
                                 WHERE entity_id=%s AND {credit_col}=%s AND status='draft'""",
                            (e["entity_id"], doc_id))
                if kind == "bill":
                    cur.execute("""SELECT COUNT(*) n FROM expenses
                                    WHERE entity_id=%s AND bill_id=%s AND status<>'draft'""",
                                (e["entity_id"], doc_id))
                    if cur.fetchone()["n"]:
                        raise ValueError("该采购发票已被非草稿费用单引用，不能删除")
                    cur.execute("""UPDATE expenses SET bill_id=NULL
                                    WHERE entity_id=%s AND bill_id=%s AND status='draft'""",
                                (e["entity_id"], doc_id))
                cur.execute("""SELECT COUNT(*) n FROM bank_lines
                                WHERE entity_id=%s AND matched_type=%s AND matched_id=%s""",
                            (e["entity_id"], kind, doc_id))
                if cur.fetchone()["n"]:
                    raise ValueError("该单据已匹配银行流水，请先取消匹配再删除")

            elif kind == "order":
                checks = [
                    ("SELECT COUNT(*) n FROM order_fulfilments WHERE order_id=%s", (doc_id,)),
                    ("SELECT COUNT(*) n FROM order_lines WHERE order_id=%s AND done_qty<>0", (doc_id,)),
                    ("SELECT COUNT(*) n FROM invoices WHERE entity_id=%s AND source_order_id=%s",
                     (e["entity_id"], doc_id)),
                    ("SELECT COUNT(*) n FROM bills WHERE entity_id=%s AND source_po_id=%s",
                     (e["entity_id"], doc_id)),
                ]
                for sql, args in checks:
                    cur.execute(sql, args)
                    if cur.fetchone()["n"]:
                        raise ValueError("订单已有履行记录或已转出单据，不能删除")

            elif kind in ("payment_received", "payment_made"):
                direction = "received" if kind == "payment_received" else "made"
                cur.execute("DELETE FROM settlements WHERE direction=%s AND payment_id=%s",
                            (direction, doc_id))
                source_type = "payment_received" if direction == "received" else "payment_made"
                cur.execute("""SELECT entry_id, entry_no, status FROM journal_entries
                                WHERE entity_id=%s AND source_type=%s AND source_id=%s FOR UPDATE""",
                            (e["entity_id"], source_type, doc_id))
                linked_entries = cur.fetchall()
                if any(x["status"] != "draft" for x in linked_entries):
                    raise ValueError("该收付款已有关联的非草稿分录，不能删除")
                for entry in linked_entries:
                    cur.execute("DELETE FROM journal_lines WHERE entry_id=%s", (entry["entry_id"],))
                    cur.execute("DELETE FROM journal_entries WHERE entry_id=%s AND status='draft'",
                                (entry["entry_id"],))
                    append_audit(conn, {
                        "entity_id": e["entity_id"], "actor": actor, "actor_role": current_role(),
                        "action": "journal.delete", "object_type": "journal_entries",
                        "object_id": str(entry["entry_id"]),
                        "detail": {"entryNo": entry["entry_no"], "deletedWith": row[cfg["no"]]}})

            elif kind == "journal":
                if row.get("reversal_of_entry_id") or row.get("reversed_by_entry_id"):
                    raise ValueError("冲销关系中的分录不能删除")
                cur.execute("""SELECT COUNT(*) n FROM journal_entries
                                WHERE entity_id=%s AND entry_id<>%s
                                  AND (reversal_of_entry_id=%s OR reversed_by_entry_id=%s)""",
                            (e["entity_id"], doc_id, doc_id, doc_id))
                if cur.fetchone()["n"]:
                    raise ValueError("该分录已被其他分录引用，不能删除")

            for detail_table, detail_col in cfg["details"]:
                cur.execute(f"DELETE FROM {detail_table} WHERE {detail_col}=%s", (doc_id,))
            cur.execute("DELETE FROM doc_files WHERE entity_id=%s AND doc_type=%s AND doc_id=%s",
                        (e["entity_id"], cfg["docType"], doc_id))
            cur.execute("""UPDATE pending_review SET status='resolved', resolved_by=%s,
                              resolved_at=NOW(3), resolution='草稿单据已删除'
                            WHERE entity_id=%s AND ref_table=%s AND ref_id=%s AND status='open'""",
                        (actor, e["entity_id"], table, doc_id))
            cur.execute(f"DELETE FROM {table} WHERE {id_col}=%s AND entity_id=%s AND status='draft'",
                        (doc_id, e["entity_id"]))
            if cur.rowcount != 1:
                raise ValueError(f"只有草稿状态的{cfg['label']}可以删除")

        append_audit(conn, {
            "entity_id": e["entity_id"], "actor": actor, "actor_role": current_role(),
            "action": f"{kind.replace('_received', '').replace('_made', '')}.delete",
            "object_type": table, "object_id": str(doc_id),
            "detail": {"documentNo": row[cfg["no"]], "status": "draft"}})
    return J({"ok": True, "kind": kind, "id": doc_id, "status": "deleted"})


@app.post("/pending-review/<int:review_id>/resolve")
def resolve_review(review_id):
    require_writer()
    p = request.get_json(force=True) or {}
    e = entity_or_404()
    status = "dismissed" if p.get("action") == "dismiss" else "resolved"
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pending_review WHERE review_id=%s AND entity_id=%s",
                        (review_id, e["entity_id"]))
            row = cur.fetchone()
            if not row:
                raise ValueError("待复核项不存在")
            if row["status"] != "open":
                raise ValueError("该待复核项已处理")
            cur.execute("""UPDATE pending_review SET status=%s, resolved_by=%s,
                           resolved_at=NOW(3), resolution=%s WHERE review_id=%s""",
                        (status, p.get("actor", "accountant"), p.get("resolution"), review_id))
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "accountant"),
                                "action": f"pending_review.{status}",
                                "object_type": "pending_review", "object_id": str(review_id),
                                "detail": {"kind": row["kind"], "reason": row["reason"],
                                           "resolution": p.get("resolution")}})
    return J({"reviewId": review_id, "status": status})


@app.post("/bank/lines")
def add_bank_line():
    require_writer()
    p = request.get_json(force=True) or {}
    e = entity_or_404()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                        (p.get("bankAccountId"), e["entity_id"]))
            acct = cur.fetchone()
            if not acct:
                raise ValueError("银行账户不存在")
            ccy = acct["currency"]
            line_ccy = str(p.get("currency") or ccy).upper()
            if line_ccy != ccy:
                raise ValueError(f"流水币种 {line_ccy} 与账户币种 {ccy} 不一致")

            amount = dec(p.get("amountOriginal"))
            functional, fx_rate = amount, dec(1)
            if ccy != e["functional_currency"]:
                cur.execute("""SELECT rate_date, from_ccy, to_ccy, rate FROM fx_rates
                                WHERE from_ccy=%s AND to_ccy=%s AND rate_date<=%s
                                ORDER BY rate_date DESC LIMIT 10""",
                            (ccy, e["functional_currency"], p.get("txnDate")))
                rows = cur.fetchall()
                if not rows:
                    raise ValueError(f"缺少 {ccy}→{e['functional_currency']} 在 {p.get('txnDate')} 的汇率")
                row = rows[0]
                fx_rate = dec(row["rate"])
                from core.money import convert
                functional = convert(amount, fx_rate)

            cur.execute("""INSERT INTO bank_lines
                (entity_id,bank_account_id,bank_ref,txn_date,amount_original,currency,
                 counterparty_name,amount_functional,fx_rate,fx_rate_date,source_file_path,
                 statement_import_batch_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (e["entity_id"], acct["account_id"], p.get("bankRef"), p.get("txnDate"),
                 amount, ccy, p.get("counterpartyName"), functional, fx_rate,
                 p.get("txnDate"), p.get("sourceFilePath"), p.get("batchId")))
            line_id = cur.lastrowid
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "accountant"),
                                "action": "bank_line.create", "object_type": "bank_lines",
                                "object_id": str(line_id),
                                "detail": {"amount": float(amount), "currency": ccy,
                                           "fxRate": float(fx_rate)}})
    return J({"lineId": line_id, "currency": ccy,
              "amountFunctional": float(functional), "fxRate": float(fx_rate)})


@app.get("/bank/lines/<int:line_id>/files")
def bank_line_files(line_id):
    """流水的附件清单（回单、存款单、支票影像）。"""
    e = entity_or_404()
    rows = query("""SELECT file_id, file_name, file_type, file_size, sha256_hash, uploaded_by, uploaded_at
                      FROM bank_line_files WHERE line_id=%s AND entity_id=%s ORDER BY file_id""",
                 (line_id, e["entity_id"]))
    return J({"files": [dict(r, uploaded_at=r["uploaded_at"].isoformat(sep=" ", timespec="milliseconds"))
                        for r in rows]})


@app.post("/bank/lines/<int:line_id>/files")
def bank_line_file_add(line_id):
    """登记流水附件：与发票/账单附件同一套 SHA-256 与留存规则。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    name = str(p.get("fileName") or "").strip()
    path = str(p.get("storagePath") or "").strip()
    sha = str(p.get("sha256") or "").strip().lower()
    size = int(p.get("fileSize") or 0)
    if not name or not path:
        raise ValueError("缺少文件名或存储路径")
    if len(sha) != 64:
        raise ValueError("SHA-256 必须是 64 位十六进制")
    line = query_one("""SELECT line_id, txn_date FROM bank_lines
                         WHERE line_id=%s AND entity_id=%s""", (line_id, e["entity_id"]))
    if not line:
        raise ValueError("银行流水不存在")
    retention = date(int(str(line["txn_date"])[:4]) + 7, 12, 31)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO bank_line_files
                (entity_id, line_id, file_name, file_type, file_size, sha256_hash, storage_path,
                 uploaded_by, retention_until)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (e["entity_id"], line_id, name[:255],
                         str(p.get("fileType") or "other")[:64], size, sha, path[:500],
                         p.get("actor", "system"), retention))
            fid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "bank_line_file.upload", "object_type": "bank_line_files",
                            "object_id": str(fid),
                            "detail": {"lineId": line_id, "fileName": name,
                                       "fileSize": size, "sha256": sha}})
    return J({"fileId": fid, "sha256": sha, "fileSize": size})


@app.get("/bank-line-files/<int:file_id>")
def bank_line_file_get(file_id):
    e = entity_or_404()
    row = query_one("""SELECT * FROM bank_line_files
                        WHERE file_id=%s AND entity_id=%s""", (file_id, e["entity_id"]))
    if not row:
        raise ValueError("附件不存在")
    return J(dict(row, uploaded_at=row["uploaded_at"].isoformat(sep=" ", timespec="milliseconds")))


@app.post("/bank/lines/<int:line_id>/post")
def bank_line_post(line_id):
    """无单据的流水直接入账：手续费、利息、银行杂费这类。

    生成一条两行分录：银行科目 ←→ 对方科目，并把流水标记为已匹配。
    金额正负决定借贷方向，不能由调用方指定。
    """
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    actor = str(p.get("actor") or "system")
    line = query_one("""SELECT l.*, a.account_code AS bank_code, a.name AS bank_name
                          FROM bank_lines l JOIN bank_accounts a ON a.account_id=l.bank_account_id
                         WHERE l.line_id=%s AND l.entity_id=%s""", (line_id, e["entity_id"]))
    if not line:
        raise ValueError("银行流水不存在")
    if str(line.get("match_status")) == "matched":
        raise ValueError("这笔流水已经匹配或入账，不能重复记账")

    code = str(p.get("accountCode") or "").strip()
    if not code:
        raise ValueError("请选择对方科目")
    acct = query_one("""SELECT account_code, account_name FROM accounts
                         WHERE entity_id=%s AND account_code=%s""", (e["entity_id"], code))
    if not acct:
        raise ValueError(f"科目 {code} 不存在")

    amt = dec(line["amount_functional"] or line["amount_original"])
    bank_code = str(line["bank_code"])
    desc = (str(p.get("description") or "").strip()
            or str(line.get("counterparty_name") or "")[:120]
            or f"银行流水 {line['txn_date']}")

    # 钱进银行：借银行 / 贷对方；钱出银行：借对方 / 贷银行
    if amt >= 0:
        dr, cr, dr_amt, cr_amt = bank_code, code, amt, amt
    else:
        dr, cr, dr_amt, cr_amt = code, bank_code, -amt, -amt

    with transaction() as conn:
        with conn.cursor() as cur:
            entry_no = next_no(conn, e["entity_id"], str(line["txn_date"])[:10], "journal")
            # period 是生成列（由 entry_date 推出），不能显式插入
            cur.execute("""INSERT INTO journal_entries
                (entity_id, entry_no, entry_date, source_type, source_id, description,
                 status, total_debit, total_credit, created_by,
                 report_ready, reconciled_at, reconciled_by, retention_until)
                VALUES (%s,%s,%s,'bank_line',%s,%s,'draft',%s,%s,%s,0,NOW(3),%s,
                        DATE_ADD(%s, INTERVAL 7 YEAR))""",
                        (e["entity_id"], entry_no, str(line["txn_date"])[:10],
                         line_id, desc, float(dr_amt), float(cr_amt),
                         actor, actor, str(line["txn_date"])[:10]))
            entry_id = cur.lastrowid
            for seq, (code_, amt_) in enumerate([(dr, dr_amt), (cr, cr_amt)], start=1):
                cur.execute("""INSERT INTO journal_lines
                    (entry_id, line_no, account_code, debit, credit, description, ccy)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (entry_id, seq, code_,
                             float(amt_) if seq == 1 else 0,
                             0 if seq == 1 else float(amt_), desc[:200],
                             str(line["currency"])))
            # 行插完才置为已过账：触发器不允许往已过账分录追加行
            cur.execute("""UPDATE journal_entries
                              SET status='posted', posted_by=%s, posted_at=NOW(3)
                            WHERE entry_id=%s""", (actor, entry_id))
            cur.execute("""UPDATE bank_lines
                              SET match_status='matched', matched_type='journal',
                                  matched_id=%s, match_confidence='high', match_rule='manual',
                                  matched_currency=currency,
                                  matched_amount_at_rate=amount_original
                            WHERE line_id=%s""", (entry_id, line_id))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "bank_line.post", "object_type": "journal_entries",
                            "object_id": str(entry_id),
                            "detail": {"lineId": line_id, "entryNo": entry_no,
                                       "accountCode": code,
                                       "amount": float(dr_amt)}})
    return J({"entryId": entry_id, "entryNo": entry_no, "accountCode": code,
              "amount": float(dr_amt)})


@app.post("/bank/import-check")
def bank_import_check():
    return J(bankrec.validate_statement(request.get_json(force=True) or {}))


def bank_match_core(acct_id: int) -> dict:
    """给某个账户的未匹配流水算候选（确定性打分，不动数据）。"""
    e = entity_or_404()
    acct = query_one("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                     (acct_id, e["entity_id"]))
    if not acct:
        raise ValueError("银行账户不存在")

    lines = query("""SELECT line_id AS lineId, bank_account_id, currency, amount_original,
                            txn_date, bank_ref, counterparty_name, fx_rate
                       FROM bank_lines WHERE bank_account_id=%s
                         AND match_status IN ('unmatched','pending')""", (acct_id,))
    docs = query("""SELECT invoice_id AS docId, 'invoice' AS docType, invoice_no AS doc_no,
                           currency, (gross_original-settled_original) AS outstanding_original,
                           invoice_date AS txn_date, supplier_name AS counterparty_name
                      FROM invoices WHERE entity_id=%s AND status='posted'
                        AND (gross_original-settled_original)>0""", (e["entity_id"],))
    rates = query("""SELECT rate_date, from_ccy, to_ccy, rate FROM fx_rates
                      WHERE rate_date>=DATE_SUB(CURDATE(), INTERVAL 400 DAY)""")
    from core.service import load_rules
    rules = load_rules()

    bl = [dict(l, amount_original=float(dec(l["amount_original"])),
               fx_rate=float(dec(l["fx_rate"])) if l["fx_rate"] is not None else None,
               txn_date=l["txn_date"].isoformat()) for l in lines]
    dc = [dict(d, outstanding_original=float(dec(d["outstanding_original"])),
               txn_date=d["txn_date"].isoformat()) for d in docs]
    rt = [dict(r, rate=float(dec(r["rate"])), rate_date=r["rate_date"].isoformat()) for r in rates]

    return bankrec.match_bank_lines(bl, dc, rules["fx_policy"], rt)


@app.post("/bank/match")
def bank_match():
    """给账户里的未匹配流水算候选（只算不写）。"""
    p = request.get_json(force=True) or {}
    return J(bank_match_core(int(p.get("bankAccountId") or 0)))


def bank_confirm_match_core(p: dict) -> dict:
    """人工确认一条流水与发票匹配（可被 API 与智能体工具共用）。"""
    e = entity_or_404()
    line_id, doc_id = p.get("lineId"), p.get("docId")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bank_lines WHERE line_id=%s AND entity_id=%s", (line_id, e["entity_id"]))
            line = cur.fetchone()
            if not line:
                raise ValueError("流水不存在")
            cur.execute("SELECT * FROM invoices WHERE invoice_id=%s AND entity_id=%s", (doc_id, e["entity_id"]))
            inv = cur.fetchone()
            if not inv:
                raise ValueError("发票不存在")

            same = str(line["currency"]).upper() == str(inv["currency"]).upper()
            diff = abs(dec(line["amount_original"]) - (dec(inv["gross_original"]) - dec(inv["settled_original"])))
            if not same and not p.get("reason"):
                raise ValueError("跨币种匹配必须填写人工确认理由")

            cur.execute("""UPDATE bank_lines SET match_status='matched', matched_type='invoice',
                           matched_id=%s, match_confidence='high', match_rule=%s,
                           matched_currency=%s, matched_amount_at_rate=%s WHERE line_id=%s""",
                        (doc_id, p.get("rule", "P2"), inv["currency"],
                         dec(line["amount_original"]), line_id))
            cur.execute("""UPDATE invoices SET settled_original = LEAST(gross_original,
                           settled_original + %s) WHERE invoice_id=%s""",
                        (dec(line["amount_original"]), doc_id))
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "accountant"),
                                "action": "bank_match.confirm", "object_type": "bank_lines",
                                "object_id": str(line_id),
                                "detail": {"invoiceId": doc_id, "diff": float(diff),
                                           "reason": p.get("reason"), "crossCurrency": not same}})
    return {"lineId": line_id, "invoiceId": doc_id, "matched": True,
            "crossCurrency": not same, "difference": float(diff)}


@app.post("/bank/confirm-match")
def bank_confirm_match():
    require_writer()
    return J(bank_confirm_match_core(request.get_json(force=True) or {}))


@app.post("/fx/revalue")
def do_revalue():
    require_writer()
    p = request.get_json(force=True) or {}
    period = p.get("period")
    if not period:
        raise ValueError("必须提供 period（YYYY-MM）")
    return J(run_revaluation(period, p.get("actor", "accountant")))


@app.post("/fx/anomalies")
def fx_anomalies():
    p = request.get_json(force=True) or {}
    rows = query("SELECT rate_date, from_ccy, to_ccy, rate FROM fx_rates ORDER BY rate_date")
    rates = [dict(r, rate=float(dec(r["rate"])), rate_date=r["rate_date"].isoformat()) for r in rows]
    return J(bankrec.detect_rate_anomalies(rates, int(p.get("windowDays", 30)),
                                           float(p.get("thresholdPercent", 5))))


@app.post("/journal/<int:entry_id>/reverse")
def do_reverse(entry_id):
    require_writer()
    p = request.get_json(force=True) or {}
    return J(reverse_entry(entry_id, p.get("actor", "accountant"), p.get("reason", "")))


# ---------------------------------------------------------------- 智能体平台
@app.get("/agents/list")
def agents_list():
    from core.agents import registry, tools_deterministic as _t  # noqa: F401
    from core.agents import toolbox
    e = entity_or_404()
    return J({
        "agents": [{"id": k, "label": v["label"], "tools": registry.whitelist(k),
                    "role": "advisor" if k in registry.advisor_agents() else "role"}
                   for k, v in registry.AGENTS.items()],
        "tools": toolbox.describe(),
        "canWrite": False,
        "note": "所有工具均为只读；记账/作废/冲销只能由人工确认后由确定性代码执行",
        "entityId": e["entity_id"],
    })


@app.post("/agents/run")
def agents_run():
    """跑一个智能体。只出建议，不写账。"""
    from core.agents import runtime as ar
    p = request.get_json(force=True) or {}
    agent = str(p.get("agent") or "controller")
    text = str(p.get("text") or "").strip()
    tok = str(p.get("progressToken") or "").strip()
    from flask import g as _g
    _g.ledu_lang = str(p.get("lang") or request.args.get("lang") or "en")
    _g.ledu_text = text
    set_progress(tok, "agent", "正在理解你的问题")
    if not text:
        raise ValueError("指令不能为空")
    e = entity_or_404()
    # 把关键业务事实注入上下文，避免智能体反复查同一件事或「说查不到」
    ctx = dict(p.get("context") or {})
    ctx.setdefault("company", e.get("entity_name"))
    ctx.setdefault("functionalCurrency", e.get("functional_currency"))
    ctx.setdefault("twoTierStatus", e.get("two_tier_status"))
    ctx.setdefault("today", __import__("datetime").date.today().isoformat())
    r = ar.run(agent, text, actor=p.get("actor", "owner"),
               scene=p.get("scene"), context=ctx,
               entity_id=e["entity_id"],
               allow_write=bool(p.get("allowWrite", True)),
               role=current_role() or "admin")
    set_progress(tok, "done", "完成")
    return J(r)


@app.get("/agents/runs")
def agents_runs():
    e = entity_or_404()
    try:
        limit = min(200, max(1, int(request.args.get("limit", 50))))
    except (TypeError, ValueError):
        limit = 50
    rows = query("""SELECT run_id, agent, trigger_by, scene, verdict, tokens, latency_ms,
                           model, error, created_at
                      FROM ai_run WHERE entity_id=%s ORDER BY run_id DESC LIMIT %s""",
                 (e["entity_id"], limit))
    return J({"runs": [{**dict(r), "created_at": r["created_at"].isoformat(sep=" ", timespec="minutes")}
                       for r in rows]})


@app.get("/agents/stats")
def agents_stats():
    from core.agents import runtime as ar, learning
    e = entity_or_404()
    return J({"stats": ar.stats(), "learning": learning.summary(e["entity_id"])})


@app.get("/agents/learning")
def agents_learning():
    from core.agents import learning
    e = entity_or_404()
    return J({"rules": learning.list_rules(e["entity_id"]),
              "summary": learning.summary(e["entity_id"])})


@app.get("/agents/extractor/learning")
def agents_extractor_learning():
    """票据识别的学习情况：纠正样本、学到的规则、最近改了什么。"""
    from core.agents import extractor_learning as exl
    e = entity_or_404()
    eid = e["entity_id"]
    recent = []
    for r in query("""SELECT sample_id, vendor_key, changed, actor, created_at
                        FROM extract_samples WHERE entity_id=%s
                        ORDER BY sample_id DESC LIMIT 10""", (eid,)):
        try:
            changed = json.loads(r["changed"])
        except (TypeError, ValueError):
            changed = []
        recent.append({"sampleId": r["sample_id"], "vendorKey": r["vendor_key"],
                       "changed": changed, "actor": r["actor"],
                       "at": r["created_at"].isoformat(sep=" ", timespec="minutes")
                       if hasattr(r["created_at"], "isoformat") else str(r["created_at"])})
    rules = []
    for r in exl.rules_for(eid):
        rules.append({**r, "label": exl.LEARNABLE_FIELDS.get(str(r["field"]), str(r["field"]))})
    sm = exl.summary(eid)
    for f in sm.get("topFields") or []:
        f["label"] = exl.LEARNABLE_FIELDS.get(str(f["field"]), str(f["field"]))
    return J({"summary": sm, "rules": rules, "recent": recent})


@app.post("/agents/extractor/promote")
def agents_extractor_promote():
    """立刻把够格的纠正固化成规则（定时任务每天也跑一次）。"""
    require_writer()
    from core.agents import extractor_learning as exl
    e = entity_or_404()
    return J({"promoted": exl.promote(e["entity_id"])})


@app.post("/agents/learning/promote")
def agents_learning_promote():
    require_writer()
    from core.agents import learning
    e = entity_or_404()
    return J({"promoted": learning.promote(e["entity_id"])})


@app.post("/agents/learning/<int:rule_id>/status")
def agents_learning_status(rule_id):
    require_writer()
    from core.agents import learning
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    ok = learning.set_status(rule_id, str(p.get("status") or "paused"), e["entity_id"])
    return J({"ok": ok})


# ---------------------------------------------------------------- 学习固化定时任务
@app.get("/jobs/learning")
def jobs_learning_state():
    """学习固化任务的状态：观察期、最近动作。定时任务每天 02:30 HKT 跑一次。"""
    from core.agents import scheduler, learning
    e = entity_or_404()
    eid = e["entity_id"]
    obs = scheduler.observation_state(eid)
    return J({"observation": obs, "history": scheduler.history(eid, 10),
              "conflicts": scheduler.conflicts(eid),
              "summary": learning.summary(eid),
              "schedule": {"cron": "30 18 * * *", "tz": "UTC",
                           "localTime": "02:30 Asia/Hong_Kong"}})


@app.post("/jobs/learning/run")
def jobs_learning_run():
    """立刻跑一次固化（与定时任务同一套逻辑：先降级冲突，再固化）。"""
    require_writer()
    from core.agents import scheduler
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    res = scheduler.run_daily(entity_id=e["entity_id"],
                              actor=str(p.get("actor") or "learning-bot"),
                              dry_run=bool(p.get("dryRun")))
    return J(res)


# ---------------------------------------------------------------- AI 待确认动作
@app.get("/ai/actions")
def ai_actions_list():
    """待确认的提案。人在这里看卡片、点确认或放弃。"""
    from core.agents import actions as ai_actions
    e = entity_or_404()
    status = str(request.args.get("status") or "proposed")
    if status == "proposed":
        return J({"actions": ai_actions.pending(e["entity_id"], int(request.args.get("limit") or 20)),
                  "status": status})
    rows = query("""SELECT action_id, action_type, title, summary, status, created_by,
                           confirmed_by, created_at, decided_at, result
                      FROM ai_actions WHERE entity_id=%s AND status=%s
                     ORDER BY action_id DESC LIMIT 50""", (e["entity_id"], status))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("summary", "result"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except (TypeError, ValueError):
                    pass
        for k in ("created_at", "decided_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat(sep=" ", timespec="minutes")
        out.append(d)
    return J({"actions": out, "status": status})


@app.post("/ai/actions")
def ai_action_propose():
    """（内部）登记一个提案。工具层也走这里，保证只有一个入口。"""
    require_writer()
    from core.agents import actions as ai_actions
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    payload = p.get("payload") or {}
    payload.setdefault("actor", p.get("actor") or "agent")
    role_map = {"bill": "create_bill", "invoice": "create_invoice",
                "expense": "create_expense"}
    kind = str(p.get("kind") or p.get("actionType") or "bill")
    return J(ai_actions.propose(e["entity_id"], role_map.get(kind, kind), payload,
                                actor=str(p.get("actor") or "agent"),
                                run_id=p.get("runId"),
                                source_file=p.get("sourceFile")))


def ai_bank_statement_executor(p: dict) -> dict:
    """确认后：导入流水 → 给账户算候选 → 自动核销 P1/P2 高置信匹配。"""
    res = bank_import_core({**p, "actor": p.get("actor") or "agent"})
    m = bank_match_core(int(p.get("bankAccountId") or 0))
    matched = 0
    for x in (m.get("matches") or []):
        if not x.get("autoMatch"):
            continue
        bank_confirm_match_core({"lineId": x["lineId"], "docId": x["docId"],
                                 "rule": x.get("rule"), "reason": "对账单导入后自动匹配",
                                 "actor": p.get("actor") or "agent"})
        matched += 1
    return {"imported": res.get("inserted"), "skipped": res.get("skipped"),
            "duplicate": bool(res.get("duplicate")),
            "batchId": res.get("batchId"),
            "matched": matched,
            "pending": len(m.get("pending") or []),
            "unmatched": len(m.get("unmatched") or []),
            "href": "?p=reconcile"}


@app.post("/ai/actions/<int:action_id>/confirm")
def ai_action_confirm(action_id):
    """人工确认：以登录用户身份执行，写审计。智能体不能调这个接口（要 X-Ledu-Role）。"""
    require_writer()
    from core.agents import actions as ai_actions
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    actor = str(p.get("actor") or "").strip()
    if not actor:
        raise ValueError("确认必须带操作人（登录用户）")
    role = current_role()
    return J(ai_actions.confirm(action_id, actor, e["entity_id"], role,
                                post_executor=one_click_post,
                                bank_executor=ai_bank_statement_executor,
                                options={"bankAccountId": p.get("bankAccountId"),
                                         "accountCode": p.get("accountCode"),
                                         "creditKey": p.get("creditKey"),
                                         "expenseNature": p.get("expenseNature"),
                                         "fields": p.get("fields") or {},
                                         "answers": p.get("answers") or {}}))


@app.post("/ai/actions/<int:action_id>/cancel")
def ai_action_cancel(action_id):
    require_writer()
    from core.agents import actions as ai_actions
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    return J(ai_actions.cancel(action_id, str(p.get("actor") or "user"),
                               e["entity_id"], current_role()))


@app.post("/ai/import")
def ai_import_document():
    """导入一张单据：OCR/文本 → 提取 → 匹配 → 生成待确认提案（不入账）。"""
    require_writer()
    from core.agents import actions as ai_actions
    e = entity_or_404()
    p = request.get_json(silent=True) or {}
    # multipart 上传时没有 JSON：文件和其余字段在 form 里，两处都要读
    form = request.form if request.form else {}
    path = str(p.get("path") or form.get("path") or "").strip()
    text = str(p.get("text") or form.get("text") or "").strip()
    kind = str(p.get("kind") or form.get("kind") or "").strip()
    tok = str(p.get("progressToken") or form.get("progressToken") or "").strip()
    set_progress(tok, "start", "收到，开始处理")

    # 前端直传文件：存到 storage/ 再走 OCR，避免让 PHP 传绝对路径
    up = request.files.get("file") if request.files else None
    if up is not None and up.filename:
        import re as _re
        import secrets as _secrets
        from pathlib import Path as _P
        # 与界面手工上传同一个目录、同一套命名：附件在一个地方，备份与存档规则才管得到
        safe = _re.sub(r"[^A-Za-z0-9._-]+", "_", up.filename)[-80:] or "upload"
        root = UPLOAD_DIR
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"{date.today().strftime('%Y%m%d')}-{_secrets.token_hex(6)}-{safe}"
        up.save(str(dest))
        try:
            dest.chmod(0o640)
        except OSError:
            pass
        path = str(dest)

    if not text and path:
        set_progress(tok, "ocr", "正在读取文件并提取文字（OCR）")
        from core.ocr import OCRError, extract_text
        try:
            got = extract_text(path)
        except OCRError as ex:
            return J({"error": "ocr_error", "message": str(ex)}, 400)
        text = got.get("text") or ""
    if len(text.strip()) < 10:
        return J({"error": "ocr_error",
                  "message": "没有识别到文字；扫描件请确认清晰度，或改用粘贴文本"}, 400)

    # 先区分对账单、期初余额表和业务单据，避免对非发票材料白跑一次模型。
    # 银行月结单不是发票：先拦下来，别用发票模型去解析流水
    set_progress(tok, "classify", "正在判断这是发票、对账单还是上年结转表")
    # 上年结转：科目余额表（有「科目代码 + 借方/贷方」，没有日期/摘要列）
    from core import opening as _opening
    if _opening.looks_like_trial_balance(text):
        set_progress(tok, "opening", "正在读科目余额表")
        parsed = _opening.parse_trial_balance(text, e["entity_id"])
        if not parsed.get("rows"):
            return J({"error": "opening_parse_failed",
                      "message": "没读到科目行；" + "；".join(parsed.get("warnings") or []),
                      }, 400)
        from core.agents import actions as _ai_actions
        set_progress(tok, "propose", "正在核对科目与借贷平衡")
        od = request.args.get("openingDate") or ""
        prop = _ai_actions.propose_opening(
            e["entity_id"], parsed, actor=str(p.get("actor") or form.get("actor") or "user"),
            opening_date=od, source_file=path.rsplit("/", 1)[-1] if path else None,
            source_path=path or None,
            source_name=(up.filename if up is not None and up.filename else None))
        set_progress(tok, "done", "识别完成")
        prop["kind"] = "opening"
        return J(prop)

    from core.ai import AIError, extract_invoice, looks_like_statement
    ext = (path.rsplit(".", 1)[-1].lower() if path and "." in path else "")
    # 银行对账单：电子表格一律按对账单处理；PDF/图片看关键词
    chk = looks_like_statement(text)
    is_stmt = chk["isStatement"] or ext in ("csv", "xlsx", "xls")
    if is_stmt:
        # 对账单就在 AI 页面处理完：解析 → 认账户 → 生成「导入 + 自动核销」提案
        if not path:
            return J({"error": "statement_needs_file",
                      "message": "对账单需要上传文件（PDF/CSV/XLSX）才能解析。"}, 400)
        set_progress(tok, "parse_statement", "正在解析对账单流水")
        from core.statement_parser import parse_statement
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            parsed = parse_statement(raw, path.rsplit("/", 1)[-1])
        except Exception as ex:
            return J({"error": "statement_parse_failed",
                      "message": f"对账单解析失败：{ex}"}, 400)
        rows = parsed.get("rows") or []
        if not rows:
            return J({"error": "statement_empty",
                      "message": "没有解析出任何交易行，请换一份清晰的对账单。"}, 400)
        meta = parsed.get("meta") or {}
        acct = None
        flat = text.replace(" ", "").replace("-", "")
        cands = query("""SELECT account_id, name, currency, account_number_masked, account_number
                           FROM bank_accounts WHERE entity_id=%s AND status='active'""",
                      (e["entity_id"],))
        for a in cands:
            num = str(a.get("account_number") or "").replace("-", "")
            if num and num in flat:
                acct = a
                break
        if acct is None and len(cands) == 1:
            acct = cands[0]
        if acct is None:
            acct = {"account_id": 0, "name": "（未识别账户，请在卡片上选择）",
                    "currency": "HKD", "account_number_masked": ""}
        import hashlib as _h
        prop = ai_actions.propose_bank_statement(
            e["entity_id"], rows=rows,
            header={"openingBalance": meta.get("openingBalance"),
                    "closingBalance": meta.get("closingBalance"),
                    "totalDebits": meta.get("totalDebits"),
                    "totalCredits": meta.get("totalCredits"),
                    "periodStart": min(r["date"] for r in rows),
                    "periodEnd": max(r["date"] for r in rows)},
            sha=_h.sha256(raw).hexdigest(), account=dict(acct),
            warnings=(parsed.get("warnings") or [])[:4],
            actor=str(p.get("actor") or form.get("actor") or "user"),
            source_file=path.rsplit("/", 1)[-1])
        prop["kind"] = "statement"
        prop["accounts"] = [{"accountId": int(a["account_id"]), "name": a["name"],
                             "currency": a["currency"],
                             "account": a["account_number_masked"]} for a in cands]
        return J(prop)


    set_progress(tok, "extract", "正在用模型识别字段（金额、日期、往来单位）")
    from core.agents import extractor_learning as exl
    _hint_vendor = exl.guess_vendor(text, e["entity_id"])
    try:
        data = extract_invoice(text, hints=exl.hints_text(e["entity_id"], _hint_vendor))
    except AIError as ex:
        return J({"error": "ai_error", "message": str(ex)}, 503)

    # 识别之后先套学到的规则（同一供应商的名称/币种/税额不该每次不一样）
    _raw = dict(data)
    data = exl.apply_rules(data, e["entity_id"])

    # 方向由单据角色决定，而不是由「对方有没有建档」决定：
    #   本公司是开票方 → 销售；本公司是受票方 → 采购。
    # 同时核对实体的中英文/法定名称，避免 OCR 使用别名时把销售发票误判成采购。
    def _norm2(x: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(x or "").lower())

    sup = str(data.get("supplierName") or "").strip()
    cust = str(data.get("customerName") or "").strip()
    self_keys = {_norm2(e.get(k)) for k in
                 ("entity_name", "legal_name", "legal_name_zh") if _norm2(e.get(k))}

    def _is_self(name: str) -> bool:
        key = _norm2(name)
        return bool(key) and any(
            key == own or (min(len(key), len(own)) >= 6 and (key in own or own in key))
            for own in self_keys)

    sup_is_self, cust_is_self = _is_self(sup), _is_self(cust)
    m_vendor = ai_actions.match_party("create_bill", sup, e["entity_id"])
    m_customer = ai_actions.match_party("create_invoice", cust, e["entity_id"])
    direction_needs_confirmation = False
    if kind in ("bill", "invoice", "expense"):
        direction_why = "由调用方指定"
    elif sup_is_self and not cust_is_self:
        kind = "invoice"
        direction_why = f"开票方是本公司（{sup}），按销售发票处理"
    elif cust_is_self and not sup_is_self:
        kind = "bill"
        direction_why = f"受票方是本公司（{cust}），按采购发票处理"
    elif sup_is_self and cust_is_self:
        # 双方都被识别成本公司通常是 OCR 字段错位，不能武断记成内部购销。
        kind = "bill"
        direction_needs_confirmation = True
        direction_why = "开票方与受票方均像本公司，需核对购销方向"
    elif m_customer.get("matched") and cust:
        kind = "invoice"
        direction_why = f"受票方 {m_customer.get('name')} 是已建档客户，按销售发票处理"
    elif sup:
        kind = "bill"
        if m_vendor.get("matched"):
            direction_why = (f"开票方 {m_vendor.get('name')} 是已建档供应商"
                             f"（{m_vendor.get('code')}），按采购发票处理")
        elif int(m_vendor.get("historyUses") or 0) > 0:
            direction_why = (f"开票方 {sup} 在历史账单里出现过 "
                             f"{m_vendor['historyUses']} 次，按采购发票处理")
        else:
            direction_why = f"开票方 {sup} 不是本公司，按采购发票处理；未建档不影响方向判断"
    else:
        kind = "bill"
        direction_needs_confirmation = True
        direction_why = "缺少可辨认的开票方，需核对购销方向"

    # 采购优先往来开票方，销售优先往来受票方；缺失时才回退到另一方。
    party = (sup or cust) if kind in ("bill", "expense") else (cust or sup)
    if not party.strip():
        return J({"error": "no_party",
                  "message": ("没识别到开票方/受票方名称，无法确定往来单位。"
                              "直接把对方名称告诉我（例如「供应商是 ABC Ltd，金额 1,200」），"
                              "我就在这里把单建掉；也可以换一份更清晰的原件。")}, 400)
    type_map = {"bill": "create_bill", "invoice": "create_invoice", "expense": "create_expense"}
    action_type = type_map.get(kind, "create_bill")
    # 用同一套确定性规则判断支出性质。销售明确标记为不适用；采购证据不足时
    # 保留空值，确认接口会要求人选择，不能由提案层偷偷默认成公司支出。
    from core import doc_analyze
    analysis = doc_analyze.analyze(
        text, entity_id=e["entity_id"], party=party, lines=data.get("lines") or [],
        extracted={**data, "actionType": action_type})
    payload = {
        "_incomplete": ("amount" if not (data.get("amountOriginal") or data.get("lines")) else None),
        "partyName": party,
        "_supplierName": sup,
        "_customerName": cust,
        "date": data.get("invoiceDate"),
        "dueDate": data.get("dueDate"),
        "currency": data.get("currency") or "HKD",
        "amountOriginal": data.get("amountOriginal") or 0,
        "taxOriginal": data.get("taxOriginal") or 0,
        "docNo": data.get("invoiceNo"),
        "docText": text,
        "lines": data.get("lines") or [],
        "confidence": data.get("confidence"),
        "warnings": data.get("warnings") or [],
        "learned": data.get("_rulesApplied") or [],
        "directionWhy": direction_why,
        "directionNeedsConfirmation": direction_needs_confirmation,
        "expenseNature": analysis.get("expenseNature") or "",
        "_natureWhy": analysis.get("expenseNatureWhy") or "",
        "actor": str(p.get("actor") or form.get("actor") or "user"),
    }
    set_progress(tok, "propose", "正在核对往来单位、科目与重复单据")
    prop = ai_actions.propose(e["entity_id"], action_type, payload,
                              actor=str(p.get("actor") or form.get("actor") or "user"),
                              source_file=path.rsplit("/", 1)[-1] if path else None,
                              actor_role="system",
                              source_path=path or None,
                              source_name=(up.filename if up is not None and up.filename else
                                           (path.rsplit("/", 1)[-1] if path else None)))
    prop["extraction"] = {k: data.get(k) for k in
                          ("invoiceNo", "supplierName", "customerName", "invoiceDate",
                           "dueDate", "currency", "amountOriginal", "taxOriginal",
                           "grossOriginal", "confidence", "warnings")}
    prop["analysis"] = analysis
    set_progress(tok, "done", "识别完成")
    prop["kind"] = kind
    prop["fields"] = {"partyName": party, "date": data.get("invoiceDate"),
                      "docNo": data.get("invoiceNo"), "currency": data.get("currency") or "HKD",
                      "amountOriginal": data.get("amountOriginal") or 0,
                      "taxOriginal": data.get("taxOriginal") or 0}
    prop["editable"] = True
    return J(prop)


@app.post("/agents/feedback")
def agents_feedback():
    require_writer()
    from core.agents import learning
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    ok = learning.record(str(p.get("agent") or "accountant"),
                         str(p.get("sceneKey") or ""),
                         p.get("suggested"), p.get("accepted"),
                         entity_id=e["entity_id"])
    return J({"recorded": ok, "learnable": learning.learnable(str(p.get("sceneKey") or ""))})


@app.get("/agent/tools")
def agent_tools():
    """智能体状态与工具清单。"""
    from core import agent
    return J(agent.agent_info())


@app.post("/agent/reconciliation-snapshot")
def agent_snapshot():
    """对账快照 —— 由 DSH HKFRS 财务守门人智能体计算。"""
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    lines = query("""SELECT line_id, bank_ref, txn_date, amount_original, currency,
                            counterparty_name FROM bank_lines
                       WHERE entity_id=%s AND match_status IN ('unmatched','pending')""",
                  (e["entity_id"],))
    items = [{"ref": l["bank_ref"] or f"BL-{l['line_id']}",
              "date": l["txn_date"].isoformat(),
              "amount": float(dec(l["amount_original"])),
              "category": l["currency"],
              "counterparty": l["counterparty_name"]} for l in lines]
    snapshot = {"asOf": p.get("asOf") or date.today().isoformat(),
                "accountCode": p.get("accountCode"),
                "accountName": p.get("accountName"),
                "openingBalance": float(dec(p.get("openingBalance") or 0)),
                "items": items, "adjustments": p.get("adjustments") or []}
    from core import agent
    from core.agent import AgentUnavailable
    try:
        return J(agent.reconciliation_snapshot(snapshot))
    except AgentUnavailable as ex:
        return J({"error": "agent_unavailable", "message": str(ex),
                  "authorization": "NEVER_AUTHORIZES_SIGN_OFF"}, 503)


@app.post("/agent/variance")
def agent_variance():
    """差异桥接 —— 由智能体计算，残差显式暴露。"""
    from core import agent
    from core.agent import AgentUnavailable
    p = request.get_json(force=True) or {}
    try:
        return J(agent.variance_bridge(p))
    except AgentUnavailable as ex:
        return J({"error": "agent_unavailable", "message": str(ex)}, 503)


@app.get("/export/list")
def export_list():
    """列出最近的受控导出（只读审计日志里的 export.create 记录）。"""
    e = entity_or_404()
    limit = min(200, max(1, int(request.args.get("limit") or 50)))
    rows = query("""SELECT object_id AS kind, actor, created_at, detail
                      FROM audit_log
                     WHERE entity_id=%s AND action='export.create'
                     ORDER BY seq_no DESC LIMIT %s""", (e["entity_id"], limit))
    out = []
    for r in rows:
        detail = r.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except Exception:
                detail = {}
        detail = detail or {}
        name = str(detail.get("path") or "")
        out.append({"file": name, "kind": r.get("kind"),
                    "purpose": detail.get("purpose"), "recipient": detail.get("recipient"),
                    "rows": detail.get("rows"), "sha256": detail.get("sha256") or "",
                    "actor": r.get("actor"),
                    "created_at": r["created_at"].isoformat(sep=" ", timespec="minutes")
                    if r.get("created_at") else None,
                    "exists": bool(name) and (STORAGE_DIR / name).is_file()})
    return J({"exports": out})


@app.get("/reports/unreconciled-entries")
def unreconciled_entries():
    """已过账但还没对账的分录（核销工作台底部那张表）。字段用驼峰，前端直接取。"""
    e = entity_or_404()
    limit = min(500, max(1, int(request.args.get("limit") or 100)))
    offset = max(0, int(request.args.get("offset") or 0))
    total = int(query_one("""SELECT COUNT(*) n FROM journal_entries
                               WHERE entity_id=%s AND status='posted' AND reconciled_at IS NULL""",
                          (e["entity_id"],))["n"])
    rows = query("""SELECT entry_id, entry_no, entry_date, source_type, description,
                           total_debit, total_credit, period
                      FROM journal_entries
                     WHERE entity_id=%s AND status='posted' AND reconciled_at IS NULL
                     ORDER BY entry_date DESC, entry_id DESC LIMIT %s OFFSET %s""",
                 (e["entity_id"], limit, offset))
    return J({"entries": [{
        "entryId": r["entry_id"], "entryNo": r["entry_no"],
        "entryDate": r["entry_date"].isoformat(), "sourceType": r["source_type"],
        "description": r["description"], "period": r["period"],
        "totalDebit": float(dec(r["total_debit"])),
        "totalCredit": float(dec(r["total_credit"])),
    } for r in rows], "total": total, "limit": limit, "offset": offset})


@app.post("/reports/confirm-reconciliation")
def confirm_reconciliation():
    """确认对账：只打标记，不改金额、不生成分录。

    接受三种写法（前端按行类型给）：`entry:<id>`、`invoice:<id>`、`bill:<id>`，
    也接受纯数字（当作分录 ID）。
    """
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    raw = p.get("ids") or []
    entry_ids, invoice_ids, bill_ids = [], [], []
    for item in raw:
        s_ = str(item).strip()
        if s_.isdigit():
            entry_ids.append(int(s_))
        elif ":" in s_:
            kind, _, val = s_.partition(":")
            if not val.isdigit():
                continue
            if kind == "entry":
                entry_ids.append(int(val))
            elif kind == "invoice":
                invoice_ids.append(int(val))
            elif kind == "bill":
                bill_ids.append(int(val))
    if not (entry_ids or invoice_ids or bill_ids):
        raise ValueError("没有可确认的分录")
    actor = str(p.get("actor") or "system")

    def _mark(cur, where, args):
        cur.execute(f"""UPDATE journal_entries SET reconciled_at=NOW(3), reconciled_by=%s
                         WHERE entity_id=%s AND status='posted' AND reconciled_at IS NULL
                           AND {where}""", tuple([actor, e["entity_id"]] + list(args)))
        return cur.rowcount

    n = 0
    with transaction() as conn:
        with conn.cursor() as cur:
            if entry_ids:
                ph = ",".join(["%s"] * len(entry_ids))
                n += _mark(cur, f"entry_id IN ({ph})", entry_ids)
            if invoice_ids:
                ph = ",".join(["%s"] * len(invoice_ids))
                n += _mark(cur, f"source_type='invoice' AND source_id IN ({ph})", invoice_ids)
            if bill_ids:
                ph = ",".join(["%s"] * len(bill_ids))
                n += _mark(cur, f"source_type='bill' AND source_id IN ({ph})", bill_ids)
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "reconciliation.confirm",
                            "object_type": "journal_entries",
                            "object_id": ",".join(str(i) for i in (entry_ids + invoice_ids + bill_ids)[:20]),
                            "detail": {"count": n, "entries": entry_ids[:50],
                                       "invoices": invoice_ids[:50], "bills": bill_ids[:50]}})
    return J({"confirmed": n})


@app.post("/export")
def do_export():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    kind = p.get("kind", "invoices")
    purpose = str(p.get("purpose") or "").strip()
    recipient = str(p.get("recipient") or "").strip()
    if not purpose:
        raise ValueError("导出必须填写目的")
    if not recipient:
        raise ValueError("导出必须填写接收方")

    tables = {
        "invoices": "SELECT invoice_no,supplier_name,invoice_date,currency,amount_original,tax_original,gross_original,status FROM invoices WHERE entity_id=%s LIMIT 100000",
        "bills": "SELECT bill_no,vendor_name,date,currency,amount,tax_amount,gross_original,status FROM bills WHERE entity_id=%s LIMIT 100000",
        "journal": "SELECT entry_no,entry_date,source_type,status,total_debit,total_credit FROM journal_entries WHERE entity_id=%s LIMIT 100000",
        "bank_lines": "SELECT bank_ref,txn_date,amount_original,currency,amount_functional,match_status FROM bank_lines WHERE entity_id=%s LIMIT 100000",
        "audit_log": "SELECT seq_no,actor,action,object_type,object_id,created_at FROM audit_log WHERE entity_id=%s LIMIT 100000",
    }
    if kind not in tables:
        raise ValueError(f"不支持的导出类型：{kind}")

    rows = query(tables[kind], (e["entity_id"],))
    if len(rows) == 100000:
        # 刚好触顶，可能被截断 —— 用白名单表名确认
        _kind_to_table = {
            "invoices": "invoices", "bills": "bills", "journal": "journal_entries",
            "bank_lines": "bank_lines", "audit_log": "audit_log",
        }
        safe_tbl = _kind_to_table.get(kind)
        if safe_tbl:
            total_rows = query_one(f"SELECT COUNT(*) AS c FROM {safe_tbl} WHERE entity_id=%s",
                                   (e["entity_id"],))
            if total_rows and total_rows["c"] > 100000:
                raise ValueError(f"导出数据超过单批上限 100000 行（当前 {total_rows['c']} 行），请按期间或条件分批导出")
    headers = list(rows[0].keys()) if rows else []
    _lang = str(p.get("lang") or "zh_cn")
    if _lang not in ("zh_cn", "zh_hk", "en"):
        _lang = "zh_cn"
    _li = {"zh_cn": 0, "zh_hk": 1, "en": 2}[_lang]
    # CSV 也是正式输出文件：表头与业务状态跟随导出语言；审计动作代码保留原值以便追溯。
    _headers = {
        "invoice_no": ("发票编号", "發票編號", "Invoice No."),
        "supplier_name": ("客户名称", "客戶名稱", "Customer"),
        "invoice_date": ("发票日期", "發票日期", "Invoice Date"),
        "bill_no": ("账单编号", "賬單編號", "Bill No."),
        "vendor_name": ("供应商名称", "供應商名稱", "Vendor"),
        "date": ("日期", "日期", "Date"),
        "currency": ("币种", "幣種", "Currency"),
        "amount_original": ("不含税金额（原币）", "不含稅金額（原幣）", "Net Amount (Original Currency)"),
        "tax_original": ("税额（原币）", "稅額（原幣）", "Tax (Original Currency)"),
        "gross_original": ("价税合计（原币）", "價稅合計（原幣）", "Total (Original Currency)"),
        "amount": ("不含税金额", "不含稅金額", "Net Amount"),
        "tax_amount": ("税额", "稅額", "Tax"),
        "status": ("状态", "狀態", "Status"),
        "entry_no": ("分录号", "分錄號", "Entry No."),
        "entry_date": ("分录日期", "分錄日期", "Entry Date"),
        "source_type": ("来源", "來源", "Source"),
        "total_debit": ("借方合计", "借方合計", "Total Debit"),
        "total_credit": ("贷方合计", "貸方合計", "Total Credit"),
        "bank_ref": ("银行流水号", "銀行流水號", "Bank Reference"),
        "txn_date": ("交易日期", "交易日期", "Transaction Date"),
        "amount_functional": ("折合功能货币", "折合功能貨幣", "Amount in Functional Currency"),
        "match_status": ("匹配状态", "匹配狀態", "Match Status"),
        "seq_no": ("序号", "序號", "Sequence No."),
        "actor": ("操作人", "操作人", "Actor"),
        "action": ("操作代码", "操作代碼", "Action Code"),
        "object_type": ("对象类型代码", "對象類型代碼", "Object Type Code"),
        "object_id": ("对象编号", "對象編號", "Object ID"),
        "created_at": ("创建时间", "創建時間", "Created At"),
    }
    _values = {
        "status": {
            "posted": ("已过账", "已過賬", "Posted"),
            "draft": ("草稿", "草稿", "Draft"),
            "void": ("已作废", "已作廢", "Void"),
            "reversed": ("已冲销", "已沖銷", "Reversed"),
        },
        "source_type": {
            "invoice": ("发票", "發票", "Invoice"),
            "bill": ("账单", "賬單", "Bill"),
            "manual": ("手工录入", "手工錄入", "Manual entry"),
            "opening": ("期初", "期初", "Opening"),
            "payment_received": ("收款", "收款", "Receipt"),
            "payment_made": ("付款", "付款", "Payment"),
            "expense": ("费用", "費用", "Expense"),
            "transfer": ("转账", "轉賬", "Transfer"),
            "credit_note": ("贷记单", "貸記單", "Credit note"),
        },
        "match_status": {
            "matched": ("已匹配", "已匹配", "Matched"),
            "unmatched": ("未匹配", "未匹配", "Unmatched"),
            "confirmed": ("已确认", "已確認", "Confirmed"),
            "pending": ("待处理", "待處理", "Pending"),
        },
    }
    buf = io.StringIO()
    buf.write({"zh_cn": "# 草稿 — 受控导出，供复核；非正式对外报表\n",
               "zh_hk": "# 草稿 — 受控匯出，供覆核；非正式對外報表\n",
               "en":    "# DRAFT — controlled export for review; not a formal external statement\n"}[_lang])
    _meta_label = {"zh_cn": ("用途", "接收方"), "zh_hk": ("用途", "接收方"),
                   "en": ("Purpose", "Recipient")}[_lang]
    buf.write(f"# {_meta_label[0]}: {purpose}\n# {_meta_label[1]}: {recipient}\n")
    buf.write(",".join(_headers.get(h, (h, h, h))[_li] for h in headers) + "\n")
    MONEY_HINTS = ("amount", "total", "balance", "debit", "credit", "gross",
                   "tax", "price", "rate")
    for r in rows:
        vals = []
        for h in headers:
            v = r[h]
            if v is None:
                vals.append("")
            elif h in _values and str(v) in _values[h]:
                vals.append('"' + _values[h][str(v)][_li] + '"')
            elif isinstance(v, date):
                vals.append(v.isoformat())
            elif isinstance(v, (int, float)) and any(k in h.lower() for k in MONEY_HINTS):
                # 金额与税率一律两位小数，导出后可直接用于核对
                vals.append(f'"{float(v):.2f}"')
            else:
                vals.append('"' + str(v).replace('"', '""') + '"')
        buf.write(",".join(vals) + "\n")

    text = buf.getvalue()
    sha = hashlib.sha256(text.encode()).hexdigest()
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    name = f"export-{kind}-{int(date.today().strftime('%Y%m%d'))}-{uuid.uuid4().hex[:8]}.csv"
    (STORAGE_DIR / name).write_text(text, encoding="utf-8")

    with transaction() as conn:
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "auditor"),
                            "actor_role": "auditor", "action": "export.create",
                            "object_type": "export", "object_id": kind,
                            "detail": {"kind": kind, "purpose": purpose, "recipient": recipient,
                                       "rows": len(rows), "sha256": sha, "path": name,
                                       "watermark": "DRAFT"}})

    return J({"ok": True, "kind": kind, "rows": len(rows), "file": name,
              "sha256": sha, "watermark": "DRAFT", "purpose": purpose, "recipient": recipient,
              "note": "导出已记录到审计日志；文件附带 SHA-256，接收方可独立校验完整性"})


@app.delete("/export/file/<name>")
def export_delete(name):
    """删除导出文件。

    只删磁盘上的文件，审计日志里的 export.create 记录保留 ——
    导出行为本身是审计事实，不能抹掉；文件可以被清理。
    """
    require_writer()
    e = entity_or_404()
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")
    if not safe or safe != name:
        raise ValueError("文件名不合法")
    path = STORAGE_DIR / safe
    if not path.is_file():
        raise ValueError("文件不存在或已被清理")
    try:
        size = path.stat().st_size
        path.unlink()
    except OSError as ex:
        raise ValueError(f"删除失败：{ex}")
    with transaction() as conn:
        append_audit(conn, {"entity_id": e["entity_id"], "actor": "system",
                            "action": "export.delete", "object_type": "export",
                            "object_id": safe, "detail": {"file": safe, "bytes": size}})
    return J({"deleted": safe, "bytes": size})


@app.get("/export/download/<name>")
def export_download(name):
    safe = "".join(c for c in name if c.isalnum() or c in "-_.")
    path = STORAGE_DIR / safe
    if not path.exists():
        raise ValueError("文件不存在")
    return send_file(path, as_attachment=True, download_name=safe, mimetype="text/csv")



# ------------------------------------------------------------------ 主数据
@app.get("/customers")
def customers_list():
    e = entity_or_404()
    limit, offset = page_args(default_limit=0)
    args = [e["entity_id"]]
    where = "entity_id=%s" + search_clause(
        request.args.get("q"),
        ["customer_code", "customer_name", "email", "contact_name", "phone", "mobile"], args)
    total = int(query_one(f"SELECT COUNT(*) n FROM customers WHERE {where}", tuple(args))["n"])
    rows = query(f"""SELECT customer_id, customer_code, customer_name, customer_type, default_currency,
                           payment_terms_days, is_related_party, email, status, contact_name, contact_title, phone, mobile, fax, address, district, country, website, tax_id, notes
                      FROM customers WHERE {where} ORDER BY customer_id LIMIT %s OFFSET %s""",
                 tuple(args + [limit, offset]))
    return J({"customers": rows, "total": total, "limit": limit, "offset": offset})


@app.post("/customers")
def customers_save():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    with transaction() as conn:
        with conn.cursor() as cur:
            if p.get("customerId"):
                cur.execute("""UPDATE customers SET customer_code=%s, customer_name=%s,
                               customer_type=%s,
                               default_currency=%s, payment_terms_days=%s,
                               is_related_party=%s, email=%s, status=%s,
                               contact_name=%s,
                               contact_title=%s,
                               phone=%s,
                               mobile=%s,
                               fax=%s,
                               address=%s,
                               district=%s,
                               country=%s,
                               website=%s,
                               tax_id=%s,
                               notes=%s
                               WHERE customer_id=%s AND entity_id=%s""",
                            (p.get("customerCode"), p.get("customerName"),
                             _customer_type(p.get("customerType")),
                             p.get("defaultCurrency", "HKD"), int(p.get("paymentTermsDays", 30)),
                             1 if p.get("isRelatedParty") else 0, p.get("email"),
                             p.get("status", "active"),
                             p.get("contactName"), p.get("contactTitle"), p.get("phone"), p.get("mobile"), p.get("fax"), p.get("address"), p.get("district"), p.get("country"), p.get("website"), p.get("taxId"), p.get("notes"), int(p["customerId"]), e["entity_id"]))
                cid = int(p["customerId"])
            else:
                ccode = (p.get("customerCode") or "").strip() \
                    or _next_party_code(conn, "customers", "customer_code", "C", e["entity_id"])
                cname = (p.get("customerName") or p.get("name") or "").strip()
                if not cname:
                    raise ValueError("客户名称不能为空")
                cur.execute("""INSERT INTO customers
                    (entity_id, customer_code, customer_name, customer_type, default_currency,
                     payment_terms_days, is_related_party, email, status,
                     contact_name,
                     contact_title,
                     phone,
                     mobile,
                     fax,
                     address,
                     district,
                     country,
                     website,
                     tax_id,
                     notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (e["entity_id"], ccode, cname, _customer_type(p.get("customerType")),
                             p.get("defaultCurrency", "HKD"), int(p.get("paymentTermsDays", 30)),
                             1 if p.get("isRelatedParty") else 0, p.get("email"),
                             p.get("status", "active"),
                             p.get("contactName"), p.get("contactTitle"), p.get("phone"), p.get("mobile"), p.get("fax"), p.get("address"), p.get("district"), p.get("country"), p.get("website"), p.get("taxId"), p.get("notes")))
                cid = cur.lastrowid
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": "customer.save", "object_type": "customers",
                                "object_id": str(cid),
                                "detail": {"name": p.get("customerName"), "code": p.get("customerCode"),
                                           "type": _customer_type(p.get("customerType"))}})
    return J({"customerId": cid})


@app.get("/vendors")
def vendors_list():
    e = entity_or_404()
    limit, offset = page_args(default_limit=0)
    args = [e["entity_id"]]
    where = "entity_id=%s" + search_clause(
        request.args.get("q"),
        ["vendor_code", "vendor_name", "email", "contact_name", "phone", "mobile"], args)
    total = int(query_one(f"SELECT COUNT(*) n FROM vendors WHERE {where}", tuple(args))["n"])
    rows = query(f"""SELECT vendor_id, vendor_code, vendor_name, default_currency,
                           payment_terms_days, is_related_party, email, status, contact_name, contact_title, phone, mobile, fax, address, district, country, website, tax_id, notes
                      FROM vendors WHERE {where} ORDER BY vendor_id LIMIT %s OFFSET %s""",
                 tuple(args + [limit, offset]))
    return J({"vendors": rows, "total": total, "limit": limit, "offset": offset})


@app.get("/customers/<int:customer_id>")
def customer_detail(customer_id):
    e = entity_or_404()
    r = query_one("SELECT * FROM customers WHERE customer_id=%s AND entity_id=%s",
                  (customer_id, e["entity_id"]))
    if not r:
        raise ValueError("客户不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    d["documents"] = [dict(x) for x in query(
        """SELECT invoice_id AS id, invoice_no AS no, invoice_date AS date, currency,
                  gross_original, settled_original, status
             FROM invoices WHERE entity_id=%s AND supplier_name=%s
            ORDER BY invoice_date DESC LIMIT 20""", (e["entity_id"], r["customer_name"]))]
    for x in d["documents"]:
        x["date"] = x["date"].isoformat()
        x["gross_original"] = float(dec(x["gross_original"]))
        x["settled_original"] = float(dec(x["settled_original"]))
        x["outstanding"] = round(x["gross_original"] - x["settled_original"], 2)
    d["outstanding"] = round(sum(x["outstanding"] for x in d["documents"]), 2)
    return J(d)


@app.get("/vendors/<int:vendor_id>")
def vendor_detail(vendor_id):
    e = entity_or_404()
    r = query_one("SELECT * FROM vendors WHERE vendor_id=%s AND entity_id=%s",
                  (vendor_id, e["entity_id"]))
    if not r:
        raise ValueError("供应商不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    d["documents"] = [dict(x) for x in query(
        """SELECT bill_id AS id, bill_no AS no, date, currency, gross_original,
                  settled_original, status
             FROM bills WHERE entity_id=%s AND vendor_name=%s
            ORDER BY date DESC LIMIT 20""", (e["entity_id"], r["vendor_name"]))]
    for x in d["documents"]:
        x["date"] = x["date"].isoformat()
        x["gross_original"] = float(dec(x["gross_original"]))
        x["settled_original"] = float(dec(x["settled_original"]))
        x["outstanding"] = round(x["gross_original"] - x["settled_original"], 2)
    d["outstanding"] = round(sum(x["outstanding"] for x in d["documents"]), 2)
    return J(d)


@app.post("/vendors")
def vendors_save():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    with transaction() as conn:
        with conn.cursor() as cur:
            if p.get("vendorId"):
                cur.execute("""UPDATE vendors SET vendor_code=%s, vendor_name=%s,
                               default_currency=%s, payment_terms_days=%s,
                               is_related_party=%s, email=%s, status=%s,
                               contact_name=%s,
                               contact_title=%s,
                               phone=%s,
                               mobile=%s,
                               fax=%s,
                               address=%s,
                               district=%s,
                               country=%s,
                               website=%s,
                               tax_id=%s,
                               notes=%s
                               WHERE vendor_id=%s AND entity_id=%s""",
                            (p.get("vendorCode"), p.get("vendorName"),
                             p.get("defaultCurrency", "HKD"), int(p.get("paymentTermsDays", 30)),
                             1 if p.get("isRelatedParty") else 0, p.get("email"),
                             p.get("status", "active"),
                             p.get("contactName"), p.get("contactTitle"), p.get("phone"), p.get("mobile"), p.get("fax"), p.get("address"), p.get("district"), p.get("country"), p.get("website"), p.get("taxId"), p.get("notes"), int(p["vendorId"]), e["entity_id"]))
                vid = int(p["vendorId"])
            else:
                code = (p.get("vendorCode") or "").strip() \
                    or _next_party_code(conn, "vendors", "vendor_code", "V", e["entity_id"])
                name = (p.get("vendorName") or p.get("name") or "").strip()
                if not name:
                    raise ValueError("供应商名称不能为空")
                cur.execute("""INSERT INTO vendors
                    (entity_id, vendor_code, vendor_name, default_currency,
                     payment_terms_days, is_related_party, email, status,
                     contact_name,
                     contact_title,
                     phone,
                     mobile,
                     fax,
                     address,
                     district,
                     country,
                     website,
                     tax_id,
                     notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (e["entity_id"], code, name,
                             p.get("defaultCurrency", "HKD"), int(p.get("paymentTermsDays", 30)),
                             1 if p.get("isRelatedParty") else 0, p.get("email"),
                             p.get("status", "active"),
                             p.get("contactName"), p.get("contactTitle"), p.get("phone"), p.get("mobile"), p.get("fax"), p.get("address"), p.get("district"), p.get("country"), p.get("website"), p.get("taxId"), p.get("notes")))
                vid = cur.lastrowid
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": "vendor.save", "object_type": "vendors",
                                "object_id": str(vid),
                                "detail": {"name": p.get("vendorName"), "code": p.get("vendorCode")}})
    return J({"vendorId": vid})


# ------------------------------------------------------------------ 汇率维护
def _customer_type(value) -> str:
    """客户类型只有公司与个人两种，缺省与非法值一律按公司处理。"""
    return "individual" if str(value or "").strip().lower() == "individual" else "company"


def _next_party_code(conn, table: str, col: str, prefix: str, eid: int) -> str:
    """生成下一个编码（C-0001 / V-0001）。不靠自增，按现有最大值 +1。"""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {col} FROM {table} WHERE entity_id=%s AND {col} LIKE %s "
                    f"ORDER BY {col} DESC LIMIT 1", (eid, prefix + '-%'))
        row = cur.fetchone()
    if not row or not row[col]:
        return f"{prefix}-0001"
    try:
        n = int(str(row[col]).split('-')[-1]) + 1
    except ValueError:
        n = 1
    return f"{prefix}-{n:04d}"


@app.get("/fx/rates/list")
def rates_list():
    limit = int(request.args.get("limit", 200))
    offset = max(0, int(request.args.get("offset", 0)))
    if limit <= 0:
        limit = 2000
    limit = min(limit, 2000)
    total = int(query_one("SELECT COUNT(*) n FROM fx_rates")["n"])
    rows = query("""SELECT rate_date, from_ccy, to_ccy, rate, source, is_fallback, fetched_at
                      FROM fx_rates ORDER BY rate_date DESC, from_ccy, to_ccy
                      LIMIT %s OFFSET %s""", (limit, offset))
    return J({"rates": [dict(r, rate=float(dec(r["rate"])),
                             rate_date=r["rate_date"].isoformat(),
                             is_fallback=bool(r["is_fallback"]),
                             fetched_at=(r["fetched_at"].isoformat(sep=" ", timespec="minutes")
                                         if r.get("fetched_at") else None)) for r in rows],
              "total": total, "limit": limit, "offset": offset})


@app.post("/fx/refresh")
def fx_refresh():
    """手动立即抓取一次 ECB 汇率（与每天 09:00 定时任务同一逻辑）。"""
    require_writer()
    p = request.get_json(force=True) or {}
    from fetch_rates import refresh
    try:
        out = refresh(actor=str(p.get("actor") or "manual"))
    except RuntimeError as ex:
        return J({"error": "fetch_error", "message": str(ex)}, 502)
    return J({"ok": True, **out})


@app.post("/fx/rates")
def rate_add():
    require_writer()
    p = request.get_json(force=True) or {}
    frm = str(p.get("fromCcy", "")).upper()
    to = str(p.get("toCcy", "")).upper()
    rate = dec(p.get("rate"))
    d = p.get("rateDate")
    if not frm or not to or frm == to:
        raise ValueError("币种不合法：来源与目标必须不同")
    if not (re.fullmatch(r"[A-Z]{3}", frm) and re.fullmatch(r"[A-Z]{3}", to)):
        raise ValueError("币种代码必须是 3 位英文字母，例如 USD")
    if rate is None or rate <= 0:
        raise ValueError("汇率必须是大于 0 的数值")
    # 汇率按两位小数保存（7.80 / 1.09 这种）。
    # 但反向汇率本身就是零点零几（HKD→KRW 0.0058、HKD→JPY 0.052），
    # 两位小数会把它压成 0.01 / 0.05，误差五成以上，金额直接算错。
    # 所以小于 1 的汇率保留四位，够用又不失真。
    rate = rate.quantize(dec("0.01" if rate >= 1 else "0.0001"))
    if not d:
        raise ValueError("必须提供汇率日期")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO fx_rates (rate_date, from_ccy, to_ccy, rate, source, is_fallback)
                           VALUES (%s,%s,%s,%s,%s,0)
                           ON DUPLICATE KEY UPDATE rate=VALUES(rate), source=VALUES(source),
                                                   is_fallback=0, fetched_at=NOW(3)""",
                        (d, frm, to, rate, p.get("source", "MANUAL")))
            append_audit(conn, {"entity_id": entity_or_404()["entity_id"],
                                "actor": p.get("actor", "system"),
                                "action": "fx_rate.upsert", "object_type": "fx_rates",
                                "object_id": f"{d}:{frm}:{to}",
                                "detail": {"rate": float(rate), "pair": f"{frm}->{to}", "date": d}})
    return J({"ok": True, "pair": f"{frm}->{to}", "rate": float(rate), "rateDate": d})


# ------------------------------------------------------------------ 期间锁定
@app.get("/period-locks")
def locks_list():
    e = entity_or_404()
    rows = query("""SELECT period, status, locked_by, locked_at, note
                      FROM period_locks WHERE entity_id=%s ORDER BY period DESC""", (e["entity_id"],))
    return J({"locks": [dict(r, locked_at=r["locked_at"].isoformat(sep=" ", timespec="milliseconds") if r["locked_at"] else None)
                        for r in rows]})


@app.post("/period-locks")
def locks_set():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    period = str(p.get("period", ""))
    status = str(p.get("status", "locked"))
    if status not in ("open", "locked", "closed"):
        raise ValueError("状态只能是 open / locked / closed")
    if len(period) != 7:
        raise ValueError("期间格式应为 YYYY-MM")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO period_locks (entity_id, period, status, locked_by, locked_at, note)
                           VALUES (%s,%s,%s,%s,NOW(3),%s)
                           ON DUPLICATE KEY UPDATE status=VALUES(status), locked_by=VALUES(locked_by),
                                                   locked_at=NOW(3), note=VALUES(note)""",
                        (e["entity_id"], period, status, p.get("actor", "system"), p.get("note")))
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": "period_lock.set", "object_type": "period_locks",
                                "object_id": period,
                                "detail": {"status": status, "note": p.get("note")}})
    return J({"period": period, "status": status})


# ------------------------------------------------------------------ 附件
@app.get("/invoices/<int:invoice_id>")
def invoice_one(invoice_id):
    """单张销售发票的完整信息（详情弹窗用）。"""
    e = entity_or_404()
    r = query_one("SELECT * FROM invoices WHERE invoice_id=%s AND entity_id=%s",
                  (invoice_id, e["entity_id"]))
    if not r:
        raise ValueError("发票不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    for k in ("amount_original", "tax_original", "gross_original", "amount_functional",
              "tax_functional", "settled_original", "fx_rate", "tax_rate_implied"):
        if d.get(k) is not None:
            d[k] = float(dec(d[k]))
    d["functional_currency"] = e["functional_currency"]
    lines = query("""SELECT line_no, item_code, description, unit, quantity, unit_price,
                            amount, tax_rate, tax_amount, notes
                       FROM invoice_lines WHERE invoice_id=%s ORDER BY line_no""", (invoice_id,))
    d["lines"] = [{**dict(x),
                   "quantity": float(dec(x["quantity"])),
                   "unit_price": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "tax_rate": float(dec(x["tax_rate"])) if x["tax_rate"] is not None else None,
                   "tax_amount": float(dec(x["tax_amount"]))} for x in lines]
    return J(d)


@app.get("/bills/<int:bill_id>")
def bill_one(bill_id):
    """单张采购发票的完整信息（详情弹窗用）。"""
    e = entity_or_404()
    r = query_one("SELECT * FROM bills WHERE bill_id=%s AND entity_id=%s",
                  (bill_id, e["entity_id"]))
    if not r:
        raise ValueError("账单不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    for k in ("amount", "tax_amount", "gross_original", "amount_functional",
              "settled_original", "fx_rate"):
        if d.get(k) is not None:
            d[k] = float(dec(d[k]))
    d["functional_currency"] = e["functional_currency"]
    lines = query("""SELECT line_no, item_code, description, unit, quantity, unit_price,
                            amount, tax_rate, tax_amount, notes
                       FROM bill_lines WHERE bill_id=%s ORDER BY line_no""", (bill_id,))
    d["lines"] = [{**dict(x),
                   "quantity": float(dec(x["quantity"])),
                   "unit_price": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "tax_rate": float(dec(x["tax_rate"])) if x["tax_rate"] is not None else None,
                   "tax_amount": float(dec(x["tax_amount"]))} for x in lines]
    return J(d)


@app.get("/invoices/<int:invoice_id>/files")
def invoice_files(invoice_id):
    rows = query("""SELECT file_id, file_name, file_type, file_size, sha256_hash,
                           uploaded_by, created_at AS uploaded_at, NULL AS retention_until
                      FROM doc_files WHERE doc_type='invoice' AND doc_id=%s ORDER BY file_id""", (invoice_id,))
    return J({"files": [dict(r, uploaded_at=r["uploaded_at"].isoformat(sep=" ", timespec="milliseconds"),
                             retention_until=None)
                        for r in rows]})


@app.post("/invoice-files")
def invoice_file_register():
    """登记发票附件。统一落到 doc_files（doc_type=invoice）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    inv_id = int(p.get("invoiceId") or 0)
    name = str(p.get("fileName") or "").strip()
    path = str(p.get("storagePath") or "").strip()
    sha = str(p.get("sha256") or "").strip().lower()
    size = int(p.get("fileSize") or 0)
    if not inv_id or not name or not path:
        raise ValueError("缺少发票 ID / 文件名 / 存储路径")
    if len(sha) != 64:
        raise ValueError("SHA-256 必须是 64 位十六进制")
    if size <= 0:
        raise ValueError("文件大小必须大于 0")
    if not query_one("SELECT 1 AS x FROM invoices WHERE invoice_id=%s AND entity_id=%s",
                     (inv_id, e["entity_id"])):
        raise ValueError("发票不存在")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                VALUES (%s,'invoice',%s,%s,%s,%s,%s,%s,%s)""",
                        (e["entity_id"], inv_id, name[:255],
                         str(p.get("fileType") or "other")[:64], size, sha,
                         path[:500], p.get("actor", "system")))
            fid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "invoice_file.upload", "object_type": "doc_files",
                            "object_id": str(fid),
                            "detail": {"invoiceId": inv_id, "fileName": name,
                                       "fileSize": size, "sha256": sha}})
    return J({"fileId": fid, "sha256": sha, "fileSize": size})



# ------------------------------------------------------------------ 银行流水导入

def recalc_bank_balance(conn, account_id: int) -> float:
    """重算银行账户余额，只有一个口径，避免重复计算。

    有对账单流水时：余额 = 期初 + 流水合计（流水才是银行的真实账）。
    没有流水时：余额 = 期初 + 收付款净额（纯手工记账的账户）。
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) n, COALESCE(SUM(amount_original),0) s FROM bank_lines "
                    "WHERE bank_account_id=%s", (account_id,))
        row = cur.fetchone()
        if int(row["n"]) > 0:
            net = dec(row["s"])
            cur.execute("SELECT COALESCE(SUM(amount_functional),0) s FROM bank_lines "
                        "WHERE bank_account_id=%s", (account_id,))
            net_func = dec(cur.fetchone()["s"])
        else:
            cur.execute("SELECT COALESCE(SUM(amount),0) s FROM payments_received "
                        "WHERE bank_account_id=%s", (account_id,))
            net = dec(cur.fetchone()["s"])
            cur.execute("SELECT COALESCE(SUM(amount),0) s FROM payments_made "
                        "WHERE bank_account_id=%s", (account_id,))
            net -= dec(cur.fetchone()["s"])
            net_func = net
        cur.execute("""UPDATE bank_accounts
                          SET current_balance = opening_balance + %s,
                              current_balance_functional = opening_balance_functional + %s
                        WHERE account_id=%s""", (float(net), float(net_func), account_id))
        cur.execute("SELECT current_balance FROM bank_accounts WHERE account_id=%s", (account_id,))
        return float(dec(cur.fetchone()["current_balance"]))


def bank_import_core(p: dict) -> dict:
    """导入对账单：先做算术校验，通过才落库；同一文件（SHA-256）不重复导入。"""
    e = entity_or_404()
    acct_id = int(p.get("bankAccountId") or 0)
    acct = query_one("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                     (acct_id, e["entity_id"]))
    if not acct:
        raise ValueError("银行账户不存在")

    header = p.get("header") or {}
    lines = p.get("lines") or []
    if not isinstance(lines, list) or not lines:
        raise ValueError("对账单没有明细行")

    chk = bankrec.validate_statement({
        "currency": acct["currency"],
        "openingBalance": header.get("openingBalance"),
        "closingBalance": header.get("closingBalance"),
        "totalDebits": header.get("totalDebits"),
        "totalCredits": header.get("totalCredits"),
        "lines": [{"amount": l.get("amount")} for l in lines],
    })
    if not chk["ok"]:
        raise ValueError("算术校验未通过，整批拒收，未写入任何流水：" + str(chk["message"]))

    sha = str(p.get("sha256") or "")
    if len(sha) != 64:
        import hashlib as _h
        raw = "\n".join(f"{l.get('date')}|{l.get('amount')}|{l.get('ref')}|{l.get('counterparty')}"
                         for l in lines)
        sha = _h.sha256(raw.encode()).hexdigest()

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT batch_id FROM statement_imports
                            WHERE bank_account_id=%s AND sha256_hash=%s""", (acct_id, sha))
            dup = cur.fetchone()
            if dup:
                return {"ok": False, "duplicate": True, "batchId": dup["batch_id"],
                        "inserted": 0, "skipped": len(lines), "lineCount": len(lines),
                        "note": "该对账单已导入过（SHA-256 相同），未重复入账"}

            cur.execute("""INSERT INTO statement_imports
                (entity_id, bank_account_id, account_currency, file_name, file_format, sha256_hash,
                 period_start, period_end, opening_balance, closing_balance,
                 total_debits, total_credits, arithmetic_ok, arithmetic_diff, line_count,
                 status, imported_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,'imported',%s)""",
                        (e["entity_id"], acct_id, acct["currency"],
                         str(p.get("fileName") or "statement.csv")[:255],
                         p.get("fileFormat") or "csv", sha,
                         header.get("periodStart"), header.get("periodEnd"),
                         header.get("openingBalance"), header.get("closingBalance"),
                         header.get("totalDebits"), header.get("totalCredits"),
                         chk["difference"], len(lines), p.get("actor", "system")))
            batch_id = cur.lastrowid

            inserted = 0
            skipped = 0
            for ln in lines:
                amt = dec(ln.get("amount"))
                d = ln.get("date")
                ref = str(ln.get("ref") or "")[:128]
                counterparty = str(ln.get("counterparty") or "")[:200]
                cur.execute("""SELECT line_id FROM bank_lines
                                WHERE bank_account_id=%s AND bank_ref<=>%s
                                  AND amount_original=%s AND txn_date=%s""",
                            (acct_id, ref, amt, d))
                if cur.fetchone():
                    skipped += 1
                    continue
                fx = dec(1)
                func = amt
                if acct["currency"] != e["functional_currency"]:
                    from core.fx import lookup_rate
                    from core.service import load_rules
                    rates = [dict(r) for r in query(
                        """SELECT rate_date, from_ccy, to_ccy, rate FROM fx_rates
                            WHERE from_ccy=%s AND to_ccy=%s AND rate_date>=DATE_SUB(%s, INTERVAL 10 DAY)
                              AND rate_date<=%s ORDER BY rate_date DESC""",
                        (acct["currency"], e["functional_currency"], d, d))]
                    look = lookup_rate(rates, d, acct["currency"], e["functional_currency"],
                                       __import__("core.fx", fromlist=["normalize_policy"]).normalize_policy(load_rules()["fx_policy"]))
                    if look["ok"]:
                        fx = dec(look["rate"])
                        func = convert(amt, fx)
                    else:
                        func = None
                cur.execute("""INSERT INTO bank_lines
                    (entity_id, bank_account_id, bank_ref, txn_date, amount_original, currency,
                     counterparty_name, amount_functional, fx_rate, fx_rate_date,
                     source_file_path, statement_import_batch_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (e["entity_id"], acct_id, ref, d, amt, acct["currency"],
                             counterparty, func if func is not None else 0, fx, d,
                             str(p.get("fileName") or "statement.csv")[:500], batch_id))
                inserted += 1

            # 账户余额要跟着对账单走，否则「银行余额」永远是导入前的数。
            # 最早那份对账单的期初作为账户期初；当前余额 = 期初 + 全部流水。
            cur.execute(
                "SELECT DATE(period_start) d FROM statement_imports "
                "WHERE bank_account_id=%s ORDER BY period_start ASC, batch_id ASC LIMIT 1",
                (acct_id,))
            earliest = cur.fetchone()
            is_first = (bool(earliest)
                        and str(earliest["d"]) == str(header.get("periodStart") or ""))
            if is_first and header.get("openingBalance") is not None:
                cur.execute(
                    "UPDATE bank_accounts SET opening_balance=%s, opening_balance_functional=%s "
                    "WHERE account_id=%s",
                    (float(header["openingBalance"]), float(header["openingBalance"]), acct_id))
            new_balance = recalc_bank_balance(conn, acct_id)

            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": "bank.import", "object_type": "statement_imports",
                                "object_id": str(batch_id),
                                "detail": {"accountId": acct_id, "lines": inserted,
                                           "skipped": skipped, "sha256": sha,
                                           "balanceAfter": new_balance}})
    return {"ok": True, "batchId": batch_id, "inserted": inserted, "skipped": skipped,
            "balance": new_balance,
            "lineCount": len(lines), "sha256": sha,
            "note": f"算术校验通过；已导入 {inserted} 条，跳过重复 {skipped} 条"}


@app.post("/bank/import")
def bank_import():
    require_writer()
    return J(bank_import_core(request.get_json(force=True) or {}))


@app.get("/bank/statement-imports")
def bank_statement_imports():
    """已导入的月结单文件列表，按导入时间倒序。"""
    e = entity_or_404()
    rows = query("""
        SELECT si.batch_id, si.bank_account_id, si.account_currency,
               si.file_name, si.file_format, si.sha256_hash,
               si.period_start, si.period_end, si.line_count,
               si.status, si.imported_by, si.imported_at,
               ba.name AS account_name,
               (SELECT COUNT(*) FROM bank_lines bl
                 WHERE bl.statement_import_batch_id = si.batch_id) AS imported_lines,
               (SELECT COUNT(*) FROM bank_lines bl
                 WHERE bl.statement_import_batch_id = si.batch_id
                   AND bl.match_status = 'matched') AS matched_lines
          FROM statement_imports si
          JOIN bank_accounts ba ON ba.account_id = si.bank_account_id
         WHERE si.entity_id = %s
         ORDER BY si.imported_at DESC, si.batch_id DESC
         LIMIT 200
    """, (e["entity_id"],))
    base = STORAGE_DIR / "bank-statements" / str(e["entity_id"])
    items = []
    for r in rows:
        d = dict(r)
        ext = "." + str(d.get("file_format") or "csv").lower().lstrip(".")
        if ext not in (".csv", ".xlsx", ".xls", ".pdf"):
            ext = ".bin"
        d["has_file"] = (base / (str(d["sha256_hash"]) + ext)).is_file()
        items.append(d)
    return J({"imports": items})


@app.delete("/bank/statement-imports/<int:batch_id>")
def bank_statement_delete(batch_id: int):
    """删除一次月结单导入；已对账（match_status=matched）的流水受保护，整批拒绝删除。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(silent=True) or {}
    actor = str(p.get("actor") or "system")

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT * FROM statement_imports
                            WHERE batch_id=%s AND entity_id=%s FOR UPDATE""",
                        (batch_id, e["entity_id"]))
            si = cur.fetchone()
            if not si:
                raise ValueError("月结单不存在或已删除")

            cur.execute("""SELECT COUNT(*) AS total,
                                  COALESCE(SUM(match_status='matched'), 0) AS matched
                             FROM bank_lines
                            WHERE statement_import_batch_id=%s AND entity_id=%s""",
                        (batch_id, e["entity_id"]))
            c = cur.fetchone() or {"total": 0, "matched": 0}
            if int(c["matched"] or 0) > 0:
                raise ValueError(
                    f"该月结单已有 {int(c['matched'])} 条流水完成对账，不能删除；"
                    "请先在银行流水页撤销匹配后再删除")

            cur.execute("""DELETE FROM bank_lines
                            WHERE statement_import_batch_id=%s AND entity_id=%s
                              AND match_status <> 'matched'""",
                        (batch_id, e["entity_id"]))
            removed = cur.rowcount
            cur.execute("DELETE FROM statement_imports WHERE batch_id=%s AND entity_id=%s",
                        (batch_id, e["entity_id"]))

            # 删除的若是期间最早的一份，接着用下一份的期初，避免账户余额停留在已删对账单上
            cur.execute("""SELECT opening_balance FROM statement_imports
                            WHERE bank_account_id=%s
                            ORDER BY period_start ASC, batch_id ASC LIMIT 1""",
                        (si["bank_account_id"],))
            nxt = cur.fetchone()
            if nxt and nxt["opening_balance"] is not None:
                cur.execute("""UPDATE bank_accounts
                                  SET opening_balance=%s, opening_balance_functional=%s
                                WHERE account_id=%s""",
                            (float(nxt["opening_balance"]), float(nxt["opening_balance"]),
                             si["bank_account_id"]))
            new_balance = recalc_bank_balance(conn, si["bank_account_id"])

            append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                                "action": "bank.import.delete",
                                "object_type": "statement_imports",
                                "object_id": str(batch_id),
                                "detail": {"accountId": si["bank_account_id"],
                                           "file": si["file_name"],
                                           "linesRemoved": int(removed),
                                           "sha256": si["sha256_hash"],
                                           "balanceAfter": new_balance}})

    ext = "." + str(si.get("file_format") or "csv").lower().lstrip(".")
    if ext not in (".csv", ".xlsx", ".xls", ".pdf"):
        ext = ".bin"
    # 同一 SHA 的文件可能被导入到多个账户（文件名按 SHA 存放），确认没有其他批次引用再删原文件
    left = query_one("""SELECT COUNT(*) AS c FROM statement_imports
                         WHERE entity_id=%s AND sha256_hash=%s""",
                     (e["entity_id"], si["sha256_hash"]))
    if not left or int(left["c"] or 0) == 0:
        f = STORAGE_DIR / "bank-statements" / str(e["entity_id"]) / (str(si["sha256_hash"]) + ext)
        try:
            if f.is_file():
                f.unlink()
        except OSError:
            pass

    return {"ok": True, "batchId": batch_id, "linesRemoved": int(removed),
            "balance": new_balance}


@app.get("/bank/statement-imports/<int:batch_id>/file")
def bank_statement_file(batch_id: int):
    """下载某次导入的原始月结单；升级前导入的记录可能没有保留原文件。"""
    e = entity_or_404()
    row = query_one("""SELECT file_name, file_format, sha256_hash
                         FROM statement_imports
                        WHERE batch_id=%s AND entity_id=%s""",
                    (batch_id, e["entity_id"]))
    if not row:
        raise ValueError("月结单不存在")
    ext = str(row.get("file_format") or "csv").lower()
    if not ext.startswith("."):
        ext = "." + ext
    if ext not in (".csv", ".xlsx", ".xls", ".pdf"):
        ext = ".bin"
    path = STORAGE_DIR / "bank-statements" / str(e["entity_id"]) / (str(row["sha256_hash"]) + ext)
    if not path.is_file():
        raise ValueError("原始文件未保留，无法下载；该记录只保留导入的流水")
    return send_file(str(path), as_attachment=True,
                     download_name=str(row["file_name"] or ("statement" + ext)))


# ------------------------------------------------------------------ 收付款与核销
@app.get("/payments")
def payments_list():
    e = entity_or_404()
    limit, offset = page_args(default_limit=100)
    _q = str(request.args.get("q") or "").strip()
    _like = f"%{_q}%" if _q else None
    # 检索范围：单号 + 客户/供应商名 + 核销过的单据号
    _party_r = """COALESCE(c.customer_name,
                     (SELECT i.supplier_name FROM settlements s
                        JOIN invoices i ON i.invoice_id=s.invoice_id
                       WHERE s.direction='received' AND s.payment_id=p.payment_id
                       ORDER BY s.settlement_id LIMIT 1))"""
    _party_m = """COALESCE(v.vendor_name,
                     (SELECT b.vendor_name FROM settlements s
                        JOIN bills b ON b.bill_id=s.bill_id
                       WHERE s.direction='made' AND s.payment_id=p.payment_id
                       ORDER BY s.settlement_id LIMIT 1))"""
    _docs_r = """(SELECT GROUP_CONCAT(i2.invoice_no SEPARATOR ' ')
                    FROM settlements s2 JOIN invoices i2 ON i2.invoice_id=s2.invoice_id
                   WHERE s2.direction='received' AND s2.payment_id=p.payment_id)"""
    _docs_m = """(SELECT GROUP_CONCAT(b2.bill_no SEPARATOR ' ')
                    FROM settlements s2 JOIN bills b2 ON b2.bill_id=s2.bill_id
                   WHERE s2.direction='made' AND s2.payment_id=p.payment_id)"""
    rq = (" AND (p.payment_no LIKE %s OR " + _party_r + " LIKE %s OR "
          + _docs_r + " LIKE %s)") if _like else ""
    mq = (" AND (p.payment_no LIKE %s OR " + _party_m + " LIKE %s OR "
          + _docs_m + " LIKE %s)") if _like else ""
    rargs = [_like, _like, _like] if _like else []
    margs = [_like, _like, _like] if _like else []

    # 收款单上没有客户时，从它核销的发票反查 —— 单据上不填客户也要能看出是谁的钱
    recv = query("""SELECT p.*,
                           COALESCE(c.customer_name,
                                    (SELECT i.supplier_name FROM settlements s
                                       JOIN invoices i ON i.invoice_id=s.invoice_id
                                      WHERE s.direction='received' AND s.payment_id=p.payment_id
                                      ORDER BY s.settlement_id LIMIT 1)) AS party,
                           (SELECT GROUP_CONCAT(i2.invoice_no ORDER BY s2.settlement_id SEPARATOR ', ')
                              FROM settlements s2 JOIN invoices i2 ON i2.invoice_id=s2.invoice_id
                             WHERE s2.direction='received' AND s2.payment_id=p.payment_id) AS doc_nos,
                           (SELECT COUNT(*) FROM settlements s3
                             WHERE s3.direction='received' AND s3.payment_id=p.payment_id) AS doc_count
                      FROM payments_received p LEFT JOIN customers c ON c.customer_id=p.customer_id
                     WHERE p.entity_id=%s """ + rq + """ ORDER BY p.payment_id DESC LIMIT %s OFFSET %s""",
                 tuple([e["entity_id"]] + rargs + [limit, offset]))
    made = query("""SELECT p.*,
                           COALESCE(v.vendor_name,
                                    (SELECT b.vendor_name FROM settlements s
                                       JOIN bills b ON b.bill_id=s.bill_id
                                      WHERE s.direction='made' AND s.payment_id=p.payment_id
                                      ORDER BY s.settlement_id LIMIT 1)) AS party,
                           (SELECT GROUP_CONCAT(b2.bill_no ORDER BY s2.settlement_id SEPARATOR ', ')
                              FROM settlements s2 JOIN bills b2 ON b2.bill_id=s2.bill_id
                             WHERE s2.direction='made' AND s2.payment_id=p.payment_id) AS doc_nos,
                           (SELECT COUNT(*) FROM settlements s3
                             WHERE s3.direction='made' AND s3.payment_id=p.payment_id) AS doc_count
                      FROM payments_made p LEFT JOIN vendors v ON v.vendor_id=p.vendor_id
                     WHERE p.entity_id=%s """ + mq + """ ORDER BY p.payment_id DESC LIMIT %s OFFSET %s""",
                 tuple([e["entity_id"]] + margs + [limit, offset]))
    # 总数也要跟着检索条件走，否则搜完了还是显示全部条数
    total_recv = int(query_one(
        "SELECT COUNT(*) n FROM payments_received p "
        "LEFT JOIN customers c ON c.customer_id=p.customer_id "
        "WHERE p.entity_id=%s" + rq, tuple([e["entity_id"]] + rargs))["n"])
    total_made = int(query_one(
        "SELECT COUNT(*) n FROM payments_made p "
        "LEFT JOIN vendors v ON v.vendor_id=p.vendor_id "
        "WHERE p.entity_id=%s" + mq, tuple([e["entity_id"]] + margs))["n"])
    def ser(rows):
        out = []
        for r in rows:
            d = dict(r)
            for k in ("amount", "amount_functional", "fx_rate_at_payment", "settlement_fx_diff"):
                if d.get(k) is not None:
                    d[k] = float(dec(d[k]))
            d["date"] = d["date"].isoformat()
            d["fx_rate_date"] = d["fx_rate_date"].isoformat() if d.get("fx_rate_date") else None
            d["created_at"] = d["created_at"].isoformat(sep=" ", timespec="milliseconds")
            out.append(d)
        return out
    return J({"received": ser(recv), "made": ser(made),
              "totalReceived": total_recv, "totalMade": total_made,
              "limit": limit, "offset": offset})


@app.get("/payments/open-docs")
def open_docs():
    e = entity_or_404()
    direction = request.args.get("direction", "received")
    limit, offset = page_args(default_limit=0)
    q = str(request.args.get("q") or "").strip()
    like = f"%{q}%" if q else None
    if direction == "received":
        where = "entity_id=%s AND status='posted' AND (gross_original-settled_original)>0"
        args = [e["entity_id"]]
        if like:
            where += " AND (invoice_no LIKE %s OR supplier_name LIKE %s)"
            args += [like, like]
        total = int(query_one(f"SELECT COUNT(*) n FROM invoices WHERE {where}", tuple(args))["n"])
        rows = query(f"""SELECT invoice_id AS docId, invoice_no AS docNo, currency,
                               (gross_original-settled_original) AS outstanding,
                               invoice_date AS docDate, supplier_name AS party
                          FROM invoices WHERE {where}
                         ORDER BY invoice_date LIMIT %s OFFSET %s""",
                     tuple(args + [limit, offset]))
    else:
        where = "entity_id=%s AND status='posted' AND (gross_original-settled_original)>0"
        args = [e["entity_id"]]
        if like:
            where += " AND (bill_no LIKE %s OR vendor_name LIKE %s)"
            args += [like, like]
        total = int(query_one(f"SELECT COUNT(*) n FROM bills WHERE {where}", tuple(args))["n"])
        rows = query(f"""SELECT bill_id AS docId, bill_no AS docNo, currency,
                               (gross_original-settled_original) AS outstanding,
                               date AS docDate, vendor_name AS party
                          FROM bills WHERE {where}
                         ORDER BY date LIMIT %s OFFSET %s""",
                     tuple(args + [limit, offset]))
    return J({"docs": [dict(r, outstanding=float(dec(r["outstanding"])),
                            docDate=r["docDate"].isoformat()) for r in rows],
              "total": total, "limit": limit, "offset": offset})


@app.get("/payments/<direction>/<int:payment_id>")
def payment_detail(direction, payment_id):
    """收款/付款单详情：表头 + 核销了哪些发票/账单 + 汇兑差额。"""
    e = entity_or_404()
    if direction not in ("received", "made"):
        raise ValueError("方向不合法")
    table = "payments_received" if direction == "received" else "payments_made"
    p = query_one(f"SELECT * FROM {table} WHERE payment_id=%s AND entity_id=%s",
                  (payment_id, e["entity_id"]))
    if not p:
        raise ValueError("单据不存在")

    if direction == "received":
        party = query_one("""SELECT customer_name AS n FROM customers WHERE customer_id=%s""",
                          (p.get("customer_id"),))
        if not party or not party.get("n"):
            party = query_one("""SELECT i.supplier_name AS n FROM settlements s
                                   JOIN invoices i ON i.invoice_id=s.invoice_id
                                  WHERE s.direction='received' AND s.payment_id=%s
                                  ORDER BY s.settlement_id LIMIT 1""", (payment_id,))
        settled = query("""SELECT s.settlement_id, s.settled_original, s.doc_currency,
                                  s.is_cross_currency, s.fx_diff_functional,
                                  i.invoice_id AS doc_id, i.invoice_no AS doc_no, i.invoice_date AS doc_date,
                                  i.gross_original AS doc_total, i.settled_original AS doc_settled
                             FROM settlements s JOIN invoices i ON i.invoice_id=s.invoice_id
                            WHERE s.direction='received' AND s.payment_id=%s
                            ORDER BY s.settlement_id""", (payment_id,))
    else:
        party = query_one("""SELECT vendor_name AS n FROM vendors WHERE vendor_id=%s""",
                          (p.get("vendor_id"),))
        if not party or not party.get("n"):
            party = query_one("""SELECT b.vendor_name AS n FROM settlements s
                                   JOIN bills b ON b.bill_id=s.bill_id
                                  WHERE s.direction='made' AND s.payment_id=%s
                                  ORDER BY s.settlement_id LIMIT 1""", (payment_id,))
        settled = query("""SELECT s.settlement_id, s.settled_original, s.doc_currency,
                                  s.is_cross_currency, s.fx_diff_functional,
                                  b.bill_id AS doc_id, b.bill_no AS doc_no, b.date AS doc_date,
                                  b.gross_original AS doc_total, b.settled_original AS doc_settled
                             FROM settlements s JOIN bills b ON b.bill_id=s.bill_id
                            WHERE s.direction='made' AND s.payment_id=%s
                            ORDER BY s.settlement_id""", (payment_id,))

    bank = query_one("""SELECT name, currency, account_number_masked FROM bank_accounts
                         WHERE account_id=%s""", (p.get("bank_account_id"),))
    entry = query_one("""SELECT entry_no, entry_date, status FROM journal_entries
                          WHERE entity_id=%s AND source_type IN ('payment_received','payment_made')
                            AND source_id=%s ORDER BY entry_id DESC LIMIT 1""",
                      (e["entity_id"], payment_id))

    def num(v):
        return float(dec(v)) if v is not None else None

    docs = []
    for s in settled:
        docs.append({"docId": s["doc_id"], "docNo": s["doc_no"], "docDate": str(s["doc_date"]),
                     "documentTotal": num(s["doc_total"]), "documentSettled": num(s["doc_settled"]),
                     "settledOriginal": num(s["settled_original"]), "currency": s["doc_currency"],
                     "crossCurrency": bool(s["is_cross_currency"]),
                     "fxDiff": num(s["fx_diff_functional"])})

    return J({
        "direction": direction,
        "paymentNo": p["payment_no"], "date": str(p["date"]), "status": p["status"],
        "amount": num(p["amount"]), "currency": p["currency"],
        "amountFunctional": num(p["amount_functional"]),
        "fxRate": num(p["fx_rate_at_payment"]), "fxRateDate": str(p["fx_rate_date"] or ""),
        "settlementFxDiff": num(p["settlement_fx_diff"]),
        "party": (party or {}).get("n"),
        "partyId": p.get("customer_id") if direction == "received" else p.get("vendor_id"),
        "bankAccountId": p.get("bank_account_id"),
        "bank": ({"name": bank["name"], "currency": bank["currency"],
                  "account": bank["account_number_masked"]} if bank else None),
        "entry": ({"entryNo": entry["entry_no"], "entryDate": str(entry["entry_date"]),
                   "status": entry["status"]} if entry else None),
        "createdBy": p.get("created_by"), "createdAt": p["created_at"].isoformat(sep=" ", timespec="minutes"),
        "documents": docs,
        "documentCount": len(docs),
    })


def payment_update_core(direction: str, payment_id: int, p: dict) -> dict:
    """保存收付款草稿，不执行过账、银行余额或单据已核销金额的变更。"""
    if direction not in ("received", "made"):
        raise ValueError("方向不合法")
    e = entity_or_404()
    table = "payments_received" if direction == "received" else "payments_made"
    existing = query_one(f"SELECT * FROM {table} WHERE payment_id=%s AND entity_id=%s",
                         (payment_id, e["entity_id"]))
    if not existing:
        raise ValueError("收付款单不存在")
    if existing["status"] != "draft":
        raise ValueError("只有草稿状态的收付款单可以编辑")

    amount, _ = quantize_money(p.get("amount", existing["amount"]))
    if amount is None or amount <= 0:
        raise ValueError("收付款金额必须大于 0")
    ccy = str(p.get("currency") or existing["currency"]).upper()
    d = p.get("date") or str(existing["date"])
    account_id = int(p.get("bankAccountId") or existing["bank_account_id"] or 0)
    acct = query_one("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                     (account_id, e["entity_id"]))
    if not acct:
        raise ValueError("银行账户不存在")
    if str(acct["currency"]).upper() != ccy:
        raise ValueError(f"收付款币种 {ccy} 与银行账户币种 {acct['currency']} 不一致")
    fx = _document_fx(e, ccy, d, amount)
    functional = fx["amount_functional"]
    fx_rate = fx["fx_rate"]

    if "allocations" in p:
        allocations = p.get("allocations") or []
    else:
        id_col = "invoice_id" if direction == "received" else "bill_id"
        allocations = [{"docId": x[id_col], "amount": x["settled_original"]}
                       for x in query(f"""SELECT {id_col}, settled_original FROM settlements
                                           WHERE direction=%s AND payment_id=%s""",
                                      (direction, payment_id))]
    if not isinstance(allocations, list):
        raise ValueError("核销明细格式不合法")

    actor = p.get("actor", "system")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT payment_no, status FROM {table}
                             WHERE payment_id=%s AND entity_id=%s FOR UPDATE""",
                        (payment_id, e["entity_id"]))
            locked = cur.fetchone()
            if not locked or locked["status"] != "draft":
                raise ValueError("只有草稿状态的收付款单可以编辑")

            id_col = "invoice_id" if direction == "received" else "bill_id"
            cur.execute(f"""SELECT {id_col}, settled_original FROM settlements
                             WHERE direction=%s AND payment_id=%s""", (direction, payment_id))
            old_alloc = {int(x[id_col]): dec(x["settled_original"]) for x in cur.fetchall()}
            cleaned = []
            total_alloc = dec(0)
            same_ccy_total = dec(0)
            cross_func = dec(0)
            fx_total = dec(0)
            seen_docs = set()
            for a in allocations:
                doc_id = int(a.get("docId") or 0)
                amt = dec(a.get("amount"))
                if not doc_id or amt is None or amt < 0:
                    raise ValueError("核销单据或金额不合法")
                if doc_id in seen_docs:
                    raise ValueError("同一张单据不能重复核销")
                seen_docs.add(doc_id)
                if amt == 0:
                    continue
                if direction == "received":
                    cur.execute("""SELECT invoice_id AS id, invoice_no AS doc_no, status, currency,
                                          gross_original, settled_original, fx_rate
                                     FROM invoices WHERE invoice_id=%s AND entity_id=%s""",
                                (doc_id, e["entity_id"]))
                else:
                    cur.execute("""SELECT bill_id AS id, bill_no AS doc_no, status, currency,
                                          gross_original, settled_original, fx_rate
                                     FROM bills WHERE bill_id=%s AND entity_id=%s""",
                                (doc_id, e["entity_id"]))
                doc = cur.fetchone()
                if not doc:
                    raise ValueError(f"核销单据 {doc_id} 不存在")
                if doc["status"] != "posted":
                    raise ValueError(f"{doc['doc_no']} 不是已记账单据，不能核销")
                outstanding = (dec(doc["gross_original"]) - dec(doc["settled_original"])
                               + old_alloc.get(doc_id, dec(0)))
                if amt > outstanding:
                    raise ValueError(f"核销金额 {amt} 超过 {doc['doc_no']} 未结金额 {outstanding}")
                doc_rate = dec(doc["fx_rate"] or 1)
                is_cross = doc["currency"] != ccy
                fx_diff = convert(amt, fx_rate) - convert(amt, doc_rate)
                cleaned.append((doc_id, amt, doc["currency"], 1 if is_cross else 0,
                                doc_rate, fx_diff))
                total_alloc += amt
                fx_total += fx_diff
                if is_cross:
                    cross_func += convert(amt, doc_rate)
                else:
                    same_ccy_total += amt
            if total_alloc > amount:
                raise ValueError("核销金额合计超过收付款金额")
            if convert(same_ccy_total, fx_rate) + cross_func > functional + dec("0.01"):
                raise ValueError("核销金额折合计价后超过收付款金额")

            party_id = (p.get("customerId") if direction == "received" else p.get("vendorId"))
            if party_id is None:
                party_id = existing.get("customer_id" if direction == "received" else "vendor_id")
            cur.execute(f"""UPDATE {table} SET customer_id=%s, date=%s, amount=%s, currency=%s,
                               amount_functional=%s, fx_rate_at_payment=%s, fx_rate_date=%s,
                               bank_account_id=%s, bank_account_currency=%s, settlement_fx_diff=%s
                             WHERE payment_id=%s AND entity_id=%s AND status='draft'""" if direction == "received"
                        else f"""UPDATE {table} SET vendor_id=%s, date=%s, amount=%s, currency=%s,
                               amount_functional=%s, fx_rate_at_payment=%s, fx_rate_date=%s,
                               bank_account_id=%s, bank_account_currency=%s, settlement_fx_diff=%s
                             WHERE payment_id=%s AND entity_id=%s AND status='draft'""",
                        (party_id, d, amount, ccy, functional, fx_rate, fx["fx_rate_date"],
                         account_id, acct["currency"], fx_total, payment_id, e["entity_id"]))
            cur.execute("DELETE FROM settlements WHERE direction=%s AND payment_id=%s",
                        (direction, payment_id))
            for doc_id, amt, doc_ccy, is_cross, doc_rate, fx_diff in cleaned:
                cur.execute("""INSERT INTO settlements
                    (entity_id, direction, payment_id, invoice_id, bill_id, settled_original,
                     doc_currency, bank_currency, is_cross_currency, doc_rate, settle_rate,
                     fx_diff_functional, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (e["entity_id"], direction, payment_id,
                             doc_id if direction == "received" else None,
                             doc_id if direction == "made" else None,
                             amt, doc_ccy, ccy, is_cross, doc_rate, fx_rate, fx_diff, actor))
        append_audit(conn, {
            "entity_id": e["entity_id"], "actor": actor, "actor_role": current_role(),
            "action": "payment.update", "object_type": table, "object_id": str(payment_id),
            "detail": {"paymentNo": locked["payment_no"], "amount": float(amount),
                       "currency": ccy, "allocations": len(cleaned), "status": "draft"}})
    return {"paymentId": payment_id, "paymentNo": locked["payment_no"], "direction": direction,
            "status": "draft", "amount": float(amount), "currency": ccy,
            "amountFunctional": float(functional), "fxRate": float(fx_rate),
            "settled": float(total_alloc), "fxDifference": float(fx_total),
            "allocations": len(cleaned)}


@app.post("/payments/<direction>/<int:payment_id>/update")
def payment_update(direction, payment_id):
    require_writer()
    return J(payment_update_core(direction, payment_id, request.get_json(force=True) or {}))


def payment_create_core(p: dict) -> dict:
    """收/付款并核销（可被 API 与智能体工具共用）。跨币种按结算日汇率算差额。"""
    e = entity_or_404()
    direction = str(p.get("direction", "received"))
    if direction not in ("received", "made"):
        raise ValueError("direction 只能是 received / made")

    amount, amount_rounded = quantize_money(p.get("amount"))
    if amount is None or amount <= 0:
        raise ValueError("付款金额必须大于 0")
    ccy = str(p.get("currency") or e["functional_currency"]).upper()
    d = p.get("date")
    acct = query_one("SELECT * FROM bank_accounts WHERE account_id=%s AND entity_id=%s",
                     (int(p.get("bankAccountId") or 0), e["entity_id"]))
    if not acct:
        raise ValueError("银行账户不存在")
    # 收付款必须与被记账的银行账户同币种，否则等于凭空把一种货币记进另一种货币的账户
    if str(acct["currency"]).upper() != ccy:
        raise ValueError(
            f"付款币种 {ccy} 与银行账户币种 {acct['currency']} 不一致；"
            f"请选择 {ccy} 账户，或改为按账户币种结算")

    allocations = p.get("allocations") or []
    if not allocations:
        raise ValueError("必须至少核销一张单据")
    total_alloc = sum((dec(a.get("amount")) or dec(0)) for a in allocations)
    if total_alloc > amount:
        raise ValueError("核销金额合计超过付款金额")

    from core.fx import lookup_rate, normalize_policy
    from core.service import load_rules
    policy = normalize_policy(load_rules()["fx_policy"])

    fx_rate, fx_date = dec(1), d
    functional = amount
    if ccy != e["functional_currency"]:
        rates = [dict(r) for r in query(
            """SELECT rate_date, from_ccy, to_ccy, rate FROM fx_rates
                WHERE from_ccy=%s AND to_ccy=%s AND rate_date>=DATE_SUB(%s, INTERVAL 10 DAY)
                  AND rate_date<=%s ORDER BY rate_date DESC""",
            (ccy, e["functional_currency"], d, d))]
        look = lookup_rate(rates, d, ccy, e["functional_currency"], policy)
        if not look["ok"]:
            raise ValueError(look["reason"] + "；付款外币折算缺汇率，不得估算")
        fx_rate = dec(look["rate"])
        fx_date = look["rateDate"]
        functional = convert(amount, fx_rate)

    with transaction() as conn:
        with conn.cursor() as cur:
            from core.numbering import next_no as _next_no
            doc_func_total = dec(0)
            payment_no = str(p.get("paymentNo") or "").strip() or _next_no(conn, e["entity_id"], d, "receipt" if direction == "received" else "payment")

            if direction == "received":
                cur.execute("""INSERT INTO payments_received
                    (entity_id, payment_no, customer_id, date, amount, currency, amount_functional,
                     fx_rate_at_payment, fx_rate_date, bank_account_id, bank_account_currency,
                     status, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'posted',%s)""",
                            (e["entity_id"], payment_no, p.get("customerId"), d, amount, ccy,
                             functional, fx_rate, fx_date, acct["account_id"], acct["currency"],
                             p.get("actor", "system")))
            else:
                cur.execute("""INSERT INTO payments_made
                    (entity_id, payment_no, vendor_id, date, amount, currency, amount_functional,
                     fx_rate_at_payment, fx_rate_date, bank_account_id, bank_account_currency,
                     status, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'posted',%s)""",
                            (e["entity_id"], payment_no, p.get("vendorId"), d, amount, ccy,
                             functional, fx_rate, fx_date, acct["account_id"], acct["currency"],
                             p.get("actor", "system")))
            payment_id = cur.lastrowid

            settled_total = dec(0)
            fx_total = dec(0)
            same_ccy_total = dec(0)
            cross_func = dec(0)
            for a in allocations:
                doc_id = int(a.get("docId") or 0)
                amt = dec(a.get("amount"))
                if not doc_id or amt is None or amt <= 0:
                    continue
                if direction == "received":
                    cur.execute("""SELECT invoice_id, currency, gross_original, settled_original,
                                          amount_functional, fx_rate
                                     FROM invoices WHERE invoice_id=%s AND entity_id=%s""",
                                (doc_id, e["entity_id"]))
                else:
                    cur.execute("""SELECT bill_id AS invoice_id, currency, gross_original,
                                          settled_original, amount_functional, fx_rate
                                     FROM bills WHERE bill_id=%s AND entity_id=%s""",
                                (doc_id, e["entity_id"]))
                doc = cur.fetchone()
                if not doc:
                    raise ValueError(f"单据 {doc_id} 不存在")

                doc_ccy = doc["currency"]
                out_std = dec(doc["gross_original"]) - dec(doc["settled_original"])
                if amt > out_std:
                    raise ValueError(f"核销金额 {amt} 超过单据未结 {out_std}")

                is_cross = doc_ccy != ccy
                settle_rate = fx_rate
                doc_rate = dec(doc["fx_rate"] or 1)
                # 结算日汇率与单据日汇率不同即产生汇兑差额，与「是否跨币种」无关：
                # 即便单据与收款同为 USD，只要两次汇率不同，功能货币金额就变了。
                fx_diff = convert(amt, settle_rate) - convert(amt, doc_rate)

                cur.execute("""INSERT INTO settlements
                    (entity_id, direction, payment_id, invoice_id, bill_id, settled_original,
                     doc_currency, bank_currency, is_cross_currency, doc_rate, settle_rate,
                     fx_diff_functional, created_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (e["entity_id"], direction, payment_id,
                             doc_id if direction == "received" else None,
                             doc_id if direction == "made" else None,
                             amt, doc_ccy, ccy, 1 if is_cross else 0,
                             doc_rate, settle_rate, fx_diff, p.get("actor", "system")))

                # 核销即完成银行对账：相关分录纳入财务报表
                if direction == "received":
                    cur.execute("""UPDATE journal_entries SET report_ready=1, reconciled_at=NOW(3),
                                       reconciled_by=%s
                                    WHERE entity_id=%s AND report_ready=0
                                      AND source_type='invoice' AND source_id=%s""",
                                (p.get("actor", "system"), e["entity_id"], doc_id))
                else:
                    cur.execute("""UPDATE journal_entries SET report_ready=1, reconciled_at=NOW(3),
                                       reconciled_by=%s
                                    WHERE entity_id=%s AND report_ready=0
                                      AND source_type='bill' AND source_id=%s""",
                                (p.get("actor", "system"), e["entity_id"], doc_id))
                cur.execute("""UPDATE journal_entries SET report_ready=1, reconciled_at=NOW(3),
                               reconciled_by=%s
                            WHERE entity_id=%s AND report_ready=0
                              AND source_type IN ('payment_received','payment_made') AND source_id=%s""",
                            (p.get("actor", "system"), e["entity_id"], payment_id))
                if direction == "received":
                    cur.execute("""UPDATE invoices SET settled_original = settled_original + %s
                                    WHERE invoice_id=%s""", (amt, doc_id))
                else:
                    cur.execute("""UPDATE bills SET settled_original = settled_original + %s
                                    WHERE bill_id=%s""", (amt, doc_id))
                # 余额不在这里加减：统一由 recalc_bank_balance 按流水/收付款重算，
                # 否则「导入对账单」和「登记收付款」会把同一笔钱算两次。

                settled_total += amt
                fx_total += fx_diff
                doc_func_total += convert(amt, dec(doc["fx_rate"] or 1))
                if is_cross:
                    cross_func += convert(amt, doc_rate)
                else:
                    same_ccy_total += amt

            # 上面的金额比较是「原币对原币」，跨币种时并不等价。
            # 同币种按付款汇率折算、跨币种按单据汇率折算，再与本位币付款额比较；
            # 同币种只要原币不超付就一定通过，不会因两次汇率不同误判。
            if convert(same_ccy_total, fx_rate) + cross_func > functional + dec("0.01"):
                raise ValueError(
                    f"核销金额折合 {float(convert(same_ccy_total, fx_rate) + cross_func):,.2f} HKD，"
                    f"超过收付款金额 {float(functional):,.2f} HKD")

            # 收付款落库后按统一口径重算账户余额
            recalc_bank_balance(conn, acct["account_id"])

            # 收付款必须进账簿：否则应收账款/应付账款在账上永不减少，
            # 银行余额也不变，报表与业务单据彻底脱节。
            if settled_total > 0:
                bank_side = convert(settled_total, fx_rate)
                fx_gain_loss = bank_side - doc_func_total
                entry_no = _next_no(conn, e["entity_id"], d, "journal")
                cur.execute("""INSERT INTO journal_entries
                    (entity_id,entry_no,entry_date,source_type,source_id,description,status,
                     report_ready,total_debit,total_credit,created_by,retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,'draft',1,%s,%s,%s,%s)""",
                    (e["entity_id"], entry_no, d,
                     'payment_received' if direction == 'received' else 'payment_made', payment_id,
                     f"{'收款' if direction=='received' else '付款'} {payment_no}",
                     float(bank_side), float(bank_side), p.get("actor", "system"),
                     retention_until(d, d)))
                entry_id = cur.lastrowid
                # 银行科目跟随所选账户，不能写死 1121——否则美元/人民币账户的
                # 收付款会全部记到港币账户，账面余额与银行对不上。
                bank_code = str(acct.get("account_code") or "1121")
                lines = []
                if direction == "received":
                    lines.append((bank_code, bank_side, dec(0)))
                    lines.append(("1130", dec(0), doc_func_total))
                else:
                    lines.append(("2110", doc_func_total, dec(0)))
                    lines.append((bank_code, dec(0), bank_side))
                if fx_gain_loss != 0:
                    # 差额进已实现汇兑损益，保证分录借贷相等
                    if fx_gain_loss > 0:
                        lines.append(("4410", dec(0), fx_gain_loss))
                    else:
                        lines.append(("4410", -fx_gain_loss, dec(0)))
                for i, (acct, dr, cr) in enumerate(lines, start=1):
                    cur.execute("""INSERT INTO journal_lines
                        (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (entry_id, i, acct, f"{payment_no}", float(dr), float(cr),
                         ccy, float(settled_total), float(fx_rate), d))
                cur.execute("""UPDATE journal_entries SET status='posted', posted_by=%s, posted_at=NOW(3),
                               total_debit=%s, total_credit=%s WHERE entry_id=%s""",
                            (p.get("actor", "system"),
                             float(sum(l[1] for l in lines)), float(sum(l[2] for l in lines)), entry_id))

            # 汇兑差额要回写到付款主记录，否则列表页与报表会显示 0
            tbl = "payments_received" if direction == "received" else "payments_made"
            cur.execute(f"UPDATE {tbl} SET settlement_fx_diff=%s WHERE payment_id=%s",
                        (fx_total, payment_id))

            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": f"payment.{direction}", "object_type":
                                "payments_received" if direction == "received" else "payments_made",
                                "object_id": str(payment_id),
                                "detail": {"paymentNo": payment_no, "amount": float(amount),
                                           "currency": ccy, "allocations": len(allocations),
                                           "fxDiff": float(fx_total)}})
    return {"paymentId": payment_id, "paymentNo": payment_no, "direction": direction,
            "amount": float(amount), "currency": ccy,
            "amountFunctional": float(functional), "fxRate": float(fx_rate),
            "settled": float(settled_total), "fxDifference": float(fx_total),
            "allocations": len(allocations)}


@app.post("/payments")
def payment_create():
    """收/付款并核销。跨币种时记录结算汇率与汇兑差额，差额进损益。"""
    require_writer()
    return J(payment_create_core(request.get_json(force=True) or {}))


# ------------------------------------------------------------------ 利得税
@app.get("/tax/computation")
def tax_computation():
    """利得税计算表（BIR51 结构）。资格未确定时拒绝计税。"""
    from core import tax
    e = entity_or_404()
    period = request.args.get("period") or date.today().strftime("%Y-%m")
    # ?year=2025/26 指定课税年度；不传就用今天所在的课税年度
    ya = request.args.get("year") or tax.ya_of_date(date.today())
    r = tax.compute(e, period, ya=ya)
    try:
        r["basisPeriod"] = list(tax.ya_range(ya))
    except Exception:
        pass
    r["yearOfAssessment"] = ya
    return J(r)


@app.post("/tax/lines")
def tax_line_add():
    require_writer()
    from core import tax
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    lid = tax.add_line(e, str(p.get("period") or ""), str(p.get("category") or ""),
                       str(p.get("itemName") or ""), p.get("amount"),
                       str(p.get("basisNote") or ""), p.get("actor", "system"))
    return J({"lineId": lid})


@app.delete("/tax/lines/<int:line_id>")
def tax_line_delete(line_id):
    require_writer()
    from core import tax
    e = entity_or_404()
    tax.delete_line(e, line_id, request.args.get("actor", "system"))
    return J({"ok": True})


@app.post("/tax/save")
def tax_save_snapshot():
    require_writer()
    from core import tax
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    period = str(p.get("period") or "")
    if len(period) != 7:
        raise ValueError("期间格式应为 YYYY-MM")
    r = tax.compute(e, period)
    if not r["computed"]:
        with transaction() as conn:
            add_pending(conn, {"entityId": e["entity_id"], "kind": "tax_entity_status",
                               "refTable": "tax_adjustments", "refId": None,
                               "reason": r["reason"], "severity": "warning",
                               "payload": {"period": period}})
        return J({"ok": False, "pending": True, "reason": r["reason"]}, 202)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tax_adjustments
                (entity_id, period, year_of_assessment, accounting_profit,
                 tax_adjustment_amount, assessable_profit, two_tier_applied,
                 two_tier_status_snapshot, tax_payable, provisional_tax_paid,
                 basis_note, detail, status, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                        (e["entity_id"], period, r["yearOfAssessment"],
                         r["accountingProfit"],
                         r["totalAddBack"] - r["totalDeduct"] - r["totalCapitalAllowance"],
                         r["assessableProfit"], 1 if r["twoTierApplied"] else 0,
                         r["twoTierStatus"], r["taxPayable"],
                         dec(p.get("provisionalTaxPaid") or 0),
                         str(p.get("basisNote") or "")[:500],
                         json.dumps(r, ensure_ascii=False, default=str),
                         p.get("actor", "system")))
            aid = cur.lastrowid
            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": "tax.compute", "object_type": "tax_adjustments",
                                "object_id": str(aid),
                                "detail": {"period": period, "assessable": r["assessableProfit"],
                                           "tax": r["taxPayable"]}})
    return J({"adjustmentId": aid, "period": period, "assessableProfit": r["assessableProfit"],
              "taxPayable": r["taxPayable"]})


@app.get("/tax/pdf")
def tax_pdf():
    from core import tax
    from core.pdf_reports import profits_tax_pdf, render, set_lang
    e = entity_or_404()
    lang = set_lang(request.args.get("lang") or "en", e["entity_id"])
    reports.set_report_lang(lang)
    from core.i18n import label as _L
    def _t(k, **kw):
        v = _L(lang, k)
        return v.format(**kw) if kw else v
    period = request.args.get("period") or date.today().strftime("%Y-%m")
    r = tax.compute(e, period)
    path = render(profits_tax_pdf(e, r), f"profits-tax-{period}.pdf")
    return send_file(str(path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"profits-tax-{period}.pdf")


@app.post("/entity/two-tier")
def entity_two_tier():
    """设定两级制税率资格。这是税务事实认定，必须由管理员显式操作并留痕。"""
    if not is_admin():
        raise PermissionError("仅管理员可修改实体税务资格")
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    status = str(p.get("status", ""))
    if status not in ("nominated", "not_nominated", "undetermined"):
        raise ValueError("状态只能是 nominated / not_nominated / undetermined")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE entities SET two_tier_status=%s, updated_at=NOW(3) WHERE entity_id=%s",
                        (status, e["entity_id"]))
            append_audit(conn, {"entity_id": e["entity_id"],
                                "actor": request.headers.get("X-Ledu-User", "admin"),
                                "actor_role": "admin", "action": "entity.two_tier_status",
                                "object_type": "entities", "object_id": str(e["entity_id"]),
                                "detail": {"from": e["two_tier_status"], "to": status,
                                           "basis": p.get("basis")}})
    return J({"twoTierStatus": status})


@app.get("/invoice-files/<int:file_id>")
def invoice_file_get(file_id):
    """发票附件元数据（doc_files）。"""
    e = entity_or_404()
    r = query_one("""SELECT file_id, doc_id AS invoice_id, doc_type, file_name, file_type,
                            file_size, sha256_hash, storage_path, uploaded_by, created_at
                       FROM doc_files WHERE file_id=%s AND entity_id=%s""",
                  (file_id, e["entity_id"]))
    if not r:
        raise ValueError("附件不存在")
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()}
    return J(d)


@app.post("/ai/ask")
def ai_ask():
    """自然语言查账。只读，不写库，不计算金额。"""
    p = request.get_json(force=True) or {}
    q = str(p.get("question") or "").strip()
    if len(q) < 2:
        raise ValueError("问题太短")
    from core.ai import AIError, nl_query
    try:
        return J(nl_query(q))
    except AIError as e:
        return J({"error": "ai_error", "message": str(e)}, 503)


@app.post("/ai/extract-invoice")
def ai_extract():
    """解析发票文本/文件，返回候选字段供人工确认（不自动入账）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    text = str(p.get("text") or "").strip()
    path = str(p.get("path") or "").strip()
    tok = str(p.get("progressToken") or "")
    # 兼容旧客户端的期初表分支；此只读接口没有 multipart 文件对象。
    form, up = {}, None
    meta = None

    if not text and path:
        set_progress(tok, "ocr", "正在读取文件并提取文字（OCR）")
        from core.ocr import OCRError, extract_text
        try:
            got = extract_text(path)
        except OCRError as e:
            return J({"error": "ocr_error", "message": str(e)}, 400)
        text = got["text"]
        meta = {k: v for k, v in got.items() if k != "text"}

    if not text.strip():
        return J({"error": "ocr_error",
                  "message": "没有识别到文字；扫描件请确认清晰度或改用文本粘贴"}, 400)

    set_progress(tok, "classify", "正在判断这是发票、对账单还是上年结转表")
    # 上年结转：科目余额表（有「科目代码 + 借方/贷方」，没有日期/摘要列）
    from core import opening as _opening
    if _opening.looks_like_trial_balance(text):
        set_progress(tok, "opening", "正在读科目余额表")
        parsed = _opening.parse_trial_balance(text, e["entity_id"])
        if not parsed.get("rows"):
            return J({"error": "opening_parse_failed",
                      "message": "没读到科目行；" + "；".join(parsed.get("warnings") or []),
                      }, 400)
        from core.agents import actions as _ai_actions
        set_progress(tok, "propose", "正在核对科目与借贷平衡")
        od = request.args.get("openingDate") or ""
        prop = _ai_actions.propose_opening(
            e["entity_id"], parsed, actor=str(p.get("actor") or form.get("actor") or "user"),
            opening_date=od, source_file=path.rsplit("/", 1)[-1] if path else None,
            source_path=path or None,
            source_name=(up.filename if up is not None and up.filename else None))
        set_progress(tok, "done", "识别完成")
        prop["kind"] = "opening"
        return J(prop)

    from core.ai import AIError, extract_invoice, looks_like_statement
    if looks_like_statement(text)["isStatement"]:
        return J({"error": "not_invoice",
                  "message": ("这是银行对账单，不是发票/收据；请在 AI 工作台上传原件，"
                              "系统会逐条解析并生成导入确认卡片。"),
                  "hint": {"page": "bank-import", "label": "在这里导入银行流水"}}, 400)
    try:
        data = extract_invoice(text)
    except AIError as e:
        return J({"error": "ai_error", "message": str(e)}, 503)
    if meta:
        data["ocr"] = meta
    data["sourceChars"] = len(text)
    # 顺带给出方向、单据类型与科目建议，导入界面可少问几个问题
    try:
        from core import doc_analyze
        # 与主上传链路一致：优先传受票方，让已建档客户能支持销售方向；
        # 本公司作为开票方的场景仍由实体名称规则识别。
        data["analysis"] = doc_analyze.analyze(
            text, entity_id=e["entity_id"],
            party=str(data.get("customerName") or data.get("supplierName") or ""),
            extracted=data)
    except Exception:
        pass
    return J(data)


@app.post("/ai/extract-party")
def ai_extract_party():
    """从名片/注册证书/客户资料中识别客户档案字段（只读，不写库）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    text = str(p.get("text") or "").strip()
    path = str(p.get("path") or "").strip()

    if not text and path:
        from core.ocr import OCRError, extract_text
        try:
            got = extract_text(path)
        except OCRError as ex:
            return J({"error": "ocr_error", "message": str(ex)}, 400)
        text = got.get("text") or ""

    if len(text.strip()) < 6:
        return J({"error": "ocr_error",
                  "message": "没有识别到有效文字；请上传清晰的名片/证书，或粘贴资料文本"}, 400)

    from core.ai import AIError, extract_party
    try:
        data = extract_party(text)
    except ValueError as ex:
        return J({"error": "bad_request", "message": str(ex)}, 400)
    except AIError as ex:
        return J({"error": "ai_error", "message": str(ex)}, 503)
    data["sourceChars"] = len(text)
    return J(data)


@app.post("/ai/analyze-document")
def ai_analyze_document():
    """单据分析：判断采购/销售、单据类型，推荐科目与借贷方向（只读，不写账）。"""
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    text = str(p.get("text") or "").strip()
    path = str(p.get("path") or "").strip()
    if not text and path:
        from core.ocr import OCRError, extract_text
        try:
            text = extract_text(path)["text"]
        except OCRError as ex:
            return J({"error": "ocr_error", "message": str(ex)}, 400)
    if not text:
        return J({"error": "bad_request", "message": "请提供单据文本或文件路径"}, 400)
    from core import doc_analyze
    try:
        return J(doc_analyze.analyze(
            text, entity_id=e["entity_id"], party=str(p.get("party") or ""),
            lines=p.get("lines"), extracted=p.get("extracted")))
    except Exception as ex:
        return J({"error": "analyze_failed", "message": str(ex)}, 400)


@app.post("/ai/doc-feedback")
def ai_doc_feedback():
    """人工改正方向/科目：写学习样本，够格就固化成规则。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    corrected = p.get("corrected") or {}
    if not isinstance(corrected, dict) or not corrected:
        return J({"error": "bad_request", "message": "缺少 corrected（要改正的字段）"}, 400)
    from core import doc_analyze
    return J(doc_analyze.record_feedback(
        e["entity_id"], str(p.get("text") or ""), corrected,
        actor=str(p.get("actor") or ""), predicted=p.get("predicted"),
        party=str(p.get("party") or ""), doc_kind=str(p.get("docKind") or "")))


@app.get("/ai/analyze-learning")
def ai_analyze_learning():
    """单据分析学到了什么：方向/科目的纠正样本与已固化规则。"""
    from core.agents import extractor_learning as exl
    e = entity_or_404()
    eid = e["entity_id"]
    rules = [r for r in exl.rules_for(eid) if str(r["field"]) in ("direction", "accountCode")]
    return J({"summary": exl.summary(eid), "rules": rules,
              "fields": {k: exl.LEARNABLE_FIELDS[k] for k in ("direction", "accountCode")}})


@app.post("/ai/variance")
def ai_variance():
    p = request.get_json(force=True) or {}
    from core.ai import AIError, variance_bridge
    try:
        return J(variance_bridge(p.get("expected"), p.get("actual"), p.get("factors") or []))
    except AIError as e:
        return J({"error": "ai_error", "message": str(e)}, 503)


@app.get("/ai/review-advice")
def ai_review_advice():
    e = entity_or_404()
    rows = query("""SELECT kind, severity, reason FROM pending_review
                     WHERE entity_id=%s AND status='open' ORDER BY severity='blocker' DESC""",
                 (e["entity_id"],))
    from core.ai import analyze_review_queue
    return J(analyze_review_queue(rows))


@app.get("/ai/ocr-status")
def ai_ocr_status():
    from core.ocr import available
    from config import env as _env
    return J({"tools": available(),
              "llmConfigured": bool(_env("LEDU_LLM_API_KEY")),
              "model": _env("LEDU_LLM_MODEL") or None})


# ------------------------------------------------------------------ PDF
def invoice_pdf_path(invoice_id: int, lang: str = "en"):
    """生成一张销售发票 PDF，返回文件路径（批量导出也用它）。"""
    from core.pdf import invoice_html, localize, render
    inv = query_one("SELECT * FROM invoices WHERE invoice_id=%s", (invoice_id,))
    if not inv:
        raise ValueError("发票不存在")
    e = entity_or_404()
    files = query("""SELECT file_name, file_size, sha256_hash FROM doc_files
                      WHERE doc_type='invoice' AND doc_id=%s ORDER BY file_id""", (invoice_id,))
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(inv).items()}
    d["lines"] = [{**dict(x),
                   "quantity": float(dec(x["quantity"])),
                   "unit_price": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "tax_rate": float(dec(x["tax_rate"])) if x["tax_rate"] is not None else None,
                   "tax_amount": float(dec(x["tax_amount"]))}
                  for x in query("""SELECT line_no, item_code, description, unit, quantity,
                                           unit_price, amount, tax_rate, tax_amount
                                      FROM invoice_lines WHERE invoice_id=%s ORDER BY line_no""",
                                 (invoice_id,))]
    ent = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(e).items()}
    bank = query_one("""SELECT account_holder, bank_name, bank_code, swift_code, bank_address,
                               account_number, currency FROM bank_accounts
                         WHERE entity_id=%s AND status='active' AND is_primary_receiving=1 LIMIT 1""",
                     (e["entity_id"],))
    if not bank:
        bank = query_one("""SELECT account_holder, bank_name, bank_code, swift_code, bank_address,
                                   account_number, currency FROM bank_accounts
                             WHERE entity_id=%s AND status='active' AND currency=%s
                             ORDER BY account_id LIMIT 1""",
                         (e["entity_id"], e["functional_currency"]))
    html_doc = invoice_html(d, ent, files, dict(bank) if bank else None, lang)
    html_doc = localize(html_doc, lang)
    return render(html_doc, f"invoice-{inv['invoice_no']}.pdf")


def _simple_doc_pdf(kind: str, doc: dict, lines: list, lang: str) -> "Response":
    """报价单 / 贷记单 / 订单的 PDF：与发票同一套抬头，内容按各自数据填。"""
    from core.pdf import simple_doc_html, render
    from flask import send_file
    e = entity_or_404()
    ent = query_one("SELECT * FROM entities WHERE entity_id=%s", (e["entity_id"],))
    html = simple_doc_html(kind, doc, dict(ent or {}), lines=lines, lang=lang)
    path = render(html, f"{kind}-{doc.get('no', 'doc')}.pdf")
    return send_file(str(path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"{doc.get('no') or kind}.pdf")


def _quote_pdf_response(q: dict, lang: str) -> "Response":
    e = entity_or_404()
    rows = query("""SELECT description, quantity, unit_price, amount FROM quote_lines
                     WHERE quote_id=%s ORDER BY line_no""", (q["quote_id"],))
    _pt = {"zh_cn": ("客户", "有效期至"), "zh_hk": ("客戶", "有效期至"),
           "en": ("Customer", "Valid until")}.get(lang, ("Customer", "Valid until"))
    return _simple_doc_pdf("quote", {
        "no": q["quote_no"], "date": q["quote_date"].isoformat(),
        "partyLabel": _pt[0],
        "party": q["customer_name"], "currency": q["currency"],
        "total": q["gross_original"],
        "fx_rate": q.get("fx_rate"), "fx_rate_date": q.get("fx_rate_date"),
        "amount_functional": q.get("amount_functional"),
        "functional_currency": e["functional_currency"],
        "meta": [(_pt[1],
                  q["valid_until"].isoformat() if q.get("valid_until") else "")],
    }, [{"description": r["description"], "quantity": r["quantity"],
         "unitPrice": r["unit_price"], "amount": r["amount"]} for r in rows], lang)


@app.get("/quotes/<int:quote_id>/pdf")
def quote_pdf(quote_id):
    e = entity_or_404()
    q = query_one("SELECT * FROM quotes WHERE quote_id=%s AND entity_id=%s",
                  (quote_id, e["entity_id"]))
    if not q:
        raise ValueError("报价单不存在")
    return _quote_pdf_response(q, request.args.get("lang") or "en")


def _credit_note_pdf_response(c: dict, lang: str) -> "Response":
    """贷记单 PDF 与邮件共用同一真实数据，客户/供应商称谓不混用。"""
    e = entity_or_404()
    is_customer = c["credit_type"] == "customer"
    _pt = {
        "zh_cn": ("客户" if is_customer else "供应商", "原因"),
        "zh_hk": ("客戶" if is_customer else "供應商", "原因"),
        "en": ("Customer" if is_customer else "Vendor", "Reason"),
    }.get(lang, ("Customer" if is_customer else "Vendor", "Reason"))
    return _simple_doc_pdf("credit", {
        "no": c["credit_no"], "date": c["credit_date"].isoformat(),
        "partyLabel": _pt[0], "party": c["party_name"], "currency": c["currency"],
        "total": c["gross_original"],
        "fx_rate": c.get("fx_rate"), "fx_rate_date": c.get("fx_rate_date"),
        "amount_functional": c.get("amount_functional"),
        "functional_currency": e["functional_currency"],
        "meta": [(_pt[1], c.get("reason") or "")],
    }, [], lang)


@app.get("/credit-notes/<int:credit_id>/pdf")
def credit_note_pdf(credit_id):
    e = entity_or_404()
    c = query_one("SELECT * FROM credit_notes WHERE credit_id=%s AND entity_id=%s",
                  (credit_id, e["entity_id"]))
    if not c:
        raise ValueError("贷记单不存在")
    return _credit_note_pdf_response(c, request.args.get("lang") or "en")


def _order_pdf_response(o: dict, lang: str) -> "Response":
    e = entity_or_404()
    rows = query("""SELECT description, quantity, unit_price, amount FROM order_lines
                     WHERE order_id=%s ORDER BY line_no""", (o["order_id"],))
    kind = "order_sales" if o["direction"] == "sales" else "order_purchase"
    _sales = o["direction"] == "sales"
    _pt = {"zh_cn": ("客户" if _sales else "供应商", "预计日期"),
           "zh_hk": ("客戶" if _sales else "供應商", "預計日期"),
           "en": ("Customer" if _sales else "Vendor", "Expected")}.get(
               lang, ("Customer" if _sales else "Vendor", "Expected"))
    return _simple_doc_pdf(kind, {
        "no": o["order_no"], "date": o["order_date"].isoformat(),
        "partyLabel": _pt[0],
        "party": o["party_name"], "currency": o["currency"],
        "total": o["gross_original"],
        "fx_rate": o.get("exchange_rate"),
        "amount_functional": o.get("amount_functional"),
        "functional_currency": e["functional_currency"],
        "meta": [(_pt[1],
                  o["expected_date"].isoformat() if o.get("expected_date") else "")],
    }, [{"description": r["description"], "quantity": r["quantity"],
         "unitPrice": r["unit_price"], "amount": r["amount"]} for r in rows], lang)


@app.get("/orders/<int:order_id>/pdf")
def order_pdf(order_id):
    e = entity_or_404()
    o = query_one("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s",
                  (order_id, e["entity_id"]))
    if not o:
        raise ValueError("订单不存在")
    return _order_pdf_response(o, request.args.get("lang") or "en")


@app.get("/invoices/<int:invoice_id>/pdf")
def invoice_pdf(invoice_id):
    path = invoice_pdf_path(invoice_id, request.args.get("lang") or "en")
    inv = query_one("SELECT invoice_no FROM invoices WHERE invoice_id=%s", (invoice_id,))
    return send_file(str(path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"invoice-{inv['invoice_no']}.pdf")


def bill_pdf_path(bill_id: int, lang: str = "en"):
    """生成一张采购账单 PDF，返回文件路径（批量导出也用它）。"""
    from core.pdf import bill_html, localize, render
    bill = query_one("SELECT * FROM bills WHERE bill_id=%s", (bill_id,))
    if not bill:
        raise ValueError("账单不存在")
    e = entity_or_404()
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(bill).items()}
    d["lines"] = [{**dict(x),
                   "quantity": float(dec(x["quantity"])),
                   "unit_price": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "tax_rate": float(dec(x["tax_rate"])) if x["tax_rate"] is not None else None,
                   "tax_amount": float(dec(x["tax_amount"]))}
                  for x in query("""SELECT line_no, item_code, description, unit, quantity,
                                           unit_price, amount, tax_rate, tax_amount
                                      FROM bill_lines WHERE bill_id=%s ORDER BY line_no""",
                                 (bill_id,))]
    ent = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(e).items()}
    html_doc = bill_html(d, ent, lang)
    html_doc = localize(html_doc, lang)
    return render(html_doc, f"bill-{bill['bill_no']}.pdf")


@app.get("/bills/<int:bill_id>/pdf")
def bill_pdf(bill_id):
    path = bill_pdf_path(bill_id, request.args.get("lang") or "en")
    bill = query_one("SELECT bill_no FROM bills WHERE bill_id=%s", (bill_id,))
    return send_file(str(path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"bill-{bill['bill_no']}.pdf")


# ------------------------------------------------------------------ 手工分录
@app.post("/journal")
@app.post("/journal/<int:entry_id>/update")
def journal_create(entry_id=None):
    """新建即过账；指定 entry_id 时仅保存草稿，不隐式过账。"""
    require_writer()
    return J(journal_create_core(request.get_json(force=True) or {}, entry_id=entry_id))


def journal_create_core(p, entry_id=None):
    """手工分录的共用实现（HTTP 与内部调用都用它）。"""
    e = entity_or_404()
    entry_date = p.get("entryDate")
    description = str(p.get("description") or "").strip()
    lines = p.get("lines") or []

    if not entry_date:
        raise ValueError("必须提供分录日期")
    if not description:
        raise ValueError("必须填写摘要")
    if not isinstance(lines, list) or len(lines) < 2:
        raise ValueError("分录至少需要两行")

    from core.money import dec as _d, parse_date
    if parse_date(entry_date) is None:
        raise ValueError("分录日期格式应为 YYYY-MM-DD")

    dr = _d(0); cr = _d(0)
    clean = []
    for i, ln in enumerate(lines, start=1):
        code = str(ln.get("accountCode") or "").strip()
        if not code:
            raise ValueError(f"第 {i} 行缺少科目")
        d, _ = quantize_money(ln.get("debit") or 0)
        c, _ = quantize_money(ln.get("credit") or 0)
        if d is None or c is None:
            raise ValueError(f"第 {i} 行金额非法")
        if d < 0 or c < 0:
            raise ValueError(f"第 {i} 行金额不能为负，请改用相反方向")
        if d > 0 and c > 0:
            raise ValueError(f"第 {i} 行借贷不能同时有金额")
        if d == 0 and c == 0:
            raise ValueError(f"第 {i} 行借贷都是 0")
        clean.append((code, d, c, str(ln.get("description") or "")[:200]))
        dr += d; cr += c

    if dr != cr:
        raise ValueError(f"借贷不平衡：借方 {dr}，贷方 {cr}，差额 {dr - cr}")

    with transaction() as conn:
        with conn.cursor() as cur:
            codes = [c[0] for c in clean]
            ph = ",".join(["%s"] * len(codes))
            cur.execute(f"""SELECT account_code FROM accounts
                             WHERE entity_id=%s AND account_code IN ({ph})""",
                        (e["entity_id"], *codes))
            known = {r["account_code"] for r in cur.fetchall()}
            missing = [c for c in codes if c not in known]
            if missing:
                raise ValueError("科目不存在：" + "、".join(sorted(set(missing))))

            if entry_id is not None:
                cur.execute("""SELECT * FROM journal_entries
                                WHERE entry_id=%s AND entity_id=%s FOR UPDATE""",
                            (entry_id, e["entity_id"]))
                locked = cur.fetchone()
                if not locked:
                    raise ValueError("分录不存在")
                if locked["status"] != "draft":
                    raise ValueError("只有草稿状态的分录可以编辑；已过账分录请用冲销更正")
                entry_no = locked["entry_no"]
                cur.execute("""UPDATE journal_entries SET entry_date=%s, description=%s,
                                  total_debit=%s, total_credit=%s,
                                  retention_until=DATE_ADD(%s, INTERVAL 7 YEAR)
                                WHERE entry_id=%s AND entity_id=%s AND status='draft'""",
                            (entry_date, description, dr, cr, entry_date,
                             entry_id, e["entity_id"]))
                cur.execute("DELETE FROM journal_lines WHERE entry_id=%s", (entry_id,))
                status = "draft"
            else:
                from core.numbering import next_no as _next_no
                entry_no = _next_no(conn, e["entity_id"], entry_date, "journal")
                _src = str(p.get("sourceType") or "manual")
                if _src not in ("manual", "opening"):
                    _src = "manual"
                cur.execute("""INSERT INTO journal_entries
                    (entity_id, entry_no, entry_date, source_type, description, status,
                     total_debit, total_credit, created_by, retention_until)
                    VALUES (%s,%s,%s,%s,%s,'draft',%s,%s,%s,
                            DATE_ADD(%s, INTERVAL 7 YEAR))""",
                            (e["entity_id"], entry_no, entry_date, _src, description, dr, cr,
                             p.get("actor", "system"), entry_date))
                entry_id = cur.lastrowid
                status = "posted"

            for i, (code, d, c, note) in enumerate(clean, start=1):
                cur.execute("""INSERT INTO journal_lines
                    (entry_id, line_no, account_code, description, debit, credit, ccy,
                     amount_original, rate, rate_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s)""",
                            (entry_id, i, code, note or description, d, c,
                             e["functional_currency"], d if d > 0 else c, entry_date))

            if entry_id is not None and status == "posted":
                cur.execute("""UPDATE journal_entries SET status='posted', posted_by=%s,
                                  posted_at=NOW(3) WHERE entry_id=%s""",
                            (p.get("actor", "system"), entry_id))

            append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                                "action": "journal.update" if status == "draft" else "journal.manual",
                                "object_type": "journal_entries", "object_id": str(entry_id),
                                "detail": {"entryNo": entry_no, "total": float(dr),
                                           "lines": len(clean), "status": status}})
    return {"entryId": entry_id, "entryNo": entry_no, "status": status,
            "totalDebit": float(dr), "totalCredit": float(cr)}


# ------------------------------------------------------------------ 更多报表
@app.get("/reports/general-ledger")
def r_gl():
    e = entity_or_404()
    code = request.args.get("account")
    start = request.args.get("from") or "0000-01-01"
    end = request.args.get("to") or "9999-12-31"
    if code:
        rows = query("""SELECT e.entry_no, e.entry_date, e.source_type, l.description,
                               l.debit, l.credit, l.ccy
                          FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
                         WHERE e.entity_id=%s AND l.account_code=%s
                           AND e.entry_date BETWEEN %s AND %s
                           AND e.status IN ('posted','reversed')
                         ORDER BY e.entry_date, e.entry_id, l.line_no""",
                        (e["entity_id"], code, start, end))
        out, run = [], dec(0)
        for r in rows:
            run = run + dec(r["debit"]) - dec(r["credit"])
            out.append({"entryNo": r["entry_no"], "date": r["entry_date"].isoformat(),
                        "source": r["source_type"], "description": r["description"],
                        "debit": float(dec(r["debit"])), "credit": float(dec(r["credit"])),
                        "balance": float(run), "ccy": r["ccy"]})
        acct = query_one("""SELECT account_code, account_name, normal_balance FROM accounts
                             WHERE entity_id=%s AND account_code=%s""", (e["entity_id"], code))
        return J({"account": acct, "lines": out, "closingBalance": float(run),
                  "from": start, "to": end})
    rows = query("""SELECT a.account_code, a.account_name, a.category,
                           COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
                      FROM accounts a
                      JOIN journal_lines l ON l.account_code=a.account_code
                      JOIN journal_entries e ON e.entry_id=l.entry_id
                           AND e.status IN ('posted','reversed') AND e.entity_id=a.entity_id
                     WHERE a.entity_id=%s
                     GROUP BY a.account_code, a.account_name, a.category
                     HAVING dr<>0 OR cr<>0
                     ORDER BY a.account_code""", (e["entity_id"],))
    return J({"accounts": [dict(r, dr=float(dec(r["dr"])), cr=float(dec(r["cr"])),
                               balance=float(dec(r["dr"]) - dec(r["cr"]))) for r in rows]})


@app.get("/reports/daybook")
def r_daybook():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    e = entity_or_404()
    start = request.args.get("from") or "0000-01-01"
    end = request.args.get("to") or "9999-12-31"
    rows = query("""SELECT e.entry_id, e.entry_no, e.entry_date, e.source_type, e.description,
                           e.status, e.total_debit
                      FROM journal_entries e
                     WHERE e.entity_id=%s AND e.entry_date BETWEEN %s AND %s
                     ORDER BY e.entry_date DESC, e.entry_id DESC LIMIT 500""",
                (e["entity_id"], start, end))
    return J({"entries": [dict(r, entry_date=r["entry_date"].isoformat(),
                               total_debit=float(dec(r["total_debit"]))) for r in rows],
              "from": start, "to": end})


@app.get("/reports/sales-detail")
def r_sales_detail():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    e = entity_or_404()
    rows = query("""SELECT supplier_name AS party, currency,
                           COUNT(*) AS cnt,
                           SUM(amount_original) AS net_original,
                           SUM(tax_original) AS tax_original,
                           SUM(gross_original) AS gross_original,
                           SUM(amount_functional) AS functional
                      FROM invoices WHERE entity_id=%s AND status='posted'
                     GROUP BY supplier_name, currency ORDER BY functional DESC""", (e["entity_id"],))
    return J({"rows": [dict(r, cnt=int(r["cnt"]),
                            net_original=float(dec(r["net_original"])),
                            tax_original=float(dec(r["tax_original"])),
                            gross_original=float(dec(r["gross_original"])),
                            functional=float(dec(r["functional"]))) for r in rows],
              "note": "按客户与币种分列；HKD 合计仅取折算列"})


@app.get("/reports/purchase-detail")
def r_purchase_detail():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    e = entity_or_404()
    rows = query("""SELECT vendor_name AS party, currency, COUNT(*) AS cnt,
                           SUM(gross_original) AS gross_original,
                           SUM(amount_functional) AS functional
                      FROM bills WHERE entity_id=%s AND status='posted'
                     GROUP BY vendor_name, currency ORDER BY functional DESC""", (e["entity_id"],))
    return J({"rows": [dict(r, cnt=int(r["cnt"]),
                            gross_original=float(dec(r["gross_original"])),
                            functional=float(dec(r["functional"]))) for r in rows]})


@app.get("/search")
def global_search():
    e = entity_or_404()
    q = (request.args.get("q") or "").strip()
    if len(q) < 1:
        return J({"results": []})
    like = f"%{q}%"
    out = []
    for r in query("""SELECT invoice_id, invoice_no, supplier_name, gross_original, currency, status
                        FROM invoices WHERE entity_id=%s
                         AND (invoice_no LIKE %s OR supplier_name LIKE %s)
                       LIMIT 8""", (e["entity_id"], like, like)):
        out.append({"type": "invoice", "id": r["invoice_id"], "title": r["invoice_no"],
                    "sub": f"{r['supplier_name']} · {float(dec(r['gross_original'])):,.2f} {r['currency']}",
                    "status": r["status"], "url": f"?p=invoice-view&id={r['invoice_id']}"})
    for r in query("""SELECT bill_id, bill_no, vendor_name, gross_original, currency, status
                        FROM bills WHERE entity_id=%s
                         AND (bill_no LIKE %s OR vendor_name LIKE %s) LIMIT 8""",
                  (e["entity_id"], like, like)):
        out.append({"type": "bill", "id": r["bill_id"], "title": r["bill_no"],
                    "sub": f"{r['vendor_name']} · {float(dec(r['gross_original'])):,.2f} {r['currency']}",
                    "status": r["status"], "url": "?p=bills"})
    for r in query("""SELECT entry_id, entry_no, description, total_debit, status
                        FROM journal_entries WHERE entity_id=%s
                         AND (entry_no LIKE %s OR description LIKE %s) LIMIT 8""",
                  (e["entity_id"], like, like)):
        out.append({"type": "entry", "id": r["entry_id"], "title": r["entry_no"],
                    "sub": f"{(r['description'] or '')[:60]} · {float(dec(r['total_debit'])):,.2f} HKD",
                    "status": r["status"], "url": f"?p=journal&entry={r['entry_id']}"})
    for r in query("""SELECT line_id, bank_ref, counterparty_name, amount_original, currency
                        FROM bank_lines WHERE entity_id=%s
                         AND (bank_ref LIKE %s OR counterparty_name LIKE %s) LIMIT 8""",
                  (e["entity_id"], like, like)):
        out.append({"type": "bank", "id": r["line_id"], "title": r["bank_ref"] or f"BL-{r['line_id']}",
                    "sub": f"{r['counterparty_name']} · {float(dec(r['amount_original'])):,.2f} {r['currency']}",
                    "status": "", "url": "?p=reconcile"})
    return J({"q": q, "results": out, "count": len(out)})


@app.get("/reports/dashboard-charts")
def r_dash_charts():
    """仪表盘图表数据：近 N 个月收入/成本/费用、Top 客户、账龄、现金。

    N 由 ?months= 指定，默认 12 个月（一年），允许 3–36。
    """
    e = entity_or_404()
    try:
        span = int(request.args.get("months") or 12)
    except ValueError:
        span = 12
    span = max(3, min(36, span))
    months = query("""
        SELECT period, COUNT(DISTINCT je.entry_id) AS entries,
               SUM(CASE WHEN a.category='revenue' THEN l.credit - l.debit ELSE 0 END) AS revenue,
               SUM(CASE WHEN a.category='cogs' THEN l.debit - l.credit ELSE 0 END) AS cogs,
               SUM(CASE WHEN a.category='expense' THEN l.debit - l.credit ELSE 0 END) AS expense
          FROM journal_lines l
          JOIN journal_entries je ON je.entry_id = l.entry_id
          JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = je.entity_id
         WHERE je.entity_id = %s AND je.status IN ('posted','reversed')
         GROUP BY je.period ORDER BY je.period DESC LIMIT %s""", (e["entity_id"], span))
    # 补齐整段月份：只画有数据的月，一年视图会只剩两根柱、看不出走势。
    have = {r["period"]: r for r in months}
    from datetime import date as _d
    def _shift(ym: str, back: int) -> str:
        y, m = int(ym[:4]), int(ym[5:7])
        m -= back
        while m <= 0:
            m += 12; y -= 1
        return f"{y:04d}-{m:02d}"
    # 哪些月份含期初分录（= 上年结转损益），画图时要标注，否则柱子会被误读
    opening_months = {r["period"] for r in query(
        """SELECT DISTINCT je.period FROM journal_entries je
             WHERE je.entity_id=%s AND je.status IN ('posted','reversed')
               AND je.source_type='opening'""", (e["entity_id"],))}
    # 锚定「有数据的最后一个月」，而不是今天：账簿停更时若锚到今天，
    # 真实数据会被挤出窗口，右侧出现一长串空柱，看起来像账没做完。
    _lr = query("""SELECT MAX(period) AS p, MAX(entry_date) AS d
                     FROM journal_entries
                    WHERE entity_id=%s AND status IN ('posted','reversed')""",
                (e["entity_id"],))
    _latest = _lr[0] if _lr else {}
    latest_period = _latest.get("p")
    data_through = _latest.get("d")
    anchor = latest_period or _d.today().strftime("%Y-%m")
    seq = [_shift(anchor, i) for i in range(span - 1, -1, -1)]
    trend = []
    for p_ in seq:
        r = have.get(p_)
        rev = float(dec(r["revenue"])) if r else 0.0
        cg = float(dec(r["cogs"])) if r else 0.0
        ex = float(dec(r["expense"])) if r else 0.0
        trend.append({"period": p_, "revenue": rev, "cogs": cg, "expense": ex,
                      "profit": rev - cg - ex, "hasData": bool(r),
                      "hasOpening": p_ in opening_months,
                      "entries": int(r["entries"]) if r else 0})

    top = query("""SELECT supplier_name AS party, currency, SUM(amount_functional) AS amt
                     FROM invoices WHERE entity_id=%s AND status='posted'
                    GROUP BY supplier_name, currency ORDER BY amt DESC LIMIT 6""", (e["entity_id"],))
    top_customers = [{"party": r["party"], "currency": r["currency"],
                      "amount": float(dec(r["amt"]))} for r in top]

    ag = reports.aging(e["entity_id"], "receivable")
    cash = reports.bank_balances(e["entity_id"])

    # 费用构成：按报表项目汇总，用于环形图。
    # 窗口与趋势图一致（不含期初结转），否则图上说 12 个月、饼图却按另一个期间算。
    _wy, _wm = int(seq[0][:4]), int(seq[0][5:7])
    win_start = _d(_wy, _wm, 1)
    _ly, _lm = int(seq[-1][:4]), int(seq[-1][5:7])
    if _lm == 12:
        win_end = _d(_ly, 12, 31)
    else:
        win_end = _d(_ly, _lm + 1, 1) - timedelta(days=1)
    exp_rows = query("""
        SELECT a.fs_line_item, COALESCE(SUM(l.debit - l.credit),0) AS amt
          FROM journal_lines l
          JOIN journal_entries je ON je.entry_id = l.entry_id
          JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = je.entity_id
         WHERE je.entity_id = %s AND je.status IN ('posted','reversed')
           AND (je.source_type IS NULL OR je.source_type <> 'opening')
           AND je.entry_date BETWEEN %s AND %s
           AND a.category IN ('cogs','expense')
         GROUP BY a.fs_line_item HAVING amt > 0 ORDER BY amt DESC""",
        (e["entity_id"], win_start.isoformat(), win_end.isoformat()))
    from core.i18n import column as _col
    expense_breakdown = [{"key": r["fs_line_item"], "amount": float(dec(r["amt"]))}
                         for r in exp_rows]

    # 可执行数据：逾期最久的客户 / 应收逾期概况 / 应付未结清概况。
    # 仪表盘首页直接展示，避免用户为了看「谁欠最久」再点两层。
    over_rows = query("""
        SELECT invoice_no, supplier_name AS party, due_date,
               (gross_original - settled_original) AS amt,
               DATEDIFF(CURDATE(), due_date) AS days
          FROM invoices
         WHERE entity_id=%s AND status='posted'
           AND gross_original > settled_original
           AND due_date IS NOT NULL AND due_date < CURDATE()
         ORDER BY days DESC, amt DESC LIMIT 5""", (e["entity_id"],))
    overdue_ar = [{"docNo": r["invoice_no"], "party": r["party"],
                   "dueDate": str(r["due_date"]), "amount": float(dec(r["amt"])),
                   "days": int(r["days"] or 0)} for r in over_rows]
    ar_agg = query("""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(gross_original - settled_original),0) AS amt,
               COALESCE(MAX(DATEDIFF(CURDATE(), due_date)),0) AS maxdays
          FROM invoices
         WHERE entity_id=%s AND status='posted'
           AND gross_original > settled_original
           AND due_date IS NOT NULL AND due_date < CURDATE()""", (e["entity_id"],))
    ap_agg = query("""
        SELECT COUNT(*) AS n, COALESCE(SUM(gross_original - settled_original),0) AS amt,
               MIN(due_date) AS due
          FROM bills
         WHERE entity_id=%s AND status='posted'
           AND gross_original > settled_original""", (e["entity_id"],))
    ar_over = ar_agg[0] if ar_agg else {}
    ap_open = ap_agg[0] if ap_agg else {}

    # 应收账龄分桶（按 HKD 折算）
    buckets = ag["buckets"] if isinstance(ag.get("buckets"), list) else []
    return J({"trend": trend, "topCustomers": top_customers,
              "dataThrough": str(data_through) if data_through else None,
              "window": {"from": seq[0], "to": seq[-1]},
              "arOverdue": {"count": int(ar_over.get("n") or 0),
                            "amount": float(dec(ar_over.get("amt") or 0)),
                            "maxDays": int(ar_over.get("maxdays") or 0)},
              "openAp": {"count": int(ap_open.get("n") or 0),
                         "amount": float(dec(ap_open.get("amt") or 0)),
                         "nextDue": str(ap_open.get("due")) if ap_open.get("due") else None},
              "overdueAr": overdue_ar,
              "aging": ag["byCurrency"], "agingBuckets": buckets,
              "cash": cash["groups"], "cashTotal": cash["hkdTotal"],
              "expenseBreakdown": expense_breakdown})


@app.get("/reports/statements")
def statements_json():
    e = entity_or_404()
    start = request.args.get("from") or f"{date.today().year}-01-01"
    end = request.args.get("to") or date.today().isoformat()
    return J(reports.financial_statements(e["entity_id"], e, start, end))


@app.get("/reports/statements/pdf")
def statements_pdf():
    from core.pdf_reports import full_package, render, set_lang
    e = entity_or_404()
    lang = set_lang(request.args.get("lang") or "en", e["entity_id"])
    from core.i18n import label as _L
    def _t(k, **kw):
        v = _L(lang, k)
        return v.format(**kw) if kw else v
    start = request.args.get("from") or f"{date.today().year}-01-01"
    end = request.args.get("to") or date.today().isoformat()
    fs = reports.financial_statements(e["entity_id"], e, start, end)

    # 单份「完整报表包」默认带试算表与总账；ZIP 里已有独立文件时用 ?gl=0 关掉
    with_gl = (request.args.get("gl") or "1") != "0"
    from core.pdf_reports import generic_report as _gr
    minutes = f"{start} to {end}" if lang == "en" else f"{start} 至 {end}"
    extra = []

    def m(v):
        try:
            return f"{float(v or 0):,.2f}"
        except (TypeError, ValueError):
            return ""

    tb = reports.trial_balance(e["entity_id"], end) if with_gl else {"accounts": [], "totalDebit": 0, "totalCredit": 0}
    tb_rows = [[a["accountCode"], a["accountName"], m(a["debit"]) if a["debit"] else "",
                m(a["credit"]) if a["credit"] else ""] for a in tb["accounts"]]
    # 标签跟着报表语言走，否则简中报表包里会冒出繁体表头
    L = {
        "zh_cn": {"tb": "试算表", "code": "科目", "name": "名称", "dr": "借方", "cr": "贷方",
                  "total": "合计",
                  "gl": "总分类账", "date": "日期", "desc": "摘要", "bal": "余额"},
        "zh_hk": {"tb": "試算表", "code": "科目", "name": "名稱", "dr": "借方", "cr": "貸方",
                  "total": "合計",
                  "gl": "總分類帳", "date": "日期", "desc": "摘要", "bal": "餘額"},
        "en":    {"tb": "Trial Balance", "code": "Code", "name": "Name", "dr": "Debit", "cr": "Credit",
                  "total": "Total",
                  "gl": "General Ledger", "date": "Date", "desc": "Description", "bal": "Balance"},
    }.get(lang if lang in ("zh_cn", "zh_hk", "en") else "zh_cn")

    tb_rows.append(["", L["total"], m(tb["totalDebit"]), m(tb["totalCredit"])])

    if with_gl:
        extra.append(_gr(L["tb"], minutes,
                     [{"label": L["code"]}, {"label": L["name"]},
                      {"label": L["dr"], "num": True}, {"label": L["cr"], "num": True}],
                     tb_rows, entity=e))

    gl = reports.general_ledger_detail(e["entity_id"], start, end) if with_gl else {"accounts": []}
    for acc in gl.get("accounts", []):
        rows = [[ln["date"], (ln["description"] or "")[:60],
                 m(ln["debit"]) if ln["debit"] else "", m(ln["credit"]) if ln["credit"] else "",
                 m(ln["balance"])] for ln in acc["lines"][:200]]
        if not rows:
            continue
        extra.append(_gr(f"{L['gl']} {acc['accountCode']} {acc['accountName']}", minutes,
                         [{"label": L["date"]}, {"label": L["desc"]}, {"label": L["dr"], "num": True},
                          {"label": L["cr"], "num": True}, {"label": L["bal"], "num": True}],
                         rows, entity=e))

    path = render(full_package(fs, extra), f"financial-statements-{start}-{end}.pdf")
    return send_file(str(path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"financial-statements-{end}.pdf")


@app.get("/reports/equity-changes")
def r_equity():
    e = entity_or_404()
    start = request.args.get("from") or f"{date.today().year}-01-01"
    end = request.args.get("to") or date.today().isoformat()
    return J(reports.equity_changes(e["entity_id"], start, end))


@app.get("/reports/pdf")
def report_pdf():
    """任意管理报表导出 PDF。lang 支持 zh_cn / zh_hk / en。"""
    from core.pdf_reports import generic_report, general_ledger_detail_pdf, render, set_lang
    e = entity_or_404()
    lang = set_lang(request.args.get("lang") or "en", e["entity_id"])
    # 科目名也要跟着语言走，否则英文 PDF 里会出现中文科目
    reports.set_report_lang(lang)
    from core.i18n import label as _L
    def _t(k, **kw):
        v = _L(lang, k)
        return v.format(**kw) if kw else v
    kind = request.args.get("kind") or "trial-balance"
    start = request.args.get("from") or ""
    end = request.args.get("to") or ""
    eid = e["entity_id"]

    def m(v):
        try:
            return f"{float(v):,.2f}"
        except (TypeError, ValueError):
            return "—"

    if kind == "trial-balance":
        d = reports.trial_balance(eid)
        cols = [{"label": "科目"}, {"label": "名称"}, {"label": "借方", "num": True},
                {"label": "贷方", "num": True}, {"label": "余额", "num": True}]
        rows = [[a["accountCode"], a["accountName"], m(a["debit"]), m(a["credit"]),
                 m(a["balance"])] for a in d["accounts"]]
        rows.append(["合计", "平衡" if d["balanced"] else "不平衡",
                     m(d["totalDebit"]), m(d["totalCredit"]), m(d["difference"])])
        html_doc = generic_report(_t("trial_balance"), _t("to_date", date=end or _t("daily")), cols, rows, entity=e)

    elif kind == "pnl":
        d = reports.profit_and_loss(eid, start or None, end or None)
        # 上年对比：?compare=fy（上一财务年度，默认）或 1（上年同期）或 0（不比）
        cmp_mode = str(request.args.get("compare") or "fy")
        prev, prev_from, prev_to = None, None, None
        if cmp_mode != "0" and start and end:
            from datetime import datetime as _dt, timedelta as _td
            if cmp_mode == "1":
                f = (_dt.strptime(start, "%Y-%m-%d") - _td(days=365)).strftime("%Y-%m-%d")
                t = (_dt.strptime(end, "%Y-%m-%d") - _td(days=365)).strftime("%Y-%m-%d")
            else:
                fye = (e.get("fiscal_year_end_mmdd") or "12-31")
                mm, dd = int(fye[:2]), int(fye[3:])
                y = int(end[:4])
                fy_end = _dt(y, mm, dd)
                if fy_end.strftime("%Y-%m-%d") < end:
                    fy_end = _dt(y + 1, mm, dd)
                prev_end = _dt(fy_end.year - 1, mm, dd)
                prev_start = _dt(prev_end.year - 1, mm, dd) + _td(days=1)
                f, t = prev_start.strftime("%Y-%m-%d"), prev_end.strftime("%Y-%m-%d")
            prev = reports.profit_and_loss(eid, f, t)
            prev_from, prev_to = f, t

        if prev is None:
            cols = [{"label": "项目"}, {"label": "科目"}, {"label": "金额", "num": True}]
        else:
            cols = [{"label": "项目"}, {"label": "科目"},
                    {"label": "本期", "num": True},
                    {"label": "上年", "num": True},
                    {"label": "变动", "num": True}]
        rows = []
        prev_by = {}
        if prev is not None:
            for k in ("revenue", "costOfSales", "otherIncome", "otherGains",
                      "operatingExpenses", "financeCosts", "taxExpense"):
                prev_by[k] = {str(i["accountCode"]): float(i["amount"]) for i in prev[k]["items"]}

        def _row(lab, code, cur, old=None):
            if prev is None:
                return [lab, code, m(cur)]
            dlt = (cur or 0) - (old or 0)
            return [lab, code, m(cur), m(old), ("+" if dlt > 0.004 else "") + m(dlt)]
        for lab, key in (("收入", "revenue"), ("销售成本", "costOfSales"),
                         ("其他收入", "otherIncome"), ("其他收益／（亏损）", "otherGains"),
                         ("经营费用", "operatingExpenses"), ("财务费用", "financeCosts"),
                         ("税项", "taxExpense")):
            sec = d[key]
            old_sec = (prev[key] if prev is not None else None)
            rows.append(_row(lab, "", sec["total"], (old_sec["total"] if old_sec else None)))
            for i in sec["items"]:
                code = str(i["accountCode"])
                rows.append(_row(i["accountName"], i["accountCode"], i["amount"],
                                 (prev_by.get(key, {}).get(code) if prev is not None else None)))
        rows.append(_row("毛利", "", d["grossProfit"], (prev["grossProfit"] if prev is not None else None)))
        rows.append(_row("除税前溢利", "", d["profitBeforeTax"], (prev["profitBeforeTax"] if prev is not None else None)))
        rows.append(_row("本期溢利", "", d["netProfit"], (prev["netProfit"] if prev is not None else None)))
        _sub = (_t("period_range", start=start, end=end) if start else _t("to_date", date=end or _t("daily")))
        if prev is not None:
            _sub += "　·　上年 " + prev_from + " ~ " + prev_to
        html_doc = generic_report(_t("statement_of_profit_or_loss"), _sub, cols, rows, entity=e)

    elif kind == "balance-sheet":
        d = reports.balance_sheet(eid, end or None)
        cols = [{"label": "项目"}, {"label": "科目"}, {"label": "金额", "num": True}]
        rows = []
        for lab, sec in (("资产", d["assets"]), ("负债", d["liabilities"]), ("权益", d["equity"])):
            rows.append([lab, "", m(sec["total"])])
            for i in sec["items"]:
                rows.append([i["accountName"], i["accountCode"], m(i["amount"])])
        rows.append(["勾稽差额", "平衡" if d["check"]["balanced"] else "不平衡",
                     m(d["check"]["difference"])])
        html_doc = generic_report(_t("statement_of_financial_position"), _t("as_at", date=end or _t("daily")), cols, rows, entity=e)

    elif kind == "cash-flow":
        d = reports.cash_flow(eid, start or None, end or None)
        cols = [{"label": "项目"}, {"label": "金额", "num": True}]
        rows = [["期初现金及现金等价物", m(d.get("openingCash", 0))],
                ["本期净利／（亏损）", m(d.get("netProfit", 0))]]
        for x in d.get("nonCash") or []:
            rows.append([f"非现金调整：{x.get('account')}", m(x.get("amount", 0))])
        for x in d.get("workingCapital") or []:
            rows.append([f"营运资金变动：{x.get('label')}", m(x.get("amount", 0))])
        rows += [["经营活动带来的现金净额", m(d["operating"])],
                 ["投资活动带来的现金净额", m(d["investing"])],
                 ["融资活动带来的现金净额", m(d["financing"])],
                 ["现金净变动", m(d["netChange"])],
                 ["期末现金余额", m(d["closingCash"])]]
        _cf_sub = (_t("period_range", start=start, end=end) if start and end
                   else _t("to_date", date=end or _t("daily")))
        html_doc = generic_report(_t("cash_flow_report"), _cf_sub,
                                  cols, rows, d.get("note", ""), entity=e)

    elif kind == "account-types":
        d = reports.account_type_summary(eid, start or None, end or None)
        cols = [{"label": "帐户类型"}, {"label": "借项", "num": True}, {"label": "贷项", "num": True}]
        rows = []
        for g in d["groups"]:
            rows.append([g["label"], "", ""])
            for it in g["items"]:
                rows.append([it["type"], m(it["debit"]), m(it["credit"])])
        rows.append(["合计", m(d["debit"]), m(d["credit"])])
        html_doc = generic_report(_t("account_type_summary"),
                                  f"{start or ''} → {end or ''}", cols, rows, entity=e)

    elif kind == "gl-detail":
        acc = request.args.get("account") or None
        d = reports.general_ledger_detail(eid, start or None, end or None, acc)
        html_doc = general_ledger_detail_pdf(d, e, start or None, end or None)

    elif kind == "aging":
        d = reports.aging(eid, request.args.get("side", "receivable"))
        cols = [{"label": "币种"}] + [{"label": b, "num": True} for b in ("0-30", "31-60", "61-90", "90+")] \
             + [{"label": "原币合计", "num": True}, {"label": "折 HKD", "num": True}]
        rows = [[g["currency"], m(g["0-30"]), m(g["31-60"]), m(g["61-90"]),
                 m(g["90+"]), m(g["total"]), m(g["functionalHkd"])] for g in d["byCurrency"]]
        html_doc = generic_report(_t("aging_report"), _t("to_date", date=end or _t("daily")), cols, rows, d.get("note", ""), entity=e)

    elif kind == "bank-balances":
        d = reports.bank_balances(eid)
        cols = [{"label": "账户"}, {"label": "币种"}, {"label": "原币余额", "num": True},
                {"label": "折 HKD", "num": True}]
        rows = []
        for g in d["groups"]:
            for a in g["accounts"]:
                rows.append([a["name"], a["currency"], m(a["current_balance"]),
                             m(a["current_balance_functional"])])
        rows.append(["HKD 折算合计", "HKD", "—", m(d["hkdTotal"])])
        html_doc = generic_report(_t("bank_balances"), _t("to_date", date=end or _t("daily")), cols, rows, d.get("note", ""), entity=e)

    elif kind == "fx":
        d = reports.fx_gain_loss(eid)
        cols = [{"label": "科目"}, {"label": "名称"}, {"label": "来源"}, {"label": "金额", "num": True}]
        rows = [[i["accountCode"], i["accountName"], i["sourceType"], m(i["amount"])]
                for i in d["items"]]
        rows.append(["合计", "", "", m(d["total"])])
        html_doc = generic_report(_t("fx_report"), _t("to_date", date=end or _t("daily")), cols, rows, d.get("note", ""), entity=e)

    elif kind == "gl":
        acc_rows = query(f"""SELECT a.account_code, {reports._name_col()} AS account_name, a.category,
                                   COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
                              FROM accounts a
                              JOIN journal_lines l ON l.account_code=a.account_code
                              JOIN journal_entries e ON e.entry_id=l.entry_id
                                   AND e.status IN ('posted','reversed') AND e.entity_id=a.entity_id
                             WHERE a.entity_id=%s
                             GROUP BY a.account_code, {reports._name_col()}, a.category
                             HAVING dr<>0 OR cr<>0 ORDER BY a.account_code""", (eid,))
        cols = [{"label": "科目"}, {"label": "名称"}, {"label": "类别"},
                {"label": "借方", "num": True}, {"label": "贷方", "num": True}, {"label": "余额", "num": True}]
        rows = [[r["account_code"], r["account_name"], r["category"], m(r["dr"]),
                 m(r["cr"]), m(dec(r["dr"]) - dec(r["cr"]))] for r in acc_rows]
        html_doc = generic_report(_t("general_ledger"), _t("to_date", date=end or _t("daily")), cols, rows, entity=e)

    elif kind == "daybook":
        rows_db = query("""SELECT entry_no, entry_date, source_type, description, status, total_debit
                             FROM journal_entries WHERE entity_id=%s
                              AND (%s='' OR entry_date >= %s) AND (%s='' OR entry_date <= %s)
                            ORDER BY entry_date DESC, entry_id DESC LIMIT 500""",
                        (eid, start, start, end, end))
        cols = [{"label": "日期"}, {"label": "分录号"}, {"label": "来源"}, {"label": "摘要"},
                {"label": "状态"}, {"label": "借方合计", "num": True}]
        rows = [[r["entry_date"].isoformat(), r["entry_no"], r["source_type"],
                 (r["description"] or "")[:60], r["status"], m(r["total_debit"])] for r in rows_db]
        html_doc = generic_report(_t("daybook"), (_t("period_range", start=start, end=end) if start else _t("to_date", date=end or _t("daily"))), cols, rows, entity=e)

    elif kind == "sales-detail":
        rows_db = query("""SELECT supplier_name, currency, COUNT(*) n,
                                  SUM(gross_original) gross, SUM(amount_functional) func
                             FROM invoices WHERE entity_id=%s AND status='posted'
                            GROUP BY supplier_name, currency ORDER BY func DESC""", (eid,))
        cols = [{"label": "客户"}, {"label": "币种"}, {"label": "张数", "num": True},
                {"label": "价税合计", "num": True}, {"label": "折 HKD", "num": True}]
        rows = [[r["supplier_name"], r["currency"], str(r["n"]), m(r["gross"]), m(r["func"])]
                for r in rows_db]
        html_doc = generic_report(_t("sales_detail"), _t("to_date", date=end or _t("daily")), cols, rows,
                                  "按客户与币种分列；HKD 合计仅取折算列", entity=e)

    elif kind == "purchase-detail":
        rows_db = query("""SELECT vendor_name, currency, COUNT(*) n,
                                  SUM(gross_original) gross, SUM(amount_functional) func
                             FROM bills WHERE entity_id=%s AND status='posted'
                            GROUP BY vendor_name, currency ORDER BY func DESC""", (eid,))
        cols = [{"label": "供应商"}, {"label": "币种"}, {"label": "张数", "num": True},
                {"label": "价税合计", "num": True}, {"label": "折 HKD", "num": True}]
        rows = [[r["vendor_name"], r["currency"], str(r["n"]), m(r["gross"]), m(r["func"])]
                for r in rows_db]
        html_doc = generic_report(_t("purchase_detail"), _t("to_date", date=end or _t("daily")), cols, rows, entity=e)

    elif kind == "ratios":
        d = reports.financial_ratios(eid)
        cols = [{"label": "比率"}, {"label": "数值", "num": True},
                {"label": "计算式"}, {"label": "单位"}]
        rows = []
        for i in d["items"]:
            v = "—" if i["value"] is None else (
                f"{i['value']*100:.2f}" if i["unit"] == "%" else f"{i['value']:.4g}")
            rows.append([i["name"], v, i["formula"], i["unit"]])
        html_doc = generic_report(_t("ratios"), _t("to_date", date=end or _t("daily")), cols, rows, d.get("note", ""), entity=e)

    elif kind == "customer-balances":
        d = reports.customer_balances(eid)
        cols = [{"label": "客户"}, {"label": "币种"}, {"label": "发票数", "num": True},
                {"label": "已开票", "num": True}, {"label": "已收款", "num": True},
                {"label": "未收", "num": True}, {"label": "折 HKD", "num": True}]
        rows = [[r["party"], r["currency"], str(r["invoices"]), m(r["invoiced"]),
                 m(r["settled"]), m(r["outstanding"]), m(r["outstandingFunctional"])]
                for r in d["rows"]]
        rows.append(["合计", "HKD", "", "", "", "", m(d["totalFunctional"])])
        html_doc = generic_report(_t("customer_balances"), _t("to_date", date=end or _t("daily")), cols, rows, d.get("note", ""), entity=e)

    elif kind == "vendor-balances":
        d = reports.vendor_balances(eid)
        cols = [{"label": "供应商"}, {"label": "币种"}, {"label": "账单数", "num": True},
                {"label": "已收票", "num": True}, {"label": "已付款", "num": True},
                {"label": "未付", "num": True}, {"label": "折 HKD", "num": True}]
        rows = [[r["party"], r["currency"], str(r["bills"]), m(r["billed"]),
                 m(r["settled"]), m(r["outstanding"]), m(r["outstandingFunctional"])]
                for r in d["rows"]]
        rows.append(["合计", "HKD", "", "", "", "", m(d["totalFunctional"])])
        html_doc = generic_report(_t("vendor_balances"), _t("to_date", date=end or _t("daily")), cols, rows, d.get("note", ""), entity=e)

    elif kind == "profit-tax":
        year = str(request.args.get("year") or "")
        d = profit_tax_data(e, year)
        cols = [{"label": _t("item")}, {"label": _t("amount_hkd"), "num": True}]
        gross = d["grossProfit"]
        st = d["twoTierStatus"]
        st_text = {"nominated": _t("two_tier_nominated"),
                   "not_nominated": _t("two_tier_not_nominated"),
                   "undetermined": _t("two_tier_undetermined")}.get(st, st)
        rows = [
            [_t("revenue"), m(d["revenue"])],
            ["(" + _t("cost_of_sales") + ")", m(d["costOfSales"])],
            [_t("gross_profit"), m(gross)],
            [_t("other_income"), m(d["otherIncome"])],
            [_t("other_gains"), m(d["otherGains"])],
            ["(" + _t("operating_expenses") + ")", m(d["operatingExpenses"])],
            ["(" + _t("finance_costs") + ")", m(d["financeCosts"])],
            [_t("assessable_profits"), m(d["accountingProfit"])],
            [_t("two_tier_status"), st_text],
            [_t("applicable_rate"), d["rate"] or "—"],
            [_t("tax_payable"), "—" if d["taxPayable"] is None else m(d["taxPayable"])],
        ]
        html_doc = generic_report(_t("profits_tax"),
                                  f"{d['yearOfAssessment']} · {d['start']} ~ {d['end']}",
                                  cols, rows, _t("basis_posted_entries"), entity=e)

    else:
        raise ValueError(f"不支持的报表类型：{kind}")

    path = render(html_doc, f"report-{kind}-{end or date.today().isoformat()}.pdf")
    return send_file(str(path), mimetype="application/pdf", as_attachment=False,
                     download_name=f"{kind}.pdf")


@app.post("/bills/<int:bill_id>/post")
def do_post_bill(bill_id):
    require_writer()
    p = request.get_json(force=True) or {}
    return J(post_bill(bill_id, p.get("actor", "accountant")))


@app.get("/bills/<int:bill_id>/files")
def bill_files(bill_id):
    rows = query("""SELECT file_id, file_name, file_type, file_size, sha256_hash,
                           uploaded_by, created_at AS uploaded_at FROM doc_files
                      WHERE doc_type='bill' AND doc_id=%s ORDER BY file_id""", (bill_id,))
    return J({"files": [dict(r, uploaded_at=r["uploaded_at"].isoformat(sep=" ", timespec="milliseconds"))
                        for r in rows]})


@app.post("/bill-files")
def bill_file_register():
    """登记账单附件。统一落到 doc_files（doc_type=bill）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    bid = int(p.get("billId") or 0)
    name = str(p.get("fileName") or "").strip()
    path = str(p.get("storagePath") or "").strip()
    sha = str(p.get("sha256") or "").strip().lower()
    size = int(p.get("fileSize") or 0)
    if not bid or not name or not path:
        raise ValueError("缺少账单 ID / 文件名 / 存储路径")
    if len(sha) != 64:
        raise ValueError("SHA-256 必须是 64 位十六进制")
    if size <= 0:
        raise ValueError("文件大小必须大于 0")
    if not query_one("SELECT 1 AS x FROM bills WHERE bill_id=%s AND entity_id=%s",
                     (bid, e["entity_id"])):
        raise ValueError("账单不存在")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                VALUES (%s,'bill',%s,%s,%s,%s,%s,%s,%s)""",
                        (e["entity_id"], bid, name[:255],
                         str(p.get("fileType") or "other")[:64], size, sha,
                         path[:500], p.get("actor", "system")))
            fid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "bill_file.upload", "object_type": "doc_files",
                            "object_id": str(fid),
                            "detail": {"billId": bid, "fileName": name,
                                       "fileSize": size, "sha256": sha}})
    return J({"fileId": fid, "sha256": sha, "fileSize": size})

@app.post("/order-files")
def order_file_register():
    """登记订单附件（合同扫描件）。统一落到 doc_files（doc_type=order）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    oid = int(p.get("orderId") or 0)
    name = str(p.get("fileName") or "").strip()
    path = str(p.get("storagePath") or "").strip()
    sha = str(p.get("sha256") or "").strip().lower()
    size = int(p.get("fileSize") or 0)
    if not oid or not name or not path:
        raise ValueError("缺少订单 ID / 文件名 / 存储路径")
    if len(sha) != 64:
        raise ValueError("SHA-256 必须是 64 位十六进制")
    if size <= 0:
        raise ValueError("文件大小必须大于 0")
    if not query_one("SELECT 1 AS x FROM orders WHERE order_id=%s AND entity_id=%s",
                     (oid, e["entity_id"])):
        raise ValueError("订单不存在")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                VALUES (%s,'order',%s,%s,%s,%s,%s,%s,%s)""",
                        (e["entity_id"], oid, name[:255],
                         str(p.get("fileType") or "other")[:64], size, sha,
                         path[:500], p.get("actor", "system")))
            fid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "order_file.upload", "object_type": "doc_files",
                            "object_id": str(fid),
                            "detail": {"orderId": oid, "fileName": name,
                                       "fileSize": size, "sha256": sha}})
    return J({"fileId": fid, "sha256": sha, "fileSize": size})

@app.get("/company")
def company_profile():
    """公司档案 + 主收款账户，供发票抬头与报表落款使用。"""
    e = entity_or_404()
    acct = query_one("""SELECT account_holder, bank_name, bank_code, swift_code, bank_address,
                               branch, account_number, account_number_masked, currency
                          FROM bank_accounts
                         WHERE entity_id=%s AND status='active' AND is_primary_receiving=1
                         LIMIT 1""", (e["entity_id"],))
    if not acct:
        acct = query_one("""SELECT account_holder, bank_name, bank_code, swift_code, bank_address,
                                   branch, account_number, account_number_masked, currency
                              FROM bank_accounts
                             WHERE entity_id=%s AND status='active' AND currency=%s
                             ORDER BY account_id LIMIT 1""",
                            (e["entity_id"], e["functional_currency"]))
    return J({
        "name": e["entity_name"], "legalName": e.get("legal_name"),
        "legalNameZh": e.get("legal_name_zh"),
        "brNumber": e.get("br_number"),
        "addressLine1": e.get("address_line1"), "addressLine2": e.get("address_line2"),
        "district": e.get("district"), "region": e.get("region"),
        "phone": e.get("phone"), "email": e.get("email"), "website": e.get("website"),
        "functionalCurrency": e["functional_currency"],
        # 财务年度与报告框架：决定报表「本年度」口径与呈现要求
        "fiscalYearEnd": e.get("fiscal_year_end_mmdd") or "12-31",
        "reportingFramework": e.get("reporting_framework") or "full_hkfrs",
        "bank": dict(acct) if acct else None,
    })


@app.post("/company")
def company_update():
    """更新公司档案与主收款账户。属主数据变更，仅管理员可操作并留痕。"""
    if not is_admin():
        raise PermissionError("仅管理员可修改公司档案")
    e = entity_or_404()
    p = request.get_json(force=True) or {}

    def g(k, cur):
        v = p.get(k)
        return cur if v is None else str(v).strip()

    with transaction() as conn:
        with conn.cursor() as cur:
            # 财务年度（年结日）：格式 MM-DD，例如 04-30；空值表示不改
            fy_end = e.get("fiscal_year_end_mmdd") or "12-31"
            raw_fy = str(p.get("fiscalYearEnd") or "").strip()
            if raw_fy:
                import re as _re
                if not _re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", raw_fy):
                    raise ValueError("年结日格式应为 MM-DD，例如 04-30")
                # 必须是该月最后一天（财务年度按整月划）；2 月 28 / 29 都接受
                _m, _d = int(raw_fy[:2]), int(raw_fy[3:])
                import calendar as _cal
                _last_nonleap = _cal.monthrange(2026, _m)[1]   # 非闰年该月天数
                _last_leap = _cal.monthrange(2024, _m)[1]      # 闰年该月天数
                if _d not in (_last_nonleap, _last_leap):
                    raise ValueError("年结日必须是该月最后一天，例如 04-30")
                fy_end = raw_fy
            # 报告框架：full_hkfrs / sme_hkfrs
            framework = e.get("reporting_framework") or "full_hkfrs"
            raw_fw = str(p.get("reportingFramework") or "").strip()
            if raw_fw in ("full_hkfrs", "sme_hkfrs"):
                framework = raw_fw

            cur.execute("""UPDATE entities SET
                entity_name=%s, legal_name=%s, legal_name_zh=%s, br_number=%s,
                address_line1=%s, address_line2=%s, district=%s, region=%s,
                phone=%s, email=%s, website=%s,
                fiscal_year_end_mmdd=%s, reporting_framework=%s, updated_at=NOW(3)
                WHERE entity_id=%s""",
                        (g("name", e["entity_name"]), g("legalName", e.get("legal_name")),
                         _to_hk(g("legalNameZh", e.get("legal_name_zh"))),
                         g("brNumber", e.get("br_number")),
                         g("addressLine1", e.get("address_line1")),
                         g("addressLine2", e.get("address_line2")),
                         g("district", e.get("district")), g("region", e.get("region")),
                         g("phone", e.get("phone")), g("email", e.get("email")),
                         g("website", e.get("website")),
                         fy_end, framework, e["entity_id"]))

            acct = query_one("""SELECT account_id FROM bank_accounts
                                 WHERE entity_id=%s AND is_primary_receiving=1 LIMIT 1""",
                             (e["entity_id"],))
            if acct and p.get("bank"):
                b = p["bank"]
                cur.execute("""UPDATE bank_accounts SET
                    account_holder=%s, bank_name=%s, bank_code=%s, swift_code=%s,
                    bank_address=%s, account_number=%s, account_number_masked=%s, updated_at=NOW(3)
                    WHERE account_id=%s""",
                            (str(b.get("accountHolder") or "").strip() or None,
                             str(b.get("bankName") or "").strip() or None,
                             str(b.get("bankCode") or "").strip() or None,
                             str(b.get("swiftCode") or "").strip() or None,
                             str(b.get("bankAddress") or "").strip() or None,
                             str(b.get("accountNumber") or "").strip() or None,
                             ("****" + str(b.get("accountNumber") or "").strip()[-3:])
                             if b.get("accountNumber") else None,
                             acct["account_id"]))

            append_audit(conn, {"entity_id": e["entity_id"],
                                "actor": request.headers.get("X-Ledu-User", "admin"),
                                "actor_role": "admin", "action": "company.update",
                                "object_type": "entities", "object_id": str(e["entity_id"]),
                                "detail": {"name": p.get("name"),
                                           "bankUpdated": bool(p.get("bank"))}})
    return J({"ok": True})


@app.get("/reports/ratios")
def r_ratios():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    return J(reports.financial_ratios(entity_or_404()["entity_id"]))


@app.get("/reports/customer-balances")
def r_cust_bal():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    return J(reports.customer_balances(entity_or_404()["entity_id"]))


@app.get("/reports/vendor-balances")
def r_vend_bal():
    reports.set_report_lang(str(request.args.get("lang") or "en"))
    return J(reports.vendor_balances(entity_or_404()["entity_id"]))


@app.post("/accounts/<code>/active")
def account_set_active(code):
    """启用／停用科目。已发生分录的科目不允许停用，避免历史账无法追溯。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    active = bool(p.get("active"))
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT account_code, account_name, is_active FROM accounts
                            WHERE entity_id=%s AND account_code=%s""",
                        (e["entity_id"], code))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"科目 {code} 不存在")
            if not active:
                cur.execute("""SELECT COUNT(*) AS n FROM journal_lines l
                                 JOIN journal_entries je ON je.entry_id = l.entry_id
                                WHERE l.account_code=%s AND je.entity_id=%s""",
                            (code, e["entity_id"]))
                n = cur.fetchone()["n"]
                if n > 0:
                    raise ValueError(f"科目 {code} 已有 {n} 条分录，不能停用")
                cur.execute("""SELECT COUNT(*) AS n FROM accounts
                                WHERE entity_id=%s AND parent_account_code=%s AND is_active=1""",
                            (e["entity_id"], code))
                child = cur.fetchone()["n"]
                if child > 0:
                    raise ValueError(f"科目 {code} 下还有 {child} 个启用中的子科目，请先停用子科目")
            cur.execute("""UPDATE accounts SET is_active=%s
                            WHERE entity_id=%s AND account_code=%s""",
                        (1 if active else 0, e["entity_id"], code))
            append_audit(conn, {"entity_id": e["entity_id"],
                                "actor": p.get("actor", "system"),
                                "action": "account.set_active", "object_type": "accounts",
                                "object_id": code,
                                "detail": {"name": row["account_name"], "active": active}})
    return J({"accountCode": code, "active": active})


@app.get("/accounts/names")
def accounts_names():
    """科目名的三语映射：前端 acc_name() 按界面语言取名字用。

    之前前端一直在调这个地址，但后端没有这个路由，拿到的一直是空，
    于是英文界面里科目名全成了中文。
    """
    e = entity_or_404()
    rows = query("""SELECT account_code, account_name, name_zh_cn, name_zh_hk, name_en
                      FROM accounts WHERE entity_id=%s""", (e["entity_id"],))
    names = {}
    for r in rows:
        names[r["account_code"]] = {
            "zh_cn": r["name_zh_cn"] or r["account_name"],
            "zh_hk": r["name_zh_hk"] or r["account_name"],
            "en": r["name_en"] or r["account_name"],
        }
    return J({"names": names})


@app.get("/accounts/tree")
def accounts_tree():
    """科目树：带层级、是否启用、是否已有分录。"""
    e = entity_or_404()
    rows = query("""SELECT a.account_code, a.account_name, a.category, a.fs_line_item,
                           a.normal_balance, a.parent_account_code, a.is_active,
                           (SELECT COUNT(*) FROM journal_lines l
                              JOIN journal_entries je ON je.entry_id = l.entry_id
                             WHERE l.account_code = a.account_code
                               AND je.entity_id = a.entity_id) AS txn_count
                      FROM accounts a WHERE a.entity_id=%s ORDER BY a.account_code""",
                 (e["entity_id"],))
    return J({"accounts": [dict(r, txn_count=int(r["txn_count"]),
                                is_active=bool(r["is_active"])) for r in rows]})


@app.get("/currencies")
def currencies():
    """可用币种：基准货币 + 银行账户币种 + 汇率出现的币种。

    清单以数据为准而非写死；新增一个银行账户，全站表单自动出现该币种。
    """
    e = entity_or_404()
    base = e["functional_currency"]
    got = {base}
    for r in query("""SELECT DISTINCT currency FROM bank_accounts
                       WHERE entity_id=%s AND status='active'""", (e["entity_id"],)):
        if r.get("currency"):
            got.add(r["currency"])
    for r in query("SELECT DISTINCT to_ccy AS c FROM fx_rates"):
        if r["c"]:
            got.add(r["c"])
    for r in query("SELECT DISTINCT from_ccy AS c FROM fx_rates"):
        if r["c"]:
            got.add(r["c"])
    return J({"currencies": [base] + sorted(got - {base}), "base": base})


@app.get("/numbering/peek")
def numbering_peek():
    """预览下一个文件编号（不占用序号），供表单显示。"""
    from core.numbering import peek_no
    e = entity_or_404()
    d = request.args.get("date") or date.today().isoformat()
    kind = request.args.get("kind") or "invoice"
    with transaction() as conn:
        return J({"number": peek_no(conn, e["entity_id"], d, kind), "date": d, "kind": kind,
                  "format": "公司缩写 + 功能缩写 + YYYYMMDD + 当日第几份"})


@app.post("/bank/parse-statement")
def bank_parse_statement():
    """解析上传的银行月结单（CSV / XLSX / XLS / PDF，含扫描件 OCR）。

    只做「文件 → 交易行」的解析与展示，不落库；
    落库仍走 /bank/import 的算术校验，避免绕过勾稽。
    """
    require_writer()
    e = entity_or_404()
    f = request.files.get("file")
    if not f or not f.filename:
        raise ValueError("未收到文件")
    data = f.read()
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("文件超过 20MB")
    from core.statement_parser import parse_statement
    try:
        parsed = parse_statement(data, f.filename)
    except ValueError as ex:
        raise ValueError(str(ex))

    rows = parsed["rows"]
    # 归一成导入用的 CSV（date,amount,ref,counterparty），与现有导入口径一致
    buf = io.StringIO()
    buf.write("date,amount,ref,counterparty\n")
    for r in rows:
        buf.write(f'{r["date"]},{r["amount"]:.2f},"{r["ref"]}","{r["description"].replace(chr(34), chr(39))}"\n')

    debits = sum(r["debit"] for r in rows)
    credits = sum(r["credit"] for r in rows)
    meta = parsed.get("meta") or {}

    # 保留原始月结单，供「已导入月结单」列表下载；按 SHA-256 命名天然去重。
    import hashlib as _hashlib
    sha = _hashlib.sha256(data).hexdigest()
    ext = Path(f.filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls", ".pdf"):
        ext = ".bin"
    store = STORAGE_DIR / "bank-statements" / str(e["entity_id"])
    store.mkdir(parents=True, exist_ok=True)
    saved = store / (sha + ext)
    if not saved.is_file():
        saved.write_bytes(data)
        try:
            _os.chmod(saved, 0o600)
        except OSError:
            pass

    return J({
        "fileName": f.filename,
        "sha256": sha,
        "fileFormat": ext.lstrip("."),
        "source": parsed["source"],
        "rowCount": len(rows),
        "rows": rows,
        "truncated": len(rows) > 500,
        "sumDebits": round(debits, 2),
        "sumCredits": round(credits, 2),
        "warnings": parsed.get("warnings") or [],
        "meta": {
            "openingBalance": meta.get("openingBalance"),
            "closingBalance": meta.get("closingBalance"),
            "totalDebits": meta.get("totalDebits") or round(debits, 2),
            "totalCredits": meta.get("totalCredits") or round(credits, 2),
        },
        "csv": buf.getvalue(),
    })


# ---------------------------------------------------------------- 邮件
@app.get("/email/status")
def email_status():
    """SMTP 配置状态。绝不返回密码。"""
    from core import mailer
    e = entity_or_404()
    recent = query("""SELECT email_id, doc_type, doc_no, to_addrs, subject, status, sent_at
                        FROM email_log WHERE entity_id=%s ORDER BY email_id DESC LIMIT 5""",
                   (e["entity_id"],))
    return J({"smtp": mailer.status(),
              "recent": [{**r, "sent_at": r["sent_at"].isoformat()} for r in recent]})


@app.post("/email/test")
def email_test():
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    to = (p.get("to") or "").strip()
    if "@" not in to:
        raise ValueError("请填写有效的收件地址")
    from core.mailer import send
    actor = p.get("actor", "system")
    try:
        r = send(to=to, subject="[LtBooks] SMTP 测试",
                 body_text="这是一封测试邮件，用于验证 LtBooks 外发通道。\n\n"
                           f"© {date.today().year} LEDU TECH CO., LIMITED · Released under the MIT License",
                 body_html="<p>这是一封测试邮件，用于验证 <b>LtBooks</b> 的外发通道。</p>"
                           '<hr style="border:none;border-top:1px solid #E2E8F0;margin:18px 0 8px">'
                           f'<p style="font-size:12px;color:#94A3B8;margin:0">'
                           f'© {date.today().year} LEDU TECH CO., LIMITED · Released under the MIT License</p>')
    except Exception as ex:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO email_log (entity_id,doc_type,to_addrs,subject,status,error,sent_by)
                               VALUES (%s,'test',%s,%s,'failed',%s,%s)""",
                            (e["entity_id"], to, "SMTP 测试", str(ex)[:900], actor))
            append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                                "action": "email.test_failed", "object_type": "email",
                                "object_id": to, "detail": {"error": str(ex)[:200]}})
        raise
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO email_log (entity_id,doc_type,to_addrs,subject,message_id,status,sent_by)
                           VALUES (%s,'test',%s,%s,%s,'sent',%s)""",
                        (e["entity_id"], to, "SMTP 测试", r["messageId"], actor))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "email.test_sent", "object_type": "email",
                            "object_id": to, "detail": {"messageId": r["messageId"]}})
    return J({"sent": True, **r})


def _email_doc_type(value) -> tuple:
    requested = str(value or "invoice").strip().lower()
    canonical = {"sales_order": "order", "purchase_order": "order"}.get(requested, requested)
    if canonical not in ("invoice", "bill", "quote", "credit_note", "order"):
        raise ValueError("不支持的单据类型")
    return requested, canonical


@app.post("/email/send-document")
def email_send_document():
    """把往来单据以 PDF 附件发给对方。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    requested_type, doc_type = _email_doc_type(p.get("docType"))
    doc_id = int(p.get("docId") or 0)
    to = (p.get("to") or "").strip()
    cc = (p.get("cc") or "").strip() or None
    subject = (p.get("subject") or "").strip()
    message = (p.get("message") or "").strip()
    actor = p.get("actor", "system")
    _lang = str(p.get("lang") or request.args.get("lang") or "zh_cn")
    if _lang not in ("zh_cn", "zh_hk", "en"):
        _lang = "zh_cn"
    _S = {
        "zh_cn": {"invoice": "发票", "bill": "账单", "quote": "报价单", "credit_note": "贷记单",
                  "sales_order": "销售订单", "purchase_order": "采购订单"},
        "zh_hk": {"invoice": "發票", "bill": "賬單", "quote": "報價單", "credit_note": "貸記單",
                  "sales_order": "銷售訂單", "purchase_order": "採購訂單"},
        "en":    {"invoice": "Invoice", "bill": "Bill", "quote": "Quotation", "credit_note": "Credit Note",
                  "sales_order": "Sales Order", "purchase_order": "Purchase Order"},
    }[_lang]

    if "@" not in to:
        raise ValueError("请填写有效的收件地址")

    from core.mailer import send

    pdf_response = None
    pdf_path = None
    if doc_type == "invoice":
        doc = query_one("SELECT * FROM invoices WHERE invoice_id=%s AND entity_id=%s",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("发票不存在")
        doc_no = doc["invoice_no"]
        mail_kind = "invoice"
        display_date = doc.get("due_date")
        pdf_path = invoice_pdf_path(doc_id, _lang)
    elif doc_type == "bill":
        doc = query_one("SELECT * FROM bills WHERE bill_id=%s AND entity_id=%s",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("账单不存在")
        doc_no = doc["bill_no"]
        mail_kind = "bill"
        display_date = doc.get("due_date")
        pdf_path = bill_pdf_path(doc_id, _lang)
    elif doc_type == "quote":
        doc = query_one("SELECT * FROM quotes WHERE quote_id=%s AND entity_id=%s",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("报价单不存在")
        doc_no = doc["quote_no"]
        mail_kind = "quote"
        display_date = doc.get("valid_until")
        pdf_response = _quote_pdf_response(doc, _lang)
    elif doc_type == "credit_note":
        doc = query_one("SELECT * FROM credit_notes WHERE credit_id=%s AND entity_id=%s",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("贷记单不存在")
        doc_no = doc["credit_no"]
        mail_kind = "credit_note"
        display_date = doc.get("credit_date")
        pdf_response = _credit_note_pdf_response(doc, _lang)
    else:
        direction = {"sales_order": "sales", "purchase_order": "purchase"}.get(requested_type)
        if direction:
            doc = query_one("""SELECT * FROM orders
                                WHERE order_id=%s AND entity_id=%s AND direction=%s""",
                            (doc_id, e["entity_id"], direction))
        else:
            doc = query_one("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s",
                            (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("订单不存在")
        doc_no = doc["order_no"]
        mail_kind = "sales_order" if doc["direction"] == "sales" else "purchase_order"
        display_date = doc.get("expected_date")
        pdf_response = _order_pdf_response(doc, _lang)

    if pdf_response is not None:
        try:
            pdf_response.direct_passthrough = False
            pdf_bytes = pdf_response.get_data()
        finally:
            pdf_response.close()
    else:
        pdf_bytes = Path(pdf_path).read_bytes()

    subject = subject or f"{_S[mail_kind]} {doc_no} — {e['entity_name']}"
    amount = dec(doc["gross_original"])
    if doc_type in ("invoice", "bill"):
        amount -= dec(doc.get("settled_original") or 0)
    date_label = {
        "zh_cn": {"quote": "有效期至", "credit_note": "贷记日期", "order": "预计日期"}.get(doc_type, "到期日"),
        "zh_hk": {"quote": "有效期至", "credit_note": "貸記日期", "order": "預計日期"}.get(doc_type, "到期日"),
        "en": {"quote": "Valid until", "credit_note": "Credit note date", "order": "Expected date"}.get(doc_type, "Due date"),
    }[_lang]
    year = date.today().year
    copyright_txt = f"© {year} LEDU TECH CO., LIMITED · Released under the MIT License"
    body_text = message or (
        {"zh_cn": (f"您好，\n\n随函附上{_S[mail_kind]} {doc_no}。\n"
                   f"金额：{doc['currency']} {amount:,.2f}\n"
                   f"{date_label}：{display_date or '—'}\n\n"),
         "zh_hk": (f"您好，\n\n隨函附上{_S[mail_kind]} {doc_no}。\n"
                   f"金額：{doc['currency']} {amount:,.2f}\n"
                   f"{date_label}：{display_date or '—'}\n\n"),
         "en":    (f"Dear Sir/Madam,\n\nPlease find attached {_S[mail_kind]} {doc_no}.\n"
                   f"Amount: {doc['currency']} {amount:,.2f}\n"
                   f"{date_label}: {display_date or '—'}\n\n")}[_lang]
        + f"{e['entity_name']}\n\n"
        f"——\n{copyright_txt}\n")
    _body_head = {
        "zh_cn": ("<p>您好，</p>",
                  f"<p>随函附上{_S[mail_kind]} <b>{doc_no}</b>。</p>",
                  "<p>金额：<b>{cur} {amt}</b><br>{date_label}：{due}</p>"),
        "zh_hk": ("<p>您好，</p>",
                  f"<p>隨函附上{_S[mail_kind]} <b>{doc_no}</b>。</p>",
                  "<p>金額：<b>{cur} {amt}</b><br>{date_label}：{due}</p>"),
        "en":    ("<p>Dear Sir/Madam,</p>",
                  f"<p>Please find attached {_S[mail_kind]} <b>{doc_no}</b>.</p>",
                  "<p>Amount: <b>{cur} {amt}</b><br>{date_label}: {due}</p>"),
    }[_lang]
    body_html = (_body_head[0] + _body_head[1]
                 + _body_head[2].format(cur=doc['currency'], amt=f"{amount:,.2f}",
                                        date_label=date_label, due=display_date or '—')
                 + (f"<p>{message}</p>" if message else "")
                 + f"<p>{e['entity_name']}</p>"
                 + '<hr style="border:none;border-top:1px solid #E2E8F0;margin:18px 0 8px">'
                 + f'<p style="font-size:12px;color:#94A3B8;margin:0">{copyright_txt}</p>')

    try:
        r = send(to=to, cc=cc, subject=subject, body_text=body_text, body_html=body_html,
                 attachments=[(pdf_bytes, f"{doc_no}.pdf")])
    except Exception as ex:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO email_log
                               (entity_id,doc_type,doc_id,doc_no,to_addrs,cc_addrs,subject,status,error,sent_by)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,'failed',%s,%s)""",
                            (e["entity_id"], mail_kind, doc_id, doc_no, to, cc, subject,
                             str(ex)[:900], actor))
            append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                                "action": "email.document_failed", "object_type": mail_kind,
                                "object_id": str(doc_id),
                                "detail": {"to": to, "error": str(ex)[:200]}})
        raise

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO email_log
                           (entity_id,doc_type,doc_id,doc_no,to_addrs,cc_addrs,subject,
                            attachments,message_id,status,sent_by)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'sent',%s)""",
                        (e["entity_id"], mail_kind, doc_id, doc_no, to, cc, subject,
                         ",".join(r["attachments"]), r["messageId"], actor))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "email.document_sent", "object_type": mail_kind,
                            "object_id": str(doc_id),
                            "detail": {"docNo": doc_no, "to": to, "cc": cc,
                                       "messageId": r["messageId"]}})
    return J({"sent": True, "docNo": doc_no, **r})


@app.get("/email/log")
def email_log_list():
    e = entity_or_404()
    limit = int(request.args.get("limit", 200))
    offset = max(0, int(request.args.get("offset", 0)))
    if limit <= 0:
        limit = 2000
    limit = min(limit, 2000)
    total = int(query_one("SELECT COUNT(*) n FROM email_log WHERE entity_id=%s",
                          (e["entity_id"],))["n"])
    rows = query("""SELECT email_id, doc_type, doc_id, doc_no, to_addrs, cc_addrs, subject,
                           attachments, status, error, sent_by, sent_at
                      FROM email_log WHERE entity_id=%s ORDER BY email_id DESC
                      LIMIT %s OFFSET %s""", (e["entity_id"], limit, offset))
    return J({"log": [{**r, "sent_at": r["sent_at"].isoformat()} for r in rows],
              "total": total, "limit": limit, "offset": offset})



@app.get("/email/doc-info")
def email_doc_info():
    """发信前取单据信息与建议收件人（从客户/供应商档案解析邮箱）。"""
    e = entity_or_404()
    requested_type, doc_type = _email_doc_type(request.args.get("docType"))
    doc_id = int(request.args.get("docId") or 0)
    _lang = request.args.get("lang") or "zh_cn"
    if _lang not in ("zh_cn", "zh_hk", "en"):
        _lang = "zh_cn"

    if doc_type == "invoice":
        doc = query_one("""SELECT invoice_id, invoice_no, supplier_name, currency,
                                  gross_original, settled_original, due_date, status
                             FROM invoices WHERE invoice_id=%s AND entity_id=%s""",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("发票不存在")
        mail_kind = "invoice"
        doc_no = doc["invoice_no"]
        party = doc["supplier_name"]
        party_type = "customer"
        display_date = doc.get("due_date")
        date_kind = "due"
        amount_kind = "due"
        pdf_path = f"/invoices/{doc_id}/pdf"
    elif doc_type == "bill":
        doc = query_one("""SELECT bill_id, bill_no, vendor_name, currency,
                                  gross_original, settled_original, due_date, status
                             FROM bills WHERE bill_id=%s AND entity_id=%s""",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("账单不存在")
        mail_kind = "bill"
        doc_no = doc["bill_no"]
        party = doc["vendor_name"]
        party_type = "vendor"
        display_date = doc.get("due_date")
        date_kind = "due"
        amount_kind = "due"
        pdf_path = f"/bills/{doc_id}/pdf"
    elif doc_type == "quote":
        doc = query_one("""SELECT quote_id, quote_no, customer_name, currency,
                                  gross_original, valid_until, status
                             FROM quotes WHERE quote_id=%s AND entity_id=%s""",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("报价单不存在")
        mail_kind = "quote"
        doc_no = doc["quote_no"]
        party = doc["customer_name"]
        party_type = "customer"
        display_date = doc.get("valid_until")
        date_kind = "valid"
        amount_kind = "total"
        pdf_path = f"/quotes/{doc_id}/pdf"
    elif doc_type == "credit_note":
        doc = query_one("""SELECT credit_id, credit_no, credit_type, party_name, currency,
                                  gross_original, credit_date, status
                             FROM credit_notes WHERE credit_id=%s AND entity_id=%s""",
                        (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("贷记单不存在")
        mail_kind = "credit_note"
        doc_no = doc["credit_no"]
        party = doc["party_name"]
        party_type = doc["credit_type"]
        display_date = doc.get("credit_date")
        date_kind = "credit"
        amount_kind = "total"
        pdf_path = f"/credit-notes/{doc_id}/pdf"
    else:
        direction = {"sales_order": "sales", "purchase_order": "purchase"}.get(requested_type)
        if direction:
            doc = query_one("""SELECT order_id, direction, order_no, party_name, currency,
                                      gross_original, expected_date, status
                                 FROM orders
                                WHERE order_id=%s AND entity_id=%s AND direction=%s""",
                            (doc_id, e["entity_id"], direction))
        else:
            doc = query_one("""SELECT order_id, direction, order_no, party_name, currency,
                                      gross_original, expected_date, status
                                 FROM orders WHERE order_id=%s AND entity_id=%s""",
                            (doc_id, e["entity_id"]))
        if not doc:
            raise ValueError("订单不存在")
        mail_kind = "sales_order" if doc["direction"] == "sales" else "purchase_order"
        doc_no = doc["order_no"]
        party = doc["party_name"]
        party_type = "customer" if doc["direction"] == "sales" else "vendor"
        display_date = doc.get("expected_date")
        date_kind = "expected"
        amount_kind = "total"
        pdf_path = f"/orders/{doc_id}/pdf"

    if party_type == "customer":
        contact = query_one("""SELECT email FROM customers
                                WHERE entity_id=%s AND customer_name=%s AND status='active' LIMIT 1""",
                            (e["entity_id"], party))
    else:
        contact = query_one("""SELECT email FROM vendors
                                WHERE entity_id=%s AND vendor_name=%s AND status='active' LIMIT 1""",
                            (e["entity_id"], party))
    labels = {
        "zh_cn": {"invoice": "发票", "bill": "账单", "quote": "报价单", "credit_note": "贷记单",
                  "sales_order": "销售订单", "purchase_order": "采购订单"},
        "zh_hk": {"invoice": "發票", "bill": "賬單", "quote": "報價單", "credit_note": "貸記單",
                  "sales_order": "銷售訂單", "purchase_order": "採購訂單"},
        "en": {"invoice": "Invoice", "bill": "Bill", "quote": "Quotation", "credit_note": "Credit Note",
               "sales_order": "Sales Order", "purchase_order": "Purchase Order"},
    }[_lang]
    amount = dec(doc["gross_original"])
    if doc_type in ("invoice", "bill"):
        amount -= dec(doc.get("settled_original") or 0)
    return J({
        "docType": requested_type, "resolvedDocType": mail_kind, "docId": doc_id,
        "docNo": doc_no,
        "party": party,
        "partyType": party_type,
        "partyEmail": (contact or {}).get("email"),
        "currency": doc["currency"],
        "amount": float(amount),
        "amountDue": float(amount),
        "amountKind": amount_kind,
        "dueDate": display_date.isoformat() if display_date else None,
        "dateKind": date_kind,
        "status": doc["status"],
        "pdfPath": pdf_path,
        "suggestedSubject": f"{labels[mail_kind]} {doc_no} — {e['entity_name']}",
    })


# ---------------------------------------------------------------- HKFRS 15 合同
# ---------------------------------------------------------------- 复核与批准
def _review_target(kind, doc_id, entity_id):
    if kind == "invoice":
        return query_one("SELECT invoice_id AS id, invoice_no AS doc_no, status, review_status, "
                         "created_by FROM invoices WHERE invoice_id=%s AND entity_id=%s",
                         (doc_id, entity_id))
    return query_one("SELECT bill_id AS id, bill_no AS doc_no, status, review_status, "
                     "created_by FROM bills WHERE bill_id=%s AND entity_id=%s",
                     (doc_id, entity_id))


@app.post("/<string:kind>/<int:doc_id>/submit-review")
def submit_review(kind, doc_id):
    """草稿提交复核：进入待复核队列，复核通过前不可过账。"""
    require_writer()
    if kind not in ("invoices", "bills"):
        raise ValueError("单据类型不正确")
    e = entity_or_404()
    k = "invoice" if kind == "invoices" else "bill"
    d = _review_target(k, doc_id, e["entity_id"])
    if not d:
        raise ValueError("单据不存在")
    if d["status"] != "draft":
        raise ValueError("只有草稿可以提交复核")
    if d["review_status"] == "approved":
        return J({"id": doc_id, "reviewStatus": "approved", "unchanged": True})

    table = "invoices" if k == "invoice" else "bills"
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {table} SET review_status='pending' WHERE {k}_id=%s", (doc_id,))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": request.get_json(silent=True, force=True).get("actor", "system") if request.data else "system",
                            "action": f"{k}.submit_review", "object_type": table,
                            "object_id": str(doc_id), "detail": {"docNo": d["doc_no"]}})
    return J({"id": doc_id, "reviewStatus": "pending"})


@app.post("/<string:kind>/<int:doc_id>/approve")
def approve_doc(kind, doc_id):
    """复核批准。批准人不得是录单人（四眼原则），管理员除外。"""
    require_writer()
    if kind not in ("invoices", "bills"):
        raise ValueError("单据类型不正确")
    e = entity_or_404()
    k = "invoice" if kind == "invoices" else "bill"
    p = request.get_json(force=True) or {}
    actor = p.get("actor", "system")
    role = p.get("role") or request.headers.get("X-Ledu-Role", "")

    d = _review_target(k, doc_id, e["entity_id"])
    if not d:
        raise ValueError("单据不存在")
    if d["status"] != "draft":
        raise ValueError("已过账或已作废的单据不能复核")
    if d["review_status"] == "approved":
        return J({"id": doc_id, "reviewStatus": "approved", "unchanged": True})
    # 四眼原则：批准人须与录单人不同（管理员可强制通过）
    same = str(d["created_by"] or "").strip().lower() == str(actor or "").strip().lower()
    if same and role != "admin":
        raise ValueError("不能复核自己录入的单据（四眼原则）；如需强制通过请由管理员操作")

    table = "invoices" if k == "invoice" else "bills"
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""UPDATE {table}
                               SET review_status='approved', approved_by=%s,
                                   approved_at=NOW(3), approval_note=%s
                             WHERE {k}_id=%s""",
                        (actor, p.get("note"), doc_id))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": f"{k}.approve", "object_type": table,
                            "object_id": str(doc_id),
                            "detail": {"docNo": d["doc_no"], "note": p.get("note")}})
    return J({"id": doc_id, "reviewStatus": "approved", "approvedBy": actor})


@app.post("/<string:kind>/<int:doc_id>/reject")
def reject_doc(kind, doc_id):
    """复核退回：单据回到草稿并注明原因。"""
    require_writer()
    if kind not in ("invoices", "bills"):
        raise ValueError("单据类型不正确")
    e = entity_or_404()
    k = "invoice" if kind == "invoices" else "bill"
    p = request.get_json(force=True) or {}
    note = (p.get("note") or "").strip()
    if not note:
        raise ValueError("退回必须填写原因")

    d = _review_target(k, doc_id, e["entity_id"])
    if not d:
        raise ValueError("单据不存在")
    if d["status"] != "draft":
        raise ValueError("已过账的单据不能退回")

    table = "invoices" if k == "invoice" else "bills"
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""UPDATE {table} SET review_status='rejected', approval_note=%s
                             WHERE {k}_id=%s""", (note, doc_id))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": f"{k}.reject", "object_type": table,
                            "object_id": str(doc_id),
                            "detail": {"docNo": d["doc_no"], "note": note}})
    return J({"id": doc_id, "reviewStatus": "rejected"})


@app.get("/review-queue")
def review_queue():
    """待复核队列：草稿且已提交复核的发票与账单。"""
    e = entity_or_404()
    inv = query("""SELECT invoice_id AS id, invoice_no AS doc_no, supplier_name AS party,
                          invoice_date AS doc_date, currency, gross_original AS amount,
                          review_status, created_by, 'invoice' AS kind
                     FROM invoices
                    WHERE entity_id=%s AND status='draft' AND review_status IN ('pending','rejected','draft')
                    ORDER BY invoice_date DESC""", (e["entity_id"],))
    bll = query("""SELECT bill_id AS id, bill_no AS doc_no, vendor_name AS party,
                          date AS doc_date, currency, gross_original AS amount,
                          review_status, created_by, 'bill' AS kind
                     FROM bills
                    WHERE entity_id=%s AND status='draft' AND review_status IN ('pending','rejected','draft')
                    ORDER BY date DESC""", (e["entity_id"],))
    rows = []
    for r in list(inv) + list(bll):
        d = dict(r)
        d["doc_date"] = d["doc_date"].isoformat() if hasattr(d["doc_date"], "isoformat") else d["doc_date"]
        d["amount"] = float(dec(d["amount"]))
        rows.append(d)
    return J({"items": rows,
              "pending": sum(1 for x in rows if x["review_status"] == "pending"),
              "rejected": sum(1 for x in rows if x["review_status"] == "rejected"),
              "draft": sum(1 for x in rows if x["review_status"] == "draft")})



def register_attachment(path: str, *, invoice_id=None, bill_id=None, expense_id=None,
                        journal_id=None, actor="system", file_name=None) -> dict:
    """把已落盘的原件登记成单据附件（与界面手工上传同一张表、同一套约束）。"""
    import hashlib as _h
    from pathlib import Path as _P
    fp = _P(str(path))
    if not fp.is_file():
        raise ValueError(f"附件不存在：{path}")
    e = entity_or_404()
    data = fp.read_bytes()
    sha = _h.sha256(data).hexdigest()
    name = file_name or fp.name
    ext = fp.suffix.lower().lstrip(".") or "other"
    retention = None
    if invoice_id:
        row = query_one("SELECT retention_until FROM invoices WHERE invoice_id=%s", (invoice_id,))
        retention = (row or {}).get("retention_until")
    if bill_id:
        row = query_one("SELECT retention_until FROM bills WHERE bill_id=%s", (bill_id,))
        retention = (row or {}).get("retention_until")
    if expense_id:
        row = query_one("SELECT retention_until FROM expenses WHERE expense_id=%s", (expense_id,))
        retention = (row or {}).get("retention_until")
    if retention is None:
        from datetime import date as _d
        retention = _d(_d.today().year + 7, 12, 31)
    doc_type = ("invoice" if invoice_id else ("bill" if bill_id
                else ("journal" if journal_id else "expense")))
    doc_id = invoice_id or bill_id or expense_id or journal_id
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (e["entity_id"], doc_type, doc_id, name[:255], ext[:64],
                         len(data), sha, str(fp)[:500], actor))
            fid = cur.lastrowid
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "attachment.register", "object_type": "doc_files",
                            "object_id": str(fid),
                            "detail": {"docType": doc_type, "docId": doc_id,
                                       "fileName": name, "sha256": sha,
                                       "via": "ai_import"}})
    return {"fileId": fid, "fileName": name, "sha256": sha, "size": len(data)}


# ---------------------------------------------------------------- 年度 PDF 包
# 处理进度：上传/识别/建单是同步长任务，前端带一个 token 轮询这里，
# 就能看到「正在识别 → 正在匹配 → 正在生成卡片」，而不是干等。
_PROGRESS: dict = {}
_PROGRESS_TTL = 600


def set_progress(tok: str, stage: str, label: str, **extra) -> None:
    if not tok:
        return
    import time as _t
    prev = _PROGRESS.get(tok) or {}
    _PROGRESS[tok] = {"stage": stage, "label": label, "ts": _t.time(),
                      "started": prev.get("started") or _t.time(), **extra}


def get_progress(tok: str) -> dict:
    import time as _t
    item = _PROGRESS.get(tok)
    if not item:
        return {"stage": "unknown", "label": "", "elapsed": 0}
    # 顺手清理过期的
    now = _t.time()
    for k in [k for k, v in _PROGRESS.items() if now - v["ts"] > _PROGRESS_TTL]:
        _PROGRESS.pop(k, None)
    return {"stage": item["stage"], "label": item["label"],
            "elapsed": round(now - item.get("started", item["ts"]), 1)}


@app.get("/ai/progress/<tok>")
def ai_progress(tok: str):
    return J(get_progress(tok))


# 年度 PDF 包：单据多的时候一张张渲染要好几分钟，HTTP 请求撑不住，
# 所以做成后台任务，前端轮询进度再下载。
_PACK_JOBS: dict = {}
_PACK_LOCK = None


def _pack_job_dir(job_id: str):
    d = STORAGE_DIR / "packs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _year_pack_worker(job_id: str, year: int, lang: str, parts: list,
                      custom_from: str | None = None, custom_to: str | None = None) -> None:
    """在后台把报表与单据渲染成 PDF，最后打成一个 ZIP。"""
    import io
    import zipfile
    from pypdf import PdfReader, PdfWriter
    from core.i18n import PACK_MANIFEST
    job = _PACK_JOBS.get(job_id) or {}
    out_dir = _pack_job_dir(job_id)
    hdr = {"X-Ledu-Token": API_TOKEN}
    start = date.fromisoformat(custom_from) if custom_from else date(year, 1, 1)
    end = date.fromisoformat(custom_to) if custom_to else date(year, 12, 31)
    try:
        with app.app_context():
            e = query_one("SELECT * FROM entities ORDER BY entity_id LIMIT 1")
            eid = e["entity_id"]
            client = app.test_client()
            files = []

            def fetch(url):
                r = client.get(url, headers=hdr)
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
                return r.data

            def merge(blobs, name):
                w = PdfWriter()
                for b in blobs:
                    try:
                        for pg in PdfReader(io.BytesIO(b)).pages:
                            w.add_page(pg)
                    except Exception:
                        continue
                out = io.BytesIO()
                w.write(out)
                files.append((name, out.getvalue()))

            _m = PACK_MANIFEST.get(lang, PACK_MANIFEST["en"])
            _ent = e.get("entity_name") or "Entity"
            manifest = [_m["title"].format(entity=_ent, year=year),
                        _m["generated"].format(date=date.today().isoformat(), lang=lang), ""]

            def add(name, data, note=""):
                files.append((name, data))
                manifest.append(f"{name}{(' — ' + note) if note else ''}")

            # 1) 报表
            if "reports" in parts:
                job["total"] = 10
                for i, (url, name, note) in enumerate([
                    (f"/reports/statements/pdf?from={start}&to={end}&lang={lang}&gl=0",
                     f"Financial-Statements-{year}.pdf", _m["fs_note"]),
                    (f"/reports/pdf?kind=trial-balance&from={start}&to={end}&lang={lang}",
                     f"Trial-Balance-{year}.pdf", ""),
                    (f"/reports/pdf?kind=pnl&from={start}&to={end}&lang={lang}",
                     f"Profit-and-Loss-{year}.pdf", ""),
                    (f"/reports/pdf?kind=balance-sheet&from={start}&to={end}&lang={lang}",
                     f"Balance-Sheet-{year}.pdf", ""),
                    (f"/reports/pdf?kind=cash-flow&from={start}&to={end}&lang={lang}",
                     f"Cash-Flow-{year}.pdf", ""),
                    (f"/reports/pdf?kind=aging&from={start}&to={end}&lang={lang}",
                     f"Aging-{year}.pdf", ""),
                    (f"/reports/pdf?kind=gl&from={start}&to={end}&lang={lang}",
                     f"General-Ledger-{year}.pdf", ""),
                    (f"/reports/pdf?kind=sales-detail&from={start}&to={end}&lang={lang}",
                     f"Sales-Detail-{year}.pdf", ""),
                    (f"/reports/pdf?kind=purchase-detail&from={start}&to={end}&lang={lang}",
                     f"Purchase-Detail-{year}.pdf", ""),
                    (f"/reports/pdf?kind=daybook&from={start}&to={end}&lang={lang}",
                     f"Daybook-{year}.pdf", ""),
                ]):
                    try:
                        add(name, fetch(url), note)
                    except Exception as ex:
                        manifest.append(f"{name} — {_m['failed']}: {ex}")
                    job["done"] = i + 1

            # 2) 销售单
            if "invoices" in parts:
                rows = query("""SELECT invoice_id FROM invoices
                                 WHERE entity_id=%s AND invoice_date BETWEEN %s AND %s
                                   AND status IN ('posted','draft')
                                 ORDER BY invoice_date, invoice_id""", (eid, start, end))
                job["total"] = job.get("total", 0) + len(rows)
                blobs = []
                for r in rows:
                    try:
                        blobs.append(fetch(f"/invoices/{int(r['invoice_id'])}/pdf?lang={lang}"))
                    except Exception:
                        pass
                    job["done"] = job.get("done", 0) + 1
                if blobs:
                    merge(blobs, f"Sales-Invoices-{year}.pdf")
                    manifest.append(f"Sales-Invoices-{year}.pdf — " + _m["invoices_unit"].format(n=len(blobs)))

            # 3) 采购单
            if "bills" in parts:
                rows = query("""SELECT bill_id FROM bills
                                 WHERE entity_id=%s AND date BETWEEN %s AND %s
                                   AND status IN ('posted','draft')
                                 ORDER BY date, bill_id""", (eid, start, end))
                job["total"] = job.get("total", 0) + len(rows)
                blobs = []
                for r in rows:
                    try:
                        blobs.append(fetch(f"/bills/{int(r['bill_id'])}/pdf?lang={lang}"))
                    except Exception:
                        pass
                    job["done"] = job.get("done", 0) + 1
                if blobs:
                    merge(blobs, f"Purchase-Bills-{year}.pdf")
                    manifest.append(f"Purchase-Bills-{year}.pdf — " + _m["bills_unit"].format(n=len(blobs)))

            manifest += ["", _m["notes"], _m["note1"], _m["note2"], _m["note3"]]
            add(f"MANIFEST-{year}.txt", "\n".join(manifest).encode("utf-8"))

            zpath = out_dir / f"LEDU-{year}-annual-pack.zip"
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
                for name, data in files:
                    z.writestr(name, data)
            job["file"] = str(zpath)
            job["status"] = "done"
    except Exception as ex:
        job["status"] = "failed"
        job["error"] = str(ex)[:400]


@app.post("/reports/year-pack/start")
def year_pack_start():
    """排队生成年度 PDF 包；返回 jobId，前端轮询 /status 再下载。"""
    global _PACK_LOCK
    import threading
    import uuid
    p = request.get_json(force=True) or {}
    year = int(p.get("year") or date.today().year)
    start = p.get("from") or None
    end = p.get("to") or None
    lang = p.get("lang") or "en"
    parts = [x for x in (p.get("parts") or ["reports", "invoices", "bills"])
             if x in ("reports", "invoices", "bills")]
    if _PACK_LOCK is None:
        _PACK_LOCK = threading.Lock()
    job_id = uuid.uuid4().hex[:16]
    _PACK_JOBS[job_id] = {"status": "running", "done": 0, "total": 0,
                          "year": year, "lang": lang, "parts": parts,
                          "from": start, "to": end,
                          "started": date.today().isoformat()}
    threading.Thread(target=_year_pack_worker, args=(job_id, year, lang, parts, start, end),
                     daemon=True).start()
    return J({"jobId": job_id})


@app.get("/reports/year-pack/status/<job_id>")
def year_pack_status(job_id):
    job = _PACK_JOBS.get(job_id)
    if not job:
        return J({"error": "not_found", "message": "任务不存在或已过期，请重新生成"}, 404)
    return J({k: v for k, v in job.items() if k != "file"})


@app.get("/reports/year-pack/file/<job_id>")
def year_pack_file(job_id):
    from pathlib import Path as _P
    job = _PACK_JOBS.get(job_id)
    if not job or job.get("status") != "done" or not job.get("file"):
        raise ValueError("文件还没准备好")
    return send_file(job["file"], mimetype="application/zip", as_attachment=True,
                     download_name=_P(job["file"]).name)


def append_audit_via_api(actor: str, action: str, detail: dict) -> None:
    """接口层写一条审计（设置类操作也要留痕）。"""
    from core.service import append_audit
    e = entity_or_404()
    with transaction() as conn:
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor, "action": action,
                            "object_type": "app_settings", "object_id": action,
                            "detail": detail})


# ---------------------------------------------------------------- 数据备份与恢复
def _require_backup_admin() -> None:
    """备份包含全部账务和原始票据，五种操作均只允许管理员执行。"""
    if not is_admin():
        raise PermissionError("仅管理员可以管理数据备份与恢复")


def _backup_flag(value) -> bool:
    """同时接受 JSON 布尔值和 multipart 表单的 1/true，其他值一律视为未选择。"""
    return value is True or value == 1 or (
        isinstance(value, str) and value.strip().lower() in ("1", "true")
    )


def _public_backup(row: dict) -> dict:
    """显式挑选可公开字段，绝不透传核心模块中的服务器路径或临时路径。"""
    allowed = ("name", "size", "created_at", "updated_at", "database", "attachment_count",
               "archive_sha256", "pruned", "database_restored", "type",
               "label", "chain_parent", "chain_length", "changed_tables",
               "deleted_attachments", "rolling", "rolling_updates")
    result = {key: row[key] for key in allowed if key in row}
    if row.get("error"):
        # tarfile/OSError 的原文可能包含本机文件名，界面只显示安全的通用说明。
        result["error"] = "备份清单无法读取或未通过完整性校验"
    return result


def _restore_result(result: dict) -> dict:
    """恢复结果保留业务信息，服务器安全备份路径只转换成文件名。"""
    payload = _public_backup(result)
    safety = result.get("safety_backup")
    payload["safetyBackupName"] = Path(str(safety)).name if safety else None
    return payload


@app.get("/backups")
def backups_list():
    """列出可恢复备份及保留策略；损坏包仍列出，但不暴露内部错误路径。"""
    _require_backup_admin()
    from core.settings import get as settings_get

    manager = backupcore.BackupManager()
    return J({
        "backups": [_public_backup(dict(row)) for row in manager.list()],
        "settings": {
            "keep": manager.config.keep,
            "timezone": "Asia/Hong_Kong",
            "schedule": backupcore.load_schedule(),
            "lastAuto": settings_get("backup.last_auto", ""),
        },
    })


@app.post("/backups/schedule")
def backups_schedule():
    """保存自动备份时间（香港时间，最多 4 个；留空表示关闭自动备份）。"""
    _require_backup_admin()
    p = request.get_json(silent=True) or {}
    times = p.get("times")
    if not isinstance(times, list):
        raise ValueError("请提供自动备份时间列表")
    schedule = backupcore.normalize_schedule(times)
    actor = str(p.get("actor") or request.headers.get("X-Ledu-User") or "system")

    from datetime import datetime, timedelta, timezone
    from core.settings import set as settings_set

    settings_set(backupcore.SCHEDULE_KEY, ",".join(schedule), actor)
    # 改完时间不补跑今天已过去的时段，避免保存后立刻触发一次备份。
    now = datetime.now(timezone(timedelta(hours=8)))
    settings_set("backup.last_auto", now.isoformat(timespec="seconds"), actor)
    append_audit_via_api(actor, "backup.schedule", {"schedule": schedule})
    return J({"schedule": schedule})


@app.post("/backups/create")
def backups_create():
    """界面手动备份始终生成完整备份，并记录操作者、文件数和整包哈希。"""
    _require_backup_admin()
    p = request.get_json(silent=True) or {}
    actor = str(p.get("actor") or request.headers.get("X-Ledu-User") or "system")
    with backupcore.backup_operation_lock():
        result = backupcore.BackupManager().create(label="manual", incremental=False)
    append_audit_via_api(actor, "backup.create", {
        "name": result["name"],
        "attachmentCount": result.get("attachment_count"),
        "archiveSha256": result.get("archive_sha256"),
    })
    return J(_public_backup(result))


@app.post("/backups/delete")
def backups_delete():
    """删除受控目录内的单个备份；仍被增量链引用的父包会被拒绝。"""
    _require_backup_admin()
    p = request.get_json(silent=True) or {}
    name = str(p.get("name") or "")
    if not backupcore.BACKUP_NAME_RE.fullmatch(name):
        raise ValueError("请选择有效的备份包")
    actor = str(p.get("actor") or request.headers.get("X-Ledu-User") or "system")
    with backupcore.backup_operation_lock():
        result = backupcore.BackupManager().delete(name)
    append_audit_via_api(actor, "backup.delete", {"name": name})
    return J(result)


def _restore_selection(p: dict) -> tuple[bool, bool]:
    """恢复必须显式确认，并至少选择数据库或附件之一，禁止默认全量覆盖。"""
    if not _backup_flag(p.get("confirmRestore")):
        raise ValueError("confirmation_required")
    restore_database = _backup_flag(p.get("restoreDatabase"))
    restore_attachments = _backup_flag(p.get("restoreAttachments"))
    if not restore_database and not restore_attachments:
        raise ValueError("至少选择数据库或附件其中一项")
    return restore_database, restore_attachments


@app.post("/backups/restore")
def backups_restore():
    """恢复受控目录内的命名备份；核心层先验 SHA256，再创建安全备份。"""
    _require_backup_admin()
    p = request.get_json(silent=True) or {}
    restore_database, restore_attachments = _restore_selection(p)
    name = str(p.get("name") or "")
    if not backupcore.BACKUP_NAME_RE.fullmatch(name):
        raise ValueError("请选择有效的备份包")
    actor = str(p.get("actor") or request.headers.get("X-Ledu-User") or "system")
    with backupcore.backup_operation_lock():
        result = backupcore.BackupManager().restore(
            name,
            restore_database=restore_database,
            restore_attachments=restore_attachments,
            safety_backup=True,
        )
    payload = _restore_result(result)
    append_audit_via_api(actor, "backup.restore", {
        "name": name,
        "restoreDatabase": restore_database,
        "restoreAttachments": restore_attachments,
        "attachmentCount": result.get("attachment_count"),
        "safetyBackupName": payload["safetyBackupName"],
    })
    return J(payload)


@app.post("/backups/restore-upload")
def backups_restore_upload():
    """接收 512MB 以内的 LtBooks 备份包；磁盘临时文件在恢复后自动清除。"""
    _require_backup_admin()
    # PHP post_max_size 同为 520MB；此处也保护绕过 PHP 直接调用内部 API 的情形。
    if (request.content_length or 0) > 520 * 1024 * 1024:
        raise ValueError("备份包上传请求不能超过 520MB")
    p = request.form.to_dict()
    restore_database, restore_attachments = _restore_selection(p)
    archive = request.files.get("archive")
    if archive is None or not archive.filename:
        raise ValueError("请选择要恢复的 .tar.gz 备份包")
    original_name = Path(archive.filename).name
    if not original_name.lower().endswith(".tar.gz"):
        raise ValueError("备份包必须是 .tar.gz 文件")
    actor = str(p.get("actor") or request.headers.get("X-Ledu-User") or "system")

    import tempfile
    with tempfile.TemporaryDirectory(prefix="ltbooks-restore-upload-") as work:
        uploaded = Path(work) / "upload.tar.gz"
        archive.save(uploaded)
        if uploaded.stat().st_size > 512 * 1024 * 1024:
            raise ValueError("备份包不能超过 512MB")
        with backupcore.backup_operation_lock():
            result = backupcore.BackupManager().restore(
                uploaded,
                restore_database=restore_database,
                restore_attachments=restore_attachments,
                safety_backup=True,
            )
    payload = _restore_result(result)
    append_audit_via_api(actor, "backup.restore", {
        "name": original_name,
        "source": "upload",
        "restoreDatabase": restore_database,
        "restoreAttachments": restore_attachments,
        "attachmentCount": result.get("attachment_count"),
        "safetyBackupName": payload["safetyBackupName"],
    })
    return J(payload)


@app.get("/backups/download/<name>")
def backups_download(name):
    """仅流式下载白名单内的普通文件，拒绝路径穿越、符号链接和目录外目标。"""
    _require_backup_admin()
    if not backupcore.BACKUP_NAME_RE.fullmatch(name):
        return J({"error": "not_found", "message": "备份文件不存在"}, 404)
    manager = backupcore.BackupManager()
    root = Path(manager.config.backup_dir).resolve()
    candidate = root / name
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return J({"error": "not_found", "message": "备份文件不存在"}, 404)
        resolved = candidate.resolve(strict=True)
    except OSError:
        return J({"error": "not_found", "message": "备份文件不存在"}, 404)
    if resolved.parent != root or resolved.name != name:
        return J({"error": "not_found", "message": "备份文件不存在"}, 404)
    actor = str(request.headers.get("X-Ledu-User") or "system")
    append_audit_via_api(actor, "backup.download", {"name": name})
    response = send_file(resolved, mimetype="application/gzip", as_attachment=True,
                         download_name=name, conditional=True)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ---------------------------------------------------------------- 销售/采购订单（不进总账）
ORDER_STATUS_LABEL = {"draft": "草稿", "open": "已下单", "partial": "部分履行",
                      "fulfilled": "已履行完", "closed": "已关闭", "cancelled": "已取消"}
ORDER_KIND = {"sales": {"noKind": "so", "party": "customer", "doc": "invoice"},
              "purchase": {"noKind": "po", "party": "vendor", "doc": "bill"}}


def _order_serialize(row: dict) -> dict:
    d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(row).items()}
    for k in ("amount", "tax_amount", "gross_original", "amount_functional", "exchange_rate"):
        if d.get(k) is not None:
            d[k] = float(dec(d[k]))
    d["statusLabel"] = ORDER_STATUS_LABEL.get(str(d.get("status")), str(d.get("status")))
    if "editable" in d:
        d["editable"] = bool(d["editable"]) and d.get("status") in ("draft", "open")
    return d


@app.get("/orders")
def orders_list():
    e = entity_or_404()
    limit, offset = page_args(default_limit=25)
    q = str(request.args.get("q") or "").strip()
    st = str(request.args.get("status") or "").strip()
    direction = request.args.get("direction") or None
    if direction not in (None, "sales", "purchase"):
        raise ValueError("direction 只能是 sales 或 purchase")
    cond, args = ["entity_id=%s"], [e["entity_id"]]
    if direction:
        cond.append("direction=%s"); args.append(direction)
    if st and st != "all":
        cond.append("status=%s"); args.append(st)
    if q:
        cond.append("(order_no LIKE %s OR party_name LIKE %s OR reference LIKE %s OR notes LIKE %s)")
        args += [f"%{q}%"] * 4
    where = " AND ".join(cond)
    total = int(query_one(f"SELECT COUNT(*) n FROM orders WHERE {where}", tuple(args))["n"])
    rows = query(f"""SELECT o.order_id, o.direction, o.order_no, o.party_name, o.order_date,
                            o.expected_date, o.currency, o.amount, o.tax_amount, o.gross_original,
                            o.status, o.reference, o.notes,
                            (SELECT COUNT(*) FROM doc_files f WHERE f.doc_type='order' AND f.doc_id=o.order_id) AS file_count,
                            (NOT EXISTS(SELECT 1 FROM order_fulfilments f WHERE f.order_id=o.order_id)
                             AND NOT EXISTS(SELECT 1 FROM order_lines l WHERE l.order_id=o.order_id AND l.done_qty<>0)
                             AND NOT EXISTS(SELECT 1 FROM invoices i WHERE i.source_order_id=o.order_id)
                             AND NOT EXISTS(SELECT 1 FROM bills b WHERE b.source_po_id=o.order_id)) AS editable
                       FROM orders o WHERE {where.replace('entity_id', 'o.entity_id')
                                              .replace('direction=', 'o.direction=')}
                      ORDER BY o.order_id DESC LIMIT %s OFFSET %s""",
                 tuple(args + [limit, offset]))
    return J({"orders": [_order_serialize(r) for r in rows], "total": total,
              "limit": limit, "offset": offset, "statusLabels": ORDER_STATUS_LABEL})


@app.get("/orders/<int:order_id>")
def orders_detail(order_id):
    e = entity_or_404()
    head = query_one("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s",
                     (order_id, e["entity_id"]))
    if not head:
        raise ValueError("订单不存在")
    d = _order_serialize(head)
    d["functional_currency"] = e["functional_currency"]
    kind = ORDER_KIND[d["direction"]]
    d["kind"] = kind
    lines = query("""SELECT line_id, line_no, description, unit, quantity, unit_price, amount,
                            tax_rate, tax_amount, done_qty
                       FROM order_lines WHERE order_id=%s ORDER BY line_no""", (order_id,))
    d["lines"] = [{**dict(x),
                   "quantity": float(dec(x["quantity"])),
                   "unit_price": float(dec(x["unit_price"])),
                   "amount": float(dec(x["amount"])),
                   "tax_amount": float(dec(x["tax_amount"])),
                   "done_qty": float(dec(x["done_qty"])),
                   "remaining_qty": float(dec(x["quantity"]) - dec(x["done_qty"]))}
                  for x in lines]
    d["fulfilments"] = [dict(r, doc_date=r["doc_date"].isoformat(),
                             created_at=r["created_at"].isoformat(sep=" ", timespec="minutes"))
                        for r in query("""SELECT fulfilment_id, doc_no, doc_date, note, created_by, created_at
                                            FROM order_fulfilments WHERE order_id=%s
                                           ORDER BY fulfilment_id DESC""", (order_id,))]
    if d["direction"] == "purchase":
        d["docs"] = [dict(r, date=r["date"].isoformat(), gross_original=float(dec(r["gross_original"])))
                     for r in query("""SELECT bill_id AS id, bill_no AS no, `date`, gross_original, status
                                         FROM bills WHERE entity_id=%s AND source_po_id=%s ORDER BY bill_id""",
                                    (e["entity_id"], order_id))]
    else:
        d["docs"] = [dict(r, date=r["date"].isoformat(), gross_original=float(dec(r["gross_original"])))
                     for r in query("""SELECT invoice_id AS id, invoice_no AS no, invoice_date AS `date`,
                                            gross_original, status
                                         FROM invoices WHERE entity_id=%s AND source_order_id=%s
                                        ORDER BY invoice_id""",
                                    (e["entity_id"], order_id))]
    d["files"] = [
        dict(r, uploaded_at=r["uploaded_at"].isoformat(sep=" ", timespec="minutes")
             if r.get("uploaded_at") else None)
        for r in query("""SELECT f.file_id, f.file_name, f.file_type, f.file_size, f.sha256_hash,
                                 f.uploaded_by, f.created_at AS uploaded_at
                            FROM doc_files f
                           WHERE f.doc_type='order' AND f.doc_id=%s ORDER BY f.file_id DESC""", (order_id,))]
    d["editable"] = (d["status"] in ("draft", "open") and not d["fulfilments"]
                     and not d["docs"] and all(float(x["done_qty"]) == 0 for x in d["lines"]))
    return J(d)


@app.post("/orders")
@app.post("/orders/<int:order_id>/update")
def orders_create(order_id=None):
    """建订单或修改未履行订单；不进总账、不产生应收应付。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    existing = None
    if order_id is not None:
        existing = query_one("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s",
                             (order_id, e["entity_id"]))
        if not existing:
            raise ValueError("订单不存在")
        if existing["status"] not in ("draft", "open"):
            raise ValueError("已履行、已关闭或已取消的订单不能编辑")
    direction = str(p.get("direction") or "")
    if direction not in ORDER_KIND:
        raise ValueError("direction 只能是 sales 或 purchase")
    if existing and direction != existing["direction"]:
        raise ValueError("订单的销售或采购方向不能修改")
    party = str(p.get("partyName") or "").strip()
    if not party:
        raise ValueError("往来单位不能为空")
    order_date = p.get("orderDate") or date.today().isoformat()
    ccy = str(p.get("currency") or "HKD").upper()
    lines = []
    for i, ln in enumerate(p.get("lines") or [], start=1):
        desc = str(ln.get("description") or "").strip()
        if not desc:
            continue
        qty = dec(ln.get("quantity")) if ln.get("quantity") not in (None, "") else dec(1)
        price = dec(ln.get("unitPrice")) if ln.get("unitPrice") not in (None, "") else dec(0)
        if qty is None or price is None:
            raise ValueError(f"第 {i} 行数量或单价非法")
        amt = quantize_money(qty * price)[0]
        rate = dec(ln.get("taxRate")) if ln.get("taxRate") not in (None, "") else None
        tax = quantize_money(amt * (rate or 0) / 100)[0] if rate else dec(0)
        lines.append({"lineNo": i, "description": desc[:400], "unit": ln.get("unit"),
                      "quantity": qty, "unitPrice": price, "amount": amt,
                      "taxRate": rate, "taxAmount": tax})
    if not lines:
        raise ValueError("至少要有一行明细")

    total = sum((x["amount"] for x in lines), dec(0))
    tax_total = sum((x["taxAmount"] for x in lines), dec(0))
    gross = total + tax_total
    functional = gross if ccy == e["functional_currency"] else dec(0)
    actor = p.get("actor", "system")

    with transaction() as conn:
        with conn.cursor() as cur:
            if existing:
                cur.execute("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s FOR UPDATE",
                            (order_id, e["entity_id"]))
                locked = cur.fetchone()
                if not locked or locked["status"] not in ("draft", "open"):
                    raise ValueError("已履行、已关闭或已取消的订单不能编辑")
                checks = [
                    ("SELECT COUNT(*) n FROM order_fulfilments WHERE order_id=%s", (order_id,)),
                    ("SELECT COUNT(*) n FROM order_lines WHERE order_id=%s AND done_qty<>0", (order_id,)),
                    ("SELECT COUNT(*) n FROM invoices WHERE entity_id=%s AND source_order_id=%s", (e["entity_id"], order_id)),
                    ("SELECT COUNT(*) n FROM bills WHERE entity_id=%s AND source_po_id=%s", (e["entity_id"], order_id)),
                ]
                for sql, args in checks:
                    cur.execute(sql, args)
                    if cur.fetchone()["n"]:
                        raise ValueError("订单已有履行记录或已转出单据，不能再编辑")
                order_no = locked["order_no"]
                oid = order_id
                party_id = p.get("partyId") or (locked["party_id"] if party == locked["party_name"] else None)
                cur.execute("""UPDATE orders SET party_id=%s, party_name=%s, order_date=%s,
                    expected_date=%s, currency=%s, amount=%s, tax_amount=%s, gross_original=%s,
                    amount_functional=%s, contract_note=%s, reference=%s, notes=%s,
                    retention_until=DATE_ADD(%s, INTERVAL 7 YEAR)
                    WHERE order_id=%s AND entity_id=%s""",
                    (party_id, party, order_date, p.get("expectedDate") or None, ccy,
                     float(total), float(tax_total), float(gross), float(functional),
                     str(p.get("contractNote") or "")[:200] or None,
                     str(p.get("reference") or "")[:100] or None,
                     str(p.get("notes") or "")[:500] or None,
                     order_date, order_id, e["entity_id"]))
                cur.execute("DELETE FROM order_lines WHERE order_id=%s", (order_id,))
                status = locked["status"]
            else:
                order_no = _allocate_doc_no(conn, e["entity_id"], order_date,
                                            ORDER_KIND[direction]["noKind"], p.get("orderNo"),
                                            "orders", "order_no")
                cur.execute("""INSERT INTO orders
                    (entity_id, direction, order_no, party_id, party_name, order_date, expected_date,
                     currency, amount, tax_amount, gross_original, exchange_rate, amount_functional,
                     contract_note, reference, status, notes, created_by, retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,'open',%s,%s,
                            DATE_ADD(%s, INTERVAL 7 YEAR))""",
                    (e["entity_id"], direction, order_no, p.get("partyId"), party,
                     order_date, p.get("expectedDate") or None, ccy,
                     float(total), float(tax_total), float(gross), float(functional),
                     str(p.get("contractNote") or "")[:200] or None,
                     str(p.get("reference") or "")[:100] or None,
                     str(p.get("notes") or "")[:500] or None, actor, order_date))
                oid = cur.lastrowid
                status = "open"
            for ln in lines:
                cur.execute("""INSERT INTO order_lines
                    (order_id, line_no, description, unit, quantity, unit_price, amount,
                     tax_rate, tax_amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (oid, ln["lineNo"], ln["description"], ln["unit"],
                     float(ln["quantity"]), float(ln["unitPrice"]), float(ln["amount"]),
                     float(ln["taxRate"]) if ln["taxRate"] is not None else None,
                     float(ln["taxAmount"])))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "order.update" if existing else "order.create",
                            "object_type": "orders", "object_id": str(oid),
                            "detail": {"direction": direction, "orderNo": order_no,
                                       "party": party, "gross": float(gross)}})
    return J({"orderId": oid, "orderNo": order_no, "status": status, "gross": float(gross)})


@app.post("/orders/<int:order_id>/fulfil")
def orders_fulfil(order_id):
    """登记履行：采购=收货/验收，销售=发货/交付。只改数量，不产生分录。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    head = query_one("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s",
                     (order_id, e["entity_id"]))
    if not head:
        raise ValueError("订单不存在")
    if head["status"] in ("closed", "cancelled"):
        raise ValueError("已关闭或已取消的订单不能再登记")
    date_in = p.get("docDate") or date.today().isoformat()
    rows = [(int(x.get("lineId") or 0), dec(x.get("quantity")))
            for x in (p.get("lines") or [])]
    rows = [(lid, q) for lid, q in rows if lid and q and q > 0]
    if not rows:
        raise ValueError("没有要登记的数量")

    with transaction() as conn:
        with conn.cursor() as cur:
            doc_no = next_no(conn, e["entity_id"], date_in, "grn" if head["direction"] == "purchase" else "dln")
            cur.execute("""INSERT INTO order_fulfilments
                (order_id, direction, doc_no, doc_date, note, created_by)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                        (order_id, head["direction"], doc_no, date_in,
                         str(p.get("note") or "")[:300] or None, p.get("actor", "system")))
            fid = cur.lastrowid
            for lid, qty in rows:
                cur.execute("""SELECT quantity, done_qty FROM order_lines
                                WHERE line_id=%s AND order_id=%s""", (lid, order_id))
                ln = cur.fetchone()
                if not ln:
                    raise ValueError(f"订单行 {lid} 不存在")
                remain = dec(ln["quantity"]) - dec(ln["done_qty"])
                if qty > remain:
                    raise ValueError(f"数量超过未履行部分（还剩 {float(remain):g}）")
                cur.execute("UPDATE order_lines SET done_qty=done_qty+%s WHERE line_id=%s",
                            (float(qty), lid))
                cur.execute("""INSERT INTO order_fulfilment_lines
                                (fulfilment_id, order_line_id, quantity) VALUES (%s,%s,%s)""",
                            (fid, lid, float(qty)))
            cur.execute("""SELECT SUM(quantity) q, SUM(done_qty) r
                             FROM order_lines WHERE order_id=%s""", (order_id,))
            s = cur.fetchone()
            done = dec(s["r"]) >= dec(s["q"]) - dec("0.0001")
            cur.execute("UPDATE orders SET status=%s WHERE order_id=%s",
                        ("fulfilled" if done else "partial", order_id))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "order.fulfil", "object_type": "order_fulfilments",
                            "object_id": str(fid),
                            "detail": {"orderNo": head["order_no"], "docNo": doc_no, "lines": len(rows)}})
    return J({"fulfilmentId": fid, "docNo": doc_no,
              "status": "fulfilled" if done else "partial"})


@app.post("/orders/<int:order_id>/convert")
def orders_convert(order_id):
    """转成发票：销售→销售发票草稿，采购→采购账单草稿；都回指订单，过账仍走各自复核。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    head = query_one("SELECT * FROM orders WHERE order_id=%s AND entity_id=%s",
                     (order_id, e["entity_id"]))
    if not head:
        raise ValueError("订单不存在")
    if head["status"] in ("cancelled", "closed"):
        raise ValueError("已取消或已关闭的订单不能转发票")
    lines = query("""SELECT line_id, description, unit, quantity, unit_price, tax_rate, done_qty
                       FROM order_lines WHERE order_id=%s ORDER BY line_no""", (order_id,))
    use = []
    for ln in lines:
        qty = dec(ln["done_qty"]) if p.get("onlyDone") else dec(ln["quantity"])
        if qty <= 0:
            continue
        use.append({"description": ln["description"], "unit": ln["unit"],
                    "quantity": float(qty), "unitPrice": float(dec(ln["unit_price"])),
                    "taxRate": float(dec(ln["tax_rate"])) if ln["tax_rate"] is not None else None})
    if not use:
        raise ValueError("没有可开票的数量：先登记履行，或取消「只按已履行数量」")

    actor = p.get("actor", "system")
    is_sales = head["direction"] == "sales"
    if is_sales:
        from core.service import create_invoice
        res = create_invoice({
            "customerName": head["party_name"], "customerId": head["party_id"],
            "invoiceDate": p.get("date") or date.today().isoformat(),
            "revenueRecognitionDate": p.get("date") or date.today().isoformat(),
            "dueDate": p.get("dueDate") or None,
            "currency": head["currency"], "lines": use,
            "revenueAccountCode": p.get("accountCode") or "4100",
            "actor": actor,
        }, actor)
        doc_id, doc_no = res.get("invoiceId"), res.get("invoiceNo")
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE invoices SET source_order_id=%s WHERE invoice_id=%s",
                            (order_id, doc_id))
        href = f"?p=invoice-view&id={doc_id}"
    else:
        from core.service import create_bill
        res = create_bill({
            "vendorName": head["party_name"], "vendorId": head["party_id"],
            "date": p.get("date") or date.today().isoformat(),
            "dueDate": p.get("dueDate") or None,
            "currency": head["currency"], "lines": use,
            "expenseAccountCode": p.get("accountCode") or "6200",
            "actor": actor,
        }, actor)
        doc_id, doc_no = res.get("billId"), res.get("billNo")
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE bills SET source_po_id=%s WHERE bill_id=%s",
                            (order_id, doc_id))
        href = f"?p=bill-view&id={doc_id}"

    with transaction() as conn:
        append_audit(conn, {"entity_id": e["entity_id"], "actor": actor,
                            "action": "order.convert", "object_type": "orders",
                            "object_id": str(order_id),
                            "detail": {"direction": head["direction"], "orderNo": head["order_no"],
                                       "docNo": doc_no}})
    return J({"orderId": order_id, "docId": doc_id, "docNo": doc_no,
              "gross": res.get("grossOriginal"), "href": href,
              "direction": head["direction"]})


@app.post("/orders/<int:order_id>/status")
def orders_status(order_id):
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    st = str(p.get("status") or "")
    if st not in ("closed", "cancelled"):
        raise ValueError("只支持关闭或取消")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status=%s WHERE order_id=%s AND entity_id=%s",
                        (st, order_id, e["entity_id"]))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "order.status", "object_type": "orders",
                            "object_id": str(order_id), "detail": {"status": st}})
    return J({"orderId": order_id, "status": st})


# ---------------------------------------------------------------- 系统设置：大模型# ---------------------------------------------------------------- 系统设置：大模型
LLM_MODELS = [
    {"id": "deepseek-chat", "label": "DeepSeek Chat", "note": "通用；结构化输出稳定"},
    {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "note": "推理型；更慢，适合对账与判断"},
]


@app.get("/settings/llm")
def settings_llm_get():
    """当前大模型配置。密钥只回显掩码，不返回明文。"""
    from core.settings import llm_config
    c = llm_config()
    key = c["apiKey"]
    mask = (key[:4] + "…" + key[-4:]) if len(key) >= 12 else ("已设置" if key else "")
    return J({"base": c["base"], "model": c["model"], "keySet": bool(key), "keyMask": mask,
              "keyFromEnv": c["keyFromEnv"], "fromEnv": c["fromEnv"],
              "temperature": c["temperature"], "models": LLM_MODELS,
              "envHint": "地址与密钥仍以 .env 里的 LEDU_LLM_* 为准；模型名以界面选择为准"})


@app.post("/settings/llm")
def settings_llm_save():
    """保存大模型配置（只写数据库；环境变量仍优先）。"""
    require_writer()
    if current_role() not in ("admin", "accountant"):
        raise ValueError("只有管理员或会计可以修改大模型配置")
    from core.settings import set as sset, clear_cache, llm_config
    p = request.get_json(force=True) or {}
    actor = str(p.get("actor") or "system")
    base = str(p.get("base") or "").strip()
    model = str(p.get("model") or "").strip()
    key = str(p.get("apiKey") or "").strip()
    if not base.startswith(("http://", "https://")):
        raise ValueError("服务地址必须以 http:// 或 https:// 开头")
    if not model:
        raise ValueError("模型名不能为空")
    sset("llm.base", base, actor)
    sset("llm.model", model, actor)
    if key:
        sset("llm.api_key", key, actor)
    try:
        temp = float(p.get("temperature"))
        if not (0 <= temp <= 2):
            raise ValueError
        sset("llm.temperature", str(temp), actor)
    except (TypeError, ValueError):
        pass
    clear_cache()
    c = llm_config()
    append_audit_via_api(actor, "settings.llm_save",
                         {"base": c["base"], "model": c["model"], "keyChanged": bool(key)})
    return J({"ok": True, "base": c["base"], "model": c["model"]})


@app.get("/settings/email")
def settings_email_get():
    """读取 SMTP 设置（密码只返回是否已设置，不回传明文）。"""
    from core import mailer
    from core.settings import get as sget
    st = mailer.status()
    return J({
        "host": sget("smtp.host") or st.get("host", ""),
        "port": int(sget("smtp.port") or st.get("port") or 465),
        "secure": (sget("smtp.secure") or st.get("secure") or "ssl").lower(),
        "user": sget("smtp.user") or st.get("user", ""),
        "fromName": sget("smtp.from_name") or st.get("fromName") or "LEDU",
        "configured": bool((sget("smtp.host") or st.get("host")) and (sget("smtp.user") or st.get("user"))),
        "hasPassword": bool(sget("smtp.password") or st.get("hasPassword")),
        "source": "settings" if sget("smtp.host") else ("env" if st.get("host") else "none"),
    })


@app.post("/settings/email")
def settings_email_save():
    """保存 SMTP 设置。界面优先，.env 只作初始值。"""
    require_writer()
    if current_role() != "admin":
        raise ValueError("只有管理员可以修改邮件设置")
    from core.settings import set as sset, clear_cache
    p = request.get_json(force=True) or {}
    actor = str(p.get("actor") or "system")
    host = str(p.get("host") or "").strip()
    user = str(p.get("user") or "").strip()
    password = p.get("password")
    from_name = str(p.get("fromName") or "LEDU").strip()
    secure = str(p.get("secure") or "ssl").lower()
    try:
        port = int(p.get("port") or 465)
        if not (1 <= port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("端口应是 1-65535 的数字")
    if secure not in ("ssl", "tls", "none"):
        raise ValueError("加密方式应为 ssl / tls / none")
    if host and not re.fullmatch(r"[A-Za-z0-9.\-]+", host):
        raise ValueError("SMTP 主机名格式不正确")
    sset("smtp.host", host, actor)
    sset("smtp.port", str(port), actor)
    sset("smtp.secure", secure, actor)
    sset("smtp.user", user, actor)
    sset("smtp.from_name", from_name, actor)
    if password:                                   # 空密码表示「不改」
        sset("smtp.password", str(password), actor)
    clear_cache()
    append_audit_via_api(actor, "settings.email_save",
                         {"host": host, "port": port, "user": user,
                          "secure": secure, "passwordChanged": bool(password)})
    from core import mailer
    return J({"ok": True, "smtp": mailer.status()})


@app.post("/settings/llm/test")
def settings_llm_test():
    """用当前配置发一次最小请求，确认能用。"""
    from core.agents import llm as _llm
    try:
        r = _llm.chat([{"role": "user", "content": "回复两个字：可用"}], max_tokens=16)
        txt = str((r or {}).get("content") or "").strip()[:40]
        return J({"ok": True, "reply": txt})
    except Exception as ex:
        return J({"ok": False, "error": str(ex)[:200]})


@app.post("/settings/llm/model")
def settings_llm_model():
    """顶部模型切换：只换模型名。"""
    require_writer()
    from core.settings import set_model
    p = request.get_json(force=True) or {}
    model = str(p.get("model") or "").strip()
    if model not in [m["id"] for m in LLM_MODELS]:
        raise ValueError("不支持的模型")
    set_model(model, str(p.get("actor") or "system"))
    append_audit_via_api(str(p.get("actor") or "system"), "settings.llm_model", {"model": model})
    return J({"ok": True, "model": model})


# ---------------------------------------------------------------- 智能体执行工具绑定
# tools_write 需要 api 层才有完整校验的实现（分录、收付款、银行匹配），
# 在模块加载完成后注入，避免 core 反向依赖 api。
from core.agents import tools_write as _agent_write_tools
_agent_write_tools.bind("create_journal", lambda p: journal_create_core(p))
_agent_write_tools.bind("create_payment", lambda p: payment_create_core(p))
_agent_write_tools.bind("confirm_bank_match", lambda p: bank_confirm_match_core(p))
_agent_write_tools.bind("import_bank_statement", lambda p: bank_import_core(p))
_agent_write_tools.bind("match_bank_lines", lambda acct_id: bank_match_core(acct_id))
_agent_write_tools.bind("post_one_click", lambda kind, doc_id, actor, role:
                        one_click_post(kind, doc_id, actor, role))
from core.agents import toolbox as _agent_toolbox
_agent_toolbox.bind("bank_match_suggestions", lambda acct: bank_match_core(int(acct or 1)))


def _agent_read_json(path: str) -> dict:
    """智能体只读通道：复用正式 GET 接口的实体隔离、字段和报表口径。"""
    with app.test_client() as client:
        response = client.get(path, headers={"X-Ledu-Token": API_TOKEN})
    data = response.get_json() or {}
    if response.status_code >= 300:
        raise ValueError(data.get("message") or f"读取失败（{response.status_code}）")
    return data


def _agent_workbench_todo(args: dict) -> dict:
    """待办/复核/逾期队列：去掉人工页链接，只给工作台可执行依据。"""
    section = str((args or {}).get("section") or "all")
    if section not in ("all", "pending", "overdue", "draft", "bank"):
        raise ValueError("section 只能是 all / pending / overdue / draft / bank")
    data = _agent_read_json("/workbench/todo")
    items = []
    for original in data.get("items") or []:
        kind = str(original.get("kind") or "")
        if section == "pending" and kind != "pending_review":
            continue
        if section == "overdue" and kind != "overdue_ar":
            continue
        if section == "draft" and not kind.endswith("_draft"):
            continue
        if section == "bank" and kind != "bank_unmatched":
            continue
        item = {k: v for k, v in original.items() if k != "href"}
        if kind.endswith("_draft"):
            item["availableActions"] = ["document_detail 查看完整单据",
                                        "用户明确确认后用 post_document 提交复核、批准并记账"]
        elif kind == "overdue_ar":
            item["availableActions"] = ["document_detail 查看发票与未结金额",
                                        "跟进催收；收款及核销请切换到出纳岗位"]
        elif kind == "pending_review":
            item["availableActions"] = ["用 document_detail 按 docNo 查看真实原单据",
                                        "先按 reason 解除阻断；阻断解除后由用户明确确认再提交复核或记账"]
        elif kind == "bank_unmatched":
            item["availableActions"] = ["bank_lines 逐笔读取流水",
                                        "bank_match_suggestions 获取候选单据和匹配依据"]
        items.append(item)
    # 数量与口径放在 items 前面：即使模型上下文截断长列表，也能看到真实数量，
    # 不得自行数行或猜测一个与 visibleCount 不同的合计。
    return {"section": section, "visibleCount": len(items),
            "summary": data.get("summary") or {}, "today": data.get("today"),
            "note": ("所有后续操作都留在 AI 工作台；此工具只读，未修改业务数据。"
                     "数量只能引用 visibleCount 与 summary，不得自行估算。"),
            "items": items}


def _agent_period_close_status(args: dict) -> dict:
    """月结状态只读查询，与执行步骤的 run_period_close 写工具严格分离。"""
    import urllib.parse as _up
    period = str((args or {}).get("period") or date.today().strftime("%Y-%m"))
    data = _agent_read_json("/period-close?" + _up.urlencode({"period": period}))
    data["note"] = "这是只读状态；只有用户明确要求执行月结步骤时才可使用 run_period_close。"
    return data


def _agent_document_detail(args: dict) -> dict:
    """按单号给工作台返回完整单据、明细与可继续执行的真实动作。"""
    requested = str((args or {}).get("kind") or "").strip().lower()
    doc_no = str((args or {}).get("docNo") or "").strip()
    if not doc_no:
        raise ValueError("必须提供完整单号")
    specs = {
        "invoice": ("invoices", "invoice_id", "invoice_no", "/invoices/"),
        "bill": ("bills", "bill_id", "bill_no", "/bills/"),
    }
    if requested and requested not in specs:
        raise ValueError("kind 只能是 invoice / bill")
    entity = entity_or_404()
    matches = []
    for kind in ([requested] if requested else list(specs)):
        table, id_col, no_col, path = specs[kind]
        row = query_one(f"SELECT {id_col} AS id FROM {table} WHERE entity_id=%s AND {no_col}=%s",
                        (entity["entity_id"], doc_no))
        if row:
            matches.append((kind, int(row["id"]), path))
    if not matches:
        raise ValueError(f"找不到单号为 {doc_no} 的发票或账单")
    if len(matches) > 1:
        raise ValueError("该单号同时存在于发票和账单，请补充 kind")
    kind, doc_id, path = matches[0]
    document = _agent_read_json(f"{path}{doc_id}")
    outstanding = round(float(document.get("gross_original") or 0)
                        - float(document.get("settled_original") or 0), 2)
    actions = ["export_document_pdf 导出三语 PDF"]
    if document.get("status") == "draft":
        actions.insert(0, "用户明确确认后用 post_document 提交复核、批准并记账")
    elif outstanding > 0:
        actions.append("切换到出纳岗位登记收款/付款并核销")
    result = {"kind": kind, "docId": doc_id, "docNo": doc_no,
              "document": document, "outstanding": outstanding,
              "currency": document.get("currency"), "availableActions": actions,
              "note": "字段和明细来自正式单据 GET 接口；此工具只读，不提供人工页面链接。"}
    # 到期天数由代码计算，模型不得把「大约一年」等估算当成真实账龄。
    try:
        due = date.fromisoformat(str(document.get("due_date") or "")[:10])
    except ValueError:
        due = None
    if due is not None:
        days_overdue = (date.today() - due).days
        result["dueDate"] = due.isoformat()
        result["daysOverdue"] = max(0, days_overdue)
        if days_overdue > 0:
            result["agingBucket"] = ("1-30" if days_overdue <= 30 else
                                     "31-60" if days_overdue <= 60 else
                                     "61-90" if days_overdue <= 90 else "91+")
    return result


def _agent_reconciliation_detail(args: dict) -> dict:
    """按导入批次还原对账结果，避免用当前未匹配队列冒充历史明细。"""
    entity = entity_or_404()
    try:
        batch_id = int((args or {}).get("batchId") or 0)
    except (TypeError, ValueError):
        raise ValueError("batchId 必须是整数")
    if batch_id > 0:
        batch = query_one("""SELECT batch_id, bank_account_id, account_currency, file_name,
                                    period_start, period_end, line_count, status, imported_at
                               FROM statement_imports
                              WHERE entity_id=%s AND batch_id=%s""",
                          (entity["entity_id"], batch_id))
        if not batch:
            raise ValueError("找不到该对账批次，或批次不属于当前实体")
    else:
        batch = query_one("""SELECT batch_id, bank_account_id, account_currency, file_name,
                                    period_start, period_end, line_count, status, imported_at
                               FROM statement_imports WHERE entity_id=%s
                              ORDER BY imported_at DESC, batch_id DESC LIMIT 1""",
                          (entity["entity_id"],))
    if not batch:
        return {"batchId": None, "summary": {"total": 0, "matched": 0, "unmatched": 0,
                                             "pending": 0, "excluded": 0},
                "note": "当前实体尚未导入银行对账单，没有可还原的历史对账批次。", "lines": []}

    rows = query("""SELECT bl.line_id, bl.txn_date, bl.bank_ref, bl.counterparty_name,
                           bl.amount_original, bl.currency, bl.amount_functional,
                           bl.match_status, bl.matched_type, bl.matched_id,
                           bl.match_rule, bl.match_confidence, bl.matched_currency,
                           bl.matched_amount_at_rate, bl.match_rate, bl.match_rate_date,
                           i.invoice_no, b.bill_no
                      FROM bank_lines bl
                      LEFT JOIN invoices i ON bl.matched_type='invoice'
                         AND i.invoice_id=bl.matched_id AND i.entity_id=bl.entity_id
                      LEFT JOIN bills b ON bl.matched_type='bill'
                         AND b.bill_id=bl.matched_id AND b.entity_id=bl.entity_id
                     WHERE bl.entity_id=%s AND bl.statement_import_batch_id=%s
                     ORDER BY bl.txn_date, bl.line_id""",
                 (entity["entity_id"], batch["batch_id"]))
    lines = []
    by_status = {}
    for row in rows:
        status = str(row["match_status"] or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        doc_no = row["invoice_no"] or row["bill_no"]
        item = {"lineId": int(row["line_id"]), "txnDate": str(row["txn_date"]),
                "bankRef": row["bank_ref"], "counterparty": row["counterparty_name"],
                "amount": float(dec(row["amount_original"])), "currency": row["currency"],
                "functionalAmount": float(dec(row["amount_functional"])),
                "matchStatus": status, "matchedType": row["matched_type"],
                "matchedDocId": int(row["matched_id"]) if row["matched_id"] is not None else None,
                "matchedDocNo": doc_no, "matchRule": row["match_rule"],
                "matchConfidence": row["match_confidence"],
                "matchedCurrency": row["matched_currency"],
                "matchedAmountAtRate": (float(dec(row["matched_amount_at_rate"]))
                                        if row["matched_amount_at_rate"] is not None else None),
                "matchRate": (float(dec(row["match_rate"]))
                              if row["match_rate"] is not None else None),
                "matchRateDate": str(row["match_rate_date"]) if row["match_rate_date"] else None}
        if status in ("unmatched", "pending"):
            item["availableActions"] = ["bank_match_suggestions 获取当前候选与依据",
                                        "候选确认后由出纳岗位核销"]
        elif status == "matched" and doc_no:
            item["availableActions"] = ["document_detail 按 matchedDocNo 查看已匹配单据"]
        lines.append(item)
    summary = {"total": len(lines), "matched": by_status.get("matched", 0),
               "unmatched": by_status.get("unmatched", 0),
               "pending": by_status.get("pending", 0),
               "excluded": by_status.get("excluded", 0)}
    return {"batchId": int(batch["batch_id"]), "bankAccountId": int(batch["bank_account_id"]),
            "fileName": batch["file_name"], "accountCurrency": batch["account_currency"],
            "periodStart": str(batch["period_start"]) if batch["period_start"] else None,
            "periodEnd": str(batch["period_end"]) if batch["period_end"] else None,
            "importedAt": str(batch["imported_at"]), "importStatus": batch["status"],
            "importedLineCount": int(batch["line_count"]), "summary": summary,
            "note": ("这是该导入批次当前留存的逐笔匹配结果，只读且不含人工页面链接；"
                     "summary 是真实数量，未匹配项的新候选须另用 bank_match_suggestions。"),
            "lines": lines}


_agent_toolbox.bind("workbench_todo", _agent_workbench_todo)
_agent_toolbox.bind("period_close_status", _agent_period_close_status)
_agent_toolbox.bind("document_detail", _agent_document_detail)
_agent_toolbox.bind("reconciliation_detail", _agent_reconciliation_detail)


def _export_report_pdf(kind: str, frm: str = "", to: str = "", lang: str = "") -> dict:
    """智能体的「导出 PDF」：生成后返回指令台里可直接点的下载地址。

    语言三选一（简体 / 繁體 / 英文）：没指定就跟随当前界面语言，
    报表模块本来就支持，别让用户以为只能出英文。
    """
    import urllib.parse as _up
    from flask import g as _g
    e = entity_or_404()
    year = date.today().year
    frm = frm or f"{year}-01-01"
    to = to or date.today().isoformat()
    lang = (lang or getattr(_g, "ledu_lang", "") or "en").strip()
    if lang not in ("en", "zh_hk", "zh_cn"):
        lang = "en"
    # 用户没明说要哪种语言时，以界面语言为准：
    # 繁體界面下模型默认挑的「简体」不该覆盖它。
    text = str(getattr(_g, "ledu_text", "") or "")
    asked = any(k in text for k in ("简体", "簡體", "simplified", "简体字",
                                    "繁体", "繁體", "traditional", "繁体字",
                                    "英文", "english"))
    ui = str(getattr(_g, "ledu_lang", "") or "").strip()
    if not asked and ui in ("en", "zh_hk", "zh_cn"):
        lang = ui
    if kind == "statements":
        path = f"/reports/statements/pdf?from={frm}&to={to}&lang={lang}"
        name = f"Financial-Statements-{frm}-{to}.pdf"
    else:
        path = f"/reports/pdf?kind={kind}&from={frm}&to={to}&lang={lang}"
        name = f"{kind}-{frm}-{to}.pdf"
    # 先渲染一次：拿不到就当场报错，不要给用户一个死链接
    r = app.test_client().get(path, headers={"X-Ledu-Token": API_TOKEN})
    if r.status_code != 200:
        raise ValueError(f"报表生成失败（{r.status_code}）：{kind}")
    href = "/pdf/reports.php?u=" + _up.quote(path, safe="")
    return {"ok": True, "kind": kind, "from": frm, "to": to, "lang": lang,
            "fileName": name, "bytes": len(r.data), "href": href,
            "note": "点链接即可下载/预览 PDF"}


_agent_toolbox.bind("export_pdf", _export_report_pdf)


def _financial_analysis_for_agent(args: dict) -> dict:
    """财务主管完整分析：不再嵌套调用 LLM，返回真实摘要与受控下载地址。"""
    import urllib.parse as _up
    from flask import g as _g
    opts = dict(args or {})
    opts["period"] = str(opts.get("period") or "fiscal_year")
    opts["lang"] = str(opts.get("lang") or getattr(_g, "ledu_lang", "") or "zh_cn")
    opts["ai"] = "0"
    report = _build_analysis(opts)
    fmt = str(opts.get("format") or "pdf").lower()
    path = _analysis_export_file(report, fmt)
    query = {k: str(opts.get(k) or "") for k in ("period", "month", "year", "from", "to")}
    query.update({"lang": report["lang"], "ai": "0", "format": fmt})
    return {
        "ok": True, "kind": "financial_analysis", "format": fmt,
        "fileName": path.name, "bytes": path.stat().st_size,
        "href": "/pdf/analysis.php?" + _up.urlencode(query),
        "from": report["period"]["start"], "to": report["period"]["end"],
        "lang": report["lang"], "periodType": report["period"]["type"],
        "currency": report["entity"]["currency"], "summary": report["analysis"]["dataSummary"],
        "kpis": report["kpis"], "reconciled": report["reconciled"],
        "exceptions": [{"code": x["code"], "label": x["label"],
                        "difference": x["difference"], "detail": x["detail"]}
                       for x in report["checks"] if not x["ok"]],
        "analysisStatus": report["analysis"]["status"],
        "note": {
            "zh_cn": "金额与摘要来自确定性报表；未使用 AI。点链接即可下载完整报告。",
            "zh_hk": "金額與摘要來自確定性報表；未使用 AI。點連結即可下載完整報告。",
            "en": "Amounts and the summary come from deterministic statements; AI was not used. Use the link to download the full report.",
        }[report["lang"]],
    }


_agent_toolbox.bind("financial_analysis", _financial_analysis_for_agent)


def _export_document_pdf(kind, doc_no, lang="zh_cn"):
    """按单号导出单张单据 PDF：发票 / 账单 / 报价单 / 贷记单。

    AI 之前只会导报表，用户说「把 LEDU-INV-… 导出 PDF」就只能回「我没有这个工具」。
    这里按单号查 id，先渲染一次确认能出文件，再给代理链接。
    """
    import urllib.parse as _up
    kind = str(kind or "").strip().lower()
    no = str(doc_no or "").strip()
    if not no:
        raise ValueError("必须提供单号")
    table, idcol, path = {
        "invoice": ("invoices", "invoice_id", "/invoices/{}/pdf"),
        "bill":    ("bills", "bill_id", "/bills/{}/pdf"),
        "quote":   ("quotes", "quote_id", "/quotes/{}/pdf"),
        "credit":  ("credit_notes", "credit_id", "/credit-notes/{}/pdf"),
    }.get(kind) or (None, None, None)
    if not table:
        raise ValueError("kind 只能是 invoice / bill / quote / credit")
    e = entity_or_404()
    row = query_one(f"SELECT {idcol} AS id FROM {table} WHERE entity_id=%s AND "
                    + ("invoice_no" if kind == "invoice" else
                       "bill_no" if kind == "bill" else
                       "quote_no" if kind == "quote" else "credit_no") + "=%s",
                    (e["entity_id"], no))
    if not row:
        raise ValueError(f"找不到单号为 {no} 的{ {'invoice':'发票','bill':'账单','quote':'报价单','credit':'贷记单'}[kind] }")
    target = path.format(int(row["id"])) + f"?lang={lang or 'zh_cn'}"
    r = app.test_client().get(target, headers={"X-Ledu-Token": API_TOKEN})
    if r.status_code != 200:
        raise ValueError(f"单据 PDF 生成失败（{r.status_code}）：{no}")
    href = "/pdf/reports.php?u=" + _up.quote(target, safe="")
    return {"ok": True, "kind": kind, "docNo": no, "bytes": len(r.data),
            "href": href, "note": "点链接即可下载/预览这份单据的 PDF"}

_agent_toolbox.bind("export_document_pdf", _export_document_pdf)


def _post_opening_entry(entry_date, description, lines, actor="system"):
    """上年结转：一条 source=opening 的分录。不平直接拒绝，不做「先记了再调」。"""
    dr = round(sum(float(x.get("debit") or 0) for x in lines), 2)
    cr = round(sum(float(x.get("credit") or 0) for x in lines), 2)
    if abs(dr - cr) > 0.005:
        raise ValueError(f"借贷不平：借 {dr:,.2f} / 贷 {cr:,.2f}，差 {dr - cr:,.2f}")
    res = journal_create_core({"entryDate": entry_date, "description": description,
                               "lines": lines, "actor": actor,
                               "sourceType": "opening"})
    # journal_create_core 返回的是 Flask Response，这里要的是数据
    return res.get_json() if hasattr(res, "get_json") else res


_agent_write_tools.bind("post_opening", _post_opening_entry)
_agent_write_tools.bind("register_attachment", register_attachment)


def _agent_save_party(kind, args):
    """AI 建客户/供应商：走同一套保存逻辑，编码自动生成。"""
    import urllib.request as _rq
    name = str(args.get("name") or args.get("partyName") or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    payload = {"name": name,
               "email": args.get("email") or None,
               "defaultCurrency": args.get("currency") or "HKD",
               "paymentTermsDays": int(args.get("paymentTermsDays") or 30),
               "actor": str(args.get("actor") or "agent")}
    path = "/customers" if kind == "customer" else "/vendors"
    with app.test_client() as c:
        r = c.post(path, json=payload, headers={"X-Ledu-Token": API_TOKEN,
                                                "X-Ledu-Role": "admin"})
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "保存失败")
    return {"ok": True, "kind": kind, "name": name, "id": data.get("customerId") or data.get("vendorId")}


def _agent_create_simple_doc(kind, args):
    """AI 开报价单 / 贷记单。"""
    name = str(args.get("partyName") or "").strip()
    if not name:
        raise ValueError("往来单位不能为空")
    if kind == "quote":
        payload = {"customerName": name, "quoteDate": args.get("date") or None,
                   "currency": args.get("currency") or "HKD",
                   "lines": args.get("lines") or [], "actor": "agent"}
        path = "/quotes"
    else:
        payload = {"creditType": args.get("creditType") or "customer",
                   "partyName": name, "creditDate": args.get("date") or None,
                   "currency": args.get("currency") or "HKD",
                   "amountOriginal": float(args.get("amountOriginal") or 0),
                   "reason": args.get("reason") or None, "actor": "agent"}
        path = "/credit-notes"
    with app.test_client() as c:
        r = c.post(path, json=payload, headers={"X-Ledu-Token": API_TOKEN,
                                               "X-Ledu-Role": "admin"})
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "建单失败")
    return {"ok": True, "kind": kind, "docNo": data.get("quoteNo") or data.get("creditNo"),
            "id": data.get("quoteId") or data.get("creditId"), "party": name}


def _agent_export_csv(args):
    """AI 导出 CSV：复用 /export，返回文件与哈希。"""
    import urllib.parse as _up
    payload = {"kind": args.get("kind") or "invoices",
               "purpose": args.get("purpose") or "AI 导出",
               "recipient": args.get("recipient") or "内部",
               "actor": "agent"}
    with app.test_client() as c:
        r = c.post("/export", json=payload, headers={"X-Ledu-Token": API_TOKEN,
                                                    "X-Ledu-Role": "admin"})
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "导出失败")
    href = "/download.php?f=" + _up.quote(str(data.get("file") or ""), safe="") if data.get("file") else ""
    return {"ok": True, **data, "href": href}

def _agent_update_party(args):
    """改客户/供应商：按名称找到 id，再走同一条保存通道。"""
    kind = args.get("kind") or "customer"
    name = str(args.get("name") or "").strip()
    table = "customers" if kind == "customer" else "vendors"
    col = "customer_name" if kind == "customer" else "vendor_name"
    idc = "customer_id" if kind == "customer" else "vendor_id"
    e = entity_or_404()
    row = query_one(f"SELECT * FROM {table} WHERE entity_id=%s AND {col}=%s LIMIT 1",
                    (e["entity_id"], name))
    if not row:
        raise ValueError(f"找不到{ '客户' if kind=='customer' else '供应商' }：{name}")
    payload = {"customerId" if kind == "customer" else "vendorId": int(row[idc]),
               "customerCode" if kind == "customer" else "vendorCode":
                   row["customer_code" if kind == "customer" else "vendor_code"],
               "customerName" if kind == "customer" else "vendorName":
                   args.get("newName") or row[col],
               "email": args.get("email") or row.get("email"),
               "defaultCurrency": args.get("currency") or row.get("default_currency") or "HKD",
               "paymentTermsDays": int(args.get("paymentTermsDays") or row.get("payment_terms_days") or 30),
               "status": args.get("status") or row.get("status") or "active",
               "actor": "agent"}
    with app.test_client() as c:
        r = c.post("/customers" if kind == "customer" else "/vendors", json=payload,
                   headers={"X-Ledu-Token": API_TOKEN, "X-Ledu-Role": "admin"})
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "保存失败")
    return {"ok": True, "kind": kind, "name": args.get("newName") or name,
            "status": payload["status"], "id": int(row[idc])}


def _agent_create_order(args):
    """开销售/采购订单。"""
    payload = {"direction": args.get("direction") or "sales",
               "partyName": args.get("partyName"),
               "orderDate": args.get("date") or None,
               "currency": args.get("currency") or "HKD",
               "lines": args.get("lines") or [], "actor": "agent"}
    with app.test_client() as c:
        r = c.post("/orders", json=payload, headers={"X-Ledu-Token": API_TOKEN, "X-Ledu-Role": "admin"})
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "建单失败")
    return {"ok": True, "kind": payload["direction"], "orderNo": data.get("orderNo"),
            "id": data.get("orderId")}


def _agent_manage_bank_rule(args):
    """银行规则：列表 / 新建 / 删除。"""
    act = args.get("action") or "list"
    hdr = {"X-Ledu-Token": API_TOKEN, "X-Ledu-Role": "admin"}
    with app.test_client() as c:
        if act == "list":
            r = c.get("/bank-rules", headers=hdr)
        elif act == "create":
            r = c.post("/bank-rules", json={
                "name": args.get("name"), "matchText": args.get("matchText"),
                "counterAccount": args.get("counterAccount"),
                "matchField": args.get("matchField") or "any", "actor": "agent"}, headers=hdr)
        else:
            r = c.post(f"/bank-rules/{int(args.get('ruleId') or 0)}/delete", json={}, headers=hdr)
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "操作失败")
    return {"ok": True, "action": act, **data}


def _agent_set_fx_rate(args):
    """手工补录汇率。"""
    payload = {"fromCcy": str(args.get("fromCcy") or "").upper(),
               "toCcy": str(args.get("toCcy") or "HKD").upper(),
               "rate": float(args.get("rate") or 0),
               "rateDate": args.get("rateDate")}
    with app.test_client() as c:
        r = c.post("/fx/rates", json=payload, headers={"X-Ledu-Token": API_TOKEN, "X-Ledu-Role": "admin"})
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "写入汇率失败")
    return {"ok": True, **payload, "result": data}


def _agent_run_period_close(args):
    """月结：看状态或跑一步。"""
    period = args.get("period") or date.today().strftime("%Y-%m")
    hdr = {"X-Ledu-Token": API_TOKEN, "X-Ledu-Role": "admin"}
    with app.test_client() as c:
        if (args.get("action") or "list") == "list":
            r = c.get(f"/period-close?period={period}", headers=hdr)
        else:
            r = c.post("/period-close/run",
                       json={"period": period, "step": args.get("step") or "all", "actor": "agent"},
                       headers=hdr)
    data = r.get_json() or {}
    if r.status_code >= 300:
        raise ValueError(data.get("message") or "月结失败")
    return {"ok": True, "period": period, "action": args.get("action") or "list", **data}



_agent_write_tools.bind("save_customer", lambda a: _agent_save_party("customer", a))
_agent_write_tools.bind("save_vendor", lambda a: _agent_save_party("vendor", a))
_agent_write_tools.bind("create_quote", lambda a: _agent_create_simple_doc("quote", a))
_agent_write_tools.bind("create_credit", lambda a: _agent_create_simple_doc("credit", a))
_agent_write_tools.bind("export_csv", _agent_export_csv)
_agent_write_tools.bind("update_party", _agent_update_party)
_agent_write_tools.bind("create_order", _agent_create_order)
_agent_write_tools.bind("manage_bank_rule", _agent_manage_bank_rule)
_agent_write_tools.bind("set_fx_rate", _agent_set_fx_rate)
_agent_write_tools.bind("run_period_close", _agent_run_period_close)




@app.get("/company/letterhead/pdf")
def company_letterhead_pdf():
    """公司抬头纸（A4）：Logo 彩色，其余黑白。"""
    from core.pdf import letterhead_html, render
    from flask import send_file as _send
    e = entity_or_404()
    ent = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(e).items()}
    lang = request.args.get("lang") or "en"
    if lang not in ("en", "zh_cn", "zh_hk"):
        lang = "en"
    name = (ent.get("entity_code") or "company").replace(" ", "-")
    path = render(letterhead_html(ent, lang), f"letterhead-{name}-{lang}.pdf")
    return _send(str(path), mimetype="application/pdf", as_attachment=False,
                 download_name=f"letterhead-{name}.pdf")


LOGO_WEB_DIR = WEB_ASSETS_DIR


def _write_logo_variants(src: Path):
    """把上传的 Logo 转成网页与 PDF 用的多档尺寸。

    统一转成带透明通道的 PNG：白底会被去掉，深色主题下不会出现白方块。
    """
    from PIL import Image
    LOGO_WEB_DIR.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    im.load()
    if im.mode in ("RGBA", "LA"):
        rgba = im.convert("RGBA")
    else:
        rgba = im.convert("RGBA")
        # 纯白背景转透明
        datas = []
        for px in rgba.getdata():
            if px[0] > 246 and px[1] > 246 and px[2] > 246:
                datas.append((255, 255, 255, 0))
            else:
                datas.append(px)
        rgba.putdata(datas)

    # 裁掉四周透明边，让图形占满画布
    bbox = rgba.split()[-1].getbbox()
    if bbox:
        rgba = rgba.crop(bbox)

    side = max(rgba.size) + max(4, int(max(rgba.size) * 0.06))
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2), rgba)

    out = {}
    for name, size in (("logo-custom-512.png", 512), ("logo-custom-192.png", 192),
                       ("logo-custom-64.png", 64)):
        p = LOGO_WEB_DIR / name
        canvas.resize((size, size), Image.LANCZOS).save(p, optimize=True)
        out[name] = str(p)
    # favicon 用白底，避免透明在浏览器标签上发灰
    fav = Image.new("RGB", (32, 32), (255, 255, 255))
    small = canvas.resize((32, 32), Image.LANCZOS)
    fav.paste(small, (0, 0), small)
    fav.save(LOGO_WEB_DIR / "favicon.png", optimize=True)
    return out


@app.post("/company/logo")
def company_logo_upload():
    """登记并应用自定义 Logo（文件由 PHP 落盘）。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    path = str(p.get("storagePath") or "").strip()
    if not path or not Path(path).is_file():
        raise ValueError("文件不存在")
    sha = str(p.get("sha256") or "").strip()
    if len(sha) != 64:
        raise ValueError("SHA-256 缺失或不合法")
    try:
        variants = _write_logo_variants(Path(path))
    except Exception as ex:
        raise ValueError(f"不是可识别的图片文件：{ex}")

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE entities SET logo_path=%s, logo_sha256=%s,
                              logo_updated_at=NOW(3), updated_at=NOW(3)
                            WHERE entity_id=%s""", (path[:500], sha, e["entity_id"]))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "company.logo_update", "object_type": "entities",
                            "object_id": str(e["entity_id"]),
                            "detail": {"fileName": p.get("fileName"), "sha256": sha}})
    return J({"logoPath": path, "variants": variants})


@app.delete("/company/logo")
def company_logo_reset():
    """恢复内置 Logo。"""
    require_writer()
    e = entity_or_404()
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE entities SET logo_path=NULL, logo_sha256=NULL,
                              logo_updated_at=NOW(3) WHERE entity_id=%s""", (e["entity_id"],))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": "system",
                            "action": "company.logo_reset", "object_type": "entities",
                            "object_id": str(e["entity_id"]), "detail": {}})
    for name in ("logo-custom-512.png", "logo-custom-192.png", "logo-custom-64.png"):
        f = LOGO_WEB_DIR / name
        if f.is_file():
            f.unlink()
    # favicon 还原为内置
    from PIL import Image
    src = LOGO_WEB_DIR / "logo-512.png"
    if src.is_file():
        Image.open(src).convert("RGB").resize((32, 32), Image.LANCZOS).save(
            LOGO_WEB_DIR / "favicon.png", optimize=True)
    return J({"reset": True})


@app.get("/company/name-variants")
def company_name_variants():
    """公司名称的三语写法。中文名以繁体为法定版本，简体供简体界面显示。"""
    e = entity_or_404()
    zh = str(e.get("legal_name_zh") or "")
    cn = hk = zh
    if zh:
        try:
            from opencc import OpenCC
            hk = OpenCC("s2hk").convert(zh)   # 幂等：已是繁体则原样返回
            cn = OpenCC("hk2s").convert(hk)   # 转回简体
        except Exception:
            pass
    return J({"zhCn": cn, "zhHk": hk, "en": e["entity_name"]})


@app.post("/accounts")
def account_create():
    """新增会计科目。编码唯一，需指定分类与借贷方向。"""
    require_writer()
    e = entity_or_404()
    p = request.get_json(force=True) or {}
    code = str(p.get("code") or "").strip()
    name = str(p.get("name") or "").strip()
    if not code or not code.isdigit() or not (3 <= len(code) <= 6):
        raise ValueError("科目编码须为 3–6 位数字")
    if not name:
        raise ValueError("请填写科目名称")
    cat = str(p.get("category") or "").strip()
    if cat not in ("asset", "liability", "equity", "revenue", "cogs", "expense"):
        raise ValueError("科目分类不合法")
    bal = str(p.get("normalBalance") or "").strip()
    if bal not in ("debit", "credit"):
        raise ValueError("余额方向不合法")
    parent = str(p.get("parent") or "").strip() or None
    if parent and not query_one("SELECT 1 x FROM accounts WHERE entity_id=%s AND account_code=%s",
                                (e["entity_id"], parent)):
        raise ValueError("上级科目不存在")

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 x FROM accounts WHERE entity_id=%s AND account_code=%s",
                        (e["entity_id"], code))
            if cur.fetchone():
                raise ValueError(f"科目 {code} 已存在")
            cur.execute("""INSERT INTO accounts
                (account_code, entity_id, account_name, name_zh_cn, name_zh_hk, name_en,
                 category, fs_line_item, normal_balance, parent_account_code, is_active)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (code, e["entity_id"], name, name, name,
                 str(p.get("nameEn") or name), cat,
                 str(p.get("fsLineItem") or "").strip() or "other_expense",
                 bal, parent))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": p.get("actor", "system"),
                            "action": "account.create", "object_type": "accounts",
                            "object_id": code, "detail": {"name": name, "category": cat}})
    return J({"code": code, "name": name})


@app.delete("/accounts/<code>")
def account_delete(code):
    """删除会计科目。已有分录、下级科目或绑定银行账户的科目不允许删除。"""
    require_writer()
    e = entity_or_404()
    row = query_one("SELECT * FROM accounts WHERE entity_id=%s AND account_code=%s",
                    (e["entity_id"], code))
    if not row:
        raise ValueError("科目不存在")
    used = query_one("""SELECT COUNT(*) n FROM journal_lines l
                          JOIN journal_entries je ON je.entry_id=l.entry_id
                         WHERE je.entity_id=%s AND l.account_code=%s""", (e["entity_id"], code))["n"]
    if int(used) > 0:
        raise ValueError(f"科目 {code} 已有 {int(used)} 条分录，不能删除；如需停用请用「停用」")
    kids = query_one("SELECT COUNT(*) n FROM accounts WHERE entity_id=%s AND parent_account_code=%s",
                     (e["entity_id"], code))["n"]
    if int(kids) > 0:
        raise ValueError(f"科目 {code} 下有 {int(kids)} 个子科目，请先处理子科目")
    bank = query_one("SELECT COUNT(*) n FROM bank_accounts WHERE entity_id=%s AND account_code=%s",
                     (e["entity_id"], code))["n"]
    if int(bank) > 0:
        raise ValueError(f"科目 {code} 已绑定银行账户，不能删除")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM accounts WHERE entity_id=%s AND account_code=%s",
                        (e["entity_id"], code))
        append_audit(conn, {"entity_id": e["entity_id"], "actor": "system",
                            "action": "account.delete", "object_type": "accounts",
                            "object_id": code, "detail": {"name": row["account_name"]}})
    return J({"deleted": code})

if __name__ == "__main__":
    app.run(host=API_HOST, port=API_PORT, debug=False, threaded=True)

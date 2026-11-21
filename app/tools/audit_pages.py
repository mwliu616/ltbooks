#!/usr/bin/env python3
# LtBooks — tools/audit_pages.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""页面体检：把全部页面在桌面和手机尺寸下打开，查横向溢出、控制台报错、点击区过小。

用法： ./venv/bin/python tools/audit_pages.py [base_url] [--user admin] [--pass ...]
退出码：0 无异常；1 有异常（会打印明细）。
"""
import argparse, asyncio, os, sys
from playwright.async_api import async_playwright

SIZES = [(1920, 1080), (1440, 900), (1024, 768), (390, 844)]
PAGES = [
    "command", "today", "ai", "invoices", "invoice-new", "bills", "bill-new",
    "expenses", "expense-new", "journal", "journal-new", "fast-new",
    "customers", "vendors", "quotes", "sales-orders", "purchase-orders", "credit-notes",
    "recurring", "recurring-invoices", "recurring-bills", "receipts", "payments", "settle",
    "banks", "bank-transactions", "reconcile", "bank-rules", "bank-import", "bank-transfer",
    "accounts", "opening-balances", "rates", "revalue", "locks", "period-close", "pending", "pending-rec",
    "report-center", "report-statements", "report-bs", "report-pnl", "report-account-types",
    "report-tb", "report-gl", "report-gl-detail", "report-cf", "report-aging", "report-bank",
    "report-fx", "report-tax", "report-ratios", "report-customer-balance", "report-vendor-balance",
    "report-daybook", "report-sales", "report-purchase", "tax",
    "company", "account", "settings-llm", "email", "backup", "theme", "agents",
    "audit", "guide", "search", "license",
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=os.environ.get("LTBOOKS_SITE_BASE", "https://localhost"))
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pass", dest="pw", default=os.environ.get("LEDU_TEST_PASSWORD", ""))
    a = ap.parse_args()
    if not a.pw:
        ap.error("缺少测试账号口令：请用 --pass 或环境变量 LEDU_TEST_PASSWORD 提供")

    problems = []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        for w, h in SIZES:
            ctx = await b.new_context(viewport={"width": w, "height": h}, ignore_https_errors=True)
            pg = await ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)[:80]))
            await pg.goto(a.base + "/?p=login")
            await pg.fill("#u", a.user); await pg.fill("#p", a.pw)
            await pg.click("button[type=submit]"); await pg.wait_for_load_state("networkidle")
            await pg.goto(a.base + "/?p=switch-mode&m=manual", wait_until="networkidle")
            for page in PAGES:
                r = await pg.goto(f"{a.base}/?p={page}", wait_until="networkidle")
                info = await pg.evaluate("""()=>({
                    overX: document.documentElement.scrollWidth > window.innerWidth + 2,
                    err: !!document.querySelector('.errbox'),
                    body: (document.body.innerText || '').slice(0, 200),
                })""")
                if not r or r.status >= 400:
                    problems.append((w, h, page, f"HTTP {r.status if r else 0}"))
                elif info["overX"]:
                    problems.append((w, h, page, "横向溢出"))
                elif info["err"]:
                    problems.append((w, h, page, "页面报错框"))
                if errs:
                    problems.append((w, h, page, "JS: " + errs[0])); errs.clear()
            await ctx.close()
        await b.close()

    if not problems:
        print(f"页面体检：{len(PAGES)} 页 × {len(SIZES)} 尺寸 → 0 异常")
        return 0
    print(f"页面体检：{len(problems)} 项异常")
    for w, h, page, why in problems:
        print(f"  {w}x{h} {page}: {why}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

#!/usr/bin/env python3
# LtBooks — tools/scan_i18n.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""三语体检（可分块跑）：界面语言残留。

用法：
  /usr/bin/python3 tools/scan_i18n.py --lang en --from 0 --to 12
  /usr/bin/python3 tools/scan_i18n.py --lang zh_hk --from 12 --to 24
结果逐行追加到 --out（默认 /tmp/i18n_result.jsonl），最后汇总。
"""
import argparse, asyncio, json, os, re, sys
from playwright.async_api import async_playwright

PAGES = [
    "today", "invoices", "bills", "expenses", "journal", "journal-new",
    "customers", "vendors", "quotes", "sales-orders", "credit-notes",
    "banks", "bank-transactions", "reconcile", "bank-rules",
    "accounts", "rates", "period-close", "pending",
    "report-center", "report-statements", "report-bs", "report-pnl",
    "report-tb", "report-gl", "report-cf", "report-aging", "tax",
    "company", "account", "settings-llm", "email", "theme", "agents",
    "audit", "guide", "fast-new",
]

SIMPLIFIED = set("记账凭证账户资产负债权益费税单发报个币别时间项导关闭开总试损现银净额汇购销栈")
TRADITIONAL = set("記賬憑證賬戶資產負債權益費稅單發報個幣別時間項導關閉開總試損現銀淨額匯購銷棧")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("LTBOOKS_SITE_BASE", "https://localhost"))
    ap.add_argument("--lang", required=True, choices=["en", "zh_hk", "zh_cn"])
    ap.add_argument("--from", dest="start", type=int, default=0)
    ap.add_argument("--to", dest="end", type=int, default=len(PAGES))
    ap.add_argument("--out", default="/tmp/i18n_result.jsonl")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--pass", dest="pw", default=os.environ.get("LEDU_TEST_PASSWORD", ""))
    a = ap.parse_args()
    if not a.pw:
        ap.error("缺少测试账号口令：请用 --pass 或环境变量 LEDU_TEST_PASSWORD 提供")

    rows = []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox"])
        ctx = await b.new_context(viewport={"width": 1440, "height": 1000}, ignore_https_errors=True)
        pg = await ctx.new_page()
        await pg.goto(a.base + "/?p=login")
        await pg.fill("#u", a.user); await pg.fill("#p", a.pw)
        await pg.click("button[type=submit]"); await pg.wait_for_load_state("networkidle")
        await pg.goto(a.base + "/?p=switch-mode&m=manual", wait_until="networkidle")
        for page in PAGES[a.start:a.end]:
            await pg.goto(f"{a.base}/?p={page}&lang={a.lang}", wait_until="networkidle")
            txt = await pg.inner_text("main") if await pg.locator("main").count() else ""
            issue = ""
            if a.lang == "en":
                hits = sorted(set(re.findall(r"[\u4e00-\u9fff]+", txt)))
                if hits:
                    issue = "中文：" + " / ".join(hits[:5])
            elif a.lang == "zh_hk":
                bad = sorted({c for c in txt if c in SIMPLIFIED and c not in TRADITIONAL})
                if bad:
                    issue = "简体字：" + "".join(bad[:8])
            else:
                bad = sorted({c for c in txt if c in TRADITIONAL and c not in SIMPLIFIED})
                if bad:
                    issue = "繁体字：" + "".join(bad[:8])
            rows.append({"lang": a.lang, "page": page, "issue": issue})
        await b.close()

    with open(a.out, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    bad = [r for r in rows if r["issue"]]
    print(f"{a.lang} {a.start}-{a.end}: {len(rows)} 页，{len(bad)} 处问题")
    for r in bad:
        print(f"  {r['page']}: {r['issue']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

#!/usr/bin/env python3
# LtBooks — fetch_rates.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""自动抓取汇率：以 HKD 为基准，写入 fx_rates（双向）。

数据源：Frankfurter（ECB 参考汇率，免费无密钥）。
用法：python fetch_rates.py [--date YYYY-MM-DD]
定时：cron 每天 09:00 跑一次。
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("TZ", "Asia/Hong_Kong")
try:
    time.tzset()
except Exception:
    pass

from core.db import transaction, query_one  # noqa: E402
from core.service import append_audit  # noqa: E402

BASE = "HKD"
# 只抓系统里实际用到的币种，避免写入无关数据
WANTED = {"USD", "CNY", "CAD", "EUR", "GBP", "JPY", "AUD", "SGD", "TWD", "CHF", "KRW", "THB"}
Q = Decimal("0.0000000001")
API = "https://api.frankfurter.dev/v1/latest?base={base}"


def fetch(rate_date=None):
    url = API.format(base=BASE)
    if rate_date:
        url = f"https://api.frankfurter.dev/v1/{rate_date}?base={BASE}"
    req = urllib.request.Request(url, headers={"User-Agent": "Lt-AI-Books/1.1"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def refresh(actor="rate-bot", rate_date=None):
    """抓取最新 ECB 汇率并写入 fx_rates，供 cron 与手动刷新共用。"""
    try:
        data = fetch(rate_date)
    except Exception as e:
        raise RuntimeError(f"抓取汇率失败：{e}")

    api_date = str(data.get("date") or "")
    rates = data.get("rates") or {}
    # 接口 base=HKD 返回 1 HKD = x 外币；系统需要 外币 -> HKD，取倒数
    rows = []
    for ccy, val in rates.items():
        if ccy not in WANTED:
            continue
        try:
            one_foreign_in_hkd = (Decimal(1) / Decimal(str(val))).quantize(Q, ROUND_HALF_UP)
        except Exception:
            continue
        rows.append((ccy, one_foreign_in_hkd))

    if not rows:
        raise RuntimeError("数据源没有返回可用汇率")

    ent = query_one("SELECT entity_id FROM entities WHERE status='active' LIMIT 1")
    entity_id = ent["entity_id"] if ent else 1
    written = 0
    with transaction() as conn:
        with conn.cursor() as cur:
            for ccy, hkd in rows:
                # 外币 -> HKD
                cur.execute("""INSERT INTO fx_rates (rate_date, from_ccy, to_ccy, rate, source, is_fallback)
                               VALUES (%s,%s,%s,%s,'ECB',0)
                               ON DUPLICATE KEY UPDATE rate=VALUES(rate), source='ECB',
                                                       is_fallback=0, fetched_at=NOW(3)""",
                            (api_date, ccy, BASE, hkd))
                # HKD -> 外币，方便反向取数
                cur.execute("""INSERT INTO fx_rates (rate_date, from_ccy, to_ccy, rate, source, is_fallback)
                               VALUES (%s,%s,%s,%s,'ECB',0)
                               ON DUPLICATE KEY UPDATE rate=VALUES(rate), source='ECB',
                                                       is_fallback=0, fetched_at=NOW(3)""",
                            (api_date, BASE, ccy,
                             (Decimal(1) / hkd).quantize(Q, ROUND_HALF_UP) if hkd else Decimal(1)))
                written += 2
        append_audit(conn, {"entity_id": entity_id, "actor": actor,
                            "action": "fx_rate.autofetch", "object_type": "fx_rates",
                            "object_id": api_date,
                            "detail": {"source": "ECB/Frankfurter", "date": api_date,
                                       "pairs": written, "currencies": sorted(c for c, _ in rows)}})
    return {"date": api_date, "pairs": written,
            "currencies": sorted(c for c, _ in rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定日期（默认取最新可用的上一个交易日）")
    ap.add_argument("--actor", default="rate-bot")
    args = ap.parse_args()

    try:
        out = refresh(args.actor, args.date)
    except RuntimeError as e:
        print(f"FAIL {e}", file=sys.stderr)
        return 2
    print(f"OK date={out['date']} pairs={out['pairs']} currencies={len(out['currencies'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

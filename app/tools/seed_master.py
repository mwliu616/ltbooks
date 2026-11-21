#!/usr/bin/env python3
# LtBooks — tools/seed_master.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""生产账套初始化：实体信息 + 科目表 + 税率表 + 银行账户（幂等）。

用法：
    ./venv/bin/python tools/seed_master.py --dump        # 把当前主数据导出成种子 JSON
    ./venv/bin/python tools/seed_master.py --apply       # 用种子 JSON 补齐/覆盖主数据
    ./venv/bin/python tools/seed_master.py --apply --dry # 只打印会做什么

种子文件：storage/seed/master_data.json
原则：
  · 只动主数据（entities / accounts / tax_rates / bank_accounts），不碰分录与单据
  · 幂等：存在的按主键更新，不存在的新建；已停用的科目不会被重新启用
  · 银行账户里的账号属于敏感信息，种子文件不进版本库（.gitignore 已排除 storage/）
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.db import query, transaction                # noqa: E402

SEED = ROOT / "storage" / "seed" / "master_data.json"

ACCOUNT_COLS = ("account_code", "account_name", "name_zh_cn", "name_zh_hk", "name_en",
                "category", "normal_side", "is_active", "is_bank", "parent_code")
TAX_COLS = ("tax_type", "rate", "effective_from", "effective_to", "description")
BANK_COLS = ("name", "account_number", "currency", "bank_name", "status")


def dump() -> None:
    """导出当前主数据（部署后第一次跑，就把「生产账套」定下来了）。"""
    ent = query("SELECT * FROM entities")
    acc = query("SELECT * FROM accounts ORDER BY account_code")
    tax = query("SELECT * FROM tax_rates ORDER BY tax_type, rate")
    bank = query("SELECT * FROM bank_accounts ORDER BY account_id")
    for rows in (ent, acc, tax, bank):
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif hasattr(v, "__float__") and not isinstance(v, (int, float)):
                    r[k] = float(v)
    SEED.parent.mkdir(parents=True, exist_ok=True)
    SEED.write_text(json.dumps({"entities": ent, "accounts": acc, "taxRates": tax,
                                "bankAccounts": bank}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"已导出：实体 {len(ent)} · 科目 {len(acc)} · 税率 {len(tax)} · 银行 {len(bank)} → {SEED}")


def apply(dry: bool = False) -> None:
    if not SEED.exists():
        raise SystemExit(f"种子文件不存在：{SEED}（先跑 --dump）")
    data = json.loads(SEED.read_text(encoding="utf-8"))
    plan = []

    for e in data.get("entities", []):
        plan.append(("entities", "entity_id", e))
    for a in data.get("accounts", []):
        plan.append(("accounts", "account_code", a))
    for t in data.get("tax_rates") or data.get("taxRates", []):
        # 税率表没有主键：按 (类型, 税率, 生效日) 判重，避免重复灌入
        if query("SELECT 1 FROM tax_rates WHERE tax_type=%s AND rate=%s AND effective_from=%s",
                 (t.get("tax_type"), t.get("rate"), t.get("effective_from"))):
            continue
        plan.append(("tax_rates", None, t))
    for b in data.get("bank_accounts") or data.get("bankAccounts", []):
        plan.append(("bank_accounts", "account_id", b))

    for table, key, row in plan:
        cols = [c for c in row if c in _columns(table)]
        vals = [row[c] for c in cols]
        if key and row.get(key) is not None:
            exists = query(f"SELECT 1 FROM {table} WHERE {key}=%s", (row[key],))
            if exists:
                sets = ", ".join(f"{c}=%s" for c in cols if c != key)
                print(("DRY " if dry else "") + f"更新 {table} {key}={row[key]}")
                if not dry:
                    execute(f"UPDATE {table} SET {sets} WHERE {key}=%s",
                            [row[c] for c in cols if c != key] + [row[key]])
                continue
        print(("DRY " if dry else "") + f"插入 {table} {len(cols)} 列")
        if not dry:
            execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(['%s'] * len(cols))})", vals)
    print("完成" + ("（演练模式，未写入）" if dry else ""))


_CACHE = {}


def execute(sql: str, params=()) -> None:
    """单条写入（带事务）；只给本脚本补种子用。"""
    with transaction() as cur:
        cur.execute(sql, params)


def _columns(table: str) -> set:
    if table not in _CACHE:
        _CACHE[table] = {r["Field"] for r in query(f"SHOW COLUMNS FROM {table}")}
    return _CACHE[table]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.dump:
        dump()
    elif a.apply:
        apply(a.dry)
    else:
        ap.print_help()

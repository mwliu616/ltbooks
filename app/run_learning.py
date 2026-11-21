#!/usr/bin/env python3
# LtBooks — run_learning.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""学习固化定时任务（cron 每天 02:30 HKT 跑一次）。

只固化「你怎么做」这类偏好，不碰任何判断口径；冷启动 30 天只观察。
用法：
    python run_learning.py
    python run_learning.py --dry-run
    python run_learning.py --entity 1 --actor learning-bot
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("TZ", "Asia/Hong_Kong")
try:
    time.tzset()
except Exception:
    pass

from core.agents import scheduler  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entity", type=int, default=1)
    ap.add_argument("--actor", default="learning-bot")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    res = scheduler.run_daily(entity_id=args.entity, actor=args.actor, dry_run=args.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    if not res["observation"]["ready"]:
        print(f"NOTE 观察期 {res['observation']['days']}/{res['observation']['need']} 天，"
              f"本次不固化", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

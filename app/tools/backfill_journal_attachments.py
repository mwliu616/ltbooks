#!/usr/bin/env python3
# LtBooks — tools/backfill_journal_attachments.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""把已过账单据的附件补挂到对应凭证上（doc_type='journal'）。

2026-11-18 之前过账的单据，附件只挂在 bills/invoices 上，
凭证 PDF 因此没有附件页。这个脚本按 source_type/source_id 找回凭证，
把缺失的附件行复制过去；重复运行不会重复插入（按 doc_id+sha256 判重）。

用法： ./venv/bin/python tools/backfill_journal_attachments.py [--dry-run]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.db import query, transaction  # noqa: E402

DRY = "--dry-run" in sys.argv

pairs = query("""SELECT e.entry_id, e.entry_no, e.source_type, e.source_id
                   FROM journal_entries e
                  WHERE e.source_type IN ('bill', 'invoice') AND e.status='posted'""")
print(f"已过账单据凭证：{len(pairs)} 张")

copied = skipped = 0
with transaction() as conn:
    with conn.cursor() as cur:
        for p in pairs:
            src_type = "bill" if p["source_type"] == "bill" else "invoice"
            cur.execute("""SELECT file_name, file_type, file_size, sha256_hash,
                                  storage_path, uploaded_by, entity_id
                             FROM doc_files WHERE doc_type=%s AND doc_id=%s""",
                        (src_type, p["source_id"]))
            rows = cur.fetchall()
            for r in rows:
                cur.execute("""SELECT 1 FROM doc_files
                                WHERE doc_type='journal' AND doc_id=%s AND sha256_hash=%s""",
                            (p["entry_id"], r["sha256_hash"]))
                if cur.fetchone():
                    skipped += 1
                    continue
                copied += 1
                if DRY:
                    print(f"  [dry] {p['entry_no']} ← {r['file_name']}")
                    continue
                cur.execute("""INSERT INTO doc_files
                    (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                     sha256_hash, storage_path, uploaded_by)
                    VALUES (%s,'journal',%s,%s,%s,%s,%s,%s,%s)""",
                            (r["entity_id"], p["entry_id"], r["file_name"], r["file_type"],
                             r["file_size"], r["sha256_hash"], r["storage_path"],
                             r["uploaded_by"]))
print(f"补挂 {copied} 条，已存在跳过 {skipped} 条{'（dry-run，未写库）' if DRY else ''}")

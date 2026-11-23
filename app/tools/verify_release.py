#!/usr/bin/env python3
# LtBooks — tools/verify_release.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""Validate a LtBooks clean tar.gz/zip deployment archive without extracting it.

Checks archive safety, required installer files, manifest hashes, absence of
runtime/business-data files, clean SQL seeds and source syntax. The command exits
non-zero on the first failed package and prints a compact JSON summary on success.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN_DIRS = {".git", "venv", ".venv", "storage", "files", "reports-out",
                  "reports-i18n", "docs-legacy", "__pycache__"}
FORBIDDEN_FILES = {".env", "ai-deploy.conf", "initial-credentials.txt",
                   "初始账号.txt", "账号口令.txt", ".user.ini", "03-baseline.sql.gz"}
BUSINESS_INSERT = re.compile(
    r"INSERT\s+(?:IGNORE\s+)?INTO\s+`?([A-Za-z0-9_]+)`?", re.I
)
ALLOWED_SEED_TABLES = {"entities", "accounts", "tax_rates"}


class Archive:
    def __init__(self, path: Path):
        self.path = path
        self.kind = "zip" if path.suffix == ".zip" else "tar"
        self.handle = zipfile.ZipFile(path) if self.kind == "zip" else tarfile.open(path, "r:gz")
        self.names: list[str] = []
        if self.kind == "zip":
            for item in self.handle.infolist():
                if item.is_dir():
                    continue
                mode = item.external_attr >> 16
                if mode and (mode & 0o170000) == 0o120000:
                    raise ValueError(f"Symbolic link is not allowed: {item.filename}")
                self.names.append(item.filename)
        else:
            for item in self.handle.getmembers():
                if item.isdir():
                    continue
                if not item.isfile():
                    raise ValueError(f"Only regular files are allowed: {item.name}")
                self.names.append(item.name)
        if not self.names:
            raise ValueError("Archive is empty")
        roots = {PurePosixPath(name).parts[0] for name in self.names}
        if len(roots) != 1:
            raise ValueError(f"Archive must have one root directory: {sorted(roots)}")
        self.root = roots.pop()

    def close(self) -> None:
        self.handle.close()

    def read(self, relative: str) -> bytes:
        name = f"{self.root}/{relative}"
        if self.kind == "zip":
            return self.handle.read(name)
        member = self.handle.getmember(name)
        stream = self.handle.extractfile(member)
        if stream is None:
            raise ValueError(f"Cannot read {relative}")
        return stream.read()

    def relatives(self) -> list[str]:
        prefix = self.root + "/"
        return [name[len(prefix):] for name in self.names if name.startswith(prefix)]


def run_syntax(command: list[str], content: bytes, label: str) -> None:
    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    result = subprocess.run(command, input=content, capture_output=True, env=env, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")[-1000:]
        raise ValueError(f"Syntax check failed for {label}: {detail}")


def verify(path: Path) -> dict:
    archive = Archive(path)
    try:
        relatives = archive.relatives()
        for relative in relatives:
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
                raise ValueError(f"Unsafe archive path: {relative}")
            if FORBIDDEN_DIRS.intersection(pure.parts):
                raise ValueError(f"Runtime or business-data directory found: {relative}")
            if pure.name in FORBIDDEN_FILES or pure.suffix in {".pem", ".key", ".pyc"}:
                raise ValueError(f"Credential or runtime file found: {relative}")
            if pure.name.endswith(".sql.gz"):
                raise ValueError(f"Database dump is not allowed: {relative}")

        required = {"install.sh", "README.md", "LICENSE", "PACKAGE.json", "MANIFEST.txt",
                    ".env.example", "backend/api.py", "backend/agent/index.js",
                    "frontend/index.php", "sql/01-schema.sql", "sql/02-master-data.sql"}
        if "-manual-" in path.name:
            required.add("install-manual.sh")
        missing = sorted(required - set(relatives))
        if missing:
            raise ValueError(f"Missing required files: {missing}")

        metadata = json.loads(archive.read("PACKAGE.json"))
        if metadata.get("product") != "Lt-AI-Books" or metadata.get("clean") is not True:
            raise ValueError("PACKAGE.json does not identify a clean Lt-AI-Books package")

        manifest: dict[str, str] = {}
        for raw in archive.read("MANIFEST.txt").decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw)
            if not match:
                raise ValueError(f"Invalid MANIFEST.txt line: {raw[:100]}")
            manifest[match.group(2)] = match.group(1)
        expected_files = set(relatives) - {"MANIFEST.txt"}
        if set(manifest) != expected_files:
            raise ValueError("Manifest file list does not match archive contents")
        for relative, expected_hash in manifest.items():
            actual = hashlib.sha256(archive.read(relative)).hexdigest()
            if actual != expected_hash:
                raise ValueError(f"Manifest hash mismatch: {relative}")

        seed = archive.read("sql/02-master-data.sql").decode("utf-8")
        seed_tables = set(BUSINESS_INSERT.findall(seed))
        if not seed_tables <= ALLOWED_SEED_TABLES:
            raise ValueError(f"Business rows found in clean seed: {sorted(seed_tables - ALLOWED_SEED_TABLES)}")
        for forbidden in ("TEST_", "TEST_BANK", "Acme Trading", "741-869", "mwliu@",
                          "LEDU TECH CO., LIMITED', 'full_hkfrs"):
            if forbidden in seed:
                raise ValueError(f"Company-specific or demonstration seed found: {forbidden}")
        if "�" in seed:
            raise ValueError("Clean seed contains replacement characters")

        counts = {"bash": 0, "python": 0, "php": 0, "node": 0}
        for relative in relatives:
            suffix = PurePosixPath(relative).suffix
            content = archive.read(relative)
            if suffix == ".sh":
                run_syntax(["bash", "-n"], content, relative)
                counts["bash"] += 1
            elif suffix == ".py":
                compile(content.decode("utf-8"), relative, "exec")
                counts["python"] += 1
            elif suffix == ".php":
                run_syntax(["php", "-l"], content, relative)
                counts["php"] += 1
            elif suffix in {".js", ".mjs"}:
                run_syntax(["node", "--check", "--input-type=module"], content, relative)
                counts["node"] += 1
            if suffix in {".py", ".php", ".sh", ".js", ".mjs", ".json", ".example", ".sql"}:
                text = content.decode("utf-8", errors="ignore")
                for pattern in (r"sk-[A-Za-z0-9]{20,}", r"AIza[0-9A-Za-z_-]{20,}",
                                r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"):
                    if re.search(pattern, text):
                        raise ValueError(f"Possible private credential found in {relative}")

        return {
            "ok": True, "file": str(path), "variant": metadata.get("variant"),
            "files": len(relatives), "manifestHashes": len(manifest), "syntax": counts,
            "seedTables": sorted(seed_tables),
        }
    finally:
        archive.close()


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_release.py PACKAGE [PACKAGE ...]", file=sys.stderr)
        return 2
    results = []
    for name in sys.argv[1:]:
        try:
            result = verify(Path(name).resolve())
        except Exception as ex:
            print(f"FAILED {name}: {ex}", file=sys.stderr)
            return 1
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# LtBooks — config.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""运行配置：全部取自环境文件，不硬编码凭据。"""
import os
from pathlib import Path

# 以安装后的实际文件位置为默认根目录；自动、AI 和手工安装可使用不同目录。
# 环境变量只用于覆盖部署路径，不包含任何业务数据或固定服务器凭据。
APP_DIR = Path(os.environ.get("LEDU_APP_DIR", str(Path(__file__).resolve().parent))).resolve()
ENV_FILE = Path(os.environ.get("LEDU_ENV_FILE", str(APP_DIR / ".env"))).resolve()


def _load_env(path: Path) -> dict:
    out = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[k.strip()] = v
    except FileNotFoundError:
        pass
    return out


_ENV = _load_env(ENV_FILE)


def env(key: str, default=None):
    return os.environ.get(key) or _ENV.get(key) or default


RULES_DIR = Path(env("LEDU_RULES_DIR", str(APP_DIR / "rules"))).resolve()
STORAGE_DIR = Path(env("LEDU_STORAGE_DIR", str(APP_DIR / "storage"))).resolve()
WEB_ROOT = Path(env("LEDU_WEB_ROOT", "/opt/ltbooks/web")).resolve()
WEB_ASSETS_DIR = Path(env("LEDU_WEB_ASSETS_DIR", str(WEB_ROOT / "assets"))).resolve()
_upload_dirs = env("LEDU_UPLOAD_DIRS")
UPLOAD_DIRS = tuple(
    Path(item).resolve() for item in (_upload_dirs.split(os.pathsep) if _upload_dirs else [])
    if item.strip()
) or (Path(env("LEDU_UPLOAD_DIR", "/opt/ltbooks/uploads")).resolve(),
      (STORAGE_DIR / "uploads").resolve())
UPLOAD_DIR = UPLOAD_DIRS[0]


DB = {
    "host": env("LEDU_DB_HOST", "127.0.0.1"),
    "port": int(env("LEDU_DB_PORT", "3306")),
    "user": env("LEDU_DB_USER"),
    "password": env("LEDU_DB_PASSWORD", ""),
    "database": env("LEDU_DB_NAME", "ltbooks"),
    "charset": "utf8mb4",
    "cursorclass": None,  # 运行时注入 DictCursor
}

API_TOKEN = env("LEDU_API_TOKEN")
API_HOST = env("LEDU_API_HOST", "127.0.0.1")
API_PORT = int(env("LEDU_API_PORT", "8099"))

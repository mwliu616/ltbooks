# LtBooks — core/mailer.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""邮件发送（SMTP 外发）。

凭据只从 .env 读取，不落数据库、不进日志、不出现在任何 API 响应里。
发送失败一律抛出可读错误，由调用方决定是否显示给用户。
"""
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from config import ENV_FILE

# 允许的附件扩展名：只发我们自己生成的单据，不做法外通道
ALLOWED_ATTACH = {".pdf", ".png", ".jpg", ".jpeg", ".csv", ".xlsx"}


def _cfg():
    env = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    # 邮件配置也以「设置 → 邮件」为准，.env 只作首次部署的初始值
    try:
        from core import settings as _st
        g = _st.get
    except Exception:                                    # 设置模块不可用时退回 env
        g = lambda _k: ""
    return {
        "host": g("smtp.host") or env.get("LEDU_SMTP_HOST") or os.environ.get("LEDU_SMTP_HOST", ""),
        "port": int(g("smtp.port") or env.get("LEDU_SMTP_PORT") or os.environ.get("LEDU_SMTP_PORT", "465")),
        "secure": (g("smtp.secure") or env.get("LEDU_SMTP_SECURE") or os.environ.get("LEDU_SMTP_SECURE", "ssl")).lower(),
        "user": g("smtp.user") or env.get("LEDU_SMTP_USER") or os.environ.get("LEDU_SMTP_USER", ""),
        "password": g("smtp.password") or env.get("LEDU_SMTP_PASSWORD") or os.environ.get("LEDU_SMTP_PASSWORD", ""),
        "from_name": g("smtp.from_name") or env.get("LEDU_SMTP_FROM_NAME") or "LEDU",
    }


def status():
    """返回配置状态 —— 绝不包含密码。"""
    c = _cfg()
    return {
        "configured": bool(c["host"] and c["user"] and c["password"]),
        "host": c["host"],
        "port": c["port"],
        "security": c["secure"],
        "user": c["user"],
        "fromName": c["from_name"],
        "hasPassword": bool(c["password"]),
        "authRequired": True,
    }


def _connect(c):
    ctx = ssl.create_default_context()
    if c["secure"] == "ssl":
        srv = smtplib.SMTP_SSL(c["host"], c["port"], timeout=30, context=ctx)
    else:
        srv = smtplib.SMTP(c["host"], c["port"], timeout=30)
        srv.ehlo()
        srv.starttls(context=ctx)
        srv.ehlo()
    srv.login(c["user"], c["password"])
    return srv


def send(to, subject, body_text, body_html=None, attachments=None, cc=None, bcc=None):
    """发送邮件。attachments 为 [(路径, 显示名)] 或 [(bytes, 文件名)]。"""
    c = _cfg()
    if not c["host"] or not c["user"] or not c["password"]:
        raise ValueError("SMTP 未配置")

    to = [t.strip() for t in (to if isinstance(to, (list, tuple)) else str(to).split(",")) if t.strip()]
    if not to:
        raise ValueError("收件人不能为空")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((c["from_name"], c["user"]))
    msg["To"] = ", ".join(to)
    if cc:
        cc_list = cc if isinstance(cc, (list, tuple)) else str(cc).split(",")
        cc_list = [x.strip() for x in cc_list if x.strip()]
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=c["user"].split("@")[-1])
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    added = []
    for item in attachments or []:
        if isinstance(item[0], (bytes, bytearray)):
            data, name = bytes(item[0]), item[1]
        else:
            path = Path(item[0])
            if not path.is_file():
                raise ValueError(f"附件不存在：{path.name}")
            data, name = path.read_bytes(), (item[1] if len(item) > 1 and item[1] else path.name)

        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_ATTACH:
            raise ValueError(f"不允许的附件类型：{ext}")
        ctype, _ = mimetypes.guess_type(name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        added.append(name)

    recipients = list(to)
    if bcc:
        bcc_list = bcc if isinstance(bcc, (list, tuple)) else str(bcc).split(",")
        recipients += [x.strip() for x in bcc_list if x.strip()]
    if msg["Cc"]:
        recipients += [x.strip() for x in msg["Cc"].split(",")]

    srv = _connect(c)
    try:
        srv.send_message(msg, from_addr=c["user"], to_addrs=recipients)
    finally:
        try:
            srv.quit()
        except Exception:
            pass

    return {"messageId": msg["Message-ID"], "to": to,
            "cc": msg["Cc"] if msg["Cc"] else None,
            "attachments": added, "server": f'{c["host"]}:{c["port"]}'}

# LtBooks — core/ocr.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""OCR：PDF 优先抽文字层，文字层不可读时再走图像识别。
全部本地执行，不依赖视觉大模型。"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}

# 单据里常见的英文词，用于判断文本层是不是「有意义的文字」
# 简繁判别：这些字只在一种字体里出现，用于判断单据该用哪个语言包
_SIM_ONLY = set("发票号码开张总计会计服务费贸易银行帐户币额税报表应付款语资产负债权益现金转账"
                "营业时间单价数量类别备注项目合计金额日期编号")
_TRA_ONLY = set("發票號碼開張總計會計服務費貿易銀行帳戶幣額稅報表應付款語資產負債權益現金轉賬"
                "營業時間單價數量類別備註項目合計金額日期編號")

_COMMON_WORDS = {
    "the", "and", "for", "with", "invoice", "receipt", "date", "due", "total", "amount",
    "subtotal", "tax", "vat", "no", "number", "description", "qty", "price", "payment",
    "please", "company", "limited", "ltd", "inc", "hk", "hkd", "usd", "cny", "rmb",
    "account", "bank", "services", "service", "period", "terms", "balance", "charge",
}


class OCRError(Exception):
    pass


def text_quality(text):
    """判断 PDF 文本层是否可读。

    有些 PDF 用 Type 3 自定义编码且不带 ToUnicode 映射，pdftotext 会抽出
    「abacdeadebÿaagha」这类字形码 —— 长度够，但完全无意义。只看长度会把乱码
    当正文，所以这里按「结构化线索」判断：金额、日期、中文、常见词。

    返回 (可读: bool, 依据: str)。
    """
    t = text or ""
    compact = re.sub(r"\s", "", t)
    if len(compact) < 40:
        return False, "too_short"
    has_amount = bool(re.search(r"\d[\d,]{0,12}\.\d{2}", t))
    has_date = bool(re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", t))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", t)]
    hits = sum(1 for w in words if w in _COMMON_WORDS)
    if has_amount and has_date:
        return True, "amount+date"
    if has_amount or has_date:
        return True, "amount_or_date"
    if cjk >= 20:
        return True, "cjk"
    if hits >= 3 and len(words) >= 10:
        return True, "vocabulary"
    return False, "garbled"


def _run(cmd, timeout=90):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout
    except FileNotFoundError:
        raise OCRError(f"缺少工具：{cmd[0]}")
    except subprocess.TimeoutExpired:
        raise OCRError(f"处理超时：{cmd[0]}")


def _tesseract(img_path, lang="chi_tra+eng", psm=3):
    code, out = _run(["tesseract", str(img_path), "stdout", "-l", lang, "--psm", str(psm)])
    return out.decode("utf-8", "replace") if code == 0 else ""


def _tesseract_tsv(img_path, lang="chi_tra+eng", psm=3):
    """返回 (文本, 平均置信度)。

    用 TSV 输出重建文本，顺便取每词置信度 —— 简繁两包都能认出字，
    靠「哪个包更信得过」来选语言，比数关键词可靠。
    """
    code, out = _run(["tesseract", str(img_path), "stdout", "-l", lang,
                      "--psm", str(psm), "tsv"])
    if code != 0:
        return "", 0.0
    lines, cur_key, cur_words, confs = [], None, [], []
    for raw in out.decode("utf-8", "replace").splitlines()[1:]:
        cols = raw.split("\t")
        if len(cols) < 12:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if conf < 0 or not word:
            continue
        key = (cols[2], cols[3], cols[4])
        if key != cur_key:
            if cur_words:
                lines.append(" ".join(cur_words))
            cur_key, cur_words = key, []
        cur_words.append(word)
        confs.append(conf)
    if cur_words:
        lines.append(" ".join(cur_words))
    mean = sum(confs) / len(confs) if confs else 0.0
    return "\n".join(lines), mean


def detect_script(text):
    """判断文本以繁体还是简体为主。返回 'tra' / 'sim' / 'neutral'。"""
    t = text or ""
    sim = sum(1 for ch in t if ch in _SIM_ONLY)
    tra = sum(1 for ch in t if ch in _TRA_ONLY)
    if sim >= 3 and sim > tra * 2:
        return "sim"
    if tra >= 3 and tra > sim * 2:
        return "tra"
    if sim or tra:
        return "tra" if tra >= sim else "sim"
    return "neutral"


def _score(text):
    """OCR 结果打分：金额、日期、中文、单据词越多越可信。"""
    t = text or ""
    s = 0
    s += 3 * len(re.findall(r"\d[\d,]{0,12}\.\d{2}", t))          # 带小数的金额
    s += 2 * len(re.findall(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", t))  # 完整日期
    s += 2 * len(re.findall(r"\d+\s*元", t))                       # 「118元」这类
    s += min(6, len(re.findall(r"[\u4e00-\u9fff]", t)) // 12)      # 中文字数
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", t)]
    s += min(4, sum(1 for w in words if w in _COMMON_WORDS))
    return s


def _ocr_page(img_path, lang=None):
    """同一页跑几种版面切分，取信息量最多的结果。

    语言包：香港单据以繁体为主，默认 chi_tra+eng。若该包的平均置信度偏低，
    再用 chi_sim+eng 跑一遍，两包取「更信得过」的那个 —— 简体单据用繁体包
    也能认出字形，只是认错字，靠关键词数分辨不出来，必须看置信度。

    表格类凭证用 psm 3 明显好于 psm 6；纯商品列表则 psm 6 更稳。
    """
    def run(lg):
        # 先用 psm 3（整页自动分块）跑一次；信息量够就不再试其他版面，省时间
        best = _tesseract(img_path, lang=lg, psm=3)
        best_score, best_psm = _score(best), 3
        if best_score < 10:
            for psm in (6, 11):
                txt = _tesseract(img_path, lang=lg, psm=psm)
                sc = _score(txt)
                if sc > best_score:
                    best, best_score, best_psm = txt, sc, psm
        _, conf = _tesseract_tsv(img_path, lang=lg, psm=best_psm)
        return best, best_score, conf

    if lang:
        return run(lang)[0]

    best, best_score, best_conf = run("chi_tra+eng")
    if best_conf < 88:
        alt, alt_score, alt_conf = run("chi_sim+eng")
        if alt_conf > best_conf + 3 and alt_score >= best_score - 2:
            return alt
    return best


def _pdf_to_text(p):
    """把 PDF 每一页转图后 OCR。300dpi 才能看清小字号的中文。"""
    with tempfile.TemporaryDirectory() as td:
        code, _ = _run(["pdftoppm", "-r", "300", "-png", str(p), td + "/page"], timeout=240)
        if code != 0:
            raise OCRError("PDF 转图片失败")
        pages = sorted(Path(td).glob("page*.png"))
        if not pages:
            raise OCRError("PDF 没有可识别页面")
        return "\n".join(_ocr_page(pg) for pg in pages[:5])


def extract_text(path):
    p = Path(path)
    if not p.is_file():
        raise OCRError("文件不存在")
    ext = p.suffix.lower()

    if ext == ".pdf":
        code, out = _run(["pdftotext", "-layout", str(p), "-"])
        text = out.decode("utf-8", "replace") if code == 0 else ""
        ok, why = text_quality(text)
        if ok:
            return {"text": text, "method": "pdf-text-layer", "confidence": "high",
                    "textCheck": why, "sourceChars": len(re.sub(r"\s", "", text))}

        # 文字层缺失或为乱码（Type 3 自定义编码）：转图 OCR
        ocr = _pdf_to_text(p)
        ocr_ok, ocr_why = text_quality(ocr)
        return {"text": ocr,
                "method": "pdf-ocr",
                "confidence": "high" if ocr_ok else ("medium" if ocr.strip() else "low"),
                "textCheck": ocr_why,
                "fallbackFrom": f"text-layer-{why}" if text.strip() else "text-layer-empty",
                "sourceChars": len(re.sub(r"\s", "", ocr))}

    if ext in IMAGE_EXT:
        text = _ocr_page(p)
        ok, why = text_quality(text)
        return {"text": text, "method": "image-ocr",
                "confidence": "high" if ok else ("medium" if text.strip() else "low"),
                "textCheck": why, "sourceChars": len(re.sub(r"\s", "", text))}

    if ext in {".txt", ".csv", ".md"}:
        text = p.read_text(encoding="utf-8", errors="replace")
        return {"text": text, "method": "plain-text", "confidence": "high",
                "textCheck": "plain", "sourceChars": len(re.sub(r"\s", "", text))}

    raise OCRError(f"不支持的文件类型：{ext}")


def available():
    return {"pdftotext": shutil.which("pdftotext") is not None,
            "pdftoppm": shutil.which("pdftoppm") is not None,
            "tesseract": shutil.which("tesseract") is not None}

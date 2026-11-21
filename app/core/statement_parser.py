# LtBooks — core/statement_parser.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""银行月结单解析：电子表格（CSV/XLSX/XLS）与 PDF。

输出统一为交易行，交给 bankrec.validate_statement 做算术校验后再落库。
解析器只负责「把文件读成行」，不做任何账务判断。

PDF 优先读文字层；无文字层（扫描件）逐页转图后 OCR（chi_sim+eng）。
"""
import csv
import io
import re
import html as html_module
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# 列名关键词（小写比较）
COLS = {
    "date": ["日期", "交易日期", "記賬日", "记账日", "入賬日", "date", "txn date",
             "transaction date", "posting date", "value date"],
    "description": ["摘要", "說明", "说明", "描述", "交易詳情", "交易详情", "particulars",
                    "description", "details", "narrative", "reference", "備註", "备注"],
    "debit": ["支出", "借方", "支取", "付款", "debit", "withdrawal", "paid out", "dr"],
    "credit": ["存入", "貸方", "贷方", "收款", "credit", "deposit", "paid in", "cr"],
    "amount": ["金額", "金额", "交易金額", "交易金额", "amount"],
    "balance": ["餘額", "余额", "結餘", "结余", "balance", "running balance"],
    "ref": ["參考", "参考", "編號", "编号", "ref", "reference no", "cheque", "支票號"],
    "counterparty": ["對方", "对方", "交易對方", "交易对方", "往來單位", "往来单位",
                     "受款人", "付款人", "商戶", "商户", "counterparty", "payee",
                     "payer", "merchant", "beneficiary"],
}

DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})"), ("ymd",)),
    (re.compile(r"^(\d{4})/(\d{2})/(\d{2})"), ("ymd",)),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})"), ("dmy",)),
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})"), ("dmy",)),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})(?!\d)"), ("dmy2",)),
    (re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})"), ("dMy",)),
]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

NUM_RE = re.compile(r"-?\(?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?|-?\d+(?:\.\d+)?")


# ---------------------------------------------------------------- 工具
def _to_decimal(tok):
    if tok is None:
        return None
    s = str(tok).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "—", "/"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("-"):
        neg, s = True, s[1:]
    s = s.lstrip("+")
    try:
        v = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    return -v if neg else v


def _parse_date_cell(text):
    if text is None:
        return None
    if isinstance(text, (datetime, date)):
        return text.date() if isinstance(text, datetime) else text
    s = str(text).strip()
    if not s:
        return None
    for pat, (kind,) in DATE_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        try:
            if kind == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if kind == "dmy":
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if kind == "dmy2":
                y = int(m.group(3))
                return date(2000 + y, int(m.group(2)), int(m.group(1)))
            if kind == "dMy":
                mon = MONTHS.get(m.group(2).lower())
                if mon:
                    return date(int(m.group(3)), mon, int(m.group(1)))
        except ValueError:
            return None
    return None


def _norm_header(s):
    return re.sub(r"[\s\-_（）()：:]+", "", str(s or "")).lower()


def _map_columns(header_cells):
    """把表头映射为字段名。返回 {field: index}。"""
    mapping = {}
    for i, cell in enumerate(header_cells):
        h = _norm_header(cell)
        if not h:
            continue
        for field, keys in COLS.items():
            if field in mapping:
                continue
            if any(_norm_header(k) in h for k in keys):
                mapping[field] = i
                break
    return mapping


def _looks_like_header(row):
    """表头行：含日期/金额类关键词，且几乎没有数字。"""
    text = " ".join(str(c) for c in row if c is not None)
    if not text.strip():
        return False
    hits = 0
    for keys in COLS.values():
        if any(_norm_header(k) in _norm_header(text) for k in keys):
            hits += 1
    nums = sum(1 for c in row if _to_decimal(c) is not None)
    return hits >= 2 and nums == 0


# ---------------------------------------------------------------- 行归一
def _row_to_txn(cells, mapping):
    """按列映射把一行转成交易。返回 None 表示不是交易行。"""
    def get(field):
        i = mapping.get(field)
        if i is None or i >= len(cells):
            return None
        return cells[i]

    d = _parse_date_cell(get("date"))
    if d is None:
        return None

    debit = _to_decimal(get("debit"))
    credit = _to_decimal(get("credit"))
    amount = _to_decimal(get("amount"))
    balance = _to_decimal(get("balance"))

    if debit is not None or credit is not None:
        debit = abs(debit) if debit is not None else None
        credit = abs(credit) if credit is not None else None
        net = (credit or Decimal(0)) - (debit or Decimal(0))
    elif amount is not None:
        net = amount
        debit = -amount if amount < 0 else None
        credit = amount if amount > 0 else None
    else:
        return None

    desc = get("description")
    ref = get("ref")
    party = get("counterparty")
    desc = re.sub(r"\s+", " ", str(desc)).strip() if desc is not None else ""
    party_s = re.sub(r"\s+", " ", str(party)).strip() if party is not None else ""

    return {
        "date": d.isoformat(),
        "description": desc[:200],
        "counterparty": party_s[:200],
        "debit": float(debit) if debit is not None else 0.0,
        "credit": float(credit) if credit is not None else 0.0,
        "amount": float(net),
        "balance": float(balance) if balance is not None else None,
        "ref": (str(ref).strip()[:64] if ref is not None else ""),
    }


# ---------------------------------------------------------------- CSV
def _parse_csv(data):
    warnings = []
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("无法识别文件编码")

    sample = text[:4096]
    delim = ","
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # 退化为按出现次数猜
        counts = {d: sample.count(d) for d in (",", ";", "\t", "|")}
        delim = max(counts, key=counts.get) if max(counts.values()) > 0 else ","

    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ValueError("文件为空或没有可读行")
    return rows, warnings


# ---------------------------------------------------------------- 电子表格
def _parse_xlsx(data):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows = []
    warnings = []
    for ws in wb.worksheets:
        sheet_rows = []
        for r in ws.iter_rows(values_only=True):
            if r is None or all(c is None or str(c).strip() == "" for c in r):
                continue
            sheet_rows.append(list(r))
        if sheet_rows:
            rows.extend(sheet_rows)
            if len(wb.worksheets) > 1:
                warnings.append(f"工作簿含 {len(wb.worksheets)} 个工作表，已合并解析")
            break  # 只取第一个有内容的表
    wb.close()
    if not rows:
        raise ValueError("工作表为空")
    return rows, warnings


def _parse_xls(data):
    import xlrd
    wb = xlrd.open_workbook(file_contents=data)
    rows, warnings = [], []
    for sh in wb.sheets():
        for i in range(sh.nrows):
            vals = [sh.cell_value(i, j) for j in range(sh.ncols)]
            if all(str(v).strip() == "" for v in vals):
                continue
            rows.append(vals)
        if rows:
            break
    if not rows:
        raise ValueError("工作表为空")
    return rows, warnings


# ---------------------------------------------------------------- PDF
def _pdf_text(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"],
                             capture_output=True, text=True, timeout=120)
        return out.stdout or ""
    finally:
        Path(path).unlink(missing_ok=True)


def _pdf_ocr(data):
    """扫描件：逐页转图后 OCR，并用词框坐标重建版面。

    直接拼接 OCR 文本会丢掉列位置，空栏会塌陷（余额被当成支出）。
    这里取 tesseract 的 TSV 词框，按 y 聚行、按 x 还原空格，
    使后续「按列位置归集」与文字层 PDF 走同一条路径。
    """
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise ValueError("PDF 无文字层，且缺少 OCR 工具（pdftoppm / tesseract）")

    def ocr_page(img_path):
        r = subprocess.run(["tesseract", str(img_path), "-", "-l", "chi_sim+eng",
                            "--psm", "6", "tsv"], capture_output=True, text=True, timeout=300)
        words = []
        for line in (r.stdout or "").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) < 12:
                continue
            try:
                left, top, width, height = (int(cols[6]), int(cols[7]),
                                            int(cols[8]), int(cols[9]))
                conf = float(cols[10]) if cols[10] not in ("", "-1") else -1
            except ValueError:
                continue
            text = cols[11].strip()
            if text and conf > 30:
                words.append({"text": text, "left": left, "top": top,
                              "right": left + width, "h": height})
        if not words:
            return ""
        words.sort(key=lambda w: (w["top"], w["left"]))
        lines, cur = [], [words[0]]
        for w in words[1:]:
            if abs(w["top"] - cur[-1]["top"]) <= max(6, cur[-1]["h"] * 0.6):
                cur.append(w)
            else:
                lines.append(cur); cur = [w]
        lines.append(cur)

        out = []
        for ln in lines:
            ln.sort(key=lambda w: w["left"])
            total_chars = max(1, sum(len(w["text"]) for w in ln))
            avg_char = max(4.0, (ln[-1]["right"] - ln[0]["left"]) / total_chars)
            buf, prev_right = [], None
            for w in ln:
                if prev_right is not None:
                    gap = w["left"] - prev_right
                    spaces = 1 if gap < avg_char else min(40, int(gap / avg_char) + 1)
                    buf.append(" " * spaces)
                buf.append(w["text"])
                prev_right = w["right"]
            out.append("".join(buf))
        return "\n".join(out)

    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "s.pdf"
        pdf.write_bytes(data)
        subprocess.run(["pdftoppm", "-r", "300", "-png", str(pdf), str(Path(tmp) / "p")],
                       capture_output=True, timeout=300)
        return "\n".join(ocr_page(img) for img in sorted(Path(tmp).glob("p*.png")))


PDF_NUM = r"-?\(?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?"
PDF_ROW = re.compile(
    rf"^(\d{{1,2}}[/\-]\d{{1,2}}[/\-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}})\s+(.*?)\s+({PDF_NUM}(?:\s+{PDF_NUM}){{0,2}})\s*(DR|CR|Dr|Cr)?\s*$")


def _header_columns(line):
    """从表头行解析各字段的字符区间，用于按位置归列。"""
    cols = {}
    for field, keys in COLS.items():
        best = None
        for k in keys:
            i = line.find(k)
            while i != -1:
                end = i + len(k)
                if best is None or end > best[1]:
                    best = (i, end)
                i = line.find(k, i + 1)
        if best:
            cols[field] = best
    return cols


def _numbers_with_pos(line):
    """返回 [(值, 起始位置, 结束位置)]。"""
    out = []
    for m in re.finditer(PDF_NUM, line):
        v = _to_decimal(m.group(0))
        if v is not None:
            out.append((v, m.start(), m.end()))
    return out


def _clean_desc(line, date_end, first_num_start):
    """摘要 = 去掉行首日期、去掉尾部数字列之后的部分。"""
    stop = first_num_start if first_num_start is not None else len(line)
    if stop <= date_end:
        stop = len(line)
    txt = line[date_end:stop]
    return re.sub(r"\s{2,}", " ", txt).strip(" |\t")[:200]


def _cluster_positions(values, gap=6):
    """把一组字符位置聚成列簇，返回每簇中心。"""
    if not values:
        return []
    vals = sorted(values)
    groups, cur = [], [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] <= gap:
            cur.append(v)
        else:
            groups.append(cur); cur = [v]
    groups.append(cur)
    return [sum(g) / len(g) for g in groups]


def _parse_pdf_rows(text):
    """从 PDF 文本抽取交易行，按列位置归集数字。

    列锚点优先取表头；表头识别不到（OCR 扫描件常见）时，
    退而从各行数字的字符位置聚类出列，而不是按出现顺序硬套 ——
    后者会把日期里的数字当成金额。
    """
    lines = text.splitlines()

    header_cols, data_start = {}, 0
    for i, line in enumerate(lines[:60]):
        cols = _header_columns(line)
        if len(cols) >= 3 and "date" in cols:
            header_cols, data_start = cols, i + 1
            break

    parsed_lines, all_endpos = [], []
    for raw in lines[data_start:]:
        line = raw.rstrip()
        if not line.strip():
            continue
        m0 = None
        for pat, _kind in DATE_PATTERNS:
            m0 = pat.match(line.strip())
            if m0:
                break
        if not m0:
            continue
        d = _parse_date_cell(m0.group(0))
        if d is None:
            continue
        date_end = (len(line) - len(line.lstrip())) + m0.end()
        nums = [n for n in _numbers_with_pos(line) if n[1] >= date_end]
        if not nums:
            continue
        parsed_lines.append((line, d, date_end, nums))
        if not header_cols:
            all_endpos.extend(n[2] for n in nums)

    rows, warnings = [], []
    if header_cols:
        anchors = sorted([(f, span[1]) for f, span in header_cols.items()
                          if f in ("debit", "credit", "amount", "balance")], key=lambda x: x[1])
    else:
        anchors = []
        warnings.append("PDF 表头未识别，按「最右为余额、其左为金额」解析，"
                        "并用余额滚动校正，请核对预览")

    for line, d, date_end, nums in parsed_lines:
        desc = _clean_desc(line, date_end, nums[0][1])
        debit = credit = amount = balance = None
        if anchors:
            for val, _st, endpos in nums:
                field = min(anchors, key=lambda a: abs(a[1] - endpos))[0]
                if field == "balance":
                    balance = val
                elif field == "debit":
                    debit = abs(val)
                elif field == "credit":
                    credit = abs(val)
                else:
                    amount = val
        else:
            if len(nums) >= 2:
                balance = nums[-1][0]
                amount = nums[-2][0]
            else:
                amount = nums[0][0]

        if amount is not None and debit is None and credit is None:
            debit = -amount if amount < 0 else None
            credit = amount if amount > 0 else None
            net = amount
        else:
            net = (credit or Decimal(0)) - (debit or Decimal(0))
        if debit is None and credit is None and amount is None:
            continue

        rows.append({"date": d.isoformat(), "description": desc[:200],
                     "counterparty": "",
                     "debit": float(debit or 0), "credit": float(credit or 0),
                     "amount": float(net),
                     "balance": float(balance) if balance is not None else None,
                     "ref": ""})

    if not rows:
        warnings.append("PDF 中未识别到交易行，请确认是否为本行月结单格式")
    return rows, warnings


def _pdf_statement_year(text):
    """从月结单抬头取年份，如 '30 April 2025'。"""
    m = re.search(r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
                  r"September|October|November|December)\s+(\d{4})\b", text)
    if m:
        return int(m.group(3)), MONTHS_FULL[m.group(2).lower()]
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if m:
        return int(m.group(3)), int(m.group(2))
    return None, None


MONTHS_FULL = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}

MONTHS_SHORT = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# 「22 Apr」「22 April」——HSBC 等银行的行内日期不带年份
SHORT_DATE = re.compile(r"^(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                        r"(?:\s+(\d{4}))?\b", re.I)

BLOCK_STOP = re.compile(r"^(Total No\.|Total Deposit|Total Withdrawal|Continued|"
                        r"The Hongkong|Page \d)", re.I)



# 外币参考行：/OCMT/USD1024.00、/EXCH/7.795747、USD24.00 7.80384RT
# 这些数字是「原币金额 / 折算汇率」，不是本笔发生额。
_REF_LINE = re.compile(r"^(?:/\w+/.+|(?:USD|CNY|EUR|GBP|JPY|SGD|AUD|CAD|CHF|TWD|KRW|THB|MYR|PHP)\s*[\d,.]*(?:\s+[\d.]+RT)?)$", re.I)
# 期初/期末结转行：只有余额，不是交易
_BF_CF = re.compile(r"^(B/?F|C/?F)\s*BALANCE\b|^(BROUGHT|CARRIED)\s+FORWARD\b", re.I)


def _is_ref_line(text: str) -> bool:
    """外币折算参考行：金额与汇率都不是发生额。"""
    t = text.strip()
    if not t:
        return False
    if t.startswith("/"):
        return True
    return bool(_REF_LINE.match(t))


# ---------------------------------------------------------------- 坐标解析（PDF）
def _pdf_words(data: bytes):
    """pdftotext -bbox-layout → 词与坐标。坐标是判断「这笔钱在哪一列」的唯一可靠依据。"""
    import subprocess, tempfile, xml.etree.ElementTree as ET
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        out = subprocess.run(["pdftotext", "-bbox-layout", "-enc", "UTF-8", path, "-"],
                             capture_output=True, timeout=90)
        xml = out.stdout.decode("utf-8", "replace")
    finally:
        Path(path).unlink(missing_ok=True)
    if "<word" not in xml:
        return []
    words = []
    for pageno, page in enumerate(re.finditer(r"<page .*?</page>", xml, re.S)):
        for m in re.finditer(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>',
                page.group(0)):
            words.append({"x0": float(m.group(1)), "y": float(m.group(2)),
                          "x1": float(m.group(3)),
                          "t": html_module.unescape(m.group(5)), "p": pageno})
    return words


def _group_lines(words, tol=3.0):
    """把词按「页 + y」聚成行，行内按 x 排序。

    必须带页号：不同页的 y 坐标会重合，只按 y 聚会把上一页的汇总表
    混进这一页的交易描述里。
    """
    lines = []
    for w in sorted(words, key=lambda w: (w.get("p", 0), w["y"], w["x0"])):
        if (lines and lines[-1].get("p") == w.get("p")
                and abs(w["y"] - lines[-1]["y"]) <= tol):
            lines[-1]["w"].append(w)
        else:
            lines.append({"y": w["y"], "p": w.get("p", 0), "w": [w]})
    for ln in lines:
        ln["w"].sort(key=lambda w: w["x0"])
    return lines



# 页面家具：页眉页脚里的字，不能混进交易描述
_FURNITURE = re.compile(
    r"HSBC Business Direct Statement|Portfolio Summary|HKD Equivalent|\(DR=Debit|"
    r"Total balance in|Net Position|Total balance|Page \d+ of \d+|"
    r"^Number\b|^Branch\b|^\d{3}-\d{6}-\d{3}$|HK OFFICE|^Date\s+Transaction", re.I)

_AMT = re.compile(r"^-?[\d,]+\.\d{2}$")
_DATE1 = re.compile(r"^(\d{1,2})\s+([A-Z][a-z]{2})$")
_DATE2 = re.compile(r"^(\d{1,2})$")


def _parse_pdf_bbox(data: bytes):
    """按列坐标解析 PDF 月结单。

    为什么用它：正则数数字分不清「发生额」「余额」「原币金额」「汇率」——
    HSBC 的 /OCMT/USD1024.00、CNY6242.00 1.08873RT 这类行会被当成本笔金额，
    导致贷方合计虚高、算术校验通不过。按 x 坐标落到哪一列，才是确定的。
    """
    words = _pdf_words(data)
    if not words:
        return [], []

    lines = _group_lines(words)

    # 1) 找表头，取三列的右边界
    anchors = None
    header_idx = None
    for i, ln in enumerate(lines):
        texts = {w["t"]: w for w in ln["w"]}
        if "Deposit" in texts and ("Withdrawal" in texts or "Balance" in texts):
            cols = [(texts[k]["x1"], k) for k in ("Deposit", "Withdrawal", "Balance") if k in texts]
            anchors = cols
            header_idx = i
            break
    if anchors is None:
        return [], []

    year, stmt_month = _pdf_statement_year("\n".join(
        " ".join(w["t"] for w in ln["w"]) for ln in lines))
    if year is None:
        return [], []

    def to_date(dd, mon, yy):
        m = MONTHS_SHORT.get(mon.lower()[:3]) if mon else None
        if m is None:
            return None
        y = int(yy) if yy else year
        if yy is None and stmt_month and m > stmt_month:
            y -= 1
        try:
            return date(y, m, dd)
        except ValueError:
            return None

    def nearest(x1):
        """金额落在哪一列：右边界最近的锚点，超出容差就当描述里的数字。"""
        best, dist = None, 1e9
        for ax, name in anchors:
            d = abs(ax - x1)
            if d < dist:
                best, dist = name, d
        if dist > 30:
            return None
        return {"Deposit": "credit", "Withdrawal": "debit", "Balance": "balance"}.get(best)

    rows = []
    cur_date, cur_desc = None, []
    in_gap = False          # 跨页：页眉之后的抬头区要跳过，直到活动明细重新开始
    for ln in lines[header_idx + 1:]:
        txt = " ".join(w["t"] for w in ln["w"])
        if BLOCK_STOP.match(txt.strip()):
            break
        if in_gap:
            if "Account Activities" in txt:
                in_gap = False
            continue
        if re.search(r"HSBC Business Direct Statement|Page \d+ of \d+", txt, re.I):
            in_gap = True
            continue
        if _BF_CF.search(txt):
            continue
        ws = ln["w"]
        # 行首日期
        d = None
        first = ws[0]["t"] if ws else ""
        m1 = _DATE1.match(first)
        if m1:
            d = to_date(int(m1.group(1)), m1.group(2), None)
            ws = ws[1:]
        elif _DATE2.match(first) and len(ws) > 1 and ws[1]["t"][:3].lower() in MONTHS_SHORT:
            d = to_date(int(first), ws[1]["t"], None)
            ws = ws[2:]
        if d is not None:
            cur_date, cur_desc = d, []

        desc_parts, debit, credit, balance = [], None, None, None
        for w in ws:
            t = w["t"]
            if _AMT.match(t):
                col = nearest(w["x1"])
                val = _to_decimal(t)
                if col == "balance":
                    balance = abs(val) if val is not None else None
                    continue
                if col == "debit":
                    debit = abs(val) if val is not None else None
                    continue
                if col == "credit":
                    credit = abs(val) if val is not None else None
                    continue
            desc_parts.append(t)

        desc = re.sub(r"\s{2,}", " ", " ".join(desc_parts)).strip(" |")
        # 外币参考行（/OCMT/、/EXCH/、CNY6242.00 1.08873RT）：并入描述，不单列。
        # 但如果这一行本身带着发生额（如「REM USD1024.00  7,982.84」），
        # 那它就是一笔真交易，不能当参考行丢掉。
        if (debit is None and credit is None) and (_is_ref_line(desc) or desc.startswith("/")):
            if cur_desc is not None:
                cur_desc.append(desc)
            continue
        if desc:
            cur_desc.append(desc)
        if debit is None and credit is None:
            continue                    # 只有余额或只有说明：不是一笔交易
        if cur_date is None:
            continue
        net = float((credit or 0)) - float((debit or 0))
        rows.append({
            "date": cur_date.isoformat(),
            "description": re.sub(r"\s{2,}", " ", " ".join(cur_desc))[:200],
            "debit": float(debit or 0), "credit": float(credit or 0),
            "amount": net,
            "balance": float(balance) if balance is not None else None,
            "ref": "",
        })
        cur_desc = []
    return rows, ([f"已按列坐标解析出 {len(rows)} 笔交易"] if rows else [])

def _parse_pdf_activity_blocks(text):
    """按「日期块 + 描述行 + 金额行」解析银行活动明细。

    适配 HSBC Business Direct 这类排版：一个日期下挂多笔交易，
    描述可跨行，金额行不一定带日期，同一行可能同时有金额与余额。
    """
    lines = text.splitlines()

    # 1) 找列头，取各列右边界作为锚点
    anchors, header_idx = [], None
    for i, line in enumerate(lines):
        if re.search(r"\bDeposit\b", line) and re.search(r"\b(Withdrawal|Balance)\b", line):
            for kw, field in (("Deposit", "credit"), ("Withdrawal", "debit"),
                              ("Balance", "balance"), ("Amount", "amount")):
                pos = line.find(kw)
                if pos >= 0:
                    anchors.append((field, pos + len(kw)))
            if anchors:
                anchors.sort(key=lambda a: a[1])
                header_idx = i
                break
    if header_idx is None or not anchors:
        return [], []

    year, stmt_month = _pdf_statement_year(text)

    def to_date(dd, mm, y):
        yy = int(y) if y else year
        if yy is None:
            return None
        if y is None and stmt_month and mm > stmt_month:
            yy -= 1          # 跨年：月份大于账单月，属上一年
        try:
            return date(yy, mm, dd)
        except ValueError:
            return None

    def collapse(x):
        return re.sub(r"\s{2,}", " ", x).strip(" |\t")

    rows, warnings = [], []
    cur_date, cur_desc = None, []

    for raw in lines[header_idx + 1:]:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if BLOCK_STOP.match(stripped):
            break
        # 期初/期末结转：只有余额，不是交易
        if _BF_CF.search(stripped) and not SHORT_DATE.match(stripped):
            continue
        # 外币参考行（原币金额 / 汇率）：算描述的一部分，不能当发生额
        if _is_ref_line(stripped):
            if cur_desc is not None:
                cur_desc.append(collapse(stripped))
            continue

        # 行首日期（可无年份）。offset 记录去掉的前缀长度，
        # 使 rest 中的字符位置能映射回整行的列坐标。
        d, rest = None, stripped
        offset = len(line) - len(line.lstrip())
        m = SHORT_DATE.match(stripped)
        if m:
            d = to_date(int(m.group(1)), MONTHS_SHORT[m.group(2).lower()[:3]], m.group(3))
            if d:
                rest = stripped[m.end():]
                offset += m.end()
        if d is None:
            for pat, _k in DATE_PATTERNS:
                mm = pat.match(stripped)
                if mm:
                    d = _parse_date_cell(mm.group(0))
                    if d:
                        rest = stripped[mm.end():]
                        offset += mm.end()
                        break

        if d is not None:
            cur_date, cur_desc = d, []

        nums = _numbers_with_pos(rest)
        if not nums:
            if rest.strip():
                cur_desc.append(collapse(rest))
            continue
        if cur_date is None:
            continue

        # 金额前的文本属于本笔描述
        head = collapse(rest[:nums[0][1]])
        parts = cur_desc + ([head] if head else [])

        debit = credit = amount = balance = None
        for val, _st, endpos in nums:
            field = min(anchors, key=lambda a: abs(a[1] - (endpos + offset)))[0]
            if field == "balance":
                balance = val
            elif field == "debit":
                debit = abs(val)
            elif field == "credit":
                credit = abs(val)
            else:
                amount = val

        if amount is not None and debit is None and credit is None:
            debit = -amount if amount < 0 else None
            credit = amount if amount > 0 else None

        net = (credit or Decimal(0)) - (debit or Decimal(0))
        rows.append({
            "date": cur_date.isoformat(),
            "description": collapse(" ".join(x for x in parts if x))[:200],
            "debit": float(debit or 0), "credit": float(credit or 0),
            "amount": float(net),
            "balance": float(balance) if balance is not None else None,
            "ref": "",
        })
        cur_desc = []          # 同一日期下可能还有下一笔

    if rows:
        warnings.append(f"已按「日期块 + 金额行」解析出 {len(rows)} 笔交易"
                        + ("" if year else "（未能推断年份，请核对日期）"))
    return rows, warnings


def _pdf_meta(text):
    """从月结单文字里提取期初/期末余额与借贷合计。

    按行扫描而非单一正则：OCR 常把「期初結餘」拆成「期 初 结」，
    且期初与期末可能同处一行（左右两端），需分别取该行首末数字。
    """
    meta = {}

    def nums(line):
        out = []
        for m in re.finditer(PDF_NUM, line):
            v = _to_decimal(m.group(0))
            if v is not None:
                out.append(v)
        return out

    def num_after(line, keyword):
        """关键词之后出现的第一个数字。同一行有多个合计时必须按位置取。"""
        i = line.lower().find(keyword.lower())
        if i < 0:
            return None
        m = None
        for mm in re.finditer(PDF_NUM, line):
            if mm.start() >= i + len(keyword):
                m = mm
                break
        if not m:
            return None
        return _to_decimal(m.group(0))

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        flat = re.sub(r"\s+", "", line)
        ns = nums(line)
        if not ns:
            continue

        low = flat.lower()

        # HSBC Business Direct：存/支合计常在同一行，须各自按位置取，不能提前 continue
        matched_agg = False
        if re.search(r"total\s*deposit\s*amount", low) and "totalCredits" not in meta:
            v = num_after(line, "Total Deposit Amount")
            if v is not None:
                meta["totalCredits"] = float(v)
                matched_agg = True
        if re.search(r"total\s*withdrawal\s*amount", low) and "totalDebits" not in meta:
            v = num_after(line, "Total Withdrawal Amount")
            if v is not None:
                meta["totalDebits"] = float(v)
                matched_agg = True
        if matched_agg:
            continue
        is_open = any(k in flat for k in ("期初結", "期初结", "上期結", "上期结",
                                          "期初餘", "期初余")) or "openingbalance" in low
        is_close = any(k in flat for k in ("期末結", "期末结", "本期結", "本期结",
                                           "期末餘", "期末余")) or "closingbalance" in low
        is_debit = any(k in flat for k in ("支出合計", "支出合计", "總支出", "总支出")) \
                   or "totaldebit" in low
        is_credit = any(k in flat for k in ("存入合計", "存入合计", "總存入", "总存入",
                                            "入合計", "入合计")) or "totalcredit" in low

        # 一行可能同时含「支出合計」与「存入合計」，须各自独立判断
        if is_open and "openingBalance" not in meta:
            meta["openingBalance"] = float(ns[0])
            if len(ns) >= 2:
                meta["closingBalance"] = float(ns[-1])
        if is_close and "closingBalance" not in meta:
            meta["closingBalance"] = float(ns[-1])
        if is_debit and "totalDebits" not in meta:
            meta["totalDebits"] = float(ns[0])
        if is_credit and "totalCredits" not in meta:
            meta["totalCredits"] = float(ns[-1])

        # HSBC：Total balance in HKD 为组合余额，取该行末位数字
        if re.search(r"total\s*balance\s*in\s*hkd", low) and "closingBalance" not in meta:
            meta["closingBalance"] = float(ns[-1])

    # 期初缺失时用 期末 − 存 + 支 反推（月结单常只列期末）
    o, c = meta.get("openingBalance"), meta.get("closingBalance")
    d, cr = meta.get("totalDebits"), meta.get("totalCredits")
    if o is None and None not in (c, d, cr):
        # 月结单通常只列期末余额；期初由「期末 − 存入 + 支出」推算
        meta["openingBalance"] = round(c - cr + d, 2)
        meta["openingDerived"] = True

    # 勾稽校验：期初 + 贷 − 借 应等于期末，不等则丢弃这两个值
    o = meta.get("openingBalance")
    if None not in (o, c, d, cr) and abs((o + cr - d) - c) > 0.005:
        meta.pop("openingBalance", None)
        meta.pop("closingBalance", None)
    return meta


def _derive_from_balances(rows, opening=None, closing=None):
    """用「余额差额」反推每笔金额。

    列位置在 OCR 文本里会漂移，按位置归列不可靠；但余额是逐笔滚动的，
    balance[i] − balance[i−1] 就是该笔净额，符号天然正确。
    只有反推结果能与期初/期末勾稽时才采用，否则保留原解析值。
    """
    if len(rows) < 2 or any(r.get("balance") is None for r in rows):
        return None

    derived = []
    for i, r in enumerate(rows):
        if i == 0:
            if opening is None:
                derived.append(None)
                continue
            net = Decimal(str(r["balance"])) - Decimal(str(opening))
        else:
            net = Decimal(str(r["balance"])) - Decimal(str(rows[i - 1]["balance"]))
        derived.append(net)

    if opening is not None and closing is not None:
        total = sum((d for d in derived if d is not None), Decimal(0))
        start = Decimal(str(opening)) if derived[0] is not None \
            else Decimal(str(rows[0]["balance"]))
        if abs((start + total) - Decimal(str(closing))) > Decimal("0.005"):
            return None

    out = []
    for i, r in enumerate(rows):
        net = derived[i]
        if net is None:
            out.append(dict(r))
            continue
        out.append(dict(r,
                        amount=float(net),
                        debit=float(-net) if net < 0 else 0.0,
                        credit=float(net) if net > 0 else 0.0))
    return out


# ---------------------------------------------------------------- 入口
def parse_statement(data: bytes, filename: str = "") -> dict:
    """解析对账单文件，返回 {source, rows, meta, warnings}。"""
    if not data:
        raise ValueError("文件为空")
    name = (filename or "").lower()
    head = data[:8]

    if head.startswith(b"%PDF") or name.endswith(".pdf"):
        text = _pdf_text(data)
        source = "pdf"
        if len(re.sub(r"\s", "", text)) < 40:
            text = _pdf_ocr(data)
            source = "pdf-ocr"
        # 优先按「日期块 + 金额行」解析（HSBC 等银行的活动明细节）；
        # 不成再退回逐行解析。
        rows, warns = _parse_pdf_bbox(data)
        if not rows:
            rows, warns = _parse_pdf_activity_blocks(text)
        if not rows:
            rows, warns = _parse_pdf_rows(text)
        meta = _pdf_meta(text)
        derived = _derive_from_balances(rows, meta.get("openingBalance"),
                                        meta.get("closingBalance"))
        if derived is not None:
            changed = sum(1 for a, b in zip(rows, derived)
                          if abs(a["amount"] - b["amount"]) > 0.005)
            rows = derived
            if changed:
                warns.append(f"已用余额逐笔差额校正 {changed} 笔金额与收支方向"
                             "（余额滚动可自校验，比文字位置更可靠）")
        if meta.pop("openingDerived", False):
            warns.append(f"月结单未列期初余额，已按「期末 {meta.get('closingBalance'):,.2f} "
                         f"− 存入 + 支出」推算为期初 {meta.get('openingBalance'):,.2f}，请核对")
        return {"source": source, "rows": rows, "meta": meta, "warnings": warns,
                "textChars": len(text)}

    if head.startswith(b"PK") or name.endswith(".xlsx") or name.endswith(".xlsm"):
        raw, warns = _parse_xlsx(data)
        source = "xlsx"
    elif head.startswith(b"\xd0\xcf\x11\xe0") or name.endswith(".xls"):
        raw, warns = _parse_xls(data)
        source = "xls"
    else:
        raw, warns = _parse_csv(data)
        source = "csv"

    # 找表头
    header_idx, mapping = None, {}
    for i, r in enumerate(raw[:30]):
        if _looks_like_header(r):
            mapping = _map_columns(r)
            if "date" in mapping:
                header_idx = i
                break
    if header_idx is None:
        # 无表头：按位置猜 —— 首列日期，其后首个数字列金额
        mapping = {"date": 0, "description": 1}
        sample = raw[0] if raw else []
        nums = [j for j, c in enumerate(sample) if _to_decimal(c) is not None]
        if len(nums) >= 2:
            mapping["amount"], mapping["balance"] = nums[0], nums[-1]
        elif nums:
            mapping["amount"] = nums[0]
        warns.append("未识别到表头，按「首列日期 + 数字列金额」猜测，请核对预览")

    rows = []
    for r in raw[(header_idx + 1) if header_idx is not None else 0:]:
        txn = _row_to_currency_row(r, mapping)
        if txn:
            rows.append(txn)

    if not rows:
        raise ValueError("未解析出任何交易行，请检查文件格式或表头")

    return {"source": source, "rows": rows, "meta": {}, "warnings": warns,
            "detectedColumns": sorted(mapping.keys())}


def _row_to_currency_row(cells, mapping):
    return _row_to_txn(cells, mapping)

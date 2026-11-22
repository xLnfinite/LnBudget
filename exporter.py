# -*- coding: utf-8 -*-
"""多格式导出：CSV / JSON / Excel(XML) / HTML，全部使用标准库生成。"""
import csv
import html
import io
import json
from datetime import datetime

from models import INCOME

TYPE_NAMES = {INCOME: "收入", "expense": "支出"}
EXT = {"csv": "csv", "json": "json", "excel": "xls", "html": "html"}
MIME = {
    "csv": "text/csv; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "excel": "application/vnd.ms-excel",
    "html": "text/html; charset=utf-8",
}


def _esc(value):
    return html.escape(str(value), quote=False)


def _fmt(value):
    return "%.2f" % value


def _meta(records, fmt):
    income = sum(r["amount"] for r in records if r["category_type"] == INCOME)
    expense = sum(r["amount"] for r in records if r["category_type"] != INCOME)
    return {
        "app": "LnBudget",
        "format": fmt,
        "count": len(records),
        "income": round(income, 2),
        "expense": round(expense, 2),
        "balance": round(income - expense, 2),
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _csv_cell(value):
    """防止 CSV 公式注入：以 = + - @ 或制表符开头的单元格前加单引号。"""
    s = str(value)
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + s
    return s


def _csv(records):
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(["金额", "收支类型", "分类", "交易时间", "备注"])
    for r in records:
        writer.writerow([_fmt(r["amount"]), TYPE_NAMES[r["category_type"]], _csv_cell(r["category"]), r["txn_time"], _csv_cell(r["note"])])
    return buf.getvalue().encode("utf-8-sig")  # BOM 便于 Excel 正确识别中文


def _json(records):
    payload = {"meta": _meta(records, "json"), "records": records}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _excel(records):
    """SpreadsheetML 2003 格式（.xls），Excel / WPS / LibreOffice 均可打开。"""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?mso-application progid="Excel.Sheet"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        "<Styles>",
        '<Style ss:ID="head"><Font ss:Bold="1" ss:Color="#FFFFFF"/><Interior ss:Color="#4F7CFF" ss:Pattern="Solid"/></Style>',
        '<Style ss:ID="income"><Font ss:Color="#16A34A"/></Style>',
        '<Style ss:ID="expense"><Font ss:Color="#DC2626"/></Style>',
        "</Styles>",
        '<Worksheet ss:Name="账目记录"><Table>',
        '<Column ss:Width="90"/><Column ss:Width="70"/><Column ss:Width="90"/><Column ss:Width="140"/><Column ss:Width="220"/>',
        "<Row>",
    ]
    for head in ["金额", "收支类型", "分类", "交易时间", "备注"]:
        parts.append('<Cell ss:StyleID="head"><Data ss:Type="String">%s</Data></Cell>' % _esc(head))
    parts.append("</Row>")
    for r in records:
        style = "income" if r["category_type"] == INCOME else "expense"
        parts.append("<Row>")
        parts.append('<Cell ss:StyleID="%s"><Data ss:Type="Number">%s</Data></Cell>' % (style, _fmt(r["amount"])))
        parts.append('<Cell><Data ss:Type="String">%s</Data></Cell>' % _esc(TYPE_NAMES[r["category_type"]]))
        parts.append('<Cell><Data ss:Type="String">%s %s</Data></Cell>' % (_esc(r["category_icon"]), _esc(r["category"])))
        parts.append('<Cell><Data ss:Type="String">%s</Data></Cell>' % _esc(r["txn_time"]))
        parts.append('<Cell><Data ss:Type="String">%s</Data></Cell>' % _esc(r["note"]))
        parts.append("</Row>")
    parts += ["</Table></Worksheet>", "</Workbook>"]
    return "\n".join(parts).encode("utf-8")


def _html(records):
    meta = _meta(records, "html")
    rows = []
    for r in records:
        cls = "inc" if r["category_type"] == INCOME else "exp"
        rows.append(
            "<tr><td class=\"%s\">%s</td><td>%s</td><td>%s %s</td><td>%s</td><td>%s</td></tr>" % (
                cls, _fmt(r["amount"]), _esc(TYPE_NAMES[r["category_type"]]),
                _esc(r["category_icon"]), _esc(r["category"]), _esc(r["txn_time"]), _esc(r["note"]),
            )
        )
    doc = (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>LnBudget 账目导出</title>"
        "<style>"
        "body{font-family:-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f3f5fa;color:#1d2433;margin:0;padding:28px}"
        ".wrap{max-width:960px;margin:0 auto;background:#fff;border-radius:14px;padding:26px 30px;box-shadow:0 2px 12px rgba(30,41,59,.08)}"
        "h1{font-size:20px;margin:0 0 4px}"
        ".meta{color:#7a8494;font-size:13px;margin-bottom:16px}"
        ".meta b{color:#1d2433}"
        "table{width:100%%;border-collapse:collapse;font-size:14px}"
        "th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eef1f6}"
        "th{background:#f4f6fb;color:#7a8494;font-size:12px}"
        ".inc{color:#16a34a;font-weight:700}"
        ".exp{color:#e5484d;font-weight:700}"
        "@media print{body{background:#fff}.wrap{box-shadow:none}}"
        "</style></head><body><div class=\"wrap\">"
        "<h1>LnBudget 账目导出</h1>"
        "<p class=\"meta\">导出时间：%s · 共 <b>%d</b> 笔 · 收入 <b>¥%s</b> · 支出 <b>¥%s</b> · 结余 <b>¥%s</b></p>"
        "<table><thead><tr><th>金额</th><th>收支类型</th><th>分类</th><th>交易时间</th><th>备注</th></tr></thead>"
        "<tbody>%s</tbody></table></div></body></html>"
    ) % (
        _esc(meta["exported_at"]), meta["count"], _fmt(meta["income"]),
        _fmt(meta["expense"]), _fmt(meta["balance"]), "".join(rows),
    )
    return doc.encode("utf-8")


_BUILDERS = {"csv": _csv, "json": _json, "excel": _excel, "html": _html}


def build(fmt, records, start="", end=""):
    if fmt not in _BUILDERS:
        raise ValueError("不支持的导出格式")
    data = _BUILDERS[fmt](records)
    fname = "账目记录_%s_%s.%s" % (start or "全部", end or "至今", EXT[fmt])
    return data, MIME[fmt], fname

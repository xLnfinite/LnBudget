# -*- coding: utf-8 -*-
"""核心业务模型（面向对象实现）。

- Category     账目分类：名称、图标、颜色、收支类型，支持校验与序列化。
- Record       账目记录：金额、分类、交易时间（+ 可选备注），金额以"分"存储避免浮点误差。
- Ledger       账本：聚合分类与记录的业务操作，所有写操作自动写入操作日志。
"""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import config

INCOME = "income"
EXPENSE = "expense"

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_NOTE_LEN = 200
MAX_AMOUNT = Decimal("9999999999.99")   # 单笔金额上限


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_txn_time(raw):
    """把前端提交的交易时间统一为 'YYYY-MM-DD HH:MM:SS'。"""
    if raw is None:
        raise ValueError("交易时间不能为空")
    s = str(raw).strip().replace("T", " ").replace("/", "-")
    if len(s) == 10:
        s += " 00:00:00"
    elif len(s) == 16:
        s += ":00"
    if len(s) != 19:
        raise ValueError("交易时间格式不正确，应为 YYYY-MM-DD HH:MM")
    try:
        datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("交易时间不是有效日期")
    return s


def parse_amount(raw):
    """金额支持 '12.34' / 12.34 / '12'，返回以"分"为单位的整数。"""
    if raw is None or str(raw).strip() == "":
        raise ValueError("金额不能为空")
    try:
        amount = Decimal(str(raw).strip()).quantize(Decimal("0.01"))
        if amount <= 0:
            raise ValueError("金额必须大于 0")
        if amount > MAX_AMOUNT:
            raise ValueError("单笔金额不能超过 100 亿元")
    except InvalidOperation:  # NaN / Infinity / 指数过大等非法值
        raise ValueError("金额格式不正确")
    return int(amount * 100)


class CategoryInUse(ValueError):
    """分类下仍有账目时抛出。"""


class Category:
    """账目分类（面向对象核心模型之一）。"""

    TYPES = (INCOME, EXPENSE)

    def __init__(self, name, ctype=EXPENSE, icon="📦", color="#4f7cff",
                 id=None, created_at=None, updated_at=None):
        self.id = id
        self.name = str(name or "").strip()
        self.ctype = ctype
        self.icon = str(icon or "📦").strip()
        self.color = str(color or "#4f7cff").strip()
        self.created_at = created_at or now_str()
        self.updated_at = updated_at or now_str()

    def validate(self):
        if not self.name:
            raise ValueError("分类名称不能为空")
        if len(self.name) > 20:
            raise ValueError("分类名称不能超过 20 个字符")
        if self.ctype not in self.TYPES:
            raise ValueError("分类类型不正确")
        if not self.icon:
            raise ValueError("分类图标不能为空")
        if len(self.icon) > 8:
            raise ValueError("图标过长，请使用 1~2 个 emoji")
        if not COLOR_RE.match(self.color):
            raise ValueError("分类颜色格式不正确")
        return self

    def to_dict(self, usage=None):
        data = {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "type": self.ctype,
            "created_at": self.created_at,
        }
        if usage:
            data["record_count"] = usage.get("record_count", 0)
            data["month_amount"] = round(usage.get("month_amount", 0) / 100, 2)
        return data

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"], name=row["name"], icon=row["icon"], color=row["color"],
            ctype=row["ctype"], created_at=row["created_at"], updated_at=row["updated_at"],
        )


class Record:
    """账目记录：金额（元） + 分类 + 交易时间（+ 可选备注）。"""

    def __init__(self, amount, category_id, txn_time=None, note="",
                 id=None, created_at=None, updated_at=None):
        self.id = id
        self.amount_cents = parse_amount(amount)
        self.category_id = int(category_id)
        self.txn_time = parse_txn_time(txn_time or now_str())
        self.note = str(note or "").strip()
        self.created_at = created_at or now_str()
        self.updated_at = updated_at or now_str()

    def validate(self):
        if len(self.note) > MAX_NOTE_LEN:
            raise ValueError("备注不能超过 %d 个字符" % MAX_NOTE_LEN)
        return self

    @property
    def amount(self):
        return round(Decimal(self.amount_cents) / 100, 2)

    def to_dict(self, category=None):
        data = {
            "id": self.id,
            "amount": float(self.amount),
            "amount_cents": self.amount_cents,
            "category_id": self.category_id,
            "note": self.note,
            "txn_time": self.txn_time,
            "created_at": self.created_at,
        }
        if category:
            data["category_name"] = category["name"]
            data["category_icon"] = category["icon"]
            data["category_color"] = category["color"]
            data["category_type"] = category["ctype"]
        return data

    @classmethod
    def from_row(cls, row):
        rec = cls.__new__(cls)
        rec.id = row["id"]
        rec.amount_cents = row["amount_cents"]
        rec.category_id = row["category_id"]
        rec.txn_time = row["txn_time"]
        rec.note = row["note"]
        rec.created_at = row["created_at"]
        rec.updated_at = row["updated_at"]
        return rec


class Ledger:
    """账本业务层：分类 / 记录的增删改查、统计、日志，全部集中于此。"""

    def __init__(self, db):
        self.db = db

    # ================= 操作日志 =================
    def log(self, action, detail="", actor=None):
        actor = actor or {}
        self.db.execute(
            "INSERT INTO logs (ts, user, ip, action, detail) VALUES (?, ?, ?, ?, ?)",
            (now_str(), actor.get("user", ""), actor.get("ip", ""), action, detail),
        )
        self._trim_logs()

    def _trim_logs(self):
        """操作日志只保留最近 LOG_MAX_ROWS 条，防止长期运行磁盘无限增长。"""
        max_rows = int(getattr(config, "LOG_MAX_ROWS", 5000))
        self.db.execute(
            "DELETE FROM logs WHERE id <= (SELECT MAX(id) - ? FROM logs)", (max_rows,)
        )

    def list_logs(self, page=1, size=20):
        total = self.db.query_one("SELECT COUNT(*) AS n FROM logs")["n"]
        offset = (page - 1) * size
        rows = self.db.query("SELECT * FROM logs ORDER BY id DESC LIMIT ? OFFSET ?", (size, offset))
        return {"items": rows, "total": total, "page": page, "pages": max(1, (total + size - 1) // size)}

    # ================= 分类 =================
    def categories(self):
        rows = self.db.query("SELECT * FROM categories ORDER BY ctype, id")
        return [Category.from_row(r) for r in rows]

    def categories_with_usage(self, month):
        rows = self.db.query(
            "SELECT c.*, COUNT(r.id) AS record_count, "
            "COALESCE(SUM(CASE WHEN substr(r.txn_time, 1, 7) = ? THEN r.amount_cents END), 0) AS month_amount "
            "FROM categories c LEFT JOIN records r ON r.category_id = c.id "
            "GROUP BY c.id ORDER BY c.ctype, c.id",
            (month,),
        )
        out = []
        for row in rows:
            cat = Category.from_row(row)
            out.append(cat.to_dict(usage={
                "record_count": row["record_count"],
                "month_amount": row["month_amount"],
            }))
        return out

    def get_category(self, cid):
        row = self.db.query_one("SELECT * FROM categories WHERE id = ?", (cid,))
        return Category.from_row(row) if row else None

    def add_category(self, name, ctype, icon, color, actor=None):
        cat = Category(name, ctype, icon, color).validate()
        cur = self.db.execute(
            "INSERT INTO categories (name, icon, color, ctype, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (cat.name, cat.icon, cat.color, cat.ctype, cat.created_at, cat.updated_at),
        )
        cat.id = cur.lastrowid
        type_name = "收入" if cat.ctype == INCOME else "支出"
        self.log("新增分类", "%s分类「%s」" % (type_name, cat.name), actor)
        return cat

    def update_category(self, cid, name, ctype, icon, color, actor=None):
        old = self.get_category(cid)
        if old is None:
            raise ValueError("分类不存在")
        cat = Category(name, ctype, icon, color).validate()
        self.db.execute(
            "UPDATE categories SET name = ?, icon = ?, color = ?, ctype = ?, updated_at = ? WHERE id = ?",
            (cat.name, cat.icon, cat.color, cat.ctype, now_str(), cid),
        )
        self.log("修改分类", "分类「%s」→「%s」" % (old.name, cat.name), actor)
        return self.get_category(cid)

    def delete_category(self, cid, actor=None):
        old = self.get_category(cid)
        if old is None:
            raise ValueError("分类不存在")
        n = self.db.query_one("SELECT COUNT(*) AS n FROM records WHERE category_id = ?", (cid,))["n"]
        if n:
            raise CategoryInUse("分类「%s」下还有 %d 笔账目，请先删除或转移相关账目" % (old.name, n))
        self.db.execute("DELETE FROM categories WHERE id = ?", (cid,))
        self.log("删除分类", "分类「%s」" % old.name, actor)

    # ================= 账目记录 =================
    @staticmethod
    def _cat_dict(cat):
        return {"id": cat.id, "name": cat.name, "icon": cat.icon, "color": cat.color, "ctype": cat.ctype}

    def add_record(self, amount, category_id, txn_time, note="", actor=None):
        cat = self.get_category(category_id)
        if cat is None:
            raise ValueError("所选分类不存在")
        rec = Record(amount, category_id, txn_time, note).validate()
        cur = self.db.execute(
            "INSERT INTO records (amount_cents, category_id, note, txn_time, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rec.amount_cents, rec.category_id, rec.note, rec.txn_time, rec.created_at, rec.updated_at),
        )
        rec.id = cur.lastrowid
        self.log("新增账目", "%s %s ¥%s（%s）" % (cat.icon, cat.name, rec.amount, rec.txn_time), actor)
        return rec.to_dict(self._cat_dict(cat))

    def update_record(self, rid, amount, category_id, txn_time, note="", actor=None):
        row = self.db.query_one("SELECT * FROM records WHERE id = ?", (rid,))
        if row is None:
            raise ValueError("账目不存在")
        cat = self.get_category(category_id)
        if cat is None:
            raise ValueError("所选分类不存在")
        rec = Record(amount, category_id, txn_time, note).validate()
        self.db.execute(
            "UPDATE records SET amount_cents = ?, category_id = ?, note = ?, txn_time = ?, updated_at = ? WHERE id = ?",
            (rec.amount_cents, rec.category_id, rec.note, rec.txn_time, now_str(), rid),
        )
        self.log("修改账目", "%s %s ¥%s（%s）" % (cat.icon, cat.name, rec.amount, rec.txn_time), actor)
        return rec.to_dict(self._cat_dict(cat))

    def delete_record(self, rid, actor=None):
        row = self.db.query_one(
            "SELECT r.*, c.name AS category_name, c.icon AS category_icon "
            "FROM records r JOIN categories c ON c.id = r.category_id WHERE r.id = ?",
            (rid,),
        )
        if row is None:
            raise ValueError("账目不存在")
        self.db.execute("DELETE FROM records WHERE id = ?", (rid,))
        self.log("删除账目", "%s %s ¥%s" % (row["category_icon"], row["category_name"], round(row["amount_cents"] / 100, 2)), actor)

    def records(self, month="", rtype="", category_id="", q="", start="", end="", page=1, size=20):
        where, params = [], []
        if month:
            where.append("substr(r.txn_time, 1, 7) = ?")
            params.append(month)
        if rtype in (INCOME, EXPENSE):
            where.append("c.ctype = ?")
            params.append(rtype)
        if category_id:
            where.append("r.category_id = ?")
            params.append(int(category_id))
        if q:
            where.append("r.note LIKE ?")
            params.append("%" + q + "%")
        if start:
            where.append("r.txn_time >= ?")
            params.append(start)
        if end:
            where.append("r.txn_time <= ?")
            params.append(end if len(end) != 10 else end + " 23:59:59")
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        total = self.db.query_one(
            "SELECT COUNT(*) AS n FROM records r JOIN categories c ON c.id = r.category_id " + wsql, params
        )["n"]
        offset = max(0, page - 1) * size
        rows = self.db.query(
            "SELECT r.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color, c.ctype AS category_type "
            "FROM records r JOIN categories c ON c.id = r.category_id " + wsql +
            " ORDER BY r.txn_time DESC, r.id DESC LIMIT ? OFFSET ?",
            params + [size, offset],
        )
        items = []
        for row in rows:
            rec = Record.from_row(row)
            items.append(rec.to_dict({
                "id": row["category_id"], "name": row["category_name"], "icon": row["category_icon"],
                "color": row["category_color"], "ctype": row["category_type"],
            }))
        return {"items": items, "total": total, "page": page, "size": size,
                "pages": max(1, (total + size - 1) // size)}

    def export_records(self, start=None, end=None, category_id="", rtype=""):
        where, params = [], []
        if start:
            where.append("r.txn_time >= ?")
            params.append(start)
        if end:
            where.append("r.txn_time <= ?")
            params.append(end if len(end) != 10 else end + " 23:59:59")
        if rtype in (INCOME, EXPENSE):
            where.append("c.ctype = ?")
            params.append(rtype)
        if category_id:
            where.append("r.category_id = ?")
            params.append(int(category_id))
        wsql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = self.db.query(
            "SELECT r.*, c.name AS category_name, c.icon AS category_icon, c.color AS category_color, c.ctype AS category_type "
            "FROM records r JOIN categories c ON c.id = r.category_id " + wsql +
            " ORDER BY r.txn_time DESC, r.id DESC",
            params,
        )
        return [{
            "id": r["id"],
            "amount": round(r["amount_cents"] / 100, 2),
            "category": r["category_name"],
            "category_icon": r["category_icon"],
            "category_color": r["category_color"],
            "category_type": r["category_type"],
            "note": r["note"],
            "txn_time": r["txn_time"],
        } for r in rows]

    # ================= 统计 =================
    def summary(self, month):
        row = self.db.query_one(
            "SELECT "
            "COALESCE(SUM(CASE WHEN c.ctype = 'income' THEN r.amount_cents END), 0) AS income, "
            "COALESCE(SUM(CASE WHEN c.ctype = 'expense' THEN r.amount_cents END), 0) AS expense, "
            "COUNT(r.id) AS n "
            "FROM records r JOIN categories c ON c.id = r.category_id "
            "WHERE substr(r.txn_time, 1, 7) = ?",
            (month,),
        )
        recent = self.records(size=6)["items"]
        return {
            "month": month,
            "income": round(row["income"] / 100, 2),
            "expense": round(row["expense"] / 100, 2),
            "balance": round((row["income"] - row["expense"]) / 100, 2),
            "count": row["n"],
            "recent": recent,
        }

    def stats_by_category(self, month):
        rows = self.db.query(
            "SELECT c.id AS category_id, c.name, c.icon, c.color, c.ctype, "
            "COALESCE(SUM(r.amount_cents), 0) AS amount_cents, COUNT(r.id) AS n "
            "FROM categories c LEFT JOIN records r ON r.category_id = c.id AND substr(r.txn_time, 1, 7) = ? "
            "GROUP BY c.id HAVING n > 0 ORDER BY amount_cents DESC",
            (month,),
        )
        out = {INCOME: [], EXPENSE: []}
        for r in rows:
            out[r["ctype"]].append({
                "category_id": r["category_id"],
                "name": r["name"],
                "icon": r["icon"],
                "color": r["color"],
                "amount": round(r["amount_cents"] / 100, 2),
                "count": r["n"],
            })
        return out

    def trend(self, months=6):
        def shift(ym, delta):
            y, m = int(ym[:4]), int(ym[5:7])
            total = y * 12 + (m - 1) + delta
            y2, m2 = divmod(total, 12)
            return "%04d-%02d" % (y2, m2 + 1)

        current = datetime.now().strftime("%Y-%m")
        labels, income, expense = [], [], []
        for i in range(months - 1, -1, -1):
            ym = shift(current, -i)
            row = self.db.query_one(
                "SELECT "
                "COALESCE(SUM(CASE WHEN c.ctype = 'income' THEN r.amount_cents END), 0) AS inc, "
                "COALESCE(SUM(CASE WHEN c.ctype = 'expense' THEN r.amount_cents END), 0) AS exp "
                "FROM records r JOIN categories c ON c.id = r.category_id WHERE substr(r.txn_time, 1, 7) = ?",
                (ym,),
            )
            labels.append(ym)
            income.append(round(row["inc"] / 100, 2))
            expense.append(round(row["exp"] / 100, 2))
        return {"labels": labels, "income": income, "expense": expense}
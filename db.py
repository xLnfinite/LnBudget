# -*- coding: utf-8 -*-
"""SQLite 数据访问层（线程安全）。"""
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    icon       TEXT    NOT NULL DEFAULT '📦',
    color      TEXT    NOT NULL DEFAULT '#4f7cff',
    ctype      TEXT    NOT NULL CHECK (ctype IN ('income', 'expense')),
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    amount_cents INTEGER NOT NULL,
    category_id  INTEGER NOT NULL REFERENCES categories(id),
    note         TEXT    NOT NULL DEFAULT '',
    txn_time     TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    user   TEXT NOT NULL DEFAULT '',
    ip     TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_time ON records (txn_time);
CREATE INDEX IF NOT EXISTS idx_records_cat  ON records (category_id);
CREATE INDEX IF NOT EXISTS idx_logs_ts      ON logs (ts);
"""

DEFAULT_CATEGORIES = [
    ("餐饮", "🍜", "#f97316", "expense"),
    ("交通", "🚌", "#0ea5e9", "expense"),
    ("购物", "🛍️", "#ec4899", "expense"),
    ("居住", "🏠", "#8b5cf6", "expense"),
    ("娱乐", "🎮", "#22c55e", "expense"),
    ("医疗", "💊", "#ef4444", "expense"),
    ("工资", "💼", "#10b981", "income"),
    ("理财", "📈", "#3b82f6", "income"),
    ("其他", "🎁", "#64748b", "income"),
]


class Database:
    """线程安全的 SQLite 封装：所有操作通过同一连接 + 锁完成。"""

    def __init__(self, path):
        os.umask(0o077)  # 本进程新建文件默认仅属主可读写（不影响其他进程）
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.execute_script(SCHEMA)
        self._harden_permissions()
        self._seed()

    def execute_script(self, script):
        with self._lock:
            self._conn.executescript(script)
            self._conn.commit()

    def execute(self, sql, params=()):
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
            except OverflowError:
                raise ValueError("数值参数超出范围")
            self._conn.commit()
            return cur

    def query(self, sql, params=()):
        with self._lock:
            try:
                rows = self._conn.execute(sql, params).fetchall()
            except OverflowError:
                raise ValueError("数值参数超出范围")
            return [dict(row) for row in rows]

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def get_setting(self, key, default=None):
        """读取一条设置；不存在时返回 default。"""
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        """写入/覆盖一条设置（登录密码哈希等需要运行期持久化的值）。"""
        self.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

    def _seed(self):
        if self.query_one("SELECT COUNT(*) AS n FROM categories")["n"] == 0:
            from datetime import datetime
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for name, icon, color, ctype in DEFAULT_CATEGORIES:
                self.execute(
                    "INSERT INTO categories (name, icon, color, ctype, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (name, icon, color, ctype, ts, ts),
                )

    def _harden_permissions(self):
        """收紧数据库文件与目录权限（多用户 Linux 上防止他人直读账目；Windows 自动跳过）。"""
        if os.name != "posix":
            return
        try:
            os.chmod(self.path, 0o600)
            parent = os.path.dirname(self.path)
            if parent:
                os.chmod(parent, 0o700)
            for suffix in ("-wal", "-shm"):
                p = self.path + suffix
                if os.path.exists(p):
                    os.chmod(p, 0o600)
        except OSError:
            pass

    def close(self):
        with self._lock:
            self._conn.close()
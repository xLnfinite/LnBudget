# -*- coding: utf-8 -*-
"""LnBudget —— 在线记账 Web 服务（纯 Python 标准库实现，Linux / Windows 通用）。

启动：python3 app.py [--host 0.0.0.0] [--port 8000]
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import ssl
import sys
import threading
import traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import config  # noqa: E402
import exporter  # noqa: E402
from db import Database  # noqa: E402
from models import INCOME, EXPENSE, CategoryInUse, Ledger, now_str  # noqa: E402

db = Database(config.DB_PATH)
ledger = Ledger(db)

sessions = {}        # token -> {"expires": datetime}
login_fails = {}     # ip -> [datetime, ...]
login_last = {}      # ip -> datetime（登录尝试限速）

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
MAX_BODY_SIZE = 1024 * 1024   # 请求体上限 1MB

# 登录加固：
#   MIN_LOGIN_INTERVAL —— 同一 IP 两次登录尝试的最小间隔，防攻击者用多 IP 轮换持续刷 PBKDF2 计算（CPU DoS）
#   MAX_PASSWORD_LEN  —— 密码长度上限，防止超大输入进入哈希计算
#   MIN_PASSWORD_LEN  —— 修改密码时新密码的最小长度
#   MAX_USERNAME_LEN  —— 用户名长度上限
#   PASSWORD_ITERATIONS —— PBKDF2-SHA256 迭代次数（OWASP 2023 推荐 600000）
MIN_LOGIN_INTERVAL = 1.0
MAX_PASSWORD_LEN = 256
MIN_PASSWORD_LEN = 8
MAX_USERNAME_LEN = 32
PASSWORD_ITERATIONS = 600000

# 出厂初始密码：首次启动时自动写入数据库（无需用户手动生成哈希）；
# 登录后可在页面内「修改密码」，修改结果持久化到数据库 settings 表。
INITIAL_PASSWORD = "admin"


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def verify_password(password, stored):
    """校验密码：stored 格式为 pbkdf2_sha256$迭代次数$盐(hex)$哈希(hex)。"""
    try:
        algo, iterations, salt_hex, hash_hex = str(stored).split("$")
        iterations = int(iterations)
    except (ValueError, AttributeError):
        return False
    if algo != "pbkdf2_sha256" or iterations < 1 or iterations > 10000000:
        return False
    try:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt_hex), iterations, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def hash_password(password, iterations=PASSWORD_ITERATIONS):
    """生成 PBKDF2-SHA256 加盐哈希。

    注意：盐每次随机，所以同一个密码多次生成的结果一定不同——这是正常现象，
    校验时盐本身就从存储值中取出，哈希不同不代表校验失败。
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt.hex(), digest.hex())


def init_password():
    """确保数据库中存在登录账号与密码哈希，返回当前是否仍在使用初始密码。

    优先级：数据库已存哈希（运行期修改过）> config.PASSWORD_HASH（兼容旧配置）
    > 出厂初始密码 INITIAL_PASSWORD。用户名同理：数据库已存 > config.USERNAME > admin。
    """
    if not db.get_setting("username"):
        db.set_setting("username", (getattr(config, "USERNAME", "") or "admin").strip() or "admin")
    if db.get_setting("password_hash"):
        return db.get_setting("password_is_initial") == "1"
    seed = (getattr(config, "PASSWORD_HASH", "") or "").strip()
    if seed:
        db.set_setting("password_hash", seed)
        db.set_setting("password_is_initial", "0")
        return False
    db.set_setting("password_hash", hash_password(INITIAL_PASSWORD))
    db.set_setting("password_is_initial", "1")
    return True


def current_username():
    """当前生效的登录用户名：运行期修改过则取数据库，否则取配置种子。"""
    return db.get_setting("username") or (getattr(config, "USERNAME", "") or "admin")


USING_INITIAL_PASSWORD = init_password()


class LnBudgetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "LnBudget/1.0"
    timeout = 30        # 单连接读写超时（秒）：慢速连接/扫描探测 30 秒内无进展即断开，防止线程被无限占用

    # ================= 基础工具 =================
    def handle(self):
        """连接层异常统一兜底（断连、读超时、TLS 握手失败、扫描器探测等）。

        这些异常若冒泡到 socketserver，会在每次连接上打印整段 traceback 刷屏。
        业务层异常（ApiError 等）在 _dispatch 中已处理，不会流到这里。
        """
        try:
            super().handle()
        except (ConnectionError, TimeoutError, ssl.SSLError, OSError):
            self.close_connection = True

    def log_message(self, fmt, *args):
        msg = fmt % args
        msg = "".join(ch if ch >= " " and ch != "\x7f" else "?" for ch in msg)
        sys.stdout.write("[%s] %s\n" % (now_str(), msg))
        sys.stdout.flush()

    def _send(self, status, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if self._tls():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                         "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _json(self, status, payload, extra=None):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), extra=extra)

    def _ok(self, data=None):
        self._json(200, {"ok": True, "data": data})

    def _fail(self, status, message):
        self._json(status, {"ok": False, "error": message})

    def _cookie(self, name):
        header = self.headers.get("Cookie", "")
        for part in header.split(";"):
            part = part.strip()
            if part.startswith(name + "="):
                return part[len(name) + 1:]
        return None

    def _tls(self):
        """当前连接是否为 TLS（config.SSL_CERT 启用 HTTPS 时为 True）。"""
        return isinstance(self.connection, ssl.SSLSocket)

    def _session_cookie(self, token, max_age):
        """构造会话 Cookie；HTTPS 下自动追加 Secure。"""
        secure = "; Secure" if self._tls() else ""
        return "session=%s; Path=/; HttpOnly; SameSite=Lax%s; Max-Age=%d" % (token, secure, max_age)

    def _body_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > MAX_BODY_SIZE:
            remaining = min(length, MAX_BODY_SIZE + 65536)
            try:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except OSError:
                pass
            raise ApiError(413, "请求体过大")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "请求数据格式错误")
        if not isinstance(data, dict):
            raise ApiError(400, "请求数据格式错误")
        return data

    def _ip(self):
        if config.TRUST_XFF:
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    def _auth(self):
        token = self._cookie("session")
        sess = sessions.get(token) if token else None
        if not sess or sess["expires"] < datetime.now():
            if token:
                sessions.pop(token, None)
            raise ApiError(401, "未登录或登录已过期")
        sess["expires"] = datetime.now() + timedelta(hours=config.SESSION_HOURS)
        return sess["user"]

    def _csrf_check(self, path):
        if self.command in SAFE_METHODS or path == "/api/login":
            return
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            raise ApiError(403, "非法请求来源")

    @staticmethod
    def _param(qs, name, default=""):
        vals = qs.get(name)
        return vals[0] if vals else default

    # ================= 路由 =================
    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def _dispatch(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            self._csrf_check(path)
            if path.startswith("/api/"):
                self._route_api(path, qs)
            elif path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/"):])
            else:
                self._fail(404, "页面不存在")
        except ApiError as err:
            self._fail(err.status, err.message)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except ValueError as err:
            self._fail(400, str(err))
        except Exception:
            traceback.print_exc()
            try:
                self._fail(500, "服务器内部错误")
            except Exception:
                pass

    def _static(self, rel):
        rel = rel.lstrip("/")
        if rel in ("", "index.html"):
            rel = "index.html"
        static_root = os.path.realpath(config.STATIC_DIR)
        full = os.path.realpath(os.path.join(static_root, rel))
        if not (full == static_root or full.startswith(static_root + os.sep)):
            raise ApiError(403, "禁止访问")
        if not os.path.isfile(full):
            raise ApiError(404, "资源不存在")
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # ================= API =================
    def _route_api(self, path, qs):
        # -------- 会话 --------
        if self.command == "GET" and path == "/api/me":
            user = self._auth()
            return self._ok({"username": user, "server_time": now_str(),
                             "app": config.APP_NAME, "version": config.VERSION,
                             "initial_password": db.get_setting("password_is_initial") == "1"})

        if path == "/api/account":
            return self._api_account()

        if path == "/api/login":
            return self._api_login()

        if self.command == "POST" and path == "/api/logout":
            user = self._auth()
            token = self._cookie("session")
            if token:
                sessions.pop(token, None)
            ledger.log("退出登录", "用户「%s」退出登录" % user, {"user": user, "ip": self._ip()})
            return self._json(200, {"ok": True},
                              extra={"Set-Cookie": self._session_cookie("", 0)})

        # -------- 分类 --------
        if path == "/api/categories" and self.command == "GET":
            self._auth()
            month = self._param(qs, "month") or datetime.now().strftime("%Y-%m")
            return self._ok({"items": ledger.categories_with_usage(month), "month": month})

        if path == "/api/categories" and self.command == "POST":
            user = self._auth()
            body = self._body_json()
            cat = ledger.add_category(body.get("name"), body.get("type"), body.get("icon"), body.get("color"),
                                      {"user": user, "ip": self._ip()})
            return self._ok(cat.to_dict())

        # -------- 账目记录 --------
        if path == "/api/records" and self.command == "GET":
            self._auth()
            page = max(int(self._param(qs, "page") or 1), 1)
            size = min(max(int(self._param(qs, "size") or 20), 1), 100)
            data = ledger.records(
                month=self._param(qs, "month"), rtype=self._param(qs, "type"),
                category_id=self._param(qs, "category"), q=self._param(qs, "q"),
                start=self._param(qs, "start"), end=self._param(qs, "end"),
                page=page, size=size,
            )
            return self._ok(data)

        if path == "/api/records" and self.command == "POST":
            user = self._auth()
            body = self._body_json()
            rec = ledger.add_record(body.get("amount"), body.get("category_id"), body.get("txn_time"),
                                    body.get("note", ""), {"user": user, "ip": self._ip()})
            return self._ok(rec)

        # -------- 汇总与统计 --------
        if path == "/api/summary" and self.command == "GET":
            self._auth()
            month = self._param(qs, "month") or datetime.now().strftime("%Y-%m")
            return self._ok(ledger.summary(month))

        if path == "/api/stats/categories" and self.command == "GET":
            self._auth()
            month = self._param(qs, "month") or datetime.now().strftime("%Y-%m")
            stats = ledger.stats_by_category(month)
            stats["month"] = month
            return self._ok(stats)

        if path == "/api/stats/trend" and self.command == "GET":
            self._auth()
            months = min(max(int(self._param(qs, "months") or 6), 2), 24)
            return self._ok(ledger.trend(months))

        # -------- 操作日志 --------
        if path == "/api/logs" and self.command == "GET":
            self._auth()
            page = max(int(self._param(qs, "page") or 1), 1)
            size = min(max(int(self._param(qs, "size") or 20), 1), 100)
            return self._ok(ledger.list_logs(page, size))

        # -------- 导出 --------
        if path == "/api/export" and self.command == "POST":
            return self._api_export()

        m = re.fullmatch(r"/api/categories/(\d+)", path)
        if m:
            return self._api_category(int(m.group(1)))

        m = re.fullmatch(r"/api/records/(\d+)", path)
        if m:
            return self._api_record(int(m.group(1)))

        raise ApiError(404, "接口不存在")

    def _api_login(self):
        if self.command != "POST":
            raise ApiError(405, "方法不允许")
        ip = self._ip()
        now = datetime.now()
        lock_window = timedelta(minutes=config.LOGIN_LOCK_MINUTES)
        if len(login_fails) > 1000:  # 防内存膨胀：全局清理过期失败记录
            for key in list(login_fails):
                login_fails[key] = [t for t in login_fails[key] if now - t < lock_window]
                if not login_fails[key]:
                    del login_fails[key]
            for key in list(login_last):  # 同步清理限速记录
                if now - login_last[key] > timedelta(seconds=MIN_LOGIN_INTERVAL * 10):
                    del login_last[key]
        fails = [t for t in login_fails.get(ip, []) if now - t < lock_window]
        if len(fails) >= config.MAX_LOGIN_FAILS:
            left = int((lock_window - (now - min(fails))).total_seconds())
            ledger.log("登录锁定", "IP %s 失败次数过多，锁定中" % ip, {"user": "-", "ip": ip})
            raise ApiError(429, "失败次数过多，请 %d 秒后再试" % max(left, 1))
        last = login_last.get(ip)
        if last is not None and (now - last).total_seconds() < MIN_LOGIN_INTERVAL:
            # 频率限制：不读取请求体、不执行哈希计算、不写日志、不计数，
            # 防止攻击者用多 IP 轮换的方式持续刷 PBKDF2 计算拖垮 CPU。
            raise ApiError(429, "尝试过于频繁，请稍候再试")
        body = self._body_json()
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        user_ok = hmac.compare_digest(username, current_username())
        stored = db.get_setting("password_hash") or ""
        if len(password) <= MAX_PASSWORD_LEN:
            pass_ok = verify_password(password, stored)
        else:
            pass_ok = False  # 超长密码必然错误，直接跳过昂贵的 PBKDF2 计算
        if not (user_ok and pass_ok):
            fails.append(now)
            login_fails[ip] = fails
            login_last[ip] = now
            remaining = config.MAX_LOGIN_FAILS - len(fails)
            ledger.log("登录失败", "账号「%s」密码错误（IP: %s）" % (username[:20], ip),
                       {"user": username[:20] or "-", "ip": ip})
            raise ApiError(401, "账号或密码错误（剩余尝试次数 %d）" % max(remaining, 0))
        login_fails.pop(ip, None)
        login_last.pop(ip, None)
        for key in list(sessions):  # 清理过期会话，防止字典无限增长
            if sessions[key]["expires"] < now:
                del sessions[key]
        token = secrets.token_urlsafe(32)
        login_user = current_username()
        sessions[token] = {"user": login_user,
                           "expires": now + timedelta(hours=config.SESSION_HOURS)}
        ledger.log("登录成功", "用户「%s」登录（IP: %s）" % (login_user, ip),
                   {"user": login_user, "ip": ip})
        return self._json(200, {"ok": True, "data": {"username": login_user,
                                                     "initial_password": db.get_setting("password_is_initial") == "1"}},
                          extra={"Set-Cookie": self._session_cookie(token, config.SESSION_HOURS * 3600)})

    def _api_account(self):
        """修改登录账号（用户名 / 密码）：校验当前密码 → 持久化 → 所有会话失效，强制重新登录。"""
        self._auth()
        if self.command != "POST":
            raise ApiError(405, "方法不允许")
        body = self._body_json()
        current = str(body.get("current_password", ""))
        new_user = str(body.get("new_username") or "").strip()
        new_pass = str(body.get("new_password") or "")
        if len(current) > MAX_PASSWORD_LEN or not verify_password(current, db.get_setting("password_hash") or ""):
            raise ApiError(401, "当前密码不正确")
        cur_user = current_username()
        changed_user = False
        changed_pass = False
        if new_user and new_user != cur_user:
            if len(new_user) > MAX_USERNAME_LEN:
                raise ApiError(400, "用户名过长（最多 %d 个字符）" % MAX_USERNAME_LEN)
            db.set_setting("username", new_user)
            changed_user = True
        if new_pass:
            if len(new_pass) < MIN_PASSWORD_LEN:
                raise ApiError(400, "新密码至少需要 %d 位" % MIN_PASSWORD_LEN)
            if len(new_pass) > MAX_PASSWORD_LEN:
                raise ApiError(400, "新密码过长（最多 %d 位）" % MAX_PASSWORD_LEN)
            if new_pass == current:
                raise ApiError(400, "新密码不能与当前密码相同")
            db.set_setting("password_hash", hash_password(new_pass))
            db.set_setting("password_is_initial", "0")
            changed_pass = True
        if not (changed_user or changed_pass):
            raise ApiError(400, "用户名与密码均未改动")
        sessions.clear()  # 强制重新登录：包括当前令牌在内全部失效
        what = "、".join(s for s, on in (("用户名", changed_user), ("密码", changed_pass)) if on)
        ledger.log("修改账户", "用户「%s」更新了%s" % (cur_user, what), {"user": cur_user, "ip": self._ip()})
        return self._ok({"username": db.get_setting("username"), "re_login": True})

    def _api_category(self, cid):
        user = self._auth()
        if self.command == "PUT":
            body = self._body_json()
            cat = ledger.update_category(cid, body.get("name"), body.get("type"), body.get("icon"),
                                         body.get("color"), {"user": user, "ip": self._ip()})
            return self._ok(cat.to_dict())
        if self.command == "DELETE":
            try:
                ledger.delete_category(cid, {"user": user, "ip": self._ip()})
            except CategoryInUse as err:
                raise ApiError(409, str(err))
            return self._ok()
        raise ApiError(405, "方法不允许")

    def _api_record(self, rid):
        user = self._auth()
        if self.command == "PUT":
            body = self._body_json()
            rec = ledger.update_record(rid, body.get("amount"), body.get("category_id"),
                                       body.get("txn_time"), body.get("note", ""),
                                       {"user": user, "ip": self._ip()})
            return self._ok(rec)
        if self.command == "DELETE":
            ledger.delete_record(rid, {"user": user, "ip": self._ip()})
            return self._ok()
        raise ApiError(405, "方法不允许")

    def _api_export(self):
        user = self._auth()
        body = self._body_json()
        fmt = str(body.get("format", "csv")).lower()
        if fmt not in exporter.EXT:
            raise ApiError(400, "不支持的导出格式")
        start = str(body.get("start") or "").strip()
        end = str(body.get("end") or "").strip()
        if start and len(start) == 10:
            start += " 00:00:00"
        if end and len(end) == 10:
            end += " 23:59:59"
        records = ledger.export_records(start=start or None, end=end or None,
                                        category_id=str(body.get("category_id") or ""),
                                        rtype=str(body.get("type") or ""))
        data, mime, fname = exporter.build(fmt, records, start=start[:10], end=end[:10])
        ledger.log("导出账目", "格式 %s，共 %d 笔（%s ~ %s）"
                   % (fmt.upper(), len(records), start or "全部", end or "至今"),
                   {"user": user, "ip": self._ip()})
        self._send(200, data, mime, {
            "Content-Disposition": "attachment; filename=\"LnBudget-export.%s\"; filename*=UTF-8''%s"
                                   % (exporter.EXT[fmt], quote(fname)),
        })


class GuardedHTTPServer(ThreadingHTTPServer):
    """带并发上限的 ThreadingHTTPServer。

    socketserver 默认每个连接创建一个线程且没有上限，公网环境下的扫描器/
    慢速连接（Slowloris）会让线程数无限增长，最终耗尽内存导致进程被系统杀掉。
    这里用计数信号量限制同时处理的连接数，超限直接拒绝，保证进程稳定运行。
    """
    daemon_threads = True
    request_queue_size = 128   # 未 accept 连接的排队上限

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._request_guard = threading.BoundedSemaphore(config.MAX_CONCURRENT_REQUESTS)

    def process_request(self, request, client_address):
        if not self._request_guard.acquire(blocking=False):
            # 并发已达上限：直接关闭该连接，不再创建线程
            try:
                self.shutdown_request(request)
            except OSError:
                pass
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_guard.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_guard.release()

    def handle_error(self, request, client_address):
        """连接类异常（断连/超时/扫描探测）静默丢弃；只有真正的服务端异常才打印 traceback。"""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, ssl.SSLError, OSError)):
            return
        super().handle_error(request, client_address)


def build_ssl_context(cert_path, key_path=None):
    """按 PEM 证书构建 TLS 上下文（最低 TLS 1.2）。

    证书或私钥不可用时抛出 OSError / ssl.SSLError，由调用方转成友好提示。
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path or None)
    return ctx


def main():
    parser = argparse.ArgumentParser(description="LnBudget 在线记账服务")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()

    server = GuardedHTTPServer((args.host, args.port), LnBudgetHandler)
    server.daemon_threads = True
    server.timeout = 30   # 主循环无新连接时的轮询间隔

    scheme = "http"
    if config.SSL_CERT:   # 配置了证书 → 单端口只提供 HTTPS
        try:
            server.socket = build_ssl_context(config.SSL_CERT, config.SSL_KEY).wrap_socket(
                server.socket, server_side=True, do_handshake_on_connect=False)
            scheme = "https"
        except (OSError, ssl.SSLError) as err:
            server.server_close()
            print("  [错误] 启用 HTTPS 失败：%s" % err, file=sys.stderr)
            print("  请检查 config.py 的 SSL_CERT / SSL_KEY 是否为有效的 PEM 证书与私钥；"
                  "两者留空则使用明文 HTTP。", file=sys.stderr)
            return 1

    port = server.server_address[1]
    print("=" * 58)
    print("  %s v%s" % (config.APP_NAME, config.VERSION))
    print("  服务地址 : %s://%s:%d" % (scheme, args.host, port))
    if scheme == "https":
        print("  HTTPS 证书: %s" % config.SSL_CERT)
    print("  登录账号 : %s" % current_username())
    if USING_INITIAL_PASSWORD:
        print("  初始密码 : admin（尚未修改，登录后请立即在页面左侧「修改密码」中修改）")
    print("  数据文件 : %s" % config.DB_PATH)
    print("  按 Ctrl+C 停止服务")
    print("=" * 58)
    if db.get_setting("password_is_initial") == "1":
        # 初始密码 admin 是公开的：若部署后未修改，任何扫描器都能直接登录。
        print("  ⚠ 提示：当前仍在使用初始密码 admin，首次登录后请立即修改！")
        print("    修改入口：登录后点击左侧栏钥匙图标（或设置区「修改密码」）。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务 ...")
    finally:
        server.server_close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
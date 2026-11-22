# -*- coding: utf-8 -*-
"""LnBudget 端到端 API 自检脚本：在进程内启动服务（临时端口 + 临时数据库）并验证全部接口。"""
import hashlib
import json
import os
import secrets
import ssl
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import http.cookiejar
import time
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from http.server import ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import config
config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="lnbudget_test_"), "ledger.db")
config.PORT = 0

# 测试凭据：优先用环境变量 LNBUDGET_PASSWORD；未设置时随机生成，并同步生成对应哈希
# 写入 config.PASSWORD_HASH（必须在 import app 之前完成）——全程不依赖任何固定密码。
PASSWORD = os.environ.get("LNBUDGET_PASSWORD") or secrets.token_urlsafe(12)
_salt = secrets.token_bytes(16)
config.PASSWORD_HASH = "pbkdf2_sha256$600000$%s$%s" % (
    _salt.hex(),
    hashlib.pbkdf2_hmac("sha256", PASSWORD.encode("utf-8"), _salt, 600000).hex(),
)

import app as appmod

server = ThreadingHTTPServer(("127.0.0.1", 0), appmod.LnBudgetHandler)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % server.server_address[1]

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

passed = 0


def req(method, path, body=None, expect=200, csrf=True):
    global passed
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    r.add_header("Connection", "close")
    if csrf:
        r.add_header("X-Requested-With", "XMLHttpRequest")
    for attempt in (1, 2, 3, 4):
        try:
            with opener.open(r, timeout=10) as resp:
                status, raw, headers = resp.status, resp.read(), resp.headers
            break
        except urllib.error.HTTPError as e:
            status, raw, headers = e.code, e.read(), e.headers
            break
        except (ConnectionResetError, ConnectionAbortedError, TimeoutError):
            time.sleep(0.25 * attempt)
            if attempt == 4:
                raise
    if status != expect:
        raise AssertionError("%s %s -> expect %d got %d: %s" % (method, path, expect, status, raw[:200]))
    passed += 1
    print("  ok  %s %-38s -> %d" % (method, path, status))
    return raw, headers


print("== 静态资源 ==")
html, _ = req("GET", "/")
assert "LnBudget" in html.decode("utf-8")
req("GET", "/static/js/app.js")
req("GET", "/static/css/app.css")
req("GET", "/static/js/charts.js")

print("== 鉴权 ==")
# 请求体超限应返回 413
r = urllib.request.Request(base + "/api/login", data=b"x" * (1024 * 1024 + 16), method="POST")
r.add_header("Content-Type", "application/json")
r.add_header("Connection", "close")
for attempt in (1, 2, 3, 4):
    try:
        opener.open(r, timeout=10)
        raise AssertionError("请求体超限未返回 413")
    except urllib.error.HTTPError as e:
        assert e.code == 413, "expect 413 got %d" % e.code
        break
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
        time.sleep(0.25 * attempt)
        if attempt == 4:
            raise
passed += 1
print("  ok  超大请求体被拒绝 -> 413")

req("GET", "/api/me", expect=401)
req("POST", "/api/login", {"username": "admin", "password": "wrong"}, expect=401)
time.sleep(1.1)  # 登录限速（app.MIN_LOGIN_INTERVAL=1s）：失败后 1 秒内不允许再次尝试
raw, headers = req("POST", "/api/login", {"username": "admin", "password": PASSWORD})
set_cookie = headers.get("Set-Cookie", "")
assert "HttpOnly" in set_cookie and "Secure" not in set_cookie, set_cookie
print("  ok  明文 HTTP 下会话 Cookie 不带 Secure")
passed += 1
req("GET", "/api/me")

print("== 登录加固（限速 / 密码长度） ==")
# 超长密码（>256 字符）应直接失败且不进入哈希计算
req("POST", "/api/login", {"username": "admin", "password": "x" * 300}, expect=401)
# 同一 IP 间隔不足 1 秒的再次尝试应被限速（429，且不计入失败次数）
req("POST", "/api/login", {"username": "admin", "password": "wrong"}, expect=429)
time.sleep(1.1)
# 间隔足够后恢复 401
req("POST", "/api/login", {"username": "admin", "password": "wrong"}, expect=401)
time.sleep(1.1)
# 用正确密码登录，清空失败计数，避免影响后续测试
req("POST", "/api/login", {"username": "admin", "password": PASSWORD})

print("== HTTPS 支持（默认关闭） ==")
assert not config.SSL_CERT and not config.SSL_KEY, "测试环境不应默认启用 HTTPS"
try:
    appmod.build_ssl_context("/nonexistent/cert.pem", "/nonexistent/key.pem")
    raise AssertionError("证书缺失时未报错")
except (OSError, ssl.SSLError):
    print("  ok  证书/私钥缺失时正确报错")
passed += 1

print("== CSRF 防护 ==")
r = urllib.request.Request(base + "/api/export", data=b"{}", method="POST")
r.add_header("Content-Type", "application/json")
r.add_header("Connection", "close")
for attempt in (1, 2, 3, 4):
    try:
        opener.open(r, timeout=10)
        raise AssertionError("无 CSRF 头竟然通过")
    except urllib.error.HTTPError as e:
        assert e.code == 403, "expect 403 got %d" % e.code
        break
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, TimeoutError):
        time.sleep(0.25 * attempt)
        if attempt == 4:
            raise
passed += 1
print("  ok  无 X-Requested-With 被拒绝 -> 403")

print("== 分类（OOP 模型） ==")
raw, _ = req("GET", "/api/categories")
cats = json.loads(raw.decode("utf-8"))["data"]["items"]
assert len(cats) >= 9, "默认分类应为 9 个"
raw, _ = req("POST", "/api/categories", {"name": "宠物", "type": "expense", "icon": "🐶", "color": "#f97316"})
cat_id = json.loads(raw.decode("utf-8"))["data"]["id"]
req("PUT", "/api/categories/%d" % cat_id, {"name": "宠物用品", "type": "expense", "icon": "🐶", "color": "#f97316"})
req("POST", "/api/categories", {"name": "工资奖金", "type": "income", "icon": "💰", "color": "#16a34a"})
req("POST", "/api/categories", {"name": "", "type": "expense", "icon": "📦", "color": "#000000"}, expect=400)

print("== 账目记录 ==")
raw, _ = req("GET", "/api/categories")
cats = json.loads(raw.decode("utf-8"))["data"]["items"]
food = next(c["id"] for c in cats if c["name"] == "餐饮")
salary = next(c["id"] for c in cats if c["name"] == "工资")
raw, _ = req("POST", "/api/records", {"amount": 35.5, "category_id": food, "txn_time": "2026-08-16T12:30", "note": "午餐"})
rec_id = json.loads(raw.decode("utf-8"))["data"]["id"]
req("POST", "/api/records", {"amount": "8000", "category_id": salary, "txn_time": "2026-08-01T09:00", "note": "八月工资"})
req("POST", "/api/records", {"amount": -5, "category_id": food, "txn_time": "2026-08-16T12:30"}, expect=400)
req("POST", "/api/records", {"amount": 10, "category_id": 99999, "txn_time": "2026-08-16T12:30"}, expect=400)
req("PUT", "/api/records/%d" % rec_id, {"amount": 42, "category_id": food, "txn_time": "2026-08-16T13:00", "note": "午餐（改）"})
raw, _ = req("GET", "/api/records?month=2026-08&size=20")
data = json.loads(raw.decode("utf-8"))["data"]
assert data["total"] == 2, "8 月应有 2 笔"
raw, _ = req("GET", "/api/records?q=%E5%8D%88%E9%A4%90&size=20")  # q=午餐
assert json.loads(raw.decode("utf-8"))["data"]["total"] == 1

print("== 统计 ==")
raw, _ = req("GET", "/api/summary?month=2026-08")
summary = json.loads(raw.decode("utf-8"))["data"]
assert summary["income"] == 8000 and summary["expense"] == 42, summary
raw, _ = req("GET", "/api/stats/categories?month=2026-08")
stats = json.loads(raw.decode("utf-8"))["data"]
assert len(stats["expense"]) == 1 and len(stats["income"]) == 1
raw, _ = req("GET", "/api/stats/trend?months=6")
trend = json.loads(raw.decode("utf-8"))["data"]
assert len(trend["labels"]) == 6

print("== 多格式导出 ==")
raw, headers = req("POST", "/api/export", {"format": "csv"})
assert raw.decode("utf-8-sig").startswith("金额,"), "CSV 内容异常"
cd = headers.get("Content-Disposition", "")
assert "attachment" in cd and "UTF-8''" in cd, cd
raw, _ = req("POST", "/api/export", {"format": "json"})
payload = json.loads(raw.decode("utf-8"))
assert payload["meta"]["count"] == 2
raw, _ = req("POST", "/api/export", {"format": "excel"})
assert b"<Workbook" in raw and b'ss:Type="Number"' in raw
raw, _ = req("POST", "/api/export", {"format": "html"})
assert b"<table>" in raw and "账目导出".encode("utf-8") in raw
raw, _ = req("POST", "/api/records", {"amount": 1, "category_id": food, "txn_time": "2026-08-16T18:00", "note": "=1+1"})
inj_id = json.loads(raw.decode("utf-8"))["data"]["id"]
raw, _ = req("POST", "/api/export", {"format": "csv"})
assert b"'=1+1" in raw, "CSV 公式注入防护失效"
req("DELETE", "/api/records/%d" % inj_id)

raw, _ = req("POST", "/api/export", {"format": "csv", "start": "2026-08-01", "end": "2026-08-10"})
assert raw.decode("utf-8-sig").count("\r\n") == 2, "按日期范围应只导出 1 笔"
raw, _ = req("POST", "/api/export", {"format": "json", "start": "2026-08-16", "end": "2026-08-16"})
assert json.loads(raw.decode("utf-8"))["meta"]["count"] == 1, "结束日期当天账目应包含在导出内"
raw, _ = req("GET", "/api/records?start=2026-08-16&end=2026-08-16&size=20")
assert json.loads(raw.decode("utf-8"))["data"]["total"] == 1, "结束日期当天账目应包含在查询内"
req("POST", "/api/export", {"format": "docx"}, expect=400)

print("== 操作日志 ==")
raw, _ = req("GET", "/api/logs?page=1&size=50")
logs = json.loads(raw.decode("utf-8"))["data"]
assert any(l["action"] == "登录成功" for l in logs["items"])
assert any(l["action"] == "新增账目" for l in logs["items"])
assert any(l["action"] == "导出账目" for l in logs["items"])

print("== 删除与保护 ==")
req("DELETE", "/api/categories/%d" % cat_id)               # 无账目，可删除
used = next(c["id"] for c in cats if c["name"] == "餐饮")
req("DELETE", "/api/categories/%d" % used, expect=409)     # 有账目，禁止删除
req("DELETE", "/api/records/%d" % rec_id)
req("DELETE", "/api/categories/%d" % used)                 # 删除账目后可删除分类

print("== 退出登录 ==")
req("POST", "/api/logout")
req("GET", "/api/me", expect=401)

server.shutdown()
appmod.db.close()
print("\n全部 %d 项断言通过 ✓" % passed)
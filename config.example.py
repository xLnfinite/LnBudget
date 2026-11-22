# -*- coding: utf-8 -*-
"""LnBudget 全局配置模板（config.example.py）。

使用方法：复制本文件为 config.py，填入自己的密码哈希后启动服务。
说明：config.py 含登录凭据哈希，已被 .gitignore 排除，不会随仓库上传。
"""
import os

# ---------- 登录账号（整个系统仅此一个用户，防止无关人员进入） ----------
USERNAME = "admin"

# 登录密码：默认留空（空字符串）。首次启动时自动按以下顺序初始化：
#   1. 数据库里已保存的密码（运行期通过页面「修改密码」设置过，优先级最高）；
#   2. 若在此填写了哈希（格式 pbkdf2_sha256$迭代次数$盐hex$哈希hex），则作为初始密码写入数据库一次；
#   3. 都为空时，使用出厂初始密码 admin（首次登录后请立即在页面中修改）。
# 修改密码：登录后在页面中操作即可（自动持久化到 data/ledger.db 的 settings 表），无需再改本文件。
# 忘记密码：删除 data/ledger.db 中 settings 表的 password_hash 行后重启，即恢复初始密码 admin。
PASSWORD_HASH = ""

# ---------- 服务监听 ----------
HOST = "0.0.0.0"            # 0.0.0.0 表示局域网内任何设备均可通过浏览器访问
PORT = 8000

# ---------- 会话与登录安全 ----------
SESSION_HOURS = 12          # 登录有效期（小时）
MAX_LOGIN_FAILS = 5         # 连续登录失败次数上限
LOGIN_LOCK_MINUTES = 10     # 触发锁定后的封禁时长（分钟）
TRUST_XFF = False           # 仅在经过可信反向代理时改为 True，否则登录锁定可被伪造 X-Forwarded-For 绕过
LOG_MAX_ROWS = 5000         # 操作日志表最多保留条数（超出自动清理最旧记录）

# ---------- 并发与超时（抵御扫描/慢速连接，防止线程耗尽导致进程崩溃） ----------
MAX_CONCURRENT_REQUESTS = 64  # 同时处理的最大连接数，超出直接拒绝；单连接读写超时 30 秒（app.py 常量）

# ---------- HTTPS / SSL（可选，默认关闭 = 明文 HTTP） ----------
# 填写 PEM 格式证书路径即启用 HTTPS（单端口只提供 HTTPS）；两项都留空则保持 HTTP。
# 生成自签名证书（测试用）：
#   mkdir -p certs && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
#     -keyout certs/key.pem -out certs/cert.pem -subj "/CN=lnbudget.local"
# 启用后：最低 TLS 1.2；会话 Cookie 自动带 Secure；响应自动加 HSTS。
SSL_CERT = ""               # 例："/opt/LnBudget/certs/cert.pem"
SSL_KEY = ""                # 例："/opt/LnBudget/certs/key.pem"；私钥与证书同文件时可留空

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "ledger.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")

APP_NAME = "LnBudget 在线记账"
VERSION = "1.0.0"

# -*- coding: utf-8 -*-
"""LnBudget 全局配置模板（config.example.py）。

使用方法：复制本文件为 config.py，填入自己的密码哈希后启动服务。
说明：config.py 含登录凭据哈希，已被 .gitignore 排除，不会随仓库上传。
"""
import os

# ---------- 登录账号（整个系统仅此一个用户，防止无关人员进入） ----------
USERNAME = "admin"

# 登录密码：仅存 PBKDF2-SHA256 加盐哈希（格式 pbkdf2_sha256$迭代次数$盐hex$哈希hex），文件内无明文。
# 修改密码：执行下面的命令生成新哈希并替换本值——
#   python3 -c "import hashlib,os; s=os.urandom(16); d=hashlib.pbkdf2_hmac('sha256', input('新密码: ').encode(), s, 600000); print('pbkdf2_sha256$600000$%s$%s' % (s.hex(), d.hex()))"
# 说明：600000 为 OWASP（2023）对 PBKDF2-HMAC-SHA256 的推荐迭代次数。
# 旧格式（如 200000 迭代）仍然兼容可用；建议更换密码时一并升级到 600000。
# ↑ 运行上方命令后，把输出的整串 pbkdf2_sha256$... 粘贴替换下面一行即可。
PASSWORD_HASH = "在此粘贴生成的新密码哈希（格式：pbkdf2_sha256$600000$盐hex$哈希hex）"

# 可选：如需"忘记修改密码"的启动检测，可自行添加一行（填入你关心的旧哈希，不声明则跳过检测）：
# DEFAULT_PASSWORD_HASH = "pbkdf2_sha256$...$...$..."

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

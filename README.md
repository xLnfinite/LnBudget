# LnBudget 在线记账

一个零第三方依赖的个人在线记账工具：Python 标准库实现 Web 服务 + 原生 JavaScript 前端。
适配手机 / 平板 / 电脑浏览器，Linux 上开箱即用。

## 功能

- **单用户登录保护**：固定账号密码，防止无关人员进入；连续失败 5 次自动锁定 10 分钟
- **在线记账**：每笔账目包含金额、分类、交易时间（另有可选备注），支持按月 / 类型 / 分类 / 关键字筛选与分页
- **自定义分类**：名称、emoji 图标、颜色均可自定义，收入 / 支出分组管理（面向对象实现，见 `models.py`）
- **操作日志**：登录、退出、新增 / 修改 / 删除账目与分类、导出等全部留痕，记录用户、IP、时间、详情
- **账目分析图**：支出构成环形图、近 6 个月收支柱状图、结余折线图（带动画与悬浮提示），可一键下载 PNG
- **多格式导出**：CSV（带 BOM，Excel 不乱码）、Excel(.xls)、JSON、HTML 网页报表，支持自定义时间范围
- **可选 HTTPS**：在 `config.py` 填入 PEM 证书即启用（单端口仅 HTTPS，最低 TLS 1.2，自动 Secure Cookie + HSTS）
- **响应式界面**：桌面端侧边栏布局，移动端底部导航，任何浏览器均可正常使用

## 运行（Linux）

环境要求：Python 3.8+（**无需安装任何第三方库**）

```bash
cd LnBudget
python3 app.py
```

浏览器访问 `http://服务器IP:8000`，本机访问 `http://127.0.0.1:8000`。

- 默认账号：`admin`
- **⚠ 仓库不携带可用密码**：克隆后请按「首次克隆后的配置」一节生成自己的密码哈希。旧版本部署若一直沿用出厂默认密码，服务启动时会打印严重警告提醒更换。

## 首次克隆后的配置（重要）

仓库不含 `config.py`（其中存有登录凭据哈希，避免泄露），取而代之的是模板 `config.example.py`：

```bash
cp config.example.py config.py      # Windows 下改为 copy config.example.py config.py
```

然后用下方「修改端口 / 账号密码」一节的方法生成并填入自己的 `PASSWORD_HASH` 后，即可正常启动。

## 启用 HTTPS（可选）

服务内置 TLS 支持：只要在 `config.py` 中填好证书路径，服务就直接以 HTTPS 启动（单端口，只监听 HTTPS），无需反向代理、无需安装任何库。

1. 准备 PEM 格式证书。测试可先自签名：

```bash
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout certs/key.pem -out certs/cert.pem -subj "/CN=lnbudget.local"
```

2. 在 `config.py` 中填写：

```python
SSL_CERT = "certs/cert.pem"   # 证书链（PEM）
SSL_KEY  = "certs/key.pem"    # 私钥（PEM）；私钥与证书在同一文件时可留空
```

3. 正常启动（`python3 app.py`），浏览器访问 `https://服务器IP:8000`。启动横幅会显示 `https://` 与证书路径。

说明：

- 两项留空 = 明文 HTTP，与之前完全一致（默认行为）
- 启用后最低 TLS 1.2；会话 Cookie 自动加 `Secure`；所有响应自动加 `HSTS`
- 路径写错或证书无效时，启动会直接失败并打印明确错误（不会悄悄退回 HTTP）
- 自签名证书浏览器会提示"不安全"，选择继续访问即可；正式使用建议用受信任证书（如 Let's Encrypt，如 90 天到期需定期续签）

## 修改端口 / 账号密码

编辑 `config.py`：

- `PORT` / `HOST`：监听端口与地址（`0.0.0.0` 表示局域网内其他设备也可访问）
- `USERNAME`：登录账号
- `PASSWORD_HASH`：密码的 PBKDF2-SHA256 加盐哈希（推荐 600000 次迭代，符合 OWASP 2023 建议；旧哈希如 200000 次迭代仍兼容可用），生成方式：

```bash
python3 -c "import hashlib,os; s=os.urandom(16); d=hashlib.pbkdf2_hmac('sha256', input('新密码: ').encode(), s, 600000); print('pbkdf2_sha256$600000$%s$%s' % (s.hex(), d.hex()))"
```

## 后台运行与开机自启

```bash
nohup python3 app.py >> data/server.log 2>&1 &
```

systemd 单元示例（`/etc/systemd/system/lnbudget.service`）：

```ini
[Unit]
Description=LnBudget online bookkeeping
After=network.target

[Service]
WorkingDirectory=/opt/LnBudget
ExecStart=/usr/bin/python3 app.py
Restart=always
User=yourname

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lnbudget
```

## 局域网 / 外网访问

- 手机、平板与服务器连同一局域网时，直接访问 `http://服务器IP:8000` 即可
- 如无法访问，检查防火墙：`sudo ufw allow 8000`（或 `sudo firewall-cmd --add-port=8000/tcp --permanent && sudo firewall-cmd --reload`）
- 不建议直接暴露公网；如需外网访问请配置反向代理（Nginx/Caddy）并启用 HTTPS

## 数据与备份

所有数据保存在 `data/ledger.db`（SQLite，WAL 模式）。备份时建议先停止服务，再复制该文件：

```bash
python3 test_api.py     # 运行接口自检（可选，使用临时数据库，不影响正式数据）；可用环境变量 LNBUDGET_PASSWORD 指定测试密码
cp data/ledger.db data/ledger.db.bak
```

## 目录结构

```
LnBudget/
├── app.py            # 服务入口：HTTP 路由、会话、登录保护、API
├── config.py         # 账号密码、端口、锁定策略等配置
├── db.py             # SQLite 数据访问层（线程安全）
├── models.py         # 面向对象核心模型：Category / Record / Ledger
├── exporter.py       # CSV / Excel / JSON / HTML 多格式导出
├── test_api.py       # 端到端接口自检脚本
├── static/
│   ├── index.html    # 单页应用
│   ├── css/app.css   # 响应式样式与动画
│   └── js/
│       ├── app.js    # 页面逻辑（登录、记账、分类、导出、日志）
│       └── charts.js # 轻量 Canvas 图表库（环形/柱状/折线）
└── data/             # 运行时自动创建，存放 SQLite 数据库
```

## 安全说明

本项目定位个人自用，已做以下轻量加固：

- 密码以 PBKDF2-SHA256 加盐哈希存储，文件内无明文；登录失败 5 次锁定 10 分钟，同一 IP 两次尝试最小间隔 1 秒（防止多 IP 轮换刷哈希计算拖垮 CPU），密码长度上限 256 字符
- 启动时检测是否仍在使用出厂默认密码，若未修改会打印严重警告
- 会话 Cookie 使用 HttpOnly + SameSite=Lax + 256 位随机令牌；写接口校验 CSRF 自定义头；HTTPS 下自动加 `Secure`
- 请求体限制 1MB；单连接读写超时 30 秒、同时处理连接数上限 64（`config.MAX_CONCURRENT_REQUESTS`），抵御慢速连接与连接耗尽型攻击；操作日志最多保留 5000 条
- 数据库文件在 Linux 上自动收紧为 600 权限（`data/` 目录 700），其他本地用户不可读
- CSV 导出已做公式注入防护；响应包含 CSP、X-Frame-Options、Permissions-Policy 等安全头
- 登录锁定默认不信任 `X-Forwarded-For`；若经可信反向代理部署，把 `config.py` 中 `TRUST_XFF` 改为 `True`

其他部署注意事项：

- `config.py` 内含密码哈希，在 Linux 上建议 `chmod 600 config.py`；**切勿**把 `config.py` 提交到公开的 Git 仓库（哈希可被离线爆破，弱密码很快会被破出）
- 密码强度是安全的根基：请使用足够长（建议 14+ 字符）且不常见的密码；只要密码够强，即使哈希泄露也无法在合理时间内爆破

传输加密：默认明文 HTTP，同一局域网可被嗅探。需要加密时，按「启用 HTTPS」一节在 `config.py` 填入证书即可让服务直接以 HTTPS 运行（最低 TLS 1.2，自动附 HSTS），也可继续使用 Nginx/Caddy 反向代理。公网访问建议务必启用其中之一。

## 常见问题

- **端口被占用**：`python3 app.py --port 8080`（浏览器同样改用 8080）
- **忘记密码**：用上面的哈希命令生成新密码哈希，替换 `config.py` 中的 `PASSWORD_HASH` 后重启
- **页面空白 / 接口 401**：会话过期属正常现象，重新登录即可
- **HTTPS 启动失败**：看启动横幅下方的错误——通常是 `SSL_CERT` / `SSL_KEY` 路径写错，或证书与私钥不匹配；两项留空即回到 HTTP
- **浏览器提示证书不受信任**：自签名证书的正常现象，确认后继续访问；正式使用请换受信任证书
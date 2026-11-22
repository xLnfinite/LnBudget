# LnBudget 项目文档（内部知识库）

> 这份文档写给**以后的自己**：只读它就能快速回忆起系统的全貌、细节和坑。
> 三份文档分工：`README.md` = 给使用者看（怎么跑、怎么部署）；`DEVELOPMENT.md` = 给贡献者看（必须遵守什么规范）；**本文档 = 给维护者看（系统现在是什么样、为什么这样）**。
>
> 最后核对：2026-10-27。代码基线：`VERSION = 1.0.0`，后端 6 个 Python 文件 + 前端 4 个静态文件，零第三方依赖。

---

## 1. 速查卡

| 项 | 值 |
| --- | --- |
| 定位 | 单用户个人在线记账（记账 / 分类 / 统计图表 / 多格式导出 / 操作日志） |
| 运行时 | Python **3.8+**，仅标准库；前端原生 JS，无构建步骤 |
| 启动 | `python3 app.py [--host 0.0.0.0] [--port 8000]` |
| 默认地址 / 账号 | `http://<ip>:8000` · 账号 `admin` / 初始密码 `admin`（首次启动自动初始化并持久化到数据库，登录后请在页面内修改；无需手动生成哈希） |
| 数据 | `data/ledger.db`（SQLite，WAL），首次启动自动建库并写入 9 个默认分类；密码哈希存于 `settings` 表 |
| 传输加密 | 可选 HTTPS：`config.SSL_CERT` / `SSL_KEY` 填 PEM 路径即启用（单端口仅 HTTPS，TLS ≥ 1.2，自动 Secure Cookie + HSTS） |
| 自检 | `python test_api.py`（临时库 + 随机端口，55 项断言） |
| 版本来源 | `config.VERSION`（唯一） |
| 行数量级 | app.py 576 · models.py 382 · db.py 124 · exporter.py 122 · test_api.py 224<br>app.js 708 · charts.js 287 · app.css 277 · index.html 221 |

---

## 2. 需求由来（决定了很多取舍）

原始需求在 `info.txt`，只有 4 条，但决定了整个架构：

1. 首页是登录界面，但**整个系统只有一个用户**，登录只为挡住无关人员 → 单账号、固定账号密码、PBKDF2 哈希。
2. **任何设备浏览器都能正常使用** → 响应式（桌面侧边栏 / 移动底部导航）、无框架依赖、无 ES 模块（老浏览器也能跑）。
3. 记账分类**用户可自行创建，用面向对象实现** → `models.py` 的 `Category` / `Record` / `Ledger` 三个类，且这是"面向对象办法"的直接交付物，别重构掉。
4. 账目记录必须包含**金额、分类、交易时间** → 备注是可选附加项；金额用"分"存整数。

---

## 3. 目录与文件职责

```
LnBudget/
├── app.py          HTTP 层：路由分发、会话、CSRF、安全头、参数钳制、错误映射、可选 TLS 包装（不含业务规则）
├── config.py       唯一配置源：账号/哈希/端口/会话/锁定/日志上限/路径/版本
├── db.py           数据层：SCHEMA、线程安全 SQL 执行、种子数据、文件权限加固
├── models.py       业务层：Category/Record/Ledger —— 校验、金额换算、统计、操作日志
├── exporter.py     导出：CSV / JSON / SpreadsheetML(.xls) / HTML 四种编码器
├── test_api.py     端到端自检（进程内起服务，临时库，不碰正式数据）
├── README.md       使用手册
├── DEVELOPMENT.md  开发规范（红线条目：零依赖、安全项、风格）
├── PROJECT.md      本文档
├── static/
│   ├── index.html  单页应用骨架：登录视图 + 应用视图 + SVG 图标 symbol 库 + 弹窗/提示挂载点
│   ├── css/app.css 全部样式：CSS 变量、布局、动画、响应式断点 980px / 720px
│   └── js/
│       ├── app.js  全部交互：api() 封装、state、渲染器、弹窗、事件委托、启动流程
│       └── charts.js 自研 Canvas 图表库：donut / bar / line（动画 + 悬浮提示 + DPR 适配）
└── data/           运行时生成（.gitignore 已忽略）：ledger.db、-wal、-shm、server.log
```

**归属红线**：SQL 只写在 `db.py` + `models.py` 的查询字符串里；业务校验只在 `models.py`；HTTP 细节只在 `app.py`；样式只在 `app.css`；图表绘制只在 `charts.js`。

---

## 4. 请求生命周期

```
浏览器 fetch（带 Cookie: session=… + X-Requested-With: XMLHttpRequest）
  → ThreadingHTTPServer（每连接一线程，daemon，超时 30s）
  → LnBudgetHandler._dispatch()
      ├─ _csrf_check(path)        写方法且非 /api/login → 必须带 X-Requested-With
      ├─ /api/*      → _route_api（各路由内部 _auth() 校验并滑动续期会话）
      ├─ "/"         → _static("index.html")
      ├─ /static/*   → _static(rel)（realpath 前缀校验防穿越）
      └─ 其他        → 404 JSON
  → 业务层 Ledger → Database（单连接 + 锁）→ SQLite
  ← _send()：统一安全头 + 统一 JSON 外壳
```

**错误映射**（`_dispatch` 里统一收敛）：

| 异常 | 结果 |
| --- | --- |
| `ApiError(status, msg)` | 原样 `{ok:false,error:msg}` |
| `ValueError`（业务校验） | 400 |
| `CategoryInUse`（分类被占用） | 409（路由层捕获转换） |
| `BrokenPipeError` / `ConnectionResetError` | 静默忽略（客户端断开） |
| 其他 `Exception` | `traceback.print_exc()` + 500「服务器内部错误」 |

**响应外壳**：成功 `{"ok":true,"data":…}`；失败 `{"ok":false,"error":"中文提示"}`。导出接口是唯一例外（返回文件字节 + `Content-Disposition`）。

**统一安全头**（在 `_send` 中，所有响应都带）：`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: same-origin`、CSP（`default-src 'self'`；脚本仅同源；样式允许内联；`img-src 'self' data:`；`frame-ancestors 'none'`）。启用 HTTPS 时额外加 `Strict-Transport-Security: max-age=31536000`。

**TLS 层**：`config.SSL_CERT` 非空时，`main()` 在 `serve_forever()` 之前用 `build_ssl_context()`（最低 TLS 1.2）包装监听 socket，因此每个连接都是 `ssl.SSLSocket`；处理层通过 `_tls()` 判断是否为加密连接，据此决定 Cookie 是否加 `Secure`。

---

## 5. 数据模型

### 5.1 表结构（`db.py::SCHEMA`，全部 `IF NOT EXISTS`）

```
categories: id PK · name TEXT · icon TEXT(默认📦) · color TEXT(#4f7cff)
            ctype TEXT CHECK IN('income','expense') · created_at · updated_at
records:    id PK · amount_cents INTEGER · category_id →categories(id) · note TEXT ''
            txn_time TEXT · created_at · updated_at
logs:       id PK · ts TEXT · user TEXT · ip TEXT · action TEXT · detail TEXT
索引: idx_records_time(txn_time) · idx_records_cat(category_id) · idx_logs_ts(ts)
```

关系：`categories 1 ── N records`（外键，删除分类前必须先清空其账目）。

### 5.2 存储约定（最容易踩的坑）

- **金额**：数据库只存 `amount_cents`（整数分）。入：`Decimal(str(x)).quantize(0.01)` → `int(v*100)`；出：`round(Decimal(cents)/100, 2)`。API 同时返回 `amount`（float，仅展示用）与 `amount_cents`。**任何金额运算不得用 float 累加**。
- **时间**：全部 `'YYYY-MM-DD HH:MM:SS'` 字符串。前端 `datetime-local` 给的是 `YYYY-MM-DDTHH:MM`，由 `parse_txn_time` 把 `T`/`/` 归一化并按长度补 `:00`/` 00:00:00`，最终必须是 19 字符且 `strptime` 可解析。
- **按月统计**：一律 `substr(txn_time, 1, 7) = 'YYYY-MM'`——**依赖时间字符串前 7 位恰好是年月**，改格式会静默破坏所有统计。
- **日期范围**：入参若是 10 位日期，查询端补 ` 00:00:00` / ` 23:59:59`，保证"结束日当天"包含在内（`records()` 与 `export_records()` 各有一处，改一处务必同步）。
- 连接：单连接 `check_same_thread=False` + `threading.Lock`；`PRAGMA journal_mode=WAL`；`PRAGMA foreign_keys=ON`；`os.umask(0o077)`；POSIX 下 chmod 库文件 600 / 目录 700。

### 5.3 种子数据

`categories` 表为空时插入 9 个默认分类：支出（餐饮🍜 交通🚌 购物🛍️ 居住🏠 娱乐🎮 医疗💊）、收入（工资💼 理财📈 其他🎁）。只在空表时执行，不会覆盖用户数据。

---

## 6. 业务规则清单（`models.py`）

| 对象 | 规则 | 失败提示 |
| --- | --- | --- |
| 分类名 | 非空、≤ 20 字符 | 「分类名称不能为空 / 不能超过 20 个字符」 |
| 分类类型 | 必须 `income` / `expense` | 「分类类型不正确」 |
| 图标 | 非空、≤ 8 字符（约 1~2 个 emoji） | 「分类图标不能为空 / 图标过长」 |
| 颜色 | 必须匹配 `^#[0-9a-fA-F]{6}$` | 「分类颜色格式不正确」 |
| 金额 | 非空、`Decimal` 可解析、`> 0`、`≤ 9999999999.99`（约 100 亿） | 「金额必须大于 0 / 不能超过 100 亿元 / 格式不正确」 |
| 备注 | ≤ 200 字符（超长 400） | 「备注不能超过 200 个字符」 |
| 交易时间 | 见 §5.2 归一化 | 「交易时间格式不正确…」 |
| 新增/修改账目 | 分类必须存在 | 「所选分类不存在」 |
| 删除分类 | 名下账目数为 0，否则 `CategoryInUse` → 409 | 「分类「X」下还有 N 笔账目…」 |
| 删除分类/账目 | 目标不存在 → 400 | 「分类不存在 / 账目不存在」 |
| 操作日志 | 每次写操作自动落库；只保留最近 `LOG_MAX_ROWS=5000` 条（`DELETE … id <= (MAX(id)-5000)`） | — |
| 分页 | `page ≥ 1`（默认 1），`size` 钳制在 1~100（默认 20）；`pages = max(1, ceil(total/size))` | — |
| 趋势 | `months` 钳制 2~24，默认 6；从"当前月"往前推，`shift()` 处理跨年 | — |

**日志动作名**（`logs.action` 的取值，前端"操作日志"页直接展示）：登录成功 / 登录失败 / 登录锁定 / 退出登录 / 新增分类 / 修改分类 / 删除分类 / 新增账目 / 修改账目 / 删除账目 / 导出账目。`detail` 是给人看的中文串（含用户名、IP、金额、时间）。

---

## 7. API 参考

**通用**：除 `POST /api/login` 外均需登录（Cookie `session`）。写方法必须带 `X-Requested-With: XMLHttpRequest`（否则 403）。所有返回包在 `{ok,…}` 外壳里。

| 方法 | 路径 | 参数 | 返回 data | 备注 |
| --- | --- | --- | --- | --- |
| GET | `/api/me` | — | `{username, server_time, app, version}` | 未登录 401；启动时用它判断是否已登录 |
| POST | `/api/login` | body `{username, password}` | `{username}` + Set-Cookie | 失败 401（附剩余次数）；锁定 429；方法错误 405 |
| POST | `/api/logout` | — | 无 | 清会话 + 清 Cookie（Max-Age=0），写日志 |
| GET | `/api/categories` | `?month=YYYY-MM`（默认当月） | `{items:[…], month}` | 每项含 `record_count`、`month_amount`（该月合计） |
| POST | `/api/categories` | body `{name,type,icon,color}` | 分类对象 | 校验失败 400 |
| PUT | `/api/categories/{id}` | body 同上 | 更新后分类对象 | 不存在 400 |
| DELETE | `/api/categories/{id}` | — | 无 | 有账目 409 |
| GET | `/api/records` | `?month&type&category&q&start&end&page&size` | `{items,total,page,size,pages}` | 每项含分类名/图标/颜色/类型；按 `txn_time DESC, id DESC` |
| POST | `/api/records` | body `{amount, category_id, txn_time, note?}` | 记录对象（含分类信息） | 金额≤0 / 分类不存在 / 时间非法 → 400 |
| PUT | `/api/records/{id}` | body 同上 | 更新后记录对象 | 记录不存在 400 |
| DELETE | `/api/records/{id}` | — | 无 | 记录不存在 400 |
| GET | `/api/summary` | `?month` | `{month,income,expense,balance,count,recent[6]}` | 首页统计卡 + 最近 6 笔 |
| GET | `/api/stats/categories` | `?month` | `{income:[…], expense:[…], month}` | 仅含该月有账目的分类（`HAVING n>0`），按金额降序；环形图数据源 |
| GET | `/api/stats/trend` | `?months`（2~24，默认 6） | `{labels,income,expense}` | 柱状图/折线图数据源 |
| GET | `/api/logs` | `?page&size` | `{items,total,page,pages}` | 按 id 倒序 |
| POST | `/api/export` | body `{format: csv\|excel\|json\|html, start?, end?, category_id?, type?}` | 文件字节流 | 响应头 `Content-Disposition: attachment; filename="LnBudget-export.<ext>"; filename*=UTF-8''<中文名>`；格式非法 400 |

**状态码语义**：200 成功｜400 参数/校验｜401 未登录或过期｜403 CSRF｜404 路径不存在｜405 方法不允许｜409 分类被占用｜413 请求体 >1MB｜429 登录锁定｜500 内部错误。

---

## 8. 前端结构

### 8.1 页面与导航

`index.html` 一个文件两个视图：`#loginView`（未登录）/ `#appView`（已登录）。侧边栏与底部导航共 6 个页面，靠 `data-page` 属性 + `setPage()` 切换（`<section class="page" id="page-<name>">`，标题/副标题用 `data-title`/`data-sub`）：

`dashboard` 首页 · `records` 流水账目 · `categories` 账目分类 · `analysis` 账目分析 · `export` 导出账目 · `logs` 操作日志。

### 8.2 app.js 关键约定

- `api(method, path, body)`：统一加 `X-Requested-With`，401 时自动 `showLogin()`；解析 `{ok,data,error}`，失败抛 `Error(error)`。
- `state` 单例：`inApp / user / page / categories / recMap(id→记录缓存，供编辑删除) / rec(筛选与分页) / logs / dashMonth / anMonth / charts(销毁函数数组)`。
- `setPage(page)`：切激活态 → 设标题 → `destroyCharts()` → 调对应 `renderXxx()`。
- 渲染函数：`renderDashboard / renderRecords / renderCategories / renderAnalysis / renderExport / renderLogs`。
- 交互细节：列表操作用事件委托（`data-edit` / `data-del` / `data-cedit` / `data-cdel`）；删除走 `confirmDialog` 二次确认；搜索 `debounce(…,350)`；窗口 resize 时 `debounce(refreshCurrent, 300)` 重新渲染（会重新拉数据，属已知低效点）。
- **XSS 红线**：所有拼进 `innerHTML` 的动态数据必须过 `esc()`（转义 `& < > " '`）。
- 金额展示：`money()` 用 `Intl.NumberFormat("zh-CN")` 保留 2 位；统计卡有 `animateNumber()` 数字滚动动画。

### 8.3 charts.js 图表库

三个工厂函数都返回 `destroy` 清理函数（必须 push 进 `state.charts`，切页时统一销毁，否则事件监听与 rAF 泄漏）：

```js
Charts.donut(canvas, [{label, value, color}], {height, centerText:[标题, 值]})
Charts.bar(canvas, labels, [{name, color, values}], {height})
Charts.line(canvas, labels, [{name, color, values}], {height, fill})
```

内部工具：`setup()`（按父容器宽度与 `devicePixelRatio` 设定画布像素，返回 2D ctx 与逻辑宽高）、`animate()`（ease-out 绘制进度）、`showTip/hideTip`（绝对定位 `.chart-tip`）、`niceMax()`（坐标轴取整）、`moneyShort()`（轴标签万/亿缩写）、`rr()`（圆角矩形）。

**环形图几何（2026-08 修过一次 bug，勿回退）**：

```js
const maxR = Math.min(w, h) / 2 - 6;        // 环外沿上限，留 6px 边距（含悬浮外移 5px）
let r = Math.max(maxR / 1.17, 20);          // thick = 0.34r 时 r + thick/2 = 1.17r ≤ maxR
let thick = Math.max(20, r * 0.34);
if (r + thick / 2 > maxR) r = maxR - thick / 2;   // 小画布兜底
```

历史问题：旧实现 `r = min(w,h)/2 - 10` 未计入环厚，外沿超出画布 → 首页(高 230)与分析页(高 290)圆环上下被裁切。修复方式是整体按 1.17 倍约束收缩半径（直径约小 11%）。

### 8.4 样式要点

`app.css` 顶部 `:root` 定义主题变量（`--bg/--card/--line/--text/--muted/--accent/--green/--red/--radius/--shadow/--sidebar-w`）。布局：桌面 `aside.sidebar`（固定 236px）+ `.main`（左外边距）；`@media (max-width:980px)` 隐藏侧边栏、显示 `.bottomnav`；`@media (max-width:720px)` 统计卡两列、流水行改为 flex 换行卡片式。颜色/间距新增请用变量，别硬编码。

---

## 9. 安全机制盘点

| 机制 | 实现位置 | 说明 |
| --- | --- | --- |
| 密码 | `db.settings.password_hash` + `app.verify_password` / `hash_password` | PBKDF2-SHA256、16 字节随机盐（同一密码每次哈希不同属正常）；600000 迭代（OWASP 2023）；`hmac.compare_digest` 定长比较；迭代次数限制 1~1e7 防 DoS；密码长度上限 256（超长跳过哈希计算）；哈希持久化在数据库 `settings` 表，`config.PASSWORD_HASH` 仅作首次初始化种子（留空则用初始密码 `admin`） |
| 登录锁定 | `_api_login` + `login_fails` | 同 IP 10 分钟内失败 5 次 → 429 并倒计时；同一 IP 两次尝试最小间隔 1 秒（`MIN_LOGIN_INTERVAL`，429 且不计失败次数）；内存字典超 1000 项时全局清理；`TRUST_XFF=False` 默认不信任伪造头 |
| 会话 | `sessions` 字典 + Cookie | 令牌 `secrets.token_urlsafe(32)`（256 位）；`HttpOnly; SameSite=Lax; Path=/`；12h 滑动过期（每次请求续期）；登录时清理过期项 |
| CSRF | `_csrf_check` | 写方法必须带 `X-Requested-With: XMLHttpRequest`；登录接口豁免（登录前还没有会话） |
| 请求体 | `_body_json` | >1MB → 413（先排空最多 1MB+64KB 再报错，避免脏连接） |
| 慢连接 | handler `timeout=30` + `GuardedHTTPServer` 并发上限 64 | 单连接读写超时 30 秒；同时处理连接数上限 `MAX_CONCURRENT_REQUESTS=64`，超出直接关闭；连接类异常（RST / 超时 / TLS 错误）静默处理不打印 traceback |
| 路径穿越 | `_static` | `realpath` 后必须以静态根为前缀 |
| 响应头 | `_send` | CSP / X-Frame-Options / nosniff / Referrer-Policy / Permissions-Policy / no-store；TLS 下另加 HSTS |
| TLS | `build_ssl_context()` + `main()` | 配置 `SSL_CERT` 即单端口 HTTPS，最低 TLS 1.2；证书/私钥无效时拒绝启动（非零退出）并打印原因；未配置则保持 HTTP |
| Session Cookie | `_session_cookie()` | 统一构造：`Path=/; HttpOnly; SameSite=Lax`；TLS 连接自动追加 `Secure` |
| CSV 注入 | `exporter._csv_cell` | `= + - @ \t \r` 开头加 `'` 前缀 |
| HTML 注入 | `exporter._esc`（`html.escape`）+ 前端 `esc()` | 导出报表与页面渲染双保险 |
| 文件权限 | `db.Database.__init__` / `_harden_permissions` | `umask 077`；POSIX 下 600/700；Windows 跳过 |
| 修改账户 | `_api_account`（`POST /api/account`）+ 前端钥匙图标弹窗 | 校验当前密码；可同时改用户名（≤32 字符）与密码（8~256 位）；改后写入 `settings.username` / `settings.password_hash` 并清除 `password_is_initial` 标记；所有会话全部失效（含当前），前端自动刷新强制重新登录；记入操作日志 |
| 默认密码检测 | `init_password()` + `settings.password_is_initial` | 首次启动用 `config.PASSWORD_HASH` 或初始密码 `admin` 初始化；`password_is_initial=1` 时启动横幅打印警告，`/api/me` 返回 `initial_password`，前端登录后 toast 提醒立即改密 |

**已知残余风险（个人自用可接受，公网部署前要处理）**：默认明文 HTTP（可通过 `config.SSL_CERT` 内置 HTTPS 消除，见 §10.1）；会话存内存（重启即全员下线、单进程限制）；除登录外的接口无频率限制；无审计日志轮转以外的日志文件。

---

## 10. 开发与验证

### 10.1 启动 / 停止 / 后台

```bash
python3 app.py                       # 前台，Ctrl+C 停止（会优雅关闭 server 与数据库连接）
python3 app.py --port 8080           # 换端口（不改配置）
nohup python3 app.py >> data/server.log 2>&1 &     # 后台
```

**systemd 开机自启**（`/etc/systemd/system/lnbudget.service`）：

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

**局域网访问**：手机 / 平板与服务器在同一局域网时直接访问 `http://服务器IP:8000`；访问不了先检查防火墙：`sudo ufw allow 8000`（或 `sudo firewall-cmd --add-port=8000/tcp --permanent && sudo firewall-cmd --reload`）。不建议直接暴露公网，确需外网请启用 HTTPS 或反向代理。

**启用 HTTPS**：在 `config.py` 填 `SSL_CERT`（证书链 PEM）与 `SSL_KEY`（私钥 PEM，可留空表示同文件），直接 `python3 app.py` 即单端口 HTTPS；启动横幅会打印 `https://…` 与证书路径。证书无效会立即失败（退出码 1 + 中文错误），不会退回 HTTP。自签名证书生成命令见 README。

### 10.2 自检脚本

`test_api.py` 在**进程内**起服务：先把 `config.DB_PATH` 指到 `tempfile.mkdtemp()` 下的临时库、`config.PORT=0`（随机端口），再 `import app`，然后按顺序断言 56 项：静态资源 → 413 → 401 → 登录（含"HTTP 下 Cookie 不带 Secure"）→ HTTPS 配置默认关闭与坏证书报错 → CSRF 403 → 分类 CRUD（含 400 校验）→ 账目 CRUD（负数/不存在分类 400）→ 统计 → 四格式导出（含 BOM、`filename*`、公式注入、日期边界）→ 日志 → 删除保护 409 → 修改账户（新密码太短 400 / 当前密码错 401 / 改用户名+密码 200 / 旧用户名失效 401 / 旧密码失效 401 / 新账号新密码可登录 200）→ 登出。测试密码可用环境变量 `LNBUDGET_PASSWORD` 提供；未设置时自动生成随机密码（对应哈希在导入 app 前动态生成）。

> 注意：脚本依赖"可写的临时目录 + sqlite 能在其中建库"。在某些受限沙箱里（如把临时目录用 `mode=0o700` 创建的 Windows 沙箱）会报 `unable to open database file`——那是环境限制，与代码无关；在真实机器上直接跑即可。

### 10.3 手工回归清单（改前端后至少跑一遍）

登录 → 记一笔 → 编辑 → 删除 → 流水筛选/分页 → 分类增删改 → 图表渲染与悬浮提示 → 下载 PNG → 四格式导出下载 → 日志翻页 → 退出登录。

---

## 11. 扩展指南

| 需求 | 步骤 |
| --- | --- |
| 加一个 API | ① `models.py` 写业务方法（校验抛 `ValueError`，特殊冲突用专用异常）② `app._route_api` 加分支（先 `_auth()`，POST/PUT 用 `_body_json()`）③ `test_api.py` 加断言 |
| 改表结构 | ⚠️ `SCHEMA` 是 `CREATE TABLE IF NOT EXISTS`，**对已存在的库不会生效**。老库需手工 `ALTER TABLE`（或写一次性迁移脚本），并同步更新 `SCHEMA` 让新库一致 |
| 加导出格式 | `exporter.py`：写 `_xxx(records)` → 注册进 `_BUILDERS` / `EXT` / `MIME`；前端导出页加一个 `.fmt-card` 单选；`test_api.py` 加断言 |
| 加页面 | `index.html` 加 `<section class="page" id="page-xxx" data-title data-sub>` + 侧边栏与底部导航各一个 `data-page="xxx"` 按钮 → `app.js` 写 `renderXxx()` 并注册进 `setPage()` 的 `renderers` 映射 |
| 加图表 | `charts.js` 导出新工厂函数（复用 `setup/animate/showTip/niceMax`，返回 destroy）；调用方 push 进 `state.charts` |
| 加配置项 | 只加在 `config.py`（带注释说明用途与默认值），代码里用 `getattr(config, "X", 默认)` 或直接引用 |
| 多用户 / 权限 | 当前架构是单用户：`config.USERNAME` 硬编码、`sessions` 只存用户名。要扩展需重做登录与 `records`/`categories` 的归属字段 |

---

## 12. 变更记录（便于以后对照版本）

| 日期 | 文件 | 内容 |
| --- | --- | --- |
| 2026-08-26 | `DEVELOPMENT.md`（新增） | 编写开发标准文档：编码规范、API 约定、安全红线、测试与变更流程 |
| 2026-08-26 | `static/js/charts.js` | 修复环形图外沿超出画布被裁切（新增 `maxR` 约束，`r` 按 1.17 收缩） |
| 2026-10-27 | `PROJECT.md`（新增） | 本文档：系统现状知识库 |
| 2026-10-27 | `app.py`、`config.py`、`test_api.py`、`README.md`、`PROJECT.md`、`DEVELOPMENT.md` | 支持内置 HTTPS：新增 `build_ssl_context()` / `_tls()` / `_session_cookie()`，`main()` 按 `SSL_CERT` 包装监听 socket；TLS ≥ 1.2、HSTS、Cookie `Secure`；自检增至 46 项（含 HTTPS 断言） |
| 2026-11-22 | 全部文件 | 服务器稳定性加固（handler 超时 30s、并发 64、连接异常静默、HTTPS 握手延迟）；登录限速 / 密码长度上限 / 默认密码启动警告；`config.py` 移出版本控制并提供 `config.example.py`，清除仓库中的密码痕迹；`README.md` 精简为使用者向，技术细节归入本文档 |
| 2026-11-22 | `app.py`、`db.py`、`config*.py`、`static/`、`test_api.py`、文档 | 取消手动生成密码哈希：初始账号 `admin` / 密码 `admin` 首次启动自动初始化；密码哈希改存数据库 `settings` 表；新增 `POST /api/password` 在线修改密码（当前密码校验、新密码 ≥8 位、改后其他会话失效）与前端钥匙弹窗；`/api/me` 暴露 `initial_password` 标记；自检增至 55 项 |
| 2026-11-22 | `app.py`、`static/js/app.js`、`test_api.py`、文档 | 修改账户：钥匙弹窗支持同时修改用户名（存 `settings.username`，`config.USERNAME` 仅首次初始化种子）与密码；确认后所有会话失效、页面自动刷新强制重新登录；接口调整为 `POST /api/account`；自检增至 56 项 |

---

## 13. 已知局限与可选改进

- **无迁移框架**：见 §11 改表结构警告；将来若要长期演进，可引入极简 `user_version`/`PRAGMA user_version` 迁移（仍不破坏零依赖）。
- **会话在内存**：重启掉线；多进程/多实例不共享（当前单进程 `ThreadingHTTPServer` 无此问题）。
- **静态资源无缓存**：所有响应 `Cache-Control: no-store`，刷新即重拉，个人使用无所谓，但可对 `/static/` 加 ETag。
- **resize 全量重渲染**：窗口缩放防抖 300ms 后调 `refreshCurrent()`，会重新发 API 请求；小屏横竖屏切换时会闪一下。
- **日志无按操作类型索引**：目前只按时间建索引；日志量上限 5000 行，影响可忽略。
- **写入串行**：单连接 + 全局锁，高并发写入会排队；个人记账场景足够。
- **无前端自动化测试**：只有手工回归清单（§10.3）。
- **默认明文 HTTP**：需要加密时在 `config.py` 开启内置 HTTPS（§10.1）；继续用 Nginx/Caddy 反向代理也可，`TRUST_XFF` 按需打开。

---

## 14. 排障速查

| 现象 | 先查什么 |
| --- | --- |
| 页面空白 / 接口 401 | 会话过期（正常），重新登录；看 `sessions` 是否因重启清空 |
| 登录一直 429 | `login_fails` 里该 IP 未过期；等锁定窗口结束，或重启进程清空（内存态） |
| 写接口 403 | 前端 `fetch` 漏了 `X-Requested-With: XMLHttpRequest` 头 |
| 导出中文文件名乱码 | 响应头 `filename*=UTF-8''` 是否被代理改写；CSV 必须 `utf-8-sig` 带 BOM |
| 统计数字为 0 | 时间格式是否仍为 19 字符 `YYYY-MM-DD HH:MM:SS`（`substr(…,1,7)` 依赖它） |
| 金额差 1 分 | 某处用了 float 累加 / 未走 `parse_amount` |
| 环形图上下被切 | 是否有人回退了 §8.3 的 `maxR` 约束 |
| 启动报「启用 HTTPS 失败」 | `SSL_CERT` / `SSL_KEY` 路径与 PEM 格式、二者是否匹配；`SSL_CERT` 留空即回 HTTP |
| 浏览器提示证书不受信任 | 自签名证书的正常告警；生产换成受信任证书（Let's Encrypt 等） |
| 备份后数据不一致 | 备份前是否停了服务（WAL 模式热拷不安全，可先 `PRAGMA wal_checkpoint(FULL)` 再拷，或直接停服拷贝） |
| `unable to open database file` | 运行用户对 `data/` 无写权限（Linux 上 700/600 由代码设置）；或临时目录不可写（测试脚本） |

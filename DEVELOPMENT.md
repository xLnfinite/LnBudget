# LnBudget 开发标准文档

> 版本：1.0.0　·　适用于 LnBudget 在线记账系统
> 本文档为项目**开发与协作规范**，所有贡献者（含未来维护者）应遵守。与 `README.md`（使用手册）互补：README 面向使用者，本文档面向开发者。

---

## 1. 项目概述

### 1.1 定位

个人自用的在线记账工具：单用户登录保护 + 记账/分类/统计/分析图表/多格式导出/操作日志。**零第三方依赖**是最高约束之一，新增任何依赖都必须经过充分论证（见 §6.7）。

### 1.2 核心设计决策（不得随意推翻）

| 决策 | 原因 |
| --- | --- |
| 后端仅用 Python 标准库（`http.server`） | 零依赖、Linux 开箱即用、单文件部署 |
| 前端零框架（原生 JS + 手写 Canvas 图表） | 与后端零依赖理念一致，无构建步骤 |
| 金额以整数"分"（`amount_cents`）存储 | 避免二进制浮点误差，所有金额计算基于 `Decimal` |
| SQLite 单连接 + 全局锁 | 线程安全且实现简单，个人应用写入量极低 |
| 单用户固定账号 | 需求明确"只有一个用户"，登录仅防无关人员 |
| 数据全部存于 `data/ledger.db` | 备份 = 复制单文件 |

---

## 2. 技术栈与架构

### 2.1 技术栈

- **运行时**：Python 3.8+（不依赖任何第三方库）
- **后端**：`http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler`，多线程（`daemon_threads = True`）
- **前端**：原生 HTML5 + CSS3 + JavaScript（ES2017+，`"use strict"`）
- **图表**：自研 `static/js/charts.js` Canvas 图表库
- **数据库**：SQLite3，WAL 模式，外键开启

### 2.2 分层架构

```
HTTP 请求
   │
   ▼
app.py  LnBudgetHandler（路由 / 会话 / CSRF / 安全头 / 参数解析）
   │
   ▼
models.py  Ledger（业务层：增删改查 / 统计 / 日志 / 校验）
   │
   ▼
db.py  Database（数据访问层：SQL 执行，线程安全）
   │
   ▼
data/ledger.db（SQLite）
```

前端 `static/` 通过 `fetch` 调用 `/api/*` 接口，仅此一条通路。

---

## 3. 目录结构

```
LnBudget/
├── app.py            # 服务入口：HTTP 路由、会话、登录保护、API（禁止在别处重复实现路由）
├── config.py         # 全局配置（唯一配置来源，禁止硬编码可配置项）
├── db.py             # SQLite 数据访问层（线程安全；所有 SQL 表结构定义集中于此）
├── models.py         # 核心业务模型：Category / Record / Ledger（业务逻辑唯一归属）
├── exporter.py       # CSV / Excel / JSON / HTML 导出
├── test_api.py       # 端到端接口自检脚本
├── README.md         # 使用手册
├── DEVELOPMENT.md    # 本文档（开发标准）
├── static/
│   ├── index.html    # 单页应用（唯一 HTML 入口）
│   ├── css/app.css   # 全部样式（含响应式）
│   └── js/
│       ├── app.js    # 页面逻辑（仅允许操作 DOM / 调 API / 管状态）
│       └── charts.js # Canvas 图表库（仅允许图表绘制，禁止混入业务逻辑）
└── data/             # 运行时自动创建（已被 .gitignore 忽略，禁止提交）
```

**归属原则**：
- 路由 / HTTP 细节 → `app.py`
- SQL / 建表 → `db.py`
- 业务规则 / 校验 / 统计 → `models.py`
- 导出格式生成 → `exporter.py`
- 配置 → `config.py`

---

## 4. Python 编码规范

### 4.1 通用

- **Python 3.8 兼容**：不得使用 3.9+ 专属语法（如内置泛型 `list[str]`、`dict | None` 联合类型语法）。用 3.8 可用的写法（`from typing import ...`、`Optional`）。
- **编码**：文件头 `# -*- coding: utf-8 -*-`（或项目一致地省略亦可，但含中文注释的文件建议保留）。
- **缩进**：4 空格，禁止 Tab。
- **行宽**：尽量 ≤ 100 字符。
- **引号**：字符串优先单引号；含单引号的字符串用双引号。
- **命名**：
  - 模块 / 函数 / 变量：`snake_case`
  - 类：`PascalCase`（如 `CategoryInUse`、`Ledger`、`Database`）
  - 常量：`UPPER_SNAKE_CASE`（如 `MAX_NOTE_LEN`、`MAX_BODY_SIZE`）
  - 私有成员：前缀单下划线（如 `_trim_logs`、`_send`、`_lock`）
- **导入顺序**：标准库 → 空行 → 本项目模块（`import config`、`from models import ...`），见 `app.py` 顶部。

### 4.2 文档与注释

- 模块级 docstring 说明职责（见 `db.py` / `models.py` / `exporter.py` 开头）。
- 公开函数尽量有 docstring 或行内注释说明**行为与边界**（如 `parse_amount` 的返回单位是"分"）。
- 注释使用中文；注释解释"为什么"，不重复"是什么"。

### 4.3 错误处理

- 业务校验失败抛 `ValueError("中文提示")` → 由 `app.py` 统一转 400。
- 特殊业务冲突用专用异常（如 `CategoryInUse`）→ 在路由层转 409。
- HTTP 层错误统一用 `ApiError(status, message)`，禁止在路由里散落裸 `try/except`。
- 禁止吞异常：`except Exception: pass` 仅限"可忽略的收尾动作"（如权限收紧失败），且必须加注释说明理由。

### 4.4 金额与时间（关键约定）

- **金额**：任何涉及钱的运算一律 `Decimal`；入库必须 `int(amount * 100)`（分）；出库 `round(Decimal(x) / 100, 2)`。禁止使用 `float` 直接累加金额。
- **时间**：统一字符串格式 `YYYY-MM-DD HH:MM:SS`（前端提交的 `T` 分隔由 `parse_txn_time` 归一化）；"年-月"统计用 `substr(txn_time, 1, 7)`。

### 4.5 字符串格式化

保持现状风格：优先 `%` 格式化（`"%s ¥%s" % (x, y)`）。若项目后续统一迁移到 f-string，需全量一致并更新本规范。

---

## 5. SQL 与数据库规范

### 5.1 表结构（定义于 `db.py` 的 `SCHEMA`）

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `categories` | `name` / `icon` / `color` / `ctype('income'\|'expense')` | 分类；`ctype` 有 CHECK 约束 |
| `records` | `amount_cents`(INTEGER) / `category_id`(FK) / `note` / `txn_time` | 账目；外键引用 `categories(id)` |
| `logs` | `ts` / `user` / `ip` / `action` / `detail` | 操作日志 |

- 新表 / 新索引定义**只能加在 `SCHEMA` 中**（`CREATE TABLE IF NOT EXISTS`），保证老库自动升级。
- 索引：`records` 按 `txn_time`、`category_id` 建索引；`logs` 按 `ts` 建索引。新增高频查询字段需同步评估索引。
- 禁止裸 SQL 拼接用户输入；一律参数化占位符 `?` + 参数元组。
- 动态 WHERE 必须走 `where[] / params[]` 双列表拼装模式（见 `models.py` 的 `records()` / `export_records()`）。

### 5.2 连接与并发

- 全进程**单连接 + `threading.Lock`**，禁止新开连接直查。
- 所有写操作经 `Database.execute()`（自动 commit）；查询用 `query()` / `query_one()`。
- 保持 WAL 模式与 `PRAGMA foreign_keys = ON`。
- 新增建表逻辑时必须保证 `IF NOT EXISTS`，且考虑 `_harden_permissions()` 的权限一致性。

### 5.3 数据量治理

- 操作日志最多保留 `config.LOG_MAX_ROWS`（5000）条，由 `Ledger._trim_logs()` 自动裁剪。
- 内存字典（`sessions`、`login_fails`）必须有过期清理逻辑，防止无限增长（见 `app.py` 登录路径）。

---

## 6. API 设计规范

### 6.1 统一约定

- 前缀 `/api/`；除登录外全部接口需登录会话。
- 响应格式统一：
  - 成功：`{"ok": true, "data": <payload>}`
  - 失败：`{"ok": false, "error": "<中文提示>"}`
- 内容类型：`application/json; charset=utf-8`；导出接口除外。
- 状态码语义：
  - `200` 成功　`400` 参数/校验错误　`401` 未登录/过期
  - `403` 非法来源（CSRF）　`404` 接口/资源不存在　`405` 方法不允许
  - `409` 业务冲突（分类被占用）　`413` 请求体过大　`429` 登录锁定
  - `500` 未预期异常（需 `traceback.print_exc()` 留痕）

### 6.2 现有接口清单（新增接口需与之风格一致）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/me` | 当前会话信息 |
| POST | `/api/login` | 登录（含失败锁定） |
| POST | `/api/logout` | 退出 |
| GET/POST | `/api/categories` | 分类列表（带当月用量）/ 新增分类 |
| PUT/DELETE | `/api/categories/{id}` | 修改 / 删除分类（占用时 409） |
| GET/POST | `/api/records` | 账目列表（筛选+分页）/ 新增账目 |
| PUT/DELETE | `/api/records/{id}` | 修改 / 删除账目 |
| GET | `/api/summary?month=` | 月度汇总（收/支/结余/笔数/最近 6 笔） |
| GET | `/api/stats/categories?month=` | 分类统计（收入/支出分组） |
| GET | `/api/stats/trend?months=` | 近 N 月收支趋势（N 限 2~24） |
| GET | `/api/logs?page=&size=` | 操作日志分页 |
| POST | `/api/export` | 导出（`format` ∈ csv/excel/json/html） |

### 6.3 分页约定

- 入参 `page`（≥1，默认 1）、`size`（1~100，默认 20），在路由层做钳制（`max/min`）。
- 出参统一 `{"items": [...], "total": N, "page": p, "pages": M}`（`logs` 亦含 `size`）。

### 6.4 日期范围约定

- `start` / `end` 传 `YYYY-MM-DD` 时，后端自动补齐 `00:00:00` / `23:59:59`（**当天必须包含在区间内**，见 `test_api.py` 断言）。
- 查询与导出两端实现必须保持一致（均落在 `models.py`）。

### 6.5 会话与安全（写接口强制项）

- 写接口（POST/PUT/DELETE）必须校验 `X-Requested-With: XMLHttpRequest`（`_csrf_check`）。
- 登录成功下发 `Set-Cookie: session=...; Path=/; HttpOnly; SameSite=Lax; Max-Age=...`。
- 会话令牌用 `secrets.token_urlsafe(32)`。

### 6.6 导出接口

- 走 `exporter.build()`；`Content-Disposition` 同时带 ASCII 兜底 `filename` 与 UTF-8 `filename*`。
- 新增导出格式：在 `exporter.py` 注册 `_BUILDERS` / `EXT` / `MIME`，并在 `test_api.py` 补充断言。

### 6.7 依赖约束

- **禁止引入第三方 Python 库或前端 CDN/框架**。确有需要时：先在本文档登记理由 → 评估是否可用标准库/手写实现替代 → 明确部署影响（如需要 pip 安装即破坏零依赖承诺）→ 经维护者确认。

---

## 7. 前端开发规范（static/）

### 7.1 通用

- 所有 JS 文件以 `"use strict";` 开头。
- 使用 `const` / 箭头函数 / 模板字符串；禁止 `var`。
- 中文注释、中文界面文案。
- 所有动态插入的用户内容必须过 `esc()` 转义，**禁止直接拼接未转义数据进 `innerHTML`**（XSS 红线）。
- 选择器工具：`$` / `$$`；不引入 jQuery。

### 7.2 文件职责（红线）

- `app.js`：业务交互、状态、DOM 渲染、API 调用。**不得写图表绘制逻辑**。
- `charts.js`：仅图表库（`Charts.donut/bar/line`），保持无业务耦合；对外暴露 `destroy` 清理函数。
- `index.html`：结构 + 内联 SVG 图标符号；新增页面必须同时注册：`<section class="page" id="page-xxx">`、导航 `data-page="xxx"`、`setPage()` 的 renderers 映射。
- `app.css`：全部样式；颜色使用 `:root` CSS 变量；响应式断点 980px / 720px 沿用现有体系。

### 7.3 状态管理

- 全局状态集中在 `app.js` 顶部 `state` 对象，禁止散落全局变量。
- 渲染函数按页面命名 `renderXxx()`；切换页统一走 `setPage()` → `destroyCharts()` 防内存泄漏。

### 7.4 图表

- 新图表类型在 `charts.js` 中实现，复用 `setup / animate / showTip / hideTip / niceMax` 等内部工具。
- 图表实例必须注册进 `state.charts`（供 `destroyCharts()` 统一销毁），返回的 destroy 回调用于解绑事件。

### 7.5 交互细节

- 列表操作使用**事件委托**（如 `#recList` 上的 `data-edit` / `data-del`），禁止逐行绑定。
- 防抖：搜索输入 `debounce(..., 350)`。
- 危险操作（删除）必须 `confirmDialog` 二次确认。
- 异步按钮需禁用 + 文案变化（"保存中…"），`finally` 中恢复。

---

## 8. 安全规范（不可回退项）

| 项 | 要求 |
| --- | --- |
| 密码存储 | 仅存 PBKDF2-SHA256 加盐哈希，禁止明文 / 弱哈希；迭代次数推荐 600000（OWASP 2023），旧格式（如 200000）仍兼容但新生成哈希一律用 600000 |
| 登录加固 | 失败 ≥ `MAX_LOGIN_FAILS` 次锁定 `LOGIN_LOCK_MINUTES` 分钟（429）；同一 IP 两次尝试最小间隔 `MIN_LOGIN_INTERVAL`（1 秒，429，不计入失败次数）；密码长度上限 `MAX_PASSWORD_LEN`（256，超长直接失败且跳过哈希计算）；不信任 `X-Forwarded-For`（`TRUST_XFF=False`） |
| 默认密码检测 | `main()` 启动时若 `config.DEFAULT_PASSWORD_HASH` 已声明且与 `PASSWORD_HASH` 相同，打印严重警告（防忘记改密）；检测机制不得移除，但默认哈希只允许放在本地 `config.py`，**禁止**写入仓库任何文件（含注释 / 文档 / 测试） |
| 会话 | Cookie `HttpOnly + SameSite=Lax`；令牌 ≥ 256 位随机；过期清理；**TLS 连接必须带 `Secure`**（统一走 `_session_cookie()`，禁止手写 Set-Cookie） |
| CSRF | 所有写接口校验自定义头（§6.5） |
| XSS | 前端渲染一律 `esc()`；后端输出 XML/HTML 用 `html.escape` |
| 公式注入 | CSV 单元格以 `= + - @ \t \r` 开头时前置 `'`（`_csv_cell`） |
| 请求体 | 上限 1MB（413）；服务超时 30s 防慢速连接 |
| 响应头 | `_send` 统一附带 CSP / X-Frame-Options / X-Content-Type-Options / Referrer-Policy / Permissions-Policy / Cache-Control，新增端点必须复用 `_send`；TLS 下自动加 HSTS（勿手写） |
| TLS | 仅通过 `build_ssl_context()`（最低 TLS 1.2）启用；证书无效必须启动失败并给出中文提示，**禁止静默回退 HTTP** |
| 路径穿越 | 静态资源 `realpath` 后必须校验前缀（`_static`） |
| 文件权限 | Linux 下 `umask 077` + 库文件 600 / 目录 700 |
| 连接防护 | 并发上限 `MAX_CONCURRENT_REQUESTS`（默认 64，超出直接关闭连接）；单连接读写超时 30s（`LnBudgetHandler.timeout`）；客户端断连（RST）/超时/明文误连 TLS 等连接类异常一律静默丢弃，**禁止打印 traceback 或使进程退出**（由 `GuardedHTTPServer` 统一兜底，不得绕过） |

---

## 9. 测试规范

### 9.1 自检脚本（test_api.py）

- 端到端覆盖：静态资源、鉴权（401/413/锁定前失败）、登录加固（超长密码 401、同 IP 1 秒内重试 429）、CSRF（403）、分类 CRUD（含校验 400）、账目 CRUD（负数/不存在分类 400）、统计、四种导出、日期范围边界、公式注入、日志、删除保护（409）、登出。
- 使用**临时数据库**（`tempfile.mkdtemp`）+ **随机端口**，运行后不影响正式数据。
- 测试密码通过环境变量 `LNBUDGET_PASSWORD` 注入，禁止在代码中硬编码新测试凭据（现有默认值仅为向后兼容）。
- 新增 API / 行为变更时，必须在 `test_api.py` 增加对应断言，并保证 `python test_api.py` 全绿。
- 连接防护回归（前端无感知，但公网必需）：HTTP 模式下模拟"空闲连接超限（> `MAX_CONCURRENT_REQUESTS`）/ RST 断连 / 半截请求"后服务仍正常响应；HTTPS 模式下额外验证"明文请求打到 TLS 端口 / 空闲连接 30s 超时释放"后服务仍正常响应，且日志无 traceback。

### 9.2 回归要求

- 任何改动提交前运行：`python test_api.py`（全绿）。
- 前端改动至少手工回归：登录、记一笔、编辑/删除、筛选分页、图表渲染与下载 PNG、导出下载。

---

## 10. Git 与版本管理

- **提交信息**：中文，`<类型>: <简述>`，如 `feat: 新增月度预算功能`、`fix: 修复导出文件名中文乱码`、`refactor: 拆分统计查询`。
- **禁止提交**：`data/`（含 `.db` / `-wal` / `-shm`）、`__pycache__/`、`*.pyc`（见 `.gitignore`，不得改动此规则）。
- **版本号**：`config.py` 的 `VERSION` 为唯一版本来源，遵循语义化（主.次.修订）；发布时同步更新 `README.md` 与本文档头部版本。
- 每项功能变更建议配套：代码 + 测试断言 + 文档（README 或本文档）。

---

## 11. 部署与运维规范

- 启动：`python app.py [--host H] [--port P]`；命令行参数覆盖 `config.py`。
- 端口冲突：`--port` 指定；配置改动后必须重启服务生效（无热加载）。
- 备份：先停服务，再复制 `data/ledger.db`（WAL 模式下禁止热拷，避免不一致）。
- 日志：访问日志输出到 stdout，可 `nohup ... >> data/server.log 2>&1 &` 落盘。
- 公网部署：启用 HTTPS——在 `config.py` 填 `SSL_CERT` / `SSL_KEY` 走内置 TLS（单端口仅 HTTPS），或继续用反向代理（Nginx/Caddy）+ HTTPS；如代理位于可信环境才可开 `TRUST_XFF`。
- 连接层稳定：TLS 握手推迟到连接线程内完成（`do_handshake_on_connect=False`），慢速/扫描连接不会阻塞 accept；空闲连接 30s 超时自动释放，并发超过 `MAX_CONCURRENT_REQUESTS` 时新连接被直接关闭；客户端异常（断连、耗时探测）不会终止进程或刷屏 traceback。若需调整上限，改 `config.py` 的 `MAX_CONCURRENT_REQUESTS` 即可。
- 更换密码：用 README 中哈希命令生成新哈希（600000 迭代）替换 `config.py` 的 `PASSWORD_HASH`，**禁止明文密码入库**；部署前必须更换出厂默认密码，并建议 `chmod 600 config.py`（哈希可被离线爆破，且**切勿**把 `config.py` 提交到公开 Git 仓库）。

---

## 12. 变更流程（Checklist）

开发一项新功能/修复时按序执行：

1. 确认归属文件（§3 归属原则），不越层实现。
2. 遵守 §4~§8 各项规范；金额、时间、安全红线（§8）优先自查。
3. 写/改 `test_api.py` 断言 → `python test_api.py` 全绿。
4. 手工回归前端交互（§9.2）。
5. 更新 `README.md`（如影响使用者）与本文档（如影响规范本身）。
6. 若涉及新配置项 → 加入 `config.py` 并注释用途。
7. Git 提交，信息符合 §10 格式。

---

*本文档随项目演进持续维护；规范冲突时以"零依赖 + 安全红线 + 一致风格"三条最高原则裁决。*

# LnBudget 在线记账

单用户个人在线记账工具，手机 / 平板 / 电脑浏览器都能用。零第三方依赖，Python 3.8+ 直接运行。

## 快速开始

```bash
cp config.example.py config.py     # 1. 生成配置文件（Windows：copy）
python3 app.py                     # 2. 启动（启动前请先设置密码，见下节）
```

浏览器访问 `http://服务器IP:8000`，本机访问 `http://127.0.0.1:8000`，账号 `admin`。

## 必做：设置密码

仓库不提供密码。用下面的命令生成密码哈希，填到 `config.py` 的 `PASSWORD_HASH`：

```bash
python3 -c "import hashlib,os; s=os.urandom(16); d=hashlib.pbkdf2_hmac('sha256', input('新密码: ').encode(), s, 600000); print('pbkdf2_sha256$600000$%s$%s' % (s.hex(), d.hex()))"
```

- 请使用至少 14 位、不常见的密码
- `config.py` 里存有密码哈希，不要提交到公开仓库（本仓库已默认忽略）
- 端口、账号都在 `config.py` 修改，重启生效

## 常用操作

- 换端口：`python3 app.py --port 8080`
- 后台运行：`nohup python3 app.py >> data/server.log 2>&1 &`
- 备份数据：停止服务后复制 `data/ledger.db`
- 启用 HTTPS：在 `config.py` 填入 `SSL_CERT` / `SSL_KEY` 证书路径后重启即可

## 常见问题

- **忘记密码**：用上面的命令生成新哈希，替换后重启
- **端口被占用**：换一个端口启动
- **页面提示重新登录**：会话过期，正常现象，重新登录即可
- **公网访问**：建议启用 HTTPS；仅家庭局域网使用可以不开

## 更多文档

- 技术细节与维护知识：[PROJECT.md](PROJECT.md)
- 开发规范：[DEVELOPMENT.md](DEVELOPMENT.md)

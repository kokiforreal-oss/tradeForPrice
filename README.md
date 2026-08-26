## 代码结构

```
trade/
  start.sh / deploy.sh / update-remote.sh
  requirements.txt / .env.example
  data/                 # 密钥、上传、备份（勿提交）
  app/
    main.py             # FastAPI 入口：挂路由、静态资源、健康检查
    config.py           # 环境变量与目录
    core/               # 认证、数据权限、字段加密、汇率、工具函数
    db/                 # 引擎与补列、ORM 模型、空库演示数据
    api/                # HTTP 接口（按询价/订单/采购/资金等拆分）
    static/
      index.html
      css/app.css
      js/e2e.js         # 前端加解密
      js/app.js         # 页面与路由
```

接口前缀均为 `/api/...`，页面为单页应用（`#/工作台` 等）。

## 本机运行

先安装并启动 MySQL 8，建库建用户（见下方）。再在项目根目录：

```bash
chmod +x start.sh
./start.sh
```

或手动：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 修改 DATABASE_URL、SECRET_KEY（切勿把真实口令提交到版本库）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器打开：**http://127.0.0.1:8000/**  
不要使用 `/finance` 这类无哈希的路径当首页。

启动时只创建缺失的表、只给旧表补列，**不会清空已有数据**。`users` 表为空时才写入演示账号（角色：管理员、销售、采购、财务）。演示口令仅存在于本机初始化逻辑中，**本文不写明文**；登录后请立即修改，生产环境必须改 `SECRET_KEY` 并用管理员分配正式账号。

请妥善保管 `.env` 与 `data/`（含加密密钥与上传文件）。丢失密钥会导致已加密字段无法解密，服务也可能拒绝用新密钥启动。

## 安装 MySQL 8（本机 / Linux 服务器）

使用发行版或 MySQL 社区版即可。安全组一般只放行 Web 端口；**不要对公网开放 3306**。

### Ubuntu 22.04 / 24.04

```bash
sudo apt update
sudo apt install -y mysql-server
sudo systemctl enable --now mysql
sudo mysql_secure_installation
```

macOS 可用 Homebrew：`brew install mysql && brew services start mysql`。

### 建库与用户

MySQL 将 `localhost`（套接字）与 `127.0.0.1`（TCP）视为不同主机。应用连接串使用 `127.0.0.1:3306` 时，建议两边都授权。把示例中的口令换成你自己的强密码，且不要写进对外文档。

```sql
CREATE DATABASE trade CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER 'trade'@'127.0.0.1' IDENTIFIED BY '你的强密码';
GRANT ALL PRIVILEGES ON trade.* TO 'trade'@'127.0.0.1';

CREATE USER 'trade'@'localhost' IDENTIFIED BY '你的强密码';
GRANT ALL PRIVILEGES ON trade.* TO 'trade'@'localhost';

FLUSH PRIVILEGES;
```

```bash
mysql -h 127.0.0.1 -P 3306 -u trade -p trade
```

`.env` 中 `DATABASE_URL` 形如：

```
mysql+pymysql://用户:密码@127.0.0.1:3306/trade?charset=utf8mb4
```

写成 `mysql://` 也可以，应用会改成 `mysql+pymysql://`。

## Linux 服务器部署

以下以 Ubuntu 为例。把 `YOUR_HOST` 换成你的主机名或 IP。安全组放行 **80**（调试用的 8000 上线后可关）。不要放行公网 3306。

### 1. 依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx mysql-server
sudo systemctl enable --now mysql
```

按上一节建库授权。建议 Python ≥ 3.9。

### 2. 上传代码

将项目放到服务器目录（例如 `/opt/trade`），其中应有 `app/`、`requirements.txt`。

**不要用整目录覆盖反复部署**，以免冲掉远程 `.env`、`data/` 和上传文件。

以 GitHub 为发布源时（推荐）：本机先升版本再提交推送，再到**服务器**拉代码并重启：

```bash
# 本机
./prepare-release.sh
git add VERSION app/static/index.html
# 再把你改过的功能文件一起 add，然后 commit、push

# 服务器
cd /opt/trade
chmod +x upgrade-from-github.sh deploy.sh
./upgrade-from-github.sh
```

第一次若 `/opt/trade` 还不是 git 仓库，按 `upgrade-from-github.sh` 里的提示 `git init` / `git remote` / `git checkout`，不会覆盖 `.env` 和 `data/`。

也可以本机不经 GitHub、直接 rsync：`./upgrade.sh root@YOUR_HOST:/opt/trade`。两种不要混用。

### 3. 虚拟环境与配置

```bash
cd /opt/trade
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 SECRET_KEY、DATABASE_URL，勿将真实值提交到 git
```

### 4. systemd

```bash
sudo tee /etc/systemd/system/trade.service >/dev/null <<'EOF'
[Unit]
Description=Trade inquiry system
After=network.target mysql.service

[Service]
WorkingDirectory=/opt/trade
Environment=PATH=/opt/trade/.venv/bin
ExecStart=/opt/trade/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now trade
sudo systemctl status trade
```

空库才会写入演示账号。务必保留 `data/` 下的密钥文件。

### 5. Nginx

```bash
sudo tee /etc/nginx/sites-available/trade >/dev/null <<'EOF'
server {
    listen 80;
    server_name _;
    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/trade /etc/nginx/sites-enabled/trade
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

浏览器访问 `http://YOUR_HOST`。

### 6. 备份

服务器项目目录执行（需已安装 `mysqldump`）：

```bash
chmod +x backup.sh
./backup.sh
```

默认写到 `/opt/trade-backups/trade-日期.tar.gz`，内含数据库 dump、`.env`、`e2e.key`、上传附件。每天凌晨可加 crontab：

```bash
echo '15 3 * * * /opt/trade/backup.sh >> /var/log/trade-backup.log 2>&1' | crontab -
```

请再拷一份到本机或 OSS。误删 `data/e2e.key` 只能从备份恢复到原路径。

### 7. 发版

改代码后重启服务即可，不会清库：

```bash
sudo systemctl restart trade
sudo journalctl -u trade -f
curl http://127.0.0.1:8000/api/health
```

不要重建库、不要删除 `data/`。误删密钥只能从备份恢复到原路径。

## 仓库注意

- 不要提交 `.env`、`data/e2e.key`、数据库备份、真实客户导出。  
- 接口文档默认关闭；本机调试可在 `.env` 设 `ENABLE_API_DOCS=true`。  
- 健康检查：`GET /api/health`。

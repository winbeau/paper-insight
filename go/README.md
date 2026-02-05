# Paper Insight 部署配置

本目录包含：
- `go/nginx.conf`
- `go/nginx-sites-available-paper-insight.conf`
- `go/paper-insight-backend.service`

下面是快速落地步骤（按 Ubuntu/Debian 默认路径）。如为 CentOS/RHEL，请按提示改到 `conf.d/`。

**1. 安装并替换 Nginx 主配置**
```bash
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak
sudo cp /home/winbeau/Projects/paper-insight/go/nginx.conf /etc/nginx/nginx.conf
```

**2. 放置站点配置**
Ubuntu/Debian：
```bash
sudo cp /home/winbeau/Projects/paper-insight/go/nginx-sites-available-paper-insight.conf \
  /etc/nginx/sites-available/paper-insight.conf
sudo ln -s /etc/nginx/sites-available/paper-insight.conf /etc/nginx/sites-enabled/paper-insight.conf
```

CentOS/RHEL：
```bash
sudo cp /home/winbeau/Projects/paper-insight/go/nginx-sites-available-paper-insight.conf \
  /etc/nginx/conf.d/paper-insight.conf
```

**3. 检查与重启 Nginx**
```bash
sudo nginx -t
sudo systemctl restart nginx
```

**4. 放置 systemd 服务文件**
```bash
sudo cp /home/winbeau/Projects/paper-insight/go/paper-insight-backend.service \
  /etc/systemd/system/paper-insight-backend.service
sudo systemctl daemon-reload
sudo systemctl enable --now paper-insight-backend
```

**5. 安装 uv 并准备后端环境**
```bash
# 安装 uv（推荐）
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# 进入后端目录，安装依赖
cd /home/winbeau/paper-insight/backend
uv sync
```

**6. 安装 npx、Node.js、pnpm 并准备前端依赖（使用 NodeSource 的 LTS 版本，避免系统自带过旧）**
```bash
# 使用 NodeSource 安装最新 LTS 的 Node.js（包含 npm + npx）
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs

# 再确保 node/npx 可用
node -v
npx -v

# 然后装 pnpm
sudo npm install -g pnpm

# 进入前端目录，安装依赖
cd /home/winbeau/paper-insight/frontend
pnpm install

# 构建前端（注意设置部署路径与 API 前缀）
VITE_BASE=/paper-insight/ \
VITE_API_BASE_URL=/paper-insight/api \
pnpm exec vite build
```

**7. 验证服务**
```bash
sudo systemctl status paper-insight-backend --no-pager
curl -s http://127.0.0.1:8000/health
```

**重要检查点**
1. `server_name` 请替换为你的域名或实际 IP。
2. 前端目录默认是 `/var/www/paper-insight/`，确保已部署前端静态文件。
3. systemd 中的 `WorkingDirectory`、`EnvironmentFile`、`ExecStart` 路径要与你服务器真实路径一致。
4. 后端仅监听 `127.0.0.1:8000`，对外访问需经过 Nginx 反代。
5. 如需 HTTPS，请额外配置 443 端口与证书（不在本文件中）。

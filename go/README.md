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

# 进入后端目录，创建虚拟环境并安装依赖
cd /home/winbeau/paper-insight/backend
uv venv .venv
uv pip install -r requirements.txt
```

**6. 验证服务**
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

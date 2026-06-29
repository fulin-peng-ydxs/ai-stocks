# 反向代理 + TLS 终结部署（stage1·R1·T1.5）

公网 SaaS 形态下，后端 `uvicorn` **不直接对公网裸 HTTP**：前置反向代理做 **HTTPS/TLS 终结 + 限流 + 安全响应头 + 静态/`/api` 路由**，后端只绑 `127.0.0.1`。下面给两套可直接套用的模板（择一），上线时替换域名/证书路径即可。

> 现状说明：本机开发为 HTTP localhost，无需反代；本文件是 R1「反代接入 + HTTPS 生效」的**部署交付模板**，在有域名的服务器上应用后即满足 R1 验收。应用层限流/会话仍由 Redis 承载（阶段二）。

## 方案 A：Caddy（推荐，自动签发 + 自动续期 Let's Encrypt）

`deploy/Caddyfile`：
```caddy
your-domain.com {
    encode zstd gzip
    # 安全响应头
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }
    # 粗粒度限流（精细化按用户/接口的限流在应用层走 Redis）
    rate_limit {
        zone api { key {remote_host}; events 120; window 1m }
    }
    reverse_proxy 127.0.0.1:8000
}
```
启动：`caddy run --config deploy/Caddyfile`（首次自动向 ACME 申请证书，自动续期）。

## 方案 B：Nginx（手动证书 / 已有证书体系）

`deploy/nginx-ai-stocks.conf`：
```nginx
limit_req_zone $binary_remote_addr zone=api:10m rate=2r/s;

server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;          # 强制 HTTPS
}
server {
    listen 443 ssl http2;
    server_name your-domain.com;
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    client_max_body_size 8m;

    location /api/ {
        limit_req zone=api burst=20 nodelay;       # 粗粒度限流
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;          # 后端托管 frontend/dist（SPA 回退）
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 后端配合
- `start.sh prod` 启动后端托管 `frontend/dist`；**公网部署改绑 `127.0.0.1`**（`config/settings.yaml::server.host`），只让反代访问，不直接暴露 8000。
- 后端读取 `X-Forwarded-For`/`X-Forwarded-Proto` 识别真实客户端 IP（应用层限流/审计用，阶段二接入）。
- PG/Redis 仅监听 `127.0.0.1` 或内网，不对公网开放；PG 走密码认证（`AI_STOCKS_PG_PASSWORD`）。

## R1 验收对照
- ✅ 反代接入：Caddy/Nginx 任一模板转发 `/api` 与静态到 `127.0.0.1:8000`。
- ✅ HTTPS 生效：Caddy 自动签发 / Nginx 挂证书，80→443 强制跳转 + HSTS。
- ✅ 粗粒度限流 + 安全响应头在反代层；细粒度限流/验证码/token 在应用层（Redis，阶段二）。

# 反向代理 + TLS 终结部署（stage1·R1·T1.5）

本文提供反向代理、TLS、限流与安全响应头的部署模板。下方文件名是待部署配置示例，不表示仓库已有对应文件，也不代表目标服务器已部署或验收。

参考：[环境配置](../../architecture/environment-configuration.md) · [认证与权限](../../architecture/system-rbac-tenant.md)。

应用模板前须核对目标软件版本、已安装模块、证书、域名和可信转发头，并在目标环境验证。

## 部署目标

公网访问通过反向代理完成 **HTTPS/TLS 终结 + 限流 + 安全响应头 + 静态/`/api` 路由**，后端 8000 只允许可信代理访问。本机开发使用 HTTP localhost；选择下方模板后仍须完成目标环境配置与实测。

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
        proxy_set_header X-Forwarded-For $remote_addr;
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
- `./start.sh prod` 托管 `frontend/dist`，当前显式传入 `--host 0.0.0.0`，只改 YAML 的 `server.host` 不会使其绑定回环地址。部署时必须用主机防火墙或容器网络隔离确保 8000 仅代理可达；需要改为回环监听时先修改受控启动入口并验证，不能按本模板假定已生效。
- 应用层限流与审计默认使用连接地址；仅在可信代理覆盖客户端传入的 `X-Forwarded-For`、且后端禁止绕过代理直连时，才可设置 `server.trust_forwarded_for=true`。上方 Nginx 示例按单层可信代理覆盖 XFF；多层代理须单独核查信任链，完整口径见环境配置架构。
- PG/Redis 仅监听 `127.0.0.1` 或内网，不对公网开放；PG 走密码认证（`AI_STOCKS_PG_PASSWORD`）。

## R1 验收对照

以下为待执行检查项，不能仅凭复制模板标记通过：

- 代理配置校验通过，`/api` 与静态资源可达，外部无法直连后端 8000。
- 实际域名 HTTPS、证书链、80→443 跳转与 HSTS 生效。
- 代理限流与安全响应头生效，应用层 Redis 会话、验证码与限流仍正常；伪造 XFF 不能绕过限流或污染审计来源。

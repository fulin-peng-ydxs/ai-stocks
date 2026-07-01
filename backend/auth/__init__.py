"""认证与鉴权内核（多租户 RBAC stage2）。

子模块：
- constants：角色码等零依赖常量。
- security：密码 bcrypt 哈希/校验 + 强度校验（T1/T2）。
- jwt_tokens：access/refresh 签发与校验（T2）。
- T3 起补 session_store（Redis）、context、middleware、deps。
"""

"""认证与鉴权内核（多租户 RBAC stage2）。

子模块：
- constants：角色码等零依赖常量。
- security：密码 bcrypt 哈希/校验（T1）；T2 起补 jwt_tokens、session_store、context、middleware、deps。
"""

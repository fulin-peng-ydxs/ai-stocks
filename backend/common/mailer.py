"""SMTP 邮件发送封装（标准库 smtplib，零新增依赖）。

用于系统通知类邮件（注册邮箱验证码等）。配置见 settings.mail（MailConfig）：
- mail.enabled=false：降级为 dev 日志打印，不真正投递（本地开发/测试）；
- mail.enabled=true：按 use_ssl 选 SMTP_SSL(465) 或 SMTP+starttls(587) 真实发信。

SMTP 密码/授权码不入 YAML/码，运行时从 AI_STOCKS_SMTP_PASSWORD 读取（Settings.smtp_password()）。
发信失败上抛 MailError，由调用方决定是否转译为对用户可见的软失败。
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from backend.common.exceptions import AIStocksError
from backend.common.logging import get_logger
from backend.config import get_effective_settings

log = get_logger("common.mailer")


class MailError(AIStocksError):
    """邮件发送失败（SMTP 连接/认证/投递异常）。软失败口径，默认 HTTP 200 + code。"""

    code = 5006


def send_email(to: str, subject: str, body: str, *, html: str | None = None) -> None:
    """发送一封纯文本（可选 HTML）邮件。

    - to：收件人地址
    - subject：主题
    - body：纯文本正文（必填，作为 HTML 客户端的降级正文）
    - html：可选 HTML 正文

    mail.enabled=false 时仅打印开发态日志并返回；开启后 SMTP 投递失败抛 MailError。
    """
    cfg = get_effective_settings().mail_config()

    if not cfg.enabled:
        # dev 兜底：不真正发信，正文写日志便于本地联调（勿在公网开放环境依赖此路径）
        log.warning("【dev·邮件未启用】to=%s subject=%s body=%s", to, subject, body)
        return

    sender = cfg.sender or cfg.username
    if not (cfg.host and cfg.username and sender):
        raise MailError("邮件发送未正确配置（host/username/sender 缺失）")
    password = get_effective_settings().smtp_password()
    if not password:
        raise MailError("缺少环境变量 AI_STOCKS_SMTP_PASSWORD：SMTP 密码/授权码未配置")

    msg = EmailMessage()
    msg["Subject"] = subject
    # 保留发件人显示名，地址部分取 parseaddr 结果，避免非法 From 头
    name, addr = parseaddr(sender)
    msg["From"] = formataddr((name, addr)) if name else addr
    msg["To"] = to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if cfg.use_ssl:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout_sec) as s:
                s.login(cfg.username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout_sec) as s:
                s.ehlo()
                s.starttls()
                s.ehlo()
                s.login(cfg.username, password)
                s.send_message(msg)
    except MailError:
        raise
    except Exception as exc:  # noqa: BLE001 —— 统一转译为 MailError 供上层软失败
        # 不记录 password；仅记录目标与服务器信息便于排查
        log.exception("SMTP 发信失败 to=%s host=%s:%s", to, cfg.host, cfg.port)
        raise MailError("邮件发送失败，请稍后再试") from exc
    log.info("邮件已发送 to=%s subject=%s", to, subject)

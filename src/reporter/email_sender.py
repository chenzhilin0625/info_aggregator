"""
SMTP 邮件发送模块
"""
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

import pytz

logger = logging.getLogger("zhihu_analyst")
CST = pytz.timezone("Asia/Shanghai")


class EmailSender:
    def __init__(self, cfg: dict):
        self.smtp_host = cfg["smtp_host"]
        self.smtp_port = int(cfg.get("smtp_port", 465))
        self.use_ssl = cfg.get("use_ssl", True)
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.sender_name = cfg.get("sender_name", "A股日报机器人")
        self.sender = formataddr((self.sender_name, self.username))
        self.recipients = cfg.get("recipients", [])

        if not self.recipients or not any(self.recipients):
            raise ValueError("邮件收件人列表为空，请在 config.yaml 中配置 email.recipients")

    def _build_connection(self):
        if self.use_ssl:
            return smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)
        else:
            conn = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
            conn.starttls()
            return conn

    def send_report(self, report_date: str, html_content: str, md_content: str):
        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"[A股日报] {report_date} - 知乎财经分析"
        msg["From"] = self.sender
        msg["To"] = ", ".join(r for r in self.recipients if r)

        html_part = MIMEText(html_content, "html", "utf-8")
        msg.attach(html_part)

        md_bytes = md_content.encode("utf-8")
        md_attachment = MIMEApplication(md_bytes, Name=f"report_{report_date}.md")
        md_attachment["Content-Disposition"] = (
            f'attachment; filename="report_{report_date}.md"'
        )
        msg.attach(md_attachment)

        self._send(msg)
        logger.info(f"报告邮件已发送至：{self.recipients}")

    def send_cookie_expired_alert(self):
        now = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
        html = f"""
<html><body style="font-family:Microsoft YaHei,sans-serif;padding:20px">
<h2 style="color:#c62828">Cookie 已过期</h2>
<p>A股日报程序在 <strong>{now}</strong> 检测到知乎 Cookie 已失效，本次已跳过。</p>
<h3>更新步骤：</h3>
<ol>
  <li>浏览器登录 <a href="https://www.zhihu.com">知乎</a></li>
  <li>F12 > Network > 刷新 > 任意请求 Headers > Cookie</li>
  <li>复制 z_c0= 之后到 ; 之前的值</li>
  <li>更新 config/config.yaml 中的 zhihu.cookie_z_c0</li>
  <li>运行 python main.py --validate-only 验证</li>
</ol>
<p style="color:#999;font-size:12px">此邮件由 A股日报系统自动发送</p>
</body></html>
"""
        msg = MIMEMultipart()
        msg["Subject"] = "[A股日报] Cookie已过期，需要手动更新"
        msg["From"] = self.sender
        msg["To"] = ", ".join(r for r in self.recipients if r)
        msg.attach(MIMEText(html, "html", "utf-8"))
        self._send(msg)
        logger.info("Cookie 过期提醒邮件已发送")

    def _send(self, msg: MIMEMultipart):
        valid_recipients = [r for r in self.recipients if r]
        try:
            conn = self._build_connection()
            conn.login(self.username, self.password)
            conn.sendmail(self.username, valid_recipients, msg.as_string())
            conn.quit()
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP 认证失败，请检查用户名和授权码: {e}")
            raise
        except smtplib.SMTPException as e:
            logger.error(f"SMTP 发送失败: {e}")
            raise

    def test_connection(self):
        try:
            conn = self._build_connection()
            conn.login(self.username, self.password)
            conn.quit()
            logger.info("SMTP 连接测试成功")
            return True
        except Exception as e:
            logger.error(f"SMTP 连接测试失败: {e}")
            return False

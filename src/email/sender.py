"""TLS SMTP transport. Durable delivery state is owned by the weekly job."""
from email.message import EmailMessage
from email.utils import formatdate
import smtplib
import ssl

class EmailDeliveryError(RuntimeError):
    pass

def validate_email_config(config):
    if config.email_provider != 'smtp':
        raise ValueError('EMAIL_PROVIDER must be smtp')
    for name in ('smtp_host', 'email_from', 'report_email'):
        if not getattr(config, name):
            raise ValueError(f'Missing email configuration: {name}')
    for address in (config.email_from, config.report_email):
        if '\r' in address or '\n' in address or '@' not in address or ',' in address:
            raise ValueError('Configure a single valid sender and recipient address')
    if config.smtp_security not in ('ssl', 'starttls'):
        raise ValueError('SMTP_SECURITY must be ssl or starttls')

def send_report(config, *, week, markdown, html, message_id):
    validate_email_config(config)
    message = EmailMessage()
    message['Subject'] = f'🏈 Fantasy League Intelligence — Week {week} Report'
    message['From'], message['To'] = config.email_from, config.report_email
    message['Message-ID'], message['Date'] = message_id, formatdate(localtime=False)
    message.set_content(markdown)
    message.add_alternative(html, subtype='html')
    context = ssl.create_default_context()
    try:
        transport = smtplib.SMTP_SSL if config.smtp_security == 'ssl' else smtplib.SMTP
        kwargs = {'context': context} if config.smtp_security == 'ssl' else {}
        with transport(config.smtp_host, config.smtp_port, timeout=45, **kwargs) as server:
            if config.smtp_security == 'starttls':
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            refused = server.send_message(message)
            if refused:
                raise EmailDeliveryError('Recipient rejected')
    except Exception:
        raise EmailDeliveryError('EMAIL_SEND_FAILED: check provider delivery logs before retrying') from None

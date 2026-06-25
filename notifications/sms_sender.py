"""
notifications/sms_sender.py — Twilio SMS alerts.
Credentials come from environment variables set by setup_ec2.sh.
Gracefully disabled if Twilio is not configured (operator skipped it).
"""

import logging
from config import get_twilio_sid, get_twilio_token, get_twilio_from, get_alert_phone, sms_configured

logger = logging.getLogger(__name__)


class SmsSender:
    def __init__(self):
        self._enabled = sms_configured()
        if not self._enabled:
            logger.info("SMS alerts disabled — Twilio not configured")

    def send(self, message: str) -> bool:
        if not self._enabled:
            logger.debug(f"SMS (disabled): {message}")
            return False
        try:
            from twilio.rest import Client
            client = Client(get_twilio_sid(), get_twilio_token())
            client.messages.create(
                body  = message[:1600],
                from_ = get_twilio_from(),
                to    = get_alert_phone()
            )
            logger.debug(f"SMS sent: {message[:80]}")
            return True
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return False

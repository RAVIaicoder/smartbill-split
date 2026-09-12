"""
OTP delivery. In "console" mode (default, no account needed) the code is
printed to the server log and flashed on-screen for demo purposes.
Set SMS_PROVIDER=twilio in .env (with TWILIO_SID/TOKEN/FROM_NUMBER) to send
real SMS via Twilio (or adapt the same pattern for MSG91 / AWS SNS).
"""

from flask import current_app


def send_otp(phone: str, code: str):
    provider = current_app.config.get("SMS_PROVIDER", "console")

    if provider == "twilio":
        try:
            from twilio.rest import Client
            client = Client(current_app.config["TWILIO_SID"], current_app.config["TWILIO_TOKEN"])
            client.messages.create(
                body=f"Your SmartBill Split OTP is {code}. Valid for {current_app.config['OTP_EXPIRY_MINUTES']} min.",
                from_=current_app.config["TWILIO_FROM_NUMBER"],
                to=phone,
            )
            return {"sent": True, "provider": "twilio"}
        except Exception as e:
            current_app.logger.error(f"Twilio send failed: {e}")
            return {"sent": False, "provider": "twilio", "error": str(e)}

    # Demo/console mode
    current_app.logger.info(f"[DEMO OTP] {phone} -> {code}")
    return {"sent": True, "provider": "console", "demo_code": code}

"""
Payment helpers.

Implemented (works with zero paid accounts, matches "Option 2: UPI Deep
Links" from the brief):
    - build_upi_link(): standard `upi://pay?...` deep link. On a phone with
      GPay / PhonePe / Paytm installed, tapping this opens the app's own
      payment sheet pre-filled with amount + payee - the user still chooses
      which UPI app and enters their own card/UPI PIN, so SmartBill never
      touches card numbers or UPI credentials.
    - build_qr_data(): same string, rendered as a QR code client-side
      (see templates/main/pay.html - uses qrcode.js from CDN) so a second
      person can scan-to-pay.

Stubbed (Option 1 from the brief - "recommended for production"):
    - create_razorpay_link(): shows exactly where a real payment-gateway
      integration (Razorpay / Cashfree / PayU) would plug in. Requires a
      merchant account + API keys in .env; until those are set this
      function returns a clear "not configured" result instead of failing.
"""

from urllib.parse import quote
from flask import current_app


def build_upi_link(amount: float, note: str = "SmartBill payment", payee_vpa: str = None, payee_name: str = None) -> str:
    vpa = payee_vpa or current_app.config["UPI_MERCHANT_VPA"]
    name = payee_name or current_app.config["UPI_MERCHANT_NAME"]
    params = (
        f"pa={quote(vpa)}"
        f"&pn={quote(name)}"
        f"&am={amount:.2f}"
        f"&cu=INR"
        f"&tn={quote(note)}"
    )
    return f"upi://pay?{params}"


def build_qr_data(amount: float, note: str, payee_vpa: str = None, payee_name: str = None) -> str:
    # QR codes encode the same UPI URI; rendering happens client-side.
    return build_upi_link(amount, note, payee_vpa, payee_name)


def create_razorpay_link(amount: float, description: str, customer_email: str = None):
    key_id = current_app.config.get("RAZORPAY_KEY_ID")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        return {
            "configured": False,
            "message": (
                "Razorpay isn't configured yet. Add RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET to your .env to enable hosted "
                "payment links (card / netbanking / UPI in one checkout). "
                "Falling back to a direct UPI deep link."
            ),
        }

    # Real integration would look like:
    #
    # import razorpay
    # client = razorpay.Client(auth=(key_id, key_secret))
    # link = client.payment_link.create({
    #     "amount": int(amount * 100),  # paise
    #     "currency": "INR",
    #     "description": description,
    #     "customer": {"email": customer_email} if customer_email else {},
    #     "notify": {"sms": True, "email": bool(customer_email)},
    #     "callback_url": url_for("main.payment_callback", _external=True),
    #     "callback_method": "get",
    # })
    # return {"configured": True, "short_url": link["short_url"], "id": link["id"]}

    return {"configured": True, "short_url": "#", "id": "demo"}

from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash, session, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models import User, OTPRequest
from app.utils.sms import send_otp

auth_bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------------------
# HOME / LOGIN (home page IS the login page when logged out)
# ---------------------------------------------------------------------------
@auth_bp.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter(User.email_enc.isnot(None)).all()
        matched = next((u for u in user if u.email and u.email.lower() == email), None)

        if matched and matched.check_password(password):
            login_user(matched)
            matched.last_login_at = datetime.utcnow()
            db.session.commit()
            flash(f"Welcome back, {matched.name.split()[0]}!", "success")
            return redirect(url_for("main.dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("auth/login.html")


# ---------------------------------------------------------------------------
# PHONE OTP LOGIN - every single login always requires a fresh OTP
# (there is no "remember this device" option by design, per spec)
# ---------------------------------------------------------------------------
@auth_bp.route("/login/phone", methods=["GET", "POST"])
def login_phone_request():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        if not phone:
            flash("Enter a valid phone number.", "danger")
            return redirect(url_for("auth.login_phone_request"))

        matching_user = None
        for u in User.query.filter(User.phone_enc.isnot(None)).all():
            if u.phone == phone:
                matching_user = u
                break

        purpose = "login" if matching_user else "register"
        otp_req, code = OTPRequest.create(
            phone, purpose=purpose,
            length=current_app.config["OTP_LENGTH"],
            expiry_minutes=current_app.config["OTP_EXPIRY_MINUTES"],
        )
        result = send_otp(phone, code)

        session["pending_otp_id"] = otp_req.id
        session["pending_phone"] = phone
        session["pending_purpose"] = purpose

        if result.get("provider") == "console":
            flash(f"Demo mode: your OTP is {result['demo_code']} (no SMS account configured).", "info")
        else:
            flash("OTP sent to your phone.", "success")

        return redirect(url_for("auth.login_phone_verify"))

    return render_template("auth/login_phone.html")


@auth_bp.route("/login/phone/verify", methods=["GET", "POST"])
def login_phone_verify():
    otp_id = session.get("pending_otp_id")
    phone = session.get("pending_phone")
    if not otp_id or not phone:
        return redirect(url_for("auth.login_phone_request"))

    if request.method == "POST":
        code = request.form.get("otp", "").strip()
        otp_req = OTPRequest.query.get(otp_id)

        if not otp_req or not otp_req.verify(code):
            flash("Incorrect or expired OTP. Please try again.", "danger")
            return render_template("auth/login_phone_verify.html", phone=phone)

        # find or create user
        matched = None
        for u in User.query.filter(User.phone_enc.isnot(None)).all():
            if u.phone == phone:
                matched = u
                break

        if not matched:
            matched = User(name=f"User {phone[-4:]}", auth_provider="phone")
            matched.phone = phone
            db.session.add(matched)
            db.session.commit()
            flash("Phone verified - account created!", "success")

        login_user(matched)
        matched.last_login_at = datetime.utcnow()
        db.session.commit()
        session.pop("pending_otp_id", None)
        session.pop("pending_phone", None)
        session.pop("pending_purpose", None)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login_phone_verify.html", phone=phone)


# ---------------------------------------------------------------------------
# GOOGLE OAUTH LOGIN
# ---------------------------------------------------------------------------
@auth_bp.route("/login/google")
def login_google():
    if not current_app.config.get("GOOGLE_CLIENT_ID"):
        flash(
            "Google login isn't configured on this server yet. Add "
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET to .env - see README.",
            "warning",
        )
        return redirect(url_for("auth.login"))

    from app.auth.oauth import oauth_client
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth_client().authorize_redirect(redirect_uri)


@auth_bp.route("/login/google/callback")
def google_callback():
    from app.auth.oauth import oauth_client
    client = oauth_client()
    token = client.authorize_access_token()
    userinfo = token.get("userinfo") or client.userinfo()

    email = userinfo["email"]
    name = userinfo.get("name", email.split("@")[0])
    picture = userinfo.get("picture", "")

    matched = None
    for u in User.query.filter(User.email_enc.isnot(None)).all():
        if u.email and u.email.lower() == email.lower():
            matched = u
            break

    if not matched:
        matched = User(name=name, auth_provider="google", avatar_url=picture)
        matched.email = email
        db.session.add(matched)
        db.session.commit()

    login_user(matched)
    matched.last_login_at = datetime.utcnow()
    db.session.commit()
    flash(f"Signed in with Google as {matched.name}.", "success")
    return redirect(url_for("main.dashboard"))


# ---------------------------------------------------------------------------
# REGISTER (email + password)
# ---------------------------------------------------------------------------
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth.register"))
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("auth.register"))

        for u in User.query.filter(User.email_enc.isnot(None)).all():
            if u.email and u.email.lower() == email:
                flash("An account with this email already exists.", "danger")
                return redirect(url_for("auth.login"))

        user = User(name=name, auth_provider="password")
        user.email = email
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created! Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


# ---------------------------------------------------------------------------
# LOGOUT - clears session fully so next login (of any method) starts fresh,
# which is what forces phone-login users through OTP again every time.
# ---------------------------------------------------------------------------
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))

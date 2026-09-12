import random
import string
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db
from app.utils.crypto import encrypt_value, decrypt_value


def gen_id(prefix=""):
    return prefix + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


# ---------------------------------------------------------------------------
# USER
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

    # PII stored encrypted at rest; plain python access via properties below
    email_enc = db.Column("email", db.Text, unique=False, nullable=True)
    phone_enc = db.Column("phone", db.Text, unique=False, nullable=True)

    password_hash = db.Column(db.String(255), nullable=True)  # null if OAuth/OTP-only account
    auth_provider = db.Column(db.String(20), default="password")  # password | google | phone

    avatar_url = db.Column(db.String(255), default="")
    is_admin = db.Column(db.Boolean, default=False)
    is_active_account = db.Column(db.Boolean, default=True)
    dark_mode = db.Column(db.Boolean, default=False)
    currency = db.Column(db.String(6), default="INR")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    # relationships
    memberships = db.relationship("GroupMember", back_populates="user", cascade="all, delete-orphan")
    bills_paid = db.relationship("Bill", back_populates="paid_by", foreign_keys="Bill.paid_by_id")
    notifications = db.relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    # ---- encrypted PII accessors ----
    @property
    def email(self):
        return decrypt_value(self.email_enc) if self.email_enc else None

    @email.setter
    def email(self, value):
        self.email_enc = encrypt_value(value) if value else None

    @property
    def phone(self):
        return decrypt_value(self.phone_enc) if self.phone_enc else None

    @phone.setter
    def phone(self, value):
        self.phone_enc = encrypt_value(value) if value else None

    # ---- password helpers ----
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return self.password_hash and check_password_hash(self.password_hash, raw)

    # ---- profile stats used on Dashboard / Profile ----
    def pending_bills_count(self):
        return BillShare.query.filter_by(user_id=self.id, is_paid=False).count()

    def groups_count(self):
        return len(self.memberships)


# ---------------------------------------------------------------------------
# OTP (phone login)
# ---------------------------------------------------------------------------
class OTPRequest(db.Model):
    __tablename__ = "otp_requests"

    id = db.Column(db.Integer, primary_key=True)
    phone_enc = db.Column("phone", db.Text, nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(20), default="login")  # login | register
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def create(phone, purpose="login", length=6, expiry_minutes=5):
        code = "".join(random.choices(string.digits, k=length))
        req = OTPRequest(
            phone_enc=encrypt_value(phone),
            code_hash=generate_password_hash(code),
            purpose=purpose,
            expires_at=datetime.utcnow() + timedelta(minutes=expiry_minutes),
        )
        db.session.add(req)
        db.session.commit()
        return req, code  # code returned once, for the "sending" step only

    def verify(self, code):
        if self.consumed or datetime.utcnow() > self.expires_at:
            return False
        ok = check_password_hash(self.code_hash, code)
        if ok:
            self.consumed = True
            db.session.commit()
        return ok


# ---------------------------------------------------------------------------
# GROUP / MEMBERS
# ---------------------------------------------------------------------------
class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), default="")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    members = db.relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    bills = db.relationship("Bill", back_populates="group", cascade="all, delete-orphan")

    def total_pending_amount(self):
        total = 0
        for bill in self.bills:
            for share in bill.shares:
                if not share.is_paid:
                    total += share.amount
        return round(total, 2)

    def pending_bills_count(self):
        return sum(1 for b in self.bills if not b.is_fully_settled())


class GroupMember(db.Model):
    __tablename__ = "group_members"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(20), default="member")  # admin | member
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    group = db.relationship("Group", back_populates="members")
    user = db.relationship("User", back_populates="memberships")


# ---------------------------------------------------------------------------
# CATEGORY
# ---------------------------------------------------------------------------
class Category(db.Model):
    __tablename__ = "categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    icon = db.Column(db.String(20), default="🧾")

    @staticmethod
    def seed_defaults():
        defaults = [
            ("Food", "🍔"), ("Travel", "✈️"), ("Shopping", "🛍️"),
            ("Rent", "🏠"), ("Utilities", "💡"), ("Entertainment", "🎬"), ("Other", "🧾"),
        ]
        for name, icon in defaults:
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name, icon=icon))
        db.session.commit()


# ---------------------------------------------------------------------------
# BILL / BILL ITEMS / SHARES
# ---------------------------------------------------------------------------
class Bill(db.Model):
    __tablename__ = "bills"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(20), unique=True, default=lambda: gen_id("bill_"))
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    paid_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    split_type = db.Column(db.String(20), default="equal")  # equal | custom | percentage
    receipt_image = db.Column(db.String(255), default="")
    bill_date = db.Column(db.Date, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    group = db.relationship("Group", back_populates="bills")
    paid_by = db.relationship("User", back_populates="bills_paid", foreign_keys=[paid_by_id])
    category = db.relationship("Category")
    items = db.relationship("BillItem", back_populates="bill", cascade="all, delete-orphan")
    shares = db.relationship("BillShare", back_populates="bill", cascade="all, delete-orphan")

    def is_fully_settled(self):
        return all(s.is_paid for s in self.shares)


class BillItem(db.Model):
    """Optional line-items inside a bill (e.g. OCR-extracted receipt lines)."""
    __tablename__ = "bill_items"

    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, default=1)

    bill = db.relationship("Bill", back_populates="items")


class BillShare(db.Model):
    """How much each member owes for a specific bill (the 'who owes whom' unit)."""
    __tablename__ = "bill_shares"

    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    percentage = db.Column(db.Float, nullable=True)
    is_paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime, nullable=True)

    bill = db.relationship("Bill", back_populates="shares")
    user = db.relationship("User")


# ---------------------------------------------------------------------------
# PAYMENT
# ---------------------------------------------------------------------------
class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(20), unique=True, default=lambda: gen_id("pay_"))
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    payer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    payee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)  # who receives it (paid_by of bill)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(20), default="upi")  # upi | gpay | phonepe | credit_card | debit_card | cash
    status = db.Column(db.String(20), default="initiated")  # initiated | success | failed
    upi_link = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bill = db.relationship("Bill")
    payer = db.relationship("User", foreign_keys=[payer_id])
    payee = db.relationship("User", foreign_keys=[payee_id])


# ---------------------------------------------------------------------------
# NOTIFICATIONS
# ---------------------------------------------------------------------------
class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), default="")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="notifications")

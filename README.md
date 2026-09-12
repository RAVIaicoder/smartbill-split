# SmartBill Split — Technical Documentation

A working Flask web app for splitting group bills, tracking who-owes-whom,
and paying via UPI/GPay/PhonePe deep links or cards. This document lists
every technology used, how the database is structured and encrypted, how
code accesses stored data, and how to run and extend the project.

---

## 1. Language & Core Technology Stack

| Layer | Technology | Why |
|---|---|---|
| Language | **Python 3.10+** | Single language across backend, scripting, OCR, exports |
| Web framework | **Flask 3** | Lightweight, explicit, easy to reason about for a student/portfolio project |
| Templating | **Jinja2** (bundled with Flask) | Server-rendered HTML, no separate frontend build step |
| ORM / Database access | **SQLAlchemy** via **Flask-SQLAlchemy** | Python objects instead of raw SQL; swappable DB backend |
| Database migrations | **Flask-Migrate** (Alembic) | Version-controlled schema changes |
| Authentication session | **Flask-Login** | Manages "who is logged in" via secure cookies/sessions |
| OAuth (Google login) | **Authlib** | Standards-compliant OpenID Connect client |
| Password hashing | **Werkzeug security** (`generate_password_hash`) | Salted PBKDF2/scrypt hashing, never store plaintext passwords |
| Field-level encryption | **`cryptography`** (Fernet/AES) | Encrypts phone numbers & emails at rest |
| OCR (receipt scanning) | **pytesseract** + **Pillow** (wraps Google's Tesseract engine) | Extracts bill totals from photographed receipts |
| PDF export | **ReportLab** | Generates the Bill History PDF |
| Excel export | **openpyxl** | Generates the Bill History .xlsx |
| Charts | **Chart.js** (CDN, client-side JS) | Category & monthly expense charts on the Reports page |
| QR codes | **qrcode.js** (CDN, client-side JS) | Renders the UPI payment QR on the Pay page |
| Real-time (planned hook) | **Flask-SocketIO** | Installed and wired into `run.py`; ready for live notification badges |
| Frontend | **Vanilla HTML/CSS/JS** (no framework) | Server-rendered, fast, no build tooling — easy for a student project to run anywhere |
| Environment config | **python-dotenv** | Keeps secrets in `.env`, out of source control |

No JavaScript framework (React/Vue) is used — pages are rendered by Flask/Jinja
and enhanced with small vanilla-JS scripts (`static/js/app.js`) for the
dark-mode toggle, split-type switcher, and OCR upload.

---

## 2. Database

### 2.1 Engine
- **Default:** SQLite, a single file at `instance/smartbill.db`. Zero setup — perfect for development/demo/student submission.
- **Production-ready swap:** Set the `DATABASE_URL` environment variable to point at PostgreSQL or MySQL instead, e.g.:
  ```
  DATABASE_URL=postgresql://smartbill_user:password@localhost:5432/smartbill
  ```
  No code changes needed — SQLAlchemy abstracts the engine.

### 2.2 "Separate, encrypted database" requirement — how it's implemented
The brief asked for a "separate database, encrypted, to store user data, login details, OTPs, profile info."  Concretely, this app does two things:

1. **Isolation:** all persistent data lives in its own SQLite file under `instance/` (never mixed with app code), and swapping to a dedicated Postgres instance is a one-line config change — i.e. the database is architecturally separate from the web server.
2. **Field-level encryption at rest:** sensitive columns are encrypted individually using **Fernet symmetric encryption** (AES-128-CBC + HMAC) before they're written to disk:
   - `users.phone`, `users.email` — encrypted
   - OTP codes — never stored in plaintext at all; only a **hash** (`werkzeug.security`) of the code is stored, exactly like a password
   - Passwords — hashed (never encrypted/reversible), via `werkzeug.security.generate_password_hash`

   The encryption key (`FIELD_ENCRYPTION_KEY`) lives only in environment variables / `.env`, never inside the database itself. Even if the `.db` file were leaked, phone numbers and emails inside it are unreadable without that separately-held key.

   *(Note: this is field-level encryption, which is simpler to set up than full-disk database encryption like SQLCipher, but achieves the same practical goal for a student/portfolio project — the PII fields are unreadable at rest. If you need whole-database encryption for a real deployment, swap the SQLite driver for `sqlcipher3` with minimal code changes, or rely on your managed Postgres provider's at-rest encryption.)*

### 2.3 Schema (tables)

| Table | Purpose | Key columns |
|---|---|---|
| `users` | Accounts | `id`, `name`, `email` (encrypted), `phone` (encrypted), `password_hash`, `auth_provider`, `is_admin`, `dark_mode`, `currency` |
| `otp_requests` | OTP codes for phone login | `phone` (encrypted), `code_hash`, `expires_at`, `consumed` |
| `groups` | Bill-splitting groups | `id`, `name`, `description`, `created_by_id` |
| `group_members` | Many-to-many: users ↔ groups | `group_id`, `user_id`, `role` |
| `categories` | Food / Travel / Shopping / Rent / etc. | `id`, `name`, `icon` |
| `bills` | One bill/expense | `group_id`, `name`, `total_amount`, `category_id`, `paid_by_id`, `split_type`, `receipt_image`, `bill_date` |
| `bill_items` | Optional line items inside a bill (e.g. from OCR) | `bill_id`, `name`, `amount`, `quantity` |
| `bill_shares` | Who owes how much for a specific bill | `bill_id`, `user_id`, `amount`, `percentage`, `is_paid` |
| `payments` | Payment attempts/records | `bill_id`, `payer_id`, `payee_id`, `amount`, `method`, `status`, `upi_link` |
| `notifications` | In-app reminders/alerts | `user_id`, `message`, `link`, `is_read` |

Full column definitions are in `app/models.py`.

### 2.4 How code accesses stored data
Data access goes entirely through the **SQLAlchemy ORM** — there is no raw SQL anywhere in the app. Pattern used throughout `app/main/routes.py`, `app/auth/routes.py`, `app/admin/routes.py`:

```python
from app.extensions import db
from app.models import User, Bill, BillShare

# Read
user = User.query.get(user_id)
bills = Bill.query.filter_by(group_id=group_id).order_by(Bill.bill_date.desc()).all()

# Write
new_bill = Bill(name="Dinner", total_amount=1800, group_id=1, paid_by_id=user.id)
db.session.add(new_bill)
db.session.commit()

# Encrypted fields are transparent — reading/writing `user.email` or
# `user.phone` automatically encrypts/decrypts via Python @property
# descriptors defined in models.py; the rest of the codebase never touches
# raw ciphertext.
user.email = "someone@example.com"   # encrypted before hitting the DB
print(user.email)                    # decrypted transparently when read
```

Database tables are created automatically on first run (`db.create_all()` inside the app factory) — no manual setup step needed for the default SQLite mode.

---

## 3. Application Architecture

```
smartbill/
├── run.py                  # entrypoint (python run.py)
├── config.py                # all settings, reads from environment/.env
├── seed_demo_data.py        # optional: creates demo users/group/bill
├── requirements.txt
├── .env.example              # copy to .env and fill in secrets
├── instance/
│   └── smartbill.db          # SQLite file (auto-created)
└── app/
    ├── __init__.py            # application factory, registers blueprints
    ├── extensions.py          # db, login_manager, migrate, socketio instances
    ├── models.py               # all SQLAlchemy models (section 2.3)
    ├── auth/
    │   ├── routes.py            # login, register, phone OTP, Google OAuth, logout
    │   └── oauth.py              # Google OAuth client setup (Authlib)
    ├── main/
    │   └── routes.py            # dashboard, groups, bills, payments, reports,
    │                             # profile, settings, notifications, exports
    ├── admin/
    │   └── routes.py            # admin-only: manage users/groups, analytics
    ├── utils/
    │   ├── crypto.py             # Fernet field encryption helpers
    │   ├── split.py              # equal/custom/percentage split math + debt simplification
    │   ├── payments.py           # UPI deep-link builder + Razorpay stub
    │   ├── ocr.py                 # receipt OCR (pytesseract wrapper)
    │   └── sms.py                 # OTP delivery (console demo / Twilio)
    ├── templates/                # Jinja2 HTML templates
    │   ├── base.html               # sidebar app shell + dark/light theme
    │   ├── auth/                   # login, register, phone OTP screens
    │   ├── main/                   # dashboard, groups, bills, reports, etc.
    │   └── admin/
    └── static/
        ├── css/style.css          # design tokens, dark/light theme, components
        ├── js/app.js               # theme toggle, split-type UI, OCR AJAX
        └── uploads/                # uploaded receipt images
```

**Blueprints** (Flask's way of organizing routes into modules): `auth` (no URL prefix — login is the home page), `main` (no prefix), `admin` (prefix `/admin`, protected by an `@admin_required` decorator).

---

## 4. Feature-to-Implementation Map

| Requested feature | Status | Where |
|---|---|---|
| Login page as home page | ✅ Implemented | `auth.home` → redirects to `auth.login` |
| Phone OTP login (every login) | ✅ Implemented, demo SMS | `auth/routes.py`, `models.OTPRequest` |
| Login with Gmail | ✅ Implemented (needs your Google API keys) | `auth/oauth.py` |
| Register | ✅ Implemented | `auth.register` |
| Dashboard (stats, groups, reminders) | ✅ Implemented | `main.dashboard` |
| Create Group / Group Details / Add Member | ✅ Implemented | `main/routes.py` |
| Add Bill + 3 split modes | ✅ Implemented, tested | `utils/split.py` |
| Who-owes-whom | ✅ Implemented (debt simplification algorithm) | `utils/split.py::simplify_debts` |
| Bill History + search/filter | ✅ Implemented | `main.bill_history` |
| Reports (category + monthly charts) | ✅ Implemented (Chart.js) | `main.reports` |
| Notifications + reminders | ✅ Implemented | `models.Notification`, `main.send_reminder` |
| User Profile edit | ✅ Implemented | `main.profile` |
| Settings incl. Dark mode | ✅ Implemented | `main.settings`, CSS `data-theme` |
| Upload receipt + OCR amount extraction | ✅ Implemented (needs Tesseract binary installed) | `utils/ocr.py` |
| Categories (Food/Travel/Shopping/Rent) | ✅ Seeded by default | `models.Category.seed_defaults` |
| Export to PDF / Excel / CSV | ✅ Implemented | `main.export_bills` |
| UPI payment links (GPay/PhonePe/any UPI) | ✅ Implemented | `utils/payments.py::build_upi_link` |
| QR code payment | ✅ Implemented (client-side qrcode.js) | `templates/main/pay.html` |
| Credit/Debit card payment | ⚠️ UI present, backend stub | Needs Razorpay/Cashfree keys — see §6 |
| Admin: manage users/groups/delete/analytics | ✅ Implemented | `admin/routes.py` |
| Encrypted DB fields | ✅ Implemented | `utils/crypto.py` |
| Multiple groups | ✅ Supported natively (many-to-many) | `models.GroupMember` |
| Expense analytics/charts | ✅ Implemented | `main.reports` |
| Email notifications | ⚠️ Config present, sending not wired up | `config.py` MAIL_* — add Flask-Mail calls |
| Real-time updates (WebSockets) | ✅ **Implemented** — live notification push | `app/sockets.py`, `main.notify()`, `base.html` |
| Currency conversion | ⚠️ Currency field exists per-user; no live FX rate lookup | `models.User.currency` |
| Predict monthly expenses / AI receipt scanning / crypto payments / complex banking | ❌ Deliberately out of scope per your "avoid at the beginning" list | — |

---

## 5. Running the Project

```bash
# 1. Create a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Generate an encryption key and paste it into .env:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 4. (Optional) Load demo data — 4 users, 1 group, 1 bill
python seed_demo_data.py

# 5. Run
python run.py
# Visit http://localhost:5000
```

Demo logins (after step 4): `alex@smartbill.demo` / `password123` (also `sam@`, `priya@`), and `admin@smartbill.demo` / `admin1234` for the admin panel.

**OCR:** install the Tesseract binary separately for receipt scanning to work (`sudo apt-get install tesseract-ocr` on Ubuntu, `brew install tesseract` on macOS). Without it, the amount field simply stays manual.

---

---

## 6. Real-Time Notifications (WebSockets)

Implemented using **Flask-SocketIO**, entirely self-hosted — no external pub/sub service, no Redis, no third-party account needed.

**How it works:**
1. When a user logs in and any page loads, the browser opens a WebSocket connection (`app/templates/base.html`, using the Socket.IO CDN client).
2. `app/sockets.py` handles the `connect` event and puts that browser tab into a private room named `user_<their_id>` (via Flask-SocketIO's room system — Flask-Login's `current_user` is available inside socket handlers because the same session cookie is shared).
3. Whenever server code calls `notify(user_id, message, link)` (in `app/main/routes.py`) — e.g. when someone is added to a group, gets a bill share, receives a payment, or gets a reminder — it both saves a `Notification` row **and** immediately emits a `new_notification` event into that user's room:
   ```python
   socketio.emit("new_notification", {"id": n.id, "message": message, "link": link},
                 room=f"user_{user_id}")
   ```
4. If that user has a tab open, the bell badge count increments and a toast pops up in the corner **instantly**, with zero polling and no page refresh. If they're offline, the `Notification` row is still there waiting for them on the `/notifications` page next time they log in — the socket push is a live convenience layer on top of the same durable data model, not a replacement for it.

**Scaling note:** the current setup uses Flask-SocketIO's default in-process message queue, which is correct for a single server process (fine for development, a demo, or a small deployment). If you ever run multiple server processes/workers behind a load balancer, add a `message_queue` (Redis is the standard choice) so events emitted from one process reach sockets connected to another — one line change: `SocketIO(message_queue="redis://localhost:6379")`.

---

## 7. Connecting Real Payment/Auth Providers (currently stubbed)

- **Google Login:** create OAuth credentials at console.cloud.google.com → APIs & Services → Credentials → OAuth Client ID (type: Web). Add `http://localhost:5000/login/google/callback` as an authorized redirect URI. Put the client ID/secret in `.env`.
- **Real SMS OTP:** set `SMS_PROVIDER=twilio` in `.env` and fill `TWILIO_SID`, `TWILIO_TOKEN`, `TWILIO_FROM_NUMBER` (or adapt `utils/sms.py` similarly for MSG91/AWS SNS).
- **Card payments / hosted checkout:** sign up for Razorpay (or Cashfree/PayU), put `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` in `.env`. The integration point and commented example code already exist in `utils/payments.py::create_razorpay_link`.
- **UPI deep links work today with zero configuration** — they just build a standard `upi://pay?...` URI (per your Option 2), which GPay/PhonePe/Paytm all handle natively. Set `UPI_MERCHANT_VPA` in `.env` to your real UPI ID to receive real payments.

---

## 8. Security Notes
- Passwords: hashed with Werkzeug (PBKDF2), never stored or logged in plaintext.
- OTP codes: hashed, single-use, 5-minute expiry (configurable).
- PII (phone/email): encrypted at rest with a key kept outside the database.
- Admin routes: protected by both `@login_required` and an `@admin_required` decorator checking `User.is_admin`.
- File uploads: extension-restricted (`png/jpg/jpeg/webp/pdf`), size-capped at 8MB, filenames sanitized via `werkzeug.utils.secure_filename`.
- `SECRET_KEY` and `FIELD_ENCRYPTION_KEY` must be changed from the demo defaults before any real deployment — the defaults in `config.py` exist only so the project runs out-of-the-box for evaluation/demo purposes.

---

## 9. What Was Tested
Before delivery, the following were exercised end-to-end via Flask's test client: home/login/register/phone-OTP pages, login as a normal user and as an admin, dashboard, group creation with member invites, all three bill split types (equal/custom/percentage) with balance calculation, the "who owes whom" simplification, the pay flow (UPI link + QR + confirm), bill history filtering, CSV/Excel/PDF export, dark-mode toggle, notifications, and all admin pages (users, groups, deactivate/delete) — all returned correct responses and rendered expected content. Invalid input (e.g. a custom split that doesn't sum to the total) was confirmed to fail gracefully with a flash message rather than crashing. The WebSocket layer was separately verified with `flask_socketio.test_client`: a simulated user connected and joined their private room, another user added them to a group, and their socket received the `new_notification` event immediately — confirming the live-push path (not just the DB fallback) actually works.

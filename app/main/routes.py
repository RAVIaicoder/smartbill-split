import os
import csv
import io
from datetime import datetime, date

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash,
    send_file, jsonify, current_app
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app.extensions import db, socketio
from app.models import (
    User, Group, GroupMember, Bill, BillItem, BillShare,
    Payment, Category, Notification
)
from app.utils.split import split_equal, split_custom, split_percentage, compute_balances, simplify_debts
from app.utils.payments import build_upi_link, create_razorpay_link
from app.utils.ocr import scan_receipt

main_bp = Blueprint("main", __name__)


def notify(user_id, message, link=""):
    """
    Create a notification row AND push it live over WebSocket to that
    user's browser (if they have a tab open) so the bell badge updates
    instantly without a page refresh or polling.
    """
    n = Notification(user_id=user_id, message=message, link=link)
    db.session.add(n)
    db.session.flush()  # assigns n.id without committing the outer transaction
    socketio.emit(
        "new_notification",
        {"id": n.id, "message": message, "link": link},
        room=f"user_{user_id}",
    )
    return n


def user_groups():
    return [gm.group for gm in current_user.memberships]


# ---------------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------------
@main_bp.route("/dashboard")
@login_required
def dashboard():
    groups = user_groups()

    # Build all bills across the user's groups to compute balances
    bills_data = []
    all_shares = BillShare.query.filter_by(user_id=current_user.id).all()

    total_owed = sum(s.amount for s in all_shares if not s.is_paid and s.bill.paid_by_id != current_user.id)
    total_to_receive = 0.0
    for group in groups:
        for bill in group.bills:
            if bill.paid_by_id == current_user.id:
                total_to_receive += sum(
                    s.amount for s in bill.shares if not s.is_paid and s.user_id != current_user.id
                )
            bills_data.append({
                "paid_by": bill.paid_by_id,
                "shares": {s.user_id: s.amount for s in bill.shares},
            })

    total_expenses = sum(b.total_amount for g in groups for b in g.bills)

    recent_bills = (
        Bill.query.join(Group).join(GroupMember, GroupMember.group_id == Group.id)
        .filter(GroupMember.user_id == current_user.id)
        .order_by(Bill.created_at.desc()).limit(6).all()
    )

    net_balances = compute_balances(bills_data)
    my_net = net_balances.get(current_user.id, 0.0)

    return render_template(
        "main/dashboard.html",
        groups=groups,
        total_owed=round(total_owed, 2),
        total_to_receive=round(total_to_receive, 2),
        total_expenses=round(total_expenses, 2),
        my_net=round(my_net, 2),
        recent_bills=recent_bills,
        pending_bills_count=current_user.pending_bills_count(),
    )


# ---------------------------------------------------------------------------
# GROUPS
# ---------------------------------------------------------------------------
@main_bp.route("/groups/create", methods=["GET", "POST"])
@login_required
def create_group():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        member_inputs = [m.strip() for m in request.form.get("members", "").split(",") if m.strip()]

        if not name:
            flash("Group name is required.", "danger")
            return redirect(url_for("main.create_group"))

        group = Group(name=name, description=description, created_by_id=current_user.id)
        db.session.add(group)
        db.session.flush()

        db.session.add(GroupMember(group_id=group.id, user_id=current_user.id, role="admin"))

        added, not_found = [], []
        for identifier in member_inputs:
            found = None
            for u in User.query.filter(User.email_enc.isnot(None)).all():
                if u.email and u.email.lower() == identifier.lower():
                    found = u
                    break
            if not found:
                for u in User.query.filter(User.phone_enc.isnot(None)).all():
                    if u.phone == identifier:
                        found = u
                        break
            if found and found.id != current_user.id:
                db.session.add(GroupMember(group_id=group.id, user_id=found.id))
                notify(found.id, f"{current_user.name} added you to group '{name}'", url_for("main.group_details", group_id=group.id))
                added.append(identifier)
            elif found is None:
                not_found.append(identifier)

        db.session.commit()

        if not_found:
            flash(f"Group created. Couldn't find accounts for: {', '.join(not_found)} (they need to register first).", "warning")
        else:
            flash("Group created successfully!", "success")
        return redirect(url_for("main.group_details", group_id=group.id))

    return render_template("main/create_group.html")


@main_bp.route("/groups/<int:group_id>")
@login_required
def group_details(group_id):
    group = Group.query.get_or_404(group_id)
    member_ids = [gm.user_id for gm in group.members]
    if current_user.id not in member_ids:
        flash("You are not a member of this group.", "danger")
        return redirect(url_for("main.dashboard"))

    bills_data = [{"paid_by": b.paid_by_id, "shares": {s.user_id: s.amount for s in b.shares}} for b in group.bills]
    net_balances = compute_balances(bills_data)
    transactions = simplify_debts(net_balances)

    members = [gm.user for gm in group.members]
    member_lookup = {u.id: u for u in members}

    return render_template(
        "main/group_details.html",
        group=group,
        members=members,
        transactions=transactions,
        member_lookup=member_lookup,
        net_balances=net_balances,
        bills=sorted(group.bills, key=lambda b: b.created_at, reverse=True),
    )


@main_bp.route("/groups/<int:group_id>/add_member", methods=["POST"])
@login_required
def add_group_member(group_id):
    group = Group.query.get_or_404(group_id)
    identifier = request.form.get("identifier", "").strip()

    found = None
    for u in User.query.filter(User.email_enc.isnot(None)).all():
        if u.email and u.email.lower() == identifier.lower():
            found = u
            break
    if not found:
        for u in User.query.filter(User.phone_enc.isnot(None)).all():
            if u.phone == identifier:
                found = u
                break

    if not found:
        flash("No SmartBill account found with that email/phone.", "warning")
    elif found.id in [gm.user_id for gm in group.members]:
        flash("That user is already in the group.", "info")
    else:
        db.session.add(GroupMember(group_id=group.id, user_id=found.id))
        notify(found.id, f"{current_user.name} added you to group '{group.name}'", url_for("main.group_details", group_id=group.id))
        db.session.commit()
        flash(f"{found.name} added to the group.", "success")

    return redirect(url_for("main.group_details", group_id=group_id))


# ---------------------------------------------------------------------------
# ADD BILL (with split logic + optional receipt OCR)
# ---------------------------------------------------------------------------
def _allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


@main_bp.route("/groups/<int:group_id>/bills/add", methods=["GET", "POST"])
@login_required
def add_bill(group_id):
    group = Group.query.get_or_404(group_id)
    members = [gm.user for gm in group.members]
    categories = Category.query.all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        total_amount = float(request.form.get("total_amount", 0) or 0)
        category_id = request.form.get("category_id") or None
        paid_by_id = int(request.form.get("paid_by_id"))
        bill_date_str = request.form.get("bill_date") or date.today().isoformat()
        split_type = request.form.get("split_type", "equal")
        participant_ids = [int(x) for x in request.form.getlist("participants")]

        if not name or total_amount <= 0 or not participant_ids:
            flash("Bill name, a positive amount, and at least one participant are required.", "danger")
            return redirect(url_for("main.add_bill", group_id=group_id))

        try:
            if split_type == "equal":
                shares = split_equal(total_amount, participant_ids)
            elif split_type == "custom":
                custom = {int(uid): float(request.form.get(f"custom_{uid}", 0) or 0) for uid in participant_ids}
                shares = split_custom(total_amount, custom)
            elif split_type == "percentage":
                pct = {int(uid): float(request.form.get(f"pct_{uid}", 0) or 0) for uid in participant_ids}
                shares = split_percentage(total_amount, pct)
            else:
                flash("Unknown split type.", "danger")
                return redirect(url_for("main.add_bill", group_id=group_id))
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("main.add_bill", group_id=group_id))

        # optional receipt upload
        receipt_filename = ""
        file = request.files.get("receipt")
        if file and file.filename and _allowed_file(file.filename):
            receipt_filename = secure_filename(f"{group_id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
            file.save(os.path.join(current_app.config["UPLOAD_FOLDER"], receipt_filename))

        bill = Bill(
            group_id=group.id, name=name, total_amount=total_amount,
            category_id=category_id, paid_by_id=paid_by_id,
            split_type=split_type, receipt_image=receipt_filename,
            bill_date=datetime.strptime(bill_date_str, "%Y-%m-%d").date(),
        )
        db.session.add(bill)
        db.session.flush()

        for uid, amt in shares.items():
            is_paid = (uid == paid_by_id)  # the payer already covered their own share
            db.session.add(BillShare(bill_id=bill.id, user_id=uid, amount=amt, is_paid=is_paid))
            if uid != paid_by_id:
                notify(uid, f"You owe ₹{amt:.2f} for '{name}' in {group.name}", url_for("main.group_details", group_id=group.id))

        db.session.commit()
        flash("Bill added and split successfully!", "success")
        return redirect(url_for("main.group_details", group_id=group.id))

    return render_template("main/add_bill.html", group=group, members=members, categories=categories, today=date.today().isoformat())


@main_bp.route("/ocr/scan", methods=["POST"])
@login_required
def ocr_scan():
    """AJAX endpoint: upload a receipt image, get back a guessed total amount."""
    file = request.files.get("receipt")
    if not file or not file.filename or not _allowed_file(file.filename):
        return jsonify({"ok": False, "error": "Invalid or missing file."}), 400

    tmp_name = secure_filename(f"ocr_tmp_{int(datetime.utcnow().timestamp())}_{file.filename}")
    tmp_path = os.path.join(current_app.config["UPLOAD_FOLDER"], tmp_name)
    file.save(tmp_path)

    result = scan_receipt(tmp_path)
    if not result["ocr_available"]:
        result["error"] = "Tesseract OCR isn't installed on this server - enter the amount manually. See README for setup."
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# BILL HISTORY (search + filter)
# ---------------------------------------------------------------------------
@main_bp.route("/bills/history")
@login_required
def bill_history():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    date_from = request.args.get("from")
    date_to = request.args.get("to")

    query = (
        Bill.query.join(Group).join(GroupMember, GroupMember.group_id == Group.id)
        .filter(GroupMember.user_id == current_user.id)
    )
    if q:
        query = query.filter(Bill.name.ilike(f"%{q}%"))
    if category_id:
        query = query.filter(Bill.category_id == category_id)
    if date_from:
        query = query.filter(Bill.bill_date >= datetime.strptime(date_from, "%Y-%m-%d").date())
    if date_to:
        query = query.filter(Bill.bill_date <= datetime.strptime(date_to, "%Y-%m-%d").date())

    bills = query.order_by(Bill.bill_date.desc()).all()
    categories = Category.query.all()

    return render_template(
        "main/bill_history.html", bills=bills, categories=categories,
        q=q, category_id=category_id, date_from=date_from, date_to=date_to,
    )


@main_bp.route("/bills/export/<fmt>")
@login_required
def export_bills(fmt):
    bills = (
        Bill.query.join(Group).join(GroupMember, GroupMember.group_id == Group.id)
        .filter(GroupMember.user_id == current_user.id)
        .order_by(Bill.bill_date.desc()).all()
    )

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Bill", "Group", "Category", "Amount", "Paid By", "Date", "Split Type"])
        for b in bills:
            writer.writerow([b.name, b.group.name, b.category.name if b.category else "", b.total_amount, b.paid_by.name, b.bill_date, b.split_type])
        mem = io.BytesIO(buf.getvalue().encode())
        return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="smartbill_bills.csv")

    elif fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Bills"
        ws.append(["Bill", "Group", "Category", "Amount", "Paid By", "Date", "Split Type"])
        for b in bills:
            ws.append([b.name, b.group.name, b.category.name if b.category else "", b.total_amount, b.paid_by.name, str(b.bill_date), b.split_type])
        mem = io.BytesIO()
        wb.save(mem)
        mem.seek(0)
        return send_file(mem, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          as_attachment=True, download_name="smartbill_bills.xlsx")

    elif fmt == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
        from reportlab.lib.styles import getSampleStyleSheet

        mem = io.BytesIO()
        doc = SimpleDocTemplate(mem, pagesize=A4)
        styles = getSampleStyleSheet()
        data = [["Bill", "Group", "Category", "Amount", "Paid By", "Date"]]
        for b in bills:
            data.append([b.name, b.group.name, b.category.name if b.category else "-", f"₹{b.total_amount:.2f}", b.paid_by.name, str(b.bill_date)])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4C7EFF")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        doc.build([Paragraph("SmartBill Split - Bill History", styles["Title"]), table])
        mem.seek(0)
        return send_file(mem, mimetype="application/pdf", as_attachment=True, download_name="smartbill_bills.pdf")

    flash("Unknown export format.", "danger")
    return redirect(url_for("main.bill_history"))


# ---------------------------------------------------------------------------
# PAYMENTS
# ---------------------------------------------------------------------------
@main_bp.route("/pay/<int:bill_id>/<int:share_user_id>", methods=["GET", "POST"])
@login_required
def pay_bill_share(bill_id, share_user_id):
    bill = Bill.query.get_or_404(bill_id)
    share = BillShare.query.filter_by(bill_id=bill_id, user_id=share_user_id).first_or_404()

    if request.method == "POST":
        method = request.form.get("method", "upi")
        payment = Payment(
            bill_id=bill.id, payer_id=share_user_id, payee_id=bill.paid_by_id,
            amount=share.amount, method=method, status="initiated",
        )
        if method in ("upi", "gpay", "phonepe"):
            note = f"SmartBill-{bill.name}"[:40]
            payment.upi_link = build_upi_link(share.amount, note, payee_name=bill.paid_by.name)
        db.session.add(payment)
        db.session.commit()
        return redirect(url_for("main.payment_page", payment_id=payment.id))

    razorpay_info = create_razorpay_link(share.amount, f"Payment for {bill.name}")
    upi_link = build_upi_link(share.amount, f"SmartBill-{bill.name}"[:40], payee_name=bill.paid_by.name)

    return render_template(
        "main/pay.html", bill=bill, share=share, upi_link=upi_link, razorpay_info=razorpay_info,
    )


@main_bp.route("/payment/<int:payment_id>")
@login_required
def payment_page(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    return render_template("main/payment_status.html", payment=payment)


@main_bp.route("/payment/<int:payment_id>/confirm", methods=["POST"])
@login_required
def confirm_payment(payment_id):
    """
    Demo confirmation step. In production this would be a webhook from the
    payment gateway (Razorpay/Cashfree) verified by signature - never
    trusted directly from the browser.
    """
    payment = Payment.query.get_or_404(payment_id)
    payment.status = "success"
    share = BillShare.query.filter_by(bill_id=payment.bill_id, user_id=payment.payer_id).first()
    if share:
        share.is_paid = True
        share.paid_at = datetime.utcnow()
        notify(payment.payee_id, f"{payment.payer.name} paid ₹{payment.amount:.2f} for '{payment.bill.name}'")
    db.session.commit()
    flash("Payment marked as completed!", "success")
    return redirect(url_for("main.group_details", group_id=payment.bill.group_id))


# ---------------------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------------------
@main_bp.route("/reports")
@login_required
def reports():
    groups = user_groups()
    bills = [b for g in groups for b in g.bills]

    by_category = {}
    for b in bills:
        cat = b.category.name if b.category else "Other"
        by_category[cat] = by_category.get(cat, 0) + b.total_amount

    by_month = {}
    for b in bills:
        key = b.bill_date.strftime("%Y-%m")
        by_month[key] = by_month.get(key, 0) + b.total_amount
    by_month = dict(sorted(by_month.items()))

    return render_template(
        "main/reports.html",
        category_labels=list(by_category.keys()),
        category_values=[round(v, 2) for v in by_category.values()],
        month_labels=list(by_month.keys()),
        month_values=[round(v, 2) for v in by_month.values()],
        total_expenses=round(sum(by_category.values()), 2),
    )


# ---------------------------------------------------------------------------
# PROFILE / SETTINGS
# ---------------------------------------------------------------------------
@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.name = request.form.get("name", current_user.name).strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if email:
            current_user.email = email
        if phone:
            current_user.phone = phone
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))

    return render_template("main/profile.html")


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        current_user.dark_mode = request.form.get("dark_mode") == "on"
        current_user.currency = request.form.get("currency", current_user.currency)
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("main.settings"))
    return render_template("main/settings.html")


@main_bp.route("/settings/toggle-theme", methods=["POST"])
@login_required
def toggle_theme():
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    return jsonify({"dark_mode": current_user.dark_mode})


# ---------------------------------------------------------------------------
# NOTIFICATIONS
# ---------------------------------------------------------------------------
@main_bp.route("/notifications")
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for n in items:
        n.is_read = True
    db.session.commit()
    return render_template("main/notifications.html", notifications=items)


@main_bp.route("/notifications/remind/<int:group_id>/<int:user_id>", methods=["POST"])
@login_required
def send_reminder(group_id, user_id):
    group = Group.query.get_or_404(group_id)
    notify(user_id, f"{current_user.name} sent you a reminder to settle up in '{group.name}'.", url_for("main.group_details", group_id=group_id))
    db.session.commit()
    flash("Reminder sent.", "success")
    return redirect(url_for("main.group_details", group_id=group_id))

from functools import wraps
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models import User, Group, Bill, Payment

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@admin_bp.route("/")
@login_required
@admin_required
def dashboard():
    total_users = User.query.count()
    total_groups = Group.query.count()
    total_bills = Bill.query.count()
    total_payment_volume = round(sum(p.amount for p in Payment.query.filter_by(status="success").all()), 2)

    active_cutoff = datetime.utcnow() - timedelta(days=7)
    active_users = User.query.filter(User.last_login_at >= active_cutoff).count()

    return render_template(
        "admin/dashboard.html",
        total_users=total_users, total_groups=total_groups, total_bills=total_bills,
        total_payment_volume=total_payment_volume, active_users=active_users,
    )


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@login_required
@admin_required
def deactivate_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active_account = not user.is_active_account
    db.session.commit()
    flash(f"{user.name} {'deactivated' if not user.is_active_account else 'reactivated'}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own admin account.", "danger")
        return redirect(url_for("admin.users"))
    db.session.delete(user)
    db.session.commit()
    flash("Account deleted.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/groups")
@login_required
@admin_required
def groups():
    all_groups = Group.query.order_by(Group.created_at.desc()).all()
    return render_template("admin/groups.html", groups=all_groups)

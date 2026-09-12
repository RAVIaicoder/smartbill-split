"""
Run once to populate the database with demo users/groups/bills so you can
explore the app immediately: `python seed_demo_data.py`
"""
from datetime import date
from app import create_app
from app.extensions import db
from app.models import User, Group, GroupMember, Bill, BillShare, Category
from app.utils.split import split_equal

app = create_app()

with app.app_context():
    Category.seed_defaults()

    def get_or_create_user(name, email, password, is_admin=False):
        for u in User.query.filter(User.email_enc.isnot(None)).all():
            if u.email == email:
                return u
        u = User(name=name, is_admin=is_admin, auth_provider="password")
        u.email = email
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u

    admin = get_or_create_user("Admin", "admin@smartbill.demo", "admin1234", is_admin=True)
    alex = get_or_create_user("Alex Kumar", "alex@smartbill.demo", "password123")
    sam = get_or_create_user("Sam Rao", "sam@smartbill.demo", "password123")
    priya = get_or_create_user("Priya Singh", "priya@smartbill.demo", "password123")

    group = Group.query.filter_by(name="Goa Trip 2026").first()
    if not group:
        group = Group(name="Goa Trip 2026", description="Weekend getaway", created_by_id=alex.id)
        db.session.add(group)
        db.session.flush()
        for u, role in [(alex, "admin"), (sam, "member"), (priya, "member")]:
            db.session.add(GroupMember(group_id=group.id, user_id=u.id, role=role))
        db.session.commit()

        food_cat = Category.query.filter_by(name="Food").first()
        bill = Bill(
            group_id=group.id, name="Beach Shack Dinner", total_amount=1800.0,
            category_id=food_cat.id, paid_by_id=alex.id, split_type="equal",
            bill_date=date.today(),
        )
        db.session.add(bill)
        db.session.flush()

        shares = split_equal(1800.0, [alex.id, sam.id, priya.id])
        for uid, amt in shares.items():
            db.session.add(BillShare(bill_id=bill.id, user_id=uid, amount=amt, is_paid=(uid == alex.id)))
        db.session.commit()

    print("Demo data ready!")
    print("Login as: admin@smartbill.demo / admin1234  (admin)")
    print("       or: alex@smartbill.demo / password123")
    print("       or: sam@smartbill.demo  / password123")
    print("       or: priya@smartbill.demo/ password123")

import os
from flask import Flask
from sqlalchemy import event
from config import Config
from app.extensions import db, login_manager, migrate, socketio


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(os.path.join(app.instance_path), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app)

    from app import sockets  # noqa: F401 - registers @socketio.on handlers

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Blueprints
    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.admin.routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Jinja helper: unread notification count in every template
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.models import Notification
        unread = 0
        if current_user.is_authenticated:
            unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return {"app_name": "SmartBill Split", "unread_count": unread}

    with app.app_context():
        event.listen(db.engine, "connect", lambda conn, rec: (conn.execute("PRAGMA journal_mode=WAL"), conn.execute("PRAGMA busy_timeout=15000")))
        db.create_all()
        from app.models import Category
        Category.seed_defaults()

    return app

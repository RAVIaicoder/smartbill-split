"""
WebSocket event handlers for live notifications.

Each logged-in user's browser tab joins a private room named
`user_<id>` as soon as it connects. When something notification-worthy
happens server-side (added to a group, a bill share created, a payment
received, a reminder sent), `app/main/routes.py::notify()` emits a
`new_notification` event straight into that room — so the bell icon and
badge count update instantly in every open tab, with no page refresh and
no polling.

No external service is required: this runs entirely inside the Flask
process using Flask-SocketIO's built-in room system.
"""

from flask_login import current_user
from flask_socketio import join_room, leave_room

from app.extensions import socketio


@socketio.on("connect")
def handle_connect():
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")


@socketio.on("disconnect")
def handle_disconnect():
    if current_user.is_authenticated:
        leave_room(f"user_{current_user.id}")

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # socketio.run enables the WebSocket layer (used for live notification
    # badges). Falls back gracefully to plain HTTP if eventlet/gevent
    # aren't installed - see README "Real-time updates" section.
    socketio.run(app, debug=False, host="0.0.0.0", port=5000)

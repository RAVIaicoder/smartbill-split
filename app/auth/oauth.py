from authlib.integrations.flask_client import OAuth
from flask import current_app

_oauth = OAuth()
_registered = False


def oauth_client():
    global _registered
    if not _registered:
        _oauth.init_app(current_app)
        _oauth.register(
            name="google",
            client_id=current_app.config["GOOGLE_CLIENT_ID"],
            client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=current_app.config["GOOGLE_DISCOVERY_URL"],
            client_kwargs={"scope": "openid email profile"},
        )
        _registered = True
    return _oauth.google

from flask import Flask, session, url_for

from .routes import main_bp
from .rooms import get_room


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object("worldcup26.config.Config")
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_navigation():
        active_rooms = []
        memberships = session.get("memberships", {})
        for code, membership in memberships.items():
            room = get_room(code)
            if room is None:
                continue
            active_rooms.append(
                {
                    "label": f"Room {code}",
                    "href": url_for("main.room", code=code),
                    "meta": membership.get("name", ""),
                }
            )
        return {"active_rooms": active_rooms}

    return app

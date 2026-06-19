from flask import Flask, session, url_for

from .africaweather_rooms import get_room as get_africaweather_room
from .africaweather_routes import aw_bp
from .routes import main_bp
from .rooms import get_room


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object("worldcup26.config.Config")
    app.register_blueprint(main_bp)
    app.register_blueprint(aw_bp)

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

        active_aw_rooms = []
        aw_memberships = session.get("aw_memberships", {})
        for code, membership in aw_memberships.items():
            room = get_africaweather_room(code)
            if room is None:
                continue
            active_aw_rooms.append(
                {
                    "label": membership.get("team_name", f"Room {code}"),
                    "href": url_for("africaweather.room", code=code),
                    "meta": room.get("name", code),
                }
            )

        return {"active_rooms": active_rooms, "active_aw_rooms": active_aw_rooms}

    return app

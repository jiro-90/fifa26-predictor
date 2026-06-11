from flask import Flask

from .routes import main_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object("worldcup26.config.Config")
    app.register_blueprint(main_bp)
    return app

"""Flask entry point for the AI News Podcast app."""
import logging

from flask import Flask, jsonify, render_template

from config.config import Config
from routes.audio import audio_bp
from routes.episode import episode_bp
from routes.news import news_bp
from routes.search import search_bp


def create_app() -> Flask:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.SECRET_KEY

    app.register_blueprint(search_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(episode_bp)
    app.register_blueprint(audio_bp)

    @app.get("/")
    def index():
        return render_template("index.html", languages=Config.SUPPORTED_LANGUAGES)

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)

"""Flask app factory."""

import os
from flask import Flask

from src.config import Config


def create_app():
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "../frontend/templates")
    )
    app.secret_key = Config.SECRET_KEY
    
    # Register blueprints
    from src.backend.routes import main, graph, api, workers, insights, stats
    
    app.register_blueprint(main.bp)
    app.register_blueprint(graph.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(workers.bp)
    app.register_blueprint(insights.bp)
    app.register_blueprint(stats.bp)
    
    return app

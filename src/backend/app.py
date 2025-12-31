"""Flask app factory."""

import os
from flask import Flask

from src.config import Config


def create_app():
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "../frontend/templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "../frontend/static"),
        static_url_path='/static'
    )
    app.secret_key = Config.SECRET_KEY
    
    # Register blueprints
    from src.backend.routes import main, graph, api, workers, insights, stats, bellwethers, investibles, prompts, options
    
    app.register_blueprint(main.bp)
    app.register_blueprint(graph.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(workers.bp)
    app.register_blueprint(insights.bp)
    app.register_blueprint(stats.bp)
    app.register_blueprint(bellwethers.bp)
    app.register_blueprint(investibles.bp)
    app.register_blueprint(prompts.bp)
    app.register_blueprint(options.bp)
    
    return app

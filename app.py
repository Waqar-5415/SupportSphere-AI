"""SupportSphere AI - AI-powered customer support platform (Flask)."""
import json
import os
import secrets
from datetime import timedelta

from flask import Flask, g, jsonify, render_template, request
from markupsafe import Markup, escape

import ai
import api
import auth
import pages
from db import CATEGORIES, PRIORITIES, STATUSES, close_db, get_db, init_db
from icons import ICONS, icon

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:  # pragma: no cover
    pass


def load_secret_key(instance_path):
    configured = os.getenv("SECRET_KEY", "").strip()
    if configured and not configured.startswith("change-me"):
        return configured
    path = os.path.join(instance_path, "secret.key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


def create_app(test_config=None):
    app = Flask(__name__, instance_path=os.path.join(BASE_DIR, "instance"))
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.from_mapping(
        DATABASE=os.path.join(app.instance_path, "supportsphere.db"),
        GROQ_API_KEY=os.getenv("GROQ_API_KEY", ""),
        GROQ_MODEL=os.getenv("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b,openai/gpt-oss-20b",
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY", ""),
        GEMINI_MODEL=os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.8-flash,gemini-3.6-flash,gemini-2.5-flash",
        ADMIN_NAME=os.getenv("ADMIN_NAME", "Administrator"),
        ADMIN_EMAIL=os.getenv("ADMIN_EMAIL", "admin@supportsphere.ai"),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", "Admin@12345"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        MAX_CONTENT_LENGTH=256 * 1024,
        CSRF_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("SECRET_KEY", None)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = load_secret_key(app.instance_path)

    app.teardown_appcontext(close_db)
    init_db(app)

    # ------------------------------------------------------------ jinja helpers
    app.jinja_env.globals.update(icon=icon, csrf_token=auth.csrf_token)
    app.jinja_env.filters["ref"] = lambda i: f"SS-{int(i):04d}"

    @app.template_filter("localtime")
    def localtime(iso, fmt="full"):
        if not iso:
            return ""
        fallback = str(iso).replace("T", " ")[:16] + " UTC"
        return Markup(f'<time datetime="{escape(iso)}" data-local data-fmt="{escape(fmt)}">{escape(fallback)}</time>')

    @app.template_filter("initials")
    def initials(name):
        parts = [p for p in str(name or "?").split() if p]
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    @app.template_filter("hue")
    def hue(name):
        return sum(ord(c) for c in str(name)) * 37 % 360

    @app.context_processor
    def inject_globals():
        user = getattr(g, "user", None)
        unread = 0
        if user is not None:
            unread = get_db().execute(
                "SELECT COUNT(*) FROM tickets WHERE user_id = ? AND user_unread = 1", (user["id"],)
            ).fetchone()[0]
        return {
            "current_user": user,
            "unread_count": unread,
            "providers": ai.providers(app.config),
            "icons_json": ICONS,
            "categories": CATEGORIES,
            "priorities": PRIORITIES,
            "statuses": STATUSES,
        }

    # ------------------------------------------------------------ request hooks
    app.before_request(auth.load_user)
    app.before_request(auth.check_csrf)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/") or (getattr(g, "user", None) is not None):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    app.register_blueprint(auth.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(api.bp)

    # ------------------------------------------------------------ errors
    def error_response(code, title, message):
        if request.path.startswith("/api/"):
            return jsonify(error=message), code
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(404)
    def not_found(_e):
        return error_response(404, "Page not found", "We couldn't find what you were looking for.")

    @app.errorhandler(405)
    def not_allowed(_e):
        return error_response(405, "Not allowed", "That action is not available here.")

    @app.errorhandler(413)
    def too_large(_e):
        return error_response(413, "Request too large", "That request is too large.")

    @app.errorhandler(500)
    def server_error(_e):
        return error_response(500, "Something went wrong", "Something went wrong on our side. Please try again.")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    status = ", ".join(f"{p['label']}: {'connected' if p['configured'] else 'no key'}" for p in ai.providers(app.config))
    print(f"\n  SupportSphere AI running at http://127.0.0.1:{port}   [{status}]\n")
    if debug:
        app.run(host="127.0.0.1", port=port, debug=True)
    else:
        try:
            from waitress import serve

            serve(app, host="127.0.0.1", port=port, threads=8)
        except ImportError:
            app.run(host="127.0.0.1", port=port)

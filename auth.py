"""Authentication, sessions, CSRF protection and access-control decorators."""
import functools
import hmac
import re
import secrets
import time
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db, now_iso

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_FAILS = 5
WINDOW_SECONDS = 600
_FAILS = {}


def reset_rate_limits():
    _FAILS.clear()


def _recent_fails(key):
    cutoff = time.time() - WINDOW_SECONDS
    _FAILS[key] = [t for t in _FAILS.get(key, []) if t > cutoff]
    return _FAILS[key]


def valid_password(password):
    """Return an error message, or None when the password is acceptable."""
    if len(password) < 8:
        return "Your password must be at least 8 characters long."
    if len(password) > 128:
        return "Your password must be 128 characters or fewer."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Your password must contain at least one letter and one number."
    return None


# ------------------------------------------------------------------------------ CSRF
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if not current_app.config.get("CSRF_ENABLED", True):
        return None
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    expected = session.get("csrf", "")
    if not expected or not hmac.compare_digest(sent, expected):
        if request.path.startswith("/api/"):
            return jsonify(error="Your session expired. Please refresh the page and try again."), 400
        flash("Your session expired. Please try again.", "error")
        return redirect(url_for("pages.landing"))
    return None


# ------------------------------------------------------------------------------ current user
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if row and row["is_active"]:
            g.user = row
        else:
            session.pop("uid", None)


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in to continue."), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return jsonify(error="Please sign in to continue."), 401
            return redirect(url_for("auth.login", next=request.path))
        if g.user["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify(error="You do not have permission to do that."), 403
            return render_template("error.html", code=403, title="Access denied",
                                   message="This area is only available to administrators."), 403
        return view(*args, **kwargs)

    return wrapped


def safe_next(target):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def home_for(user):
    return url_for("pages.admin_overview") if user["role"] == "admin" else url_for("pages.dashboard")


# ------------------------------------------------------------------------------ routes
@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))
    error, email = None, ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = (email, request.remote_addr)
        if len(_recent_fails(key)) >= MAX_FAILS:
            error = "Too many failed attempts. Please wait a few minutes and try again."
        else:
            row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row and check_password_hash(row["password_hash"], password):
                if not row["is_active"]:
                    error = "This account has been deactivated. Please contact an administrator."
                else:
                    _FAILS.pop(key, None)
                    session.clear()
                    session["uid"] = row["id"]
                    session.permanent = bool(request.form.get("remember"))
                    db = get_db()
                    db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso(), row["id"]))
                    db.commit()
                    return redirect(safe_next(request.values.get("next")) or home_for(row))
            else:
                _recent_fails(key).append(time.time())
                error = "Incorrect email or password."
    return render_template("login.html", error=error, email=email, next=request.args.get("next", ""))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(home_for(g.user))
    errors, form = {}, {"name": "", "email": ""}
    if request.method == "POST":
        name = " ".join(request.form.get("name", "").split())
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        form = {"name": name, "email": email}
        if not 2 <= len(name) <= 60:
            errors["name"] = "Please enter your name (2 to 60 characters)."
        if not EMAIL_RE.match(email) or len(email) > 120:
            errors["email"] = "Please enter a valid email address, for example name@example.com."
        pw_error = valid_password(password)
        if pw_error:
            errors["password"] = pw_error
        elif password != confirm:
            errors["confirm"] = "The two passwords do not match."
        db = get_db()
        if "email" not in errors and db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            errors["email"] = "An account with this email already exists. Try signing in instead."
        if not errors:
            cur = db.execute(
                "INSERT INTO users (name, email, password_hash, role, created_at, last_login) VALUES (?, ?, ?, 'user', ?, ?)",
                (name, email, generate_password_hash(password), now_iso(), now_iso()),
            )
            db.commit()
            session.clear()
            session["uid"] = cur.lastrowid
            flash(f"Welcome to SupportSphere AI, {name.split(' ')[0]}!", "success")
            return redirect(url_for("pages.dashboard"))
    return render_template("register.html", errors=errors, form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("pages.landing"))

"""HTML pages: public landing, user application, admin console."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, g, render_template, request

import ai
from auth import admin_required, login_required
from db import CATEGORIES, PRIORITIES, STATUSES, TEXT_SIZES, THEMES, get_db

bp = Blueprint("pages", __name__)
PER_PAGE = 12


def first_faq_per_category():
    return get_db().execute(
        "SELECT * FROM faqs WHERE id IN (SELECT MIN(id) FROM faqs GROUP BY category) ORDER BY id"
    ).fetchall()


# ======================================================================== public
@bp.route("/")
def landing():
    return render_template("landing.html", faqs=first_faq_per_category())


@bp.route("/healthz")
def healthz():
    return {"status": "ok"}


# ======================================================================== user application
@bp.route("/app")
@login_required
def dashboard():
    db, uid = get_db(), g.user["id"]
    counts = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) AS n FROM tickets WHERE user_id = ? GROUP BY status", (uid,)):
        counts[r["status"]] = r["n"]
    recent = db.execute("SELECT * FROM tickets WHERE user_id = ? ORDER BY updated_at DESC LIMIT 4", (uid,)).fetchall()
    chats = db.execute(
        "SELECT id, title, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT 4", (uid,)
    ).fetchall()
    chat_total = db.execute("SELECT COUNT(*) FROM conversations WHERE user_id = ?", (uid,)).fetchone()[0]
    return render_template("dashboard.html", counts=counts, recent=recent, chats=chats,
                           chat_total=chat_total, popular=first_faq_per_category())


@bp.route("/app/chat")
@bp.route("/app/chat/<int:cid>", endpoint="chat_conv")
@login_required
def chat(cid=None):
    if cid is not None:
        row = get_db().execute("SELECT 1 FROM conversations WHERE id = ? AND user_id = ?", (cid, g.user["id"])).fetchone()
        if not row:
            abort(404)
    return render_template("chat.html", conv_id=cid or 0)


@bp.route("/app/help")
@login_required
def help_centre():
    return render_template("help.html")


@bp.route("/app/tickets")
@login_required
def tickets():
    db, uid = get_db(), g.user["id"]
    status = request.args.get("status", "")
    counts = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) AS n FROM tickets WHERE user_id = ? GROUP BY status", (uid,)):
        counts[r["status"]] = r["n"]
    sql, args = (
        "SELECT t.*, (SELECT COUNT(*) FROM ticket_replies r WHERE r.ticket_id = t.id) AS reply_count "
        "FROM tickets t WHERE t.user_id = ?", [uid],
    )
    if status in STATUSES:
        sql += " AND t.status = ?"
        args.append(status)
    rows = db.execute(sql + " ORDER BY t.updated_at DESC", args).fetchall()
    return render_template("tickets.html", tickets=rows, counts=counts, total=sum(counts.values()), current=status)


@bp.route("/app/tickets/<int:tid>")
@login_required
def ticket_detail(tid):
    db = get_db()
    ticket = db.execute("SELECT * FROM tickets WHERE id = ? AND user_id = ?", (tid, g.user["id"])).fetchone()
    if not ticket:
        abort(404)
    if ticket["user_unread"]:
        db.execute("UPDATE tickets SET user_unread = 0 WHERE id = ?", (tid,))
        db.commit()
    replies = db.execute(
        "SELECT r.*, u.name AS author_name FROM ticket_replies r LEFT JOIN users u ON u.id = r.author_id "
        "WHERE r.ticket_id = ? ORDER BY r.id", (tid,),
    ).fetchall()
    return render_template("ticket_detail.html", ticket=ticket, replies=replies)


@bp.route("/app/settings")
@login_required
def settings():
    return render_template("settings.html", themes=THEMES, text_sizes=TEXT_SIZES)


# ======================================================================== admin console
def _last_days(n=7):
    today = datetime.now(timezone.utc).date()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _series(db, sql, days):
    found = {r["d"]: r["n"] for r in db.execute(sql, (days[0].isoformat(),))}
    values = [found.get(d.isoformat(), 0) for d in days]
    top = max(max(values), 1)
    return [{"label": d.strftime("%a"), "value": v, "pct": round(v / top * 100)} for d, v in zip(days, values)]


def _bars(pairs):
    top = max([v for _k, v in pairs] + [1])
    return [{"label": k, "value": v, "pct": round(v / top * 100)} for k, v in pairs]


@bp.route("/admin")
@admin_required
def admin_overview():
    db = get_db()
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]  # noqa: E731
    by_status = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) n FROM tickets GROUP BY status"):
        by_status[r["status"]] = r["n"]
    by_category = {c: 0 for c in CATEGORIES}
    for r in db.execute("SELECT category, COUNT(*) n FROM tickets GROUP BY category"):
        by_category[r["category"]] = r["n"]
    sources = {"groq": 0, "gemini": 0, "faq": 0, "none": 0}
    for r in db.execute("SELECT source, COUNT(*) n FROM messages WHERE role = 'assistant' GROUP BY source"):
        if r["source"] in sources:
            sources[r["source"]] = r["n"]
    helpful = one("SELECT COUNT(*) FROM feedback WHERE kind = 'chat' AND rating = 'helpful'")
    not_helpful = one("SELECT COUNT(*) FROM feedback WHERE kind = 'chat' AND rating = 'not_helpful'")
    ratings = {str(i): 0 for i in range(1, 6)}
    for r in db.execute("SELECT rating, COUNT(*) n FROM feedback WHERE kind = 'experience' GROUP BY rating"):
        ratings[r["rating"]] = r["n"]
    rated = sum(ratings.values())
    avg_rating = round(sum(int(k) * v for k, v in ratings.items()) / rated, 1) if rated else None
    days = _last_days(7)
    ai_answers = sources["groq"] + sources["gemini"]
    total_answers = sum(sources.values())
    stats = {
        "users": one("SELECT COUNT(*) FROM users WHERE role = 'user'"),
        "tickets": sum(by_status.values()),
        "active_tickets": by_status["Open"] + by_status["In Progress"],
        "resolved": by_status["Resolved"] + by_status["Closed"],
        "questions": one("SELECT COUNT(*) FROM messages WHERE role = 'user'"),
        "avg_rating": avg_rating,
        "rated": rated,
        "helpful_pct": round(helpful / (helpful + not_helpful) * 100) if helpful + not_helpful else None,
        "ai_share": round(ai_answers / total_answers * 100) if total_answers else None,
    }
    recent = db.execute(
        "SELECT t.*, u.name AS user_name FROM tickets t JOIN users u ON u.id = t.user_id ORDER BY t.id DESC LIMIT 6"
    ).fetchall()
    return render_template(
        "admin_overview.html", stats=stats, recent=recent,
        status_bars=_bars(list(by_status.items())), category_bars=_bars(list(by_category.items())),
        source_bars=_bars([("Groq", sources["groq"]), ("Gemini", sources["gemini"]),
                           ("Help centre", sources["faq"]), ("No match", sources["none"])]),
        rating_bars=_bars([(f"{k} ★", v) for k, v in ratings.items()]),
        tickets_week=_series(db, "SELECT substr(created_at,1,10) d, COUNT(*) n FROM tickets WHERE substr(created_at,1,10) >= ? GROUP BY d", days),
        questions_week=_series(db, "SELECT substr(created_at,1,10) d, COUNT(*) n FROM messages WHERE role = 'user' AND substr(created_at,1,10) >= ? GROUP BY d", days),
        helpful=helpful, not_helpful=not_helpful,
    )


@bp.route("/admin/tickets")
@admin_required
def admin_tickets():
    db = get_db()
    f = {k: request.args.get(k, "").strip() for k in ("status", "priority", "category", "q")}
    where, args = [], []
    if f["status"] in STATUSES:
        where.append("t.status = ?"); args.append(f["status"])
    if f["priority"] in PRIORITIES:
        where.append("t.priority = ?"); args.append(f["priority"])
    if f["category"] in CATEGORIES:
        where.append("t.category = ?"); args.append(f["category"])
    if f["q"]:
        like = f"%{f['q']}%"
        where.append("(t.subject LIKE ? OR u.name LIKE ? OR u.email LIKE ? OR printf('SS-%04d', t.id) LIKE ?)")
        args += [like, like, like, like]
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = "FROM tickets t JOIN users u ON u.id = t.user_id" + clause
    total = db.execute("SELECT COUNT(*) " + base, args).fetchone()[0]
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, pages)
    rows = db.execute(
        "SELECT t.*, u.name AS user_name, u.email AS user_email, "
        "(SELECT COUNT(*) FROM ticket_replies r WHERE r.ticket_id = t.id) AS reply_count "
        + base + " ORDER BY CASE t.status WHEN 'Open' THEN 0 WHEN 'In Progress' THEN 1 ELSE 2 END, t.updated_at DESC LIMIT ? OFFSET ?",
        (*args, PER_PAGE, (page - 1) * PER_PAGE),
    ).fetchall()
    query = {k: v for k, v in f.items() if v}
    return render_template("admin_tickets.html", tickets=rows, filters=f, total=total, page=page, pages=pages, query=query)


@bp.route("/admin/tickets/<int:tid>")
@admin_required
def admin_ticket_detail(tid):
    db = get_db()
    ticket = db.execute(
        "SELECT t.*, u.name AS user_name, u.email AS user_email FROM tickets t JOIN users u ON u.id = t.user_id WHERE t.id = ?",
        (tid,),
    ).fetchone()
    if not ticket:
        abort(404)
    replies = db.execute(
        "SELECT r.*, u.name AS author_name FROM ticket_replies r LEFT JOIN users u ON u.id = r.author_id "
        "WHERE r.ticket_id = ? ORDER BY r.id", (tid,),
    ).fetchall()
    return render_template("admin_ticket_detail.html", ticket=ticket, replies=replies)


@bp.route("/admin/faqs")
@admin_required
def admin_faqs():
    faqs = get_db().execute("SELECT * FROM faqs ORDER BY category, id").fetchall()
    return render_template("admin_faqs.html", faqs=faqs)


@bp.route("/admin/users")
@admin_required
def admin_users():
    users = get_db().execute(
        "SELECT u.*, (SELECT COUNT(*) FROM tickets t WHERE t.user_id = u.id) AS ticket_count, "
        "(SELECT COUNT(*) FROM conversations c WHERE c.user_id = u.id) AS chat_count FROM users u ORDER BY u.created_at DESC"
    ).fetchall()
    return render_template("admin_users.html", users=users)


@bp.route("/admin/feedback")
@admin_required
def admin_feedback():
    rows = get_db().execute(
        "SELECT f.*, u.name AS user_name, m.content AS answer FROM feedback f "
        "LEFT JOIN users u ON u.id = f.user_id LEFT JOIN messages m ON m.id = f.message_id "
        "ORDER BY f.id DESC LIMIT 200"
    ).fetchall()
    return render_template("admin_feedback.html", items=rows)


@bp.route("/admin/ai")
@admin_required
def admin_ai():
    return render_template("admin_ai.html")

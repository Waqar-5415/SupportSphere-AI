"""JSON API (all endpoints under /api)."""
import re

from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import ai
from auth import EMAIL_RE, admin_required, login_required, valid_password
from db import AI_CHOICES, CATEGORIES, PRIORITIES, STATUSES, TEXT_SIZES, THEMES, get_db, now_iso

bp = Blueprint("api", __name__, url_prefix="/api")


def jerr(message, code=400, **extra):
    return jsonify(error=message, **extra), code


def ref(ticket_id):
    return f"SS-{ticket_id:04d}"


def msg_dict(row):
    d = dict(row)
    d["suggest_ticket"] = bool(d.get("suggest_ticket"))
    d.setdefault("feedback", None)
    return d


def user_dict(row):
    d = dict(row)
    d.pop("password_hash", None)
    return d


# ======================================================================== conversations / chat
def get_conv(cid):
    return get_db().execute(
        "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (cid, g.user["id"])
    ).fetchone()


def make_reply(history, message):
    db = get_db()
    faqs = [dict(f) for f in db.execute("SELECT * FROM faqs ORDER BY id").fetchall()]
    tickets = [
        {"ref": ref(t["id"]), "subject": t["subject"], "status": t["status"]}
        for t in db.execute(
            "SELECT id, subject, status FROM tickets WHERE user_id = ? ORDER BY id DESC LIMIT 5", (g.user["id"],)
        )
    ]
    return ai.generate_reply(
        message, history, faqs, current_app.config,
        preferred=g.user["ai_provider"], user_name=g.user["name"], tickets=tickets,
    )


def insert_assistant(cid, reply):
    db = get_db()
    cur = db.execute(
        "INSERT INTO messages (conversation_id, role, content, source, model, notice, suggest_ticket, created_at) "
        "VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?)",
        (cid, reply["content"], reply["source"], reply["model"], reply["notice"], int(reply["suggest_ticket"]), now_iso()),
    )
    db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso(), cid))
    db.commit()
    return db.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()


@bp.get("/conversations")
@login_required
def conversations_list():
    rows = get_db().execute(
        "SELECT id, title, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC, id DESC LIMIT 100",
        (g.user["id"],),
    ).fetchall()
    return jsonify(conversations=[dict(r) for r in rows])


@bp.post("/conversations")
@login_required
def conversations_create():
    db = get_db()
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, 'New chat', ?, ?)",
        (g.user["id"], ts, ts),
    )
    db.commit()
    return jsonify(conversation={"id": cur.lastrowid, "title": "New chat", "updated_at": ts}), 201


@bp.delete("/conversations/<int:cid>")
@login_required
def conversations_delete(cid):
    if not get_conv(cid):
        return jerr("That conversation could not be found.", 404)
    db = get_db()
    db.execute("DELETE FROM conversations WHERE id = ?", (cid,))
    db.commit()
    return jsonify(ok=True)


@bp.post("/conversations/<int:cid>/clear")
@login_required
def conversations_clear(cid):
    if not get_conv(cid):
        return jerr("That conversation could not be found.", 404)
    db = get_db()
    db.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
    db.execute("UPDATE conversations SET title = 'New chat', updated_at = ? WHERE id = ?", (now_iso(), cid))
    db.commit()
    return jsonify(ok=True)


@bp.get("/conversations/<int:cid>/messages")
@login_required
def messages_list(cid):
    conv = get_conv(cid)
    if not conv:
        return jerr("That conversation could not be found.", 404)
    rows = get_db().execute(
        "SELECT m.*, (SELECT rating FROM feedback f WHERE f.message_id = m.id AND f.kind = 'chat' AND f.user_id = ?) AS feedback "
        "FROM messages m WHERE m.conversation_id = ? ORDER BY m.id",
        (g.user["id"], cid),
    ).fetchall()
    return jsonify(conversation=dict(conv), messages=[msg_dict(r) for r in rows])


def _history(cid, before_id=None):
    sql = "SELECT role, content FROM messages WHERE conversation_id = ?"
    args = [cid]
    if before_id:
        sql += " AND id < ?"
        args.append(before_id)
    rows = get_db().execute(sql + " ORDER BY id DESC LIMIT ?", (*args, ai.MAX_HISTORY)).fetchall()
    return [dict(r) for r in rows][::-1]


@bp.post("/conversations/<int:cid>/messages")
@login_required
def messages_send(cid):
    conv = get_conv(cid)
    if not conv:
        return jerr("That conversation could not be found.", 404)
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    if not message:
        return jerr("Please type a question before sending.")
    if len(message) > 1500:
        return jerr("Your message is too long. Please keep it under 1500 characters.")

    db = get_db()
    history = _history(cid)
    cur = db.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
        (cid, message, now_iso()),
    )
    user_id = cur.lastrowid
    title = conv["title"]
    if title == "New chat":
        flat = " ".join(message.split())
        title = flat if len(flat) <= 48 else flat[:47].rstrip() + "…"
    db.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title, now_iso(), cid))
    db.commit()

    reply = make_reply(history, message)
    row = insert_assistant(cid, reply)
    return jsonify(user_message_id=user_id, message=msg_dict(row), conversation={"id": cid, "title": title})


@bp.post("/conversations/<int:cid>/regenerate")
@login_required
def messages_regenerate(cid):
    if not get_conv(cid):
        return jerr("That conversation could not be found.", 404)
    db = get_db()
    last = db.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (cid,)).fetchone()
    if not last or last["role"] != "assistant":
        return jerr("There is no answer to regenerate yet.")
    question = db.execute(
        "SELECT * FROM messages WHERE conversation_id = ? AND id < ? ORDER BY id DESC LIMIT 1", (cid, last["id"])
    ).fetchone()
    if not question or question["role"] != "user":
        return jerr("There is no question to answer again.")
    history = _history(cid, before_id=question["id"])
    db.execute("DELETE FROM messages WHERE id = ?", (last["id"],))
    db.execute("DELETE FROM feedback WHERE kind = 'chat' AND message_id = ?", (last["id"],))
    db.commit()
    reply = make_reply(history, question["content"])
    return jsonify(message=msg_dict(insert_assistant(cid, reply)))


# ======================================================================== help centre
@bp.get("/faqs")
@login_required
def faqs_list():
    q = (request.args.get("q") or "").strip()[:200]
    category = (request.args.get("category") or "").strip()
    faqs = get_db().execute("SELECT * FROM faqs ORDER BY id").fetchall()
    if category and category != "All":
        faqs = [f for f in faqs if f["category"] == category]
    if q:
        faqs = [f for _s, f in ai.rank_faqs(faqs, q)]
    return jsonify(faqs=[dict(f) for f in faqs], count=len(faqs))


# ======================================================================== tickets
def validate_ticket(data):
    errors = {}
    subject = str(data.get("subject") or "").strip()
    category = str(data.get("category") or "").strip()
    description = str(data.get("description") or "").strip()
    priority = str(data.get("priority") or "").strip()
    if len(subject) < 5:
        errors["subject"] = "Please enter a subject of at least 5 characters."
    elif len(subject) > 120:
        errors["subject"] = "The subject must be 120 characters or fewer."
    if category not in CATEGORIES:
        errors["category"] = "Please choose a category from the list."
    if len(description) < 15:
        errors["description"] = "Please describe the problem in at least 15 characters so we can help."
    elif len(description) > 2000:
        errors["description"] = "The description must be 2000 characters or fewer."
    if priority not in PRIORITIES:
        errors["priority"] = "Please choose a priority."
    return errors, {"subject": subject, "category": category, "description": description, "priority": priority}


def get_ticket(tid):
    db = get_db()
    if g.user["role"] == "admin":
        return db.execute("SELECT * FROM tickets WHERE id = ?", (tid,)).fetchone()
    return db.execute("SELECT * FROM tickets WHERE id = ? AND user_id = ?", (tid, g.user["id"])).fetchone()


@bp.post("/tickets")
@login_required
def tickets_create():
    errors, clean = validate_ticket(request.get_json(silent=True) or {})
    if errors:
        return jerr("Please fix the highlighted fields.", errors=errors)
    db = get_db()
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO tickets (user_id, subject, category, description, priority, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'Open', ?, ?)",
        (g.user["id"], clean["subject"], clean["category"], clean["description"], clean["priority"], ts, ts),
    )
    db.commit()
    return jsonify(ticket={"id": cur.lastrowid, "ref": ref(cur.lastrowid), "status": "Open"}), 201


@bp.post("/tickets/<int:tid>/replies")
@login_required
def tickets_reply(tid):
    ticket = get_ticket(tid)
    if not ticket:
        return jerr("That ticket could not be found.", 404)
    data = request.get_json(silent=True) or {}
    body = str(data.get("body") or "").strip()
    if len(body) < 2:
        return jerr("Please write a reply before sending.")
    if len(body) > 2000:
        return jerr("Your reply must be 2000 characters or fewer.")
    is_admin = g.user["role"] == "admin"
    status = ticket["status"]
    new_status = str(data.get("status") or "").strip()
    if is_admin:
        if new_status:
            if new_status not in STATUSES:
                return jerr("Unknown status.")
            status = new_status
        elif status == "Open":
            status = "In Progress"
    elif status in ("Resolved", "Closed"):
        status = "Open"  # a customer reply re-opens the ticket
    db = get_db()
    ts = now_iso()
    cur = db.execute(
        "INSERT INTO ticket_replies (ticket_id, author_id, author_role, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (tid, g.user["id"], "admin" if is_admin else "user", body, ts),
    )
    unread = 1 if is_admin and ticket["user_id"] != g.user["id"] else ticket["user_unread"]
    db.execute("UPDATE tickets SET status = ?, updated_at = ?, user_unread = ? WHERE id = ?", (status, ts, unread, tid))
    db.commit()
    reply = {
        "id": cur.lastrowid, "author_name": g.user["name"], "author_role": "admin" if is_admin else "user",
        "body": body, "created_at": ts,
    }
    return jsonify(reply=reply, status=status), 201


@bp.patch("/tickets/<int:tid>")
@login_required
def tickets_update(tid):
    ticket = get_ticket(tid)
    if not ticket:
        return jerr("That ticket could not be found.", 404)
    data = request.get_json(silent=True) or {}
    status, priority = ticket["status"], ticket["priority"]
    if g.user["role"] == "admin":
        if "status" in data:
            if data["status"] not in STATUSES:
                return jerr("Unknown status.")
            status = data["status"]
        if "priority" in data:
            if data["priority"] not in PRIORITIES:
                return jerr("Unknown priority.")
            priority = data["priority"]
    else:
        if data.get("status") != "Closed":
            return jerr("You can only close your own tickets.", 403)
        status = "Closed"
    db = get_db()
    unread = 1 if g.user["role"] == "admin" and status != ticket["status"] and ticket["user_id"] != g.user["id"] else ticket["user_unread"]
    db.execute(
        "UPDATE tickets SET status = ?, priority = ?, updated_at = ?, user_unread = ? WHERE id = ?",
        (status, priority, now_iso(), unread, tid),
    )
    db.commit()
    return jsonify(ticket={"id": tid, "ref": ref(tid), "status": status, "priority": priority})


# ======================================================================== feedback
@bp.post("/feedback")
@login_required
def feedback_create():
    data = request.get_json(silent=True) or {}
    kind = str(data.get("kind") or "")
    rating = str(data.get("rating") or "")
    comment = str(data.get("comment") or "").strip()
    if len(comment) > 500:
        return jerr("Comments must be 500 characters or fewer.")
    db = get_db()
    message_id = None
    if kind == "chat":
        if rating not in ("helpful", "not_helpful"):
            return jerr("Please choose helpful or not helpful.")
        message_id = data.get("message_id")
        row = None
        if isinstance(message_id, int):
            row = db.execute(
                "SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.id = ? AND c.user_id = ? AND m.role = 'assistant'",
                (message_id, g.user["id"]),
            ).fetchone()
        if row is None:
            return jerr("That chat message could not be found.", 404)
        db.execute("DELETE FROM feedback WHERE kind = 'chat' AND message_id = ? AND user_id = ?", (message_id, g.user["id"]))
    elif kind == "experience":
        if rating not in ("1", "2", "3", "4", "5"):
            return jerr("Please choose a rating from 1 to 5.")
    else:
        return jerr("Unknown feedback type.")
    db.execute(
        "INSERT INTO feedback (user_id, kind, message_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (g.user["id"], kind, message_id, rating, comment, now_iso()),
    )
    db.commit()
    return jsonify(ok=True, message="Thank you for your feedback!"), 201


# ======================================================================== account / settings
@bp.patch("/me")
@login_required
def me_update():
    data = request.get_json(silent=True) or {}
    db = get_db()
    updates, errors = {}, {}
    if "name" in data:
        name = " ".join(str(data["name"]).split())
        if 2 <= len(name) <= 60:
            updates["name"] = name
        else:
            errors["name"] = "Please enter your name (2 to 60 characters)."
    if "email" in data:
        email = str(data["email"]).strip().lower()
        if not EMAIL_RE.match(email) or len(email) > 120:
            errors["email"] = "Please enter a valid email address, for example name@example.com."
        elif db.execute("SELECT 1 FROM users WHERE email = ? AND id != ?", (email, g.user["id"])).fetchone():
            errors["email"] = "Another account already uses this email address."
        else:
            updates["email"] = email
    for field, allowed in (("theme", THEMES), ("text_size", TEXT_SIZES), ("ai_provider", AI_CHOICES)):
        if field in data:
            if data[field] in allowed:
                updates[field] = data[field]
            else:
                errors[field] = "Please choose one of the available options."
    if errors:
        return jerr("Please fix the highlighted fields.", errors=errors)
    if updates:
        cols = ", ".join(f"{k} = ?" for k in updates)
        db.execute(f"UPDATE users SET {cols} WHERE id = ?", (*updates.values(), g.user["id"]))
        db.commit()
    row = db.execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()
    return jsonify(user=user_dict(row), message="Your settings have been saved.")


@bp.post("/me/password")
@login_required
def me_password():
    data = request.get_json(silent=True) or {}
    current, new = str(data.get("current") or ""), str(data.get("new") or "")
    if not check_password_hash(g.user["password_hash"], current):
        return jerr("Please fix the highlighted fields.", errors={"current": "Your current password is incorrect."})
    problem = valid_password(new)
    if problem:
        return jerr("Please fix the highlighted fields.", errors={"new": problem})
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), g.user["id"]))
    db.commit()
    return jsonify(ok=True, message="Your password has been changed.")


@bp.delete("/me")
@login_required
def me_delete():
    data = request.get_json(silent=True) or {}
    if not check_password_hash(g.user["password_hash"], str(data.get("password") or "")):
        return jerr("Please fix the highlighted fields.", errors={"password": "That password is not correct."})
    db = get_db()
    if g.user["role"] == "admin" and db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1").fetchone()[0] <= 1:
        return jerr("You are the only administrator, so this account cannot be deleted.", 409)
    db.execute("DELETE FROM users WHERE id = ?", (g.user["id"],))
    db.commit()
    session.clear()
    return jsonify(ok=True)


# ======================================================================== admin
@bp.post("/admin/faqs")
@admin_required
def admin_faq_create():
    errors, clean = _validate_faq(request.get_json(silent=True) or {})
    if errors:
        return jerr("Please fix the highlighted fields.", errors=errors)
    db = get_db()
    cur = db.execute(
        "INSERT INTO faqs (category, question, answer, keywords) VALUES (?, ?, ?, ?)",
        (clean["category"], clean["question"], clean["answer"], clean["keywords"]),
    )
    db.commit()
    return jsonify(faq={"id": cur.lastrowid, **clean}), 201


@bp.put("/admin/faqs/<int:fid>")
@admin_required
def admin_faq_update(fid):
    db = get_db()
    if not db.execute("SELECT 1 FROM faqs WHERE id = ?", (fid,)).fetchone():
        return jerr("That article could not be found.", 404)
    errors, clean = _validate_faq(request.get_json(silent=True) or {})
    if errors:
        return jerr("Please fix the highlighted fields.", errors=errors)
    db.execute(
        "UPDATE faqs SET category = ?, question = ?, answer = ?, keywords = ? WHERE id = ?",
        (clean["category"], clean["question"], clean["answer"], clean["keywords"], fid),
    )
    db.commit()
    return jsonify(faq={"id": fid, **clean})


@bp.delete("/admin/faqs/<int:fid>")
@admin_required
def admin_faq_delete(fid):
    db = get_db()
    if not db.execute("SELECT 1 FROM faqs WHERE id = ?", (fid,)).fetchone():
        return jerr("That article could not be found.", 404)
    db.execute("DELETE FROM faqs WHERE id = ?", (fid,))
    db.commit()
    return jsonify(ok=True)


def _validate_faq(data):
    errors = {}
    category = str(data.get("category") or "").strip()
    question = str(data.get("question") or "").strip()
    answer = str(data.get("answer") or "").strip()
    keywords = re.sub(r"\s+", " ", str(data.get("keywords") or "")).strip()
    if category not in CATEGORIES:
        errors["category"] = "Please choose a category."
    if not 5 <= len(question) <= 200:
        errors["question"] = "The question must be 5 to 200 characters."
    if not 10 <= len(answer) <= 3000:
        errors["answer"] = "The answer must be 10 to 3000 characters."
    if len(keywords) > 300:
        errors["keywords"] = "Keywords must be 300 characters or fewer."
    return errors, {"category": category, "question": question, "answer": answer, "keywords": keywords}


@bp.patch("/admin/users/<int:uid>")
@admin_required
def admin_user_update(uid):
    if uid == g.user["id"]:
        return jerr("You cannot change your own role or status here.", 409)
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        return jerr("That user could not be found.", 404)
    data = request.get_json(silent=True) or {}
    role, active = row["role"], row["is_active"]
    if "role" in data:
        if data["role"] not in ("user", "admin"):
            return jerr("Unknown role.")
        role = data["role"]
    if "is_active" in data:
        active = 1 if data["is_active"] else 0
    db.execute("UPDATE users SET role = ?, is_active = ? WHERE id = ?", (role, active, uid))
    db.commit()
    return jsonify(user={"id": uid, "role": role, "is_active": active})


@bp.post("/admin/ai/test")
@admin_required
def admin_ai_test():
    pid = str((request.get_json(silent=True) or {}).get("provider") or "")
    if pid not in ai.PROVIDER_IDS:
        return jerr("Unknown provider.")
    ok, message, ms = ai.test_provider(current_app.config, pid)
    return jsonify(ok=ok, message=message, ms=ms)

"""SQLite data layer: schema, constants, seed data."""
import sqlite3
from datetime import datetime, timezone

from flask import current_app, g
from werkzeug.security import generate_password_hash

CATEGORIES = ["Account Access", "Security", "Billing", "Technical Issues", "General Help"]
PRIORITIES = ["Low", "Medium", "High"]
STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
THEMES = ["light", "dark", "system"]
TEXT_SIZES = ["normal", "large"]
AI_CHOICES = ["auto", "groq", "gemini"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    is_active INTEGER NOT NULL DEFAULT 1,
    theme TEXT NOT NULL DEFAULT 'system',
    text_size TEXT NOT NULL DEFAULT 'normal',
    ai_provider TEXT NOT NULL DEFAULT 'auto',
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS faqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    model TEXT,
    notice TEXT,
    suggest_ticket INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Medium',
    status TEXT NOT NULL DEFAULT 'Open',
    user_unread INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    author_role TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    message_id INTEGER,
    rating TEXT NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id);
"""

SEED_FAQS = [
    ("Account Access", "How do I reset my password?",
     "Open the sign-in page and choose **Forgot password**. Enter your registered email address and we will send a reset link.\n"
     "- The link is valid for 30 minutes.\n- Check your spam folder if it does not arrive within a few minutes.\n- Choose a new password of at least 8 characters.\n\n"
     "If you are already signed in, you can change it any time under **Settings > Password**.",
     "password reset forgot change login sign in credentials"),
    ("Account Access", "I can't log in to my account. What should I do?",
     "First check that your email address is spelled correctly and that Caps Lock is off. If that does not help:\n"
     "- Use **Forgot password** to reset your password.\n- Try a private/incognito window to rule out browser extensions.\n"
     "- After several failed attempts sign-in is paused for a few minutes; wait and try again.\n- If your account was deactivated, contact an administrator by ticket.",
     "login sign in locked access denied cannot log in unable"),
    ("Account Access", "How do I change the email address on my account?",
     "Go to **Settings > Profile**, edit the email field and save. The new address is used the next time you sign in.",
     "email change update address contact details"),
    ("Account Access", "How do I close or delete my account?",
     "You can delete your account yourself under **Settings > Danger zone** (you will be asked for your password). "
     "This permanently removes your tickets and conversations. If you cannot sign in, submit a ticket in the **Account Access** category.",
     "delete close remove deactivate cancel account"),
    ("Security", "How do I enable two-factor authentication (2FA)?",
     "Open **Profile and Settings > Security** and select **Enable 2FA**. Scan the QR code with an authenticator app, "
     "enter the 6-digit code to confirm, and store your backup codes somewhere safe.",
     "2fa two factor authentication mfa authenticator security code"),
    ("Security", "How can I tell if my account has been compromised?",
     "Warning signs include unexpected password-reset emails, logins from unfamiliar locations, or changes you did not make.\n"
     "- Change your password immediately.\n- Enable two-factor authentication.\n- Submit a **High** priority ticket so we can review the activity.",
     "hacked compromised suspicious unauthorized breach stolen"),
    ("Security", "Is my personal data safe?",
     "We collect only the minimum personal information needed to provide support, store passwords as salted hashes and never ask for your "
     "password or full card number in chat or tickets. Avoid including sensitive details in ticket descriptions.",
     "privacy data protection personal information safe secure gdpr"),
    ("Security", "How do I report a phishing or suspicious email?",
     "Do not click links or open attachments. Submit a ticket in the **Security** category and paste the sender address and subject line "
     "so our team can investigate.",
     "phishing scam spam fake email suspicious report fraud"),
    ("Billing", "How do I update my payment method?",
     "Go to **Billing > Payment methods**, select **Add new method**, and then set it as default. Remove the old method once the new one is saved.",
     "payment method card update change credit debit billing"),
    ("Billing", "Where can I find my invoices?",
     "Invoices are listed under **Billing > Invoice history**. Select any invoice to download it as a PDF. "
     "Invoices are emailed to your account address on the day of each charge.",
     "invoice receipt statement download history bill"),
    ("Billing", "How do I request a refund?",
     "Refunds can be requested within 14 days of a charge. Submit a ticket in the **Billing** category with the invoice number "
     "and the reason for the request. Approved refunds return to the original payment method in 5-10 working days.",
     "refund money back return reimburse cancel charge"),
    ("Billing", "Why was I charged twice?",
     "A duplicate charge is often a temporary authorization hold that disappears within a few days. If both charges remain "
     "after 5 working days, submit a **Billing** ticket with both invoice numbers and the dates.",
     "charged twice double duplicate charge overcharged billing error"),
    ("Technical Issues", "The app is loading slowly or freezing. What can I do?",
     "Try these steps in order:\n- Refresh the page and check your internet connection.\n- Close unused tabs and applications.\n"
     "- Clear your browser cache and cookies.\n- Try another supported browser.\nIf the problem continues, submit a ticket and describe what you were doing when it happened.",
     "slow loading freeze frozen lag performance crash stuck error"),
    ("Technical Issues", "Which browsers and devices are supported?",
     "We support the latest two versions of Chrome, Edge, Firefox and Safari on desktop, and current versions of Chrome and Safari on Android and iOS. "
     "Screen readers and keyboard navigation are supported.",
     "browser supported compatibility device mobile android ios safari chrome firefox edge"),
    ("Technical Issues", "I am not receiving verification or notification emails.",
     "Check your spam or junk folder and confirm the address on your profile is correct. Add our sending address to your safe-sender list, "
     "then request a new email. Some corporate mail filters block automated messages; try a personal address if possible.",
     "email not receiving verification code notification missing spam junk"),
    ("Technical Issues", "How do I clear my browser cache and cookies?",
     "In most browsers press **Ctrl+Shift+Delete** (**Cmd+Shift+Delete** on Mac), choose 'Cached images and files' and 'Cookies', "
     "pick a time range, and confirm. You may need to sign in again afterwards.",
     "clear cache cookies browser refresh storage"),
    ("General Help", "How do I contact support?",
     "You can ask the AI assistant, search the Help Centre, or open a support ticket from the **My Tickets** page. "
     "Tickets let you describe the problem in detail, receive replies from our team, and track the status.",
     "contact support help agent talk human reach"),
    ("General Help", "What are your support hours?",
     "Tickets can be submitted at any time. Our team reviews tickets Monday to Friday, 9:00 to 17:00. "
     "The AI assistant and Help Centre are available 24/7.",
     "hours availability open time schedule working days weekend"),
    ("General Help", "How long does it take to get a response to a ticket?",
     "Typical first-response targets are: **High** priority within 4 working hours, **Medium** within 1 working day, and **Low** within 3 working days. "
     "You will see a notification badge on **My Tickets** when our team replies.",
     "response time how long wait ticket sla reply status"),
    ("General Help", "How do I give feedback or suggest a feature?",
     "Use the thumbs-up / thumbs-down buttons under assistant answers, or rate your overall experience on the Dashboard. "
     "For feature ideas, open a ticket in the **General Help** category with the subject 'Feature suggestion'.",
     "feedback suggestion feature idea improve rating comment"),
]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    """Create tables, seed the knowledge base, and create the first administrator."""
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM faqs").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO faqs (category, question, answer, keywords) VALUES (?, ?, ?, ?)", SEED_FAQS
            )
        if db.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] == 0:
            email = (app.config.get("ADMIN_EMAIL") or "admin@supportsphere.ai").strip().lower()
            password = app.config.get("ADMIN_PASSWORD") or "Admin@12345"
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (existing["id"],))
            else:
                db.execute(
                    "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
                    (app.config.get("ADMIN_NAME") or "Administrator", email, generate_password_hash(password), now_iso()),
                )
        db.commit()

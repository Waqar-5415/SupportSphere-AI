"""AI layer: Groq and Google Gemini providers with automatic fallback to the Help Centre."""
import re
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
TIMEOUT = 25
MAX_HISTORY = 10
MAX_FAQ_CONTEXT = 60
RELEVANCE_THRESHOLD = 0.3
PROVIDER_IDS = ("groq", "gemini")
LABELS = {"groq": "Groq", "gemini": "Google Gemini"}

_PLACEHOLDER = re.compile(r"^(your[_\- ]|paste|xxx|changeme|<)", re.I)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could", "do", "does", "did", "for",
    "from", "get", "has", "have", "how", "i", "if", "in", "is", "it", "its", "me", "my", "of", "on",
    "or", "our", "please", "should", "so", "that", "the", "their", "there", "this", "to", "was",
    "we", "what", "when", "where", "which", "who", "why", "will", "with", "would", "you", "your",
    "need", "want", "help", "tell", "about", "am", "im", "ive",
}

SYSTEM_PROMPT = (
    "You are SupportSphere AI, the friendly customer-support assistant of the SupportSphere help desk. "
    "Be warm, clear and concise (under 150 words). Use short steps or bullet points ('- ' for bullets) and "
    "**bold** for key terms. Use the help-centre articles below as your main source of truth. "
    "If the answer is not covered, say so honestly and suggest opening a support ticket from the "
    "'My Tickets' page. You may use the user's ticket list below to answer questions about their tickets. "
    "Never ask for passwords or full payment card numbers, never invent policies, prices, links or phone "
    "numbers, and stay on the topic of customer support."
)

NO_ANSWER_REPLY = (
    "I couldn't find a good answer to that in our help centre.\n"
    "- Try rephrasing your question with different words.\n"
    "- Browse the Help Centre by category.\n"
    "- Or open a support ticket and our team will reply to you directly."
)


class AIUnavailable(Exception):
    """Raised when a provider cannot answer. The message is safe to show to administrators.

    model_problem is True when the model itself was refused (retired / unknown), so the next model should be tried.
    """

    def __init__(self, message="", model_problem=False):
        super().__init__(message)
        self.model_problem = model_problem


def clean_key(value):
    value = (value or "").strip().strip('"').strip("'").strip()
    return "" if not value or _PLACEHOLDER.match(value) else value


def providers(cfg):
    """Status of every AI provider (used by the UI)."""
    return [
        {
            "id": pid,
            "label": LABELS[pid],
            "configured": bool(clean_key(cfg.get(f"{pid.upper()}_API_KEY"))),
            "model": cfg.get(f"{pid.upper()}_MODEL"),
        }
        for pid in PROVIDER_IDS
    ]


def provider_order(cfg, preferred="auto"):
    avail = [p["id"] for p in providers(cfg) if p["configured"]]
    if preferred in avail:
        return [preferred] + [p for p in avail if p != preferred]
    return avail


# ----------------------------------------------------------------------------- provider calls
def _reason(status):
    if status in (401, 403):
        return "the API key was rejected (check it in your .env file)"
    if status in (400, 404):
        return "the model name was refused or has been retired (update the MODEL setting in .env)"
    if status == 429:
        return "the rate limit or free quota was reached"
    return f"the service returned HTTP {status}"


def _post(url, **kwargs):
    try:
        resp = requests.post(url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise AIUnavailable("the service could not be reached (network problem)") from exc
    if resp.status_code != 200:
        raise AIUnavailable(_reason(resp.status_code), model_problem=resp.status_code in (400, 404))
    try:
        return resp.json()
    except ValueError as exc:
        raise AIUnavailable("the service sent an unreadable response") from exc


def call_groq(system, history, message, key, model):
    messages = [{"role": "system", "content": system}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history if h["role"] in ("user", "assistant")]
    messages.append({"role": "user", "content": message})
    data = _post(
        GROQ_URL,
        json={"model": model, "messages": messages, "temperature": 0.4, "max_tokens": 2000},
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AIUnavailable("the service sent an unexpected response") from exc
    if not text:
        raise AIUnavailable("the service returned an empty answer")
    return text


def call_gemini(system, history, message, key, model):
    contents = []
    for h in history:
        if h["role"] in ("user", "assistant"):
            contents.append({"role": "user" if h["role"] == "user" else "model", "parts": [{"text": h["content"]}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    contents.append({"role": "user", "parts": [{"text": message}]})
    data = _post(
        GEMINI_URL.format(model=model),
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 2048},
        },
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
    )
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise AIUnavailable("the service sent an unexpected response") from exc
    if not text:
        raise AIUnavailable("the service returned an empty answer")
    return text


CALLERS = {"groq": call_groq, "gemini": call_gemini}


def model_list(value):
    """MODEL settings may hold several comma-separated names; they are tried in order."""
    return [m.strip() for m in str(value or "").split(",") if m.strip()]


def call_models(pid, system, history, message, key, models):
    """Call a provider, moving on to the next model if one is retired / unknown. Returns (text, model_used)."""
    last = None
    for model in model_list(models):
        try:
            return CALLERS[pid](system, history, message, key, model), model
        except AIUnavailable as exc:
            last = exc
            if not exc.model_problem:
                raise
    raise last or AIUnavailable("no model name is configured (check the MODEL setting in .env)")


def test_provider(cfg, pid):
    """Send a tiny request to verify a key. Returns (ok, message, milliseconds)."""
    key = clean_key(cfg.get(f"{pid.upper()}_API_KEY"))
    if not key:
        return False, "No API key found. Paste it into the .env file and restart the app.", 0
    start = time.time()
    try:
        text, used = call_models(pid, "You are a connection test.", [], "Reply with the single word OK.", key, cfg.get(f"{pid.upper()}_MODEL"))
    except AIUnavailable as exc:
        return False, f"Connection failed: {exc}.", int((time.time() - start) * 1000)
    return True, f"Connected using {used}. It replied: {text[:60]}", int((time.time() - start) * 1000)


# ----------------------------------------------------------------------------- knowledge base
def _normalise(text):
    text = text.lower()
    for phrase in ("log in", "sign in", "signin", "log-in", "sign-in"):
        text = text.replace(phrase, "login")
    for phrase in ("two times", "2 times", "double charged", "doubled"):
        text = text.replace(phrase, "twice")
    return text.replace("2fa", "twofactor").replace("two-factor", "twofactor").replace("two factor", "twofactor")


def _stem(word):
    for suffix in ("ing", "ed", "es", "s", "e"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", _normalise(text))
    return {_stem(w) for w in words if len(w) > 1 and w not in STOPWORDS}


def score_faq(query_tokens, faq):
    if not query_tokens:
        return 0.0
    q_tokens, k_tokens, a_tokens = tokenize(faq["question"]), tokenize(faq["keywords"]), tokenize(faq["answer"])
    raw = 0
    for tok in query_tokens:
        if tok in q_tokens:
            raw += 3
        elif tok in k_tokens:
            raw += 2
        elif tok in a_tokens:
            raw += 1
    return raw / (3 * len(query_tokens))


def rank_faqs(faqs, query):
    tokens = tokenize(query)
    scored = [(score_faq(tokens, f), f) for f in faqs]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def faq_reply(faqs, message):
    ranked = rank_faqs(faqs, message)
    if not ranked or ranked[0][0] < RELEVANCE_THRESHOLD:
        return None
    best = ranked[0][1]
    reply = f"**{best['question']}**\n\n{best['answer']}"
    related = [f["question"] for s, f in ranked[1:3] if s >= RELEVANCE_THRESHOLD]
    if related:
        reply += "\n\nYou might also want to look at:\n" + "\n".join(f"- {q}" for q in related)
    return reply


_GREETING = re.compile(r"^\s*(hi|hello|hey|good\s+(morning|afternoon|evening)|salam|assalam[a-z\s-]*)\b", re.I)
_THANKS = re.compile(r"\b(thanks|thank you|thx|shukriya|much appreciated)\b", re.I)


def local_reply(message, faqs, tickets, user_name=""):
    """Best-effort answer without an AI model: small talk, ticket status, then the knowledge base."""
    words = message.split()
    first = (user_name or "").split(" ")[0]
    if _GREETING.match(message) and len(words) <= 6:
        who = f" {first}" if first else ""
        return f"Hello{who}! I'm the SupportSphere assistant. Ask me about your account, billing, security or technical problems."
    if _THANKS.search(message) and len(words) <= 8:
        return "You're welcome! Is there anything else I can help you with?"
    tokens = tokenize(message)
    if "ticket" in tokens and tokens & {"status", "updat", "progress", "my", "track", "check"} or "ticket" in message.lower() and "status" in message.lower():
        if tickets:
            lines = "\n".join(f"- **{t['ref']}** — {t['subject']} ({t['status']})" for t in tickets)
            return f"Here are your most recent tickets:\n{lines}\n\nOpen **My Tickets** to see replies from our team."
        return "You don't have any tickets yet. You can open one from the **My Tickets** page whenever you need help from our team."
    return faq_reply(faqs, message)


# ----------------------------------------------------------------------------- orchestration
def build_system_prompt(faqs, user_name, tickets):
    articles = "\n\n".join(f"[{f['category']}] Q: {f['question']}\nA: {f['answer']}" for f in faqs[:MAX_FAQ_CONTEXT])
    ticket_lines = "\n".join(f"{t['ref']} | {t['subject']} | {t['status']}" for t in tickets) or "(no tickets yet)"
    who = f"You are chatting with {user_name}.\n" if user_name else ""
    return f"{SYSTEM_PROMPT}\n{who}\nHELP-CENTRE ARTICLES:\n{articles}\n\nTHE USER'S RECENT TICKETS:\n{ticket_lines}"


def generate_reply(message, history, faqs, cfg, preferred="auto", user_name="", tickets=()):
    """Return dict(content, source, model, notice, suggest_ticket). source: groq | gemini | faq | none."""
    history = list(history)[-MAX_HISTORY:]
    order = provider_order(cfg, preferred)
    failed = []
    if order:
        system = build_system_prompt(faqs, user_name, tickets)
        for pid in order:
            key = clean_key(cfg.get(f"{pid.upper()}_API_KEY"))
            try:
                text, model = call_models(pid, system, history, message, key, cfg.get(f"{pid.upper()}_MODEL"))
            except AIUnavailable:
                failed.append(pid)
                continue
            notice = None
            if failed:
                notice = f"{LABELS[failed[0]]} was unavailable, so {LABELS[pid]} answered instead."
            return {"content": text, "source": pid, "model": model, "notice": notice, "suggest_ticket": False}
        notice = "The AI engines are unavailable right now, so this answer comes from our help centre."
    else:
        notice = "AI engines are not connected yet, so this answer comes from our help centre."

    reply = local_reply(message, faqs, tickets, user_name)
    if reply:
        return {"content": reply, "source": "faq", "model": None, "notice": notice, "suggest_ticket": False}
    return {"content": NO_ANSWER_REPLY, "source": "none", "model": None, "notice": notice, "suggest_ticket": True}

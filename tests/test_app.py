"""Functional tests. Run from the project root:  python -m unittest discover -s tests -v"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai  # noqa: E402
import auth  # noqa: E402
from app import create_app  # noqa: E402

ADMIN = ("admin@test.io", "Admin@12345")


class Base(unittest.TestCase):
    keys = {"GROQ_API_KEY": "", "GEMINI_API_KEY": ""}

    def setUp(self):
        auth.reset_rate_limits()
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True, "DATABASE": os.path.join(self.tmp.name, "t.db"), "SECRET_KEY": "test",
            "CSRF_ENABLED": False, "ADMIN_EMAIL": ADMIN[0], "ADMIN_PASSWORD": ADMIN[1], **self.keys,
        })
        self.c = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # helpers
    def register(self, client=None, name="Sara Khan", email="sara@test.io", password="Passw0rd1"):
        return (client or self.c).post("/register", data={"name": name, "email": email, "password": password, "confirm": password})

    def login(self, client, email, password, **extra):
        return client.post("/login", data={"email": email, "password": password, **extra})

    def admin_client(self):
        cl = self.app.test_client()
        self.login(cl, *ADMIN)
        return cl

    def user_client(self, name="Sara Khan", email="sara@test.io"):
        cl = self.app.test_client()
        self.register(cl, name=name, email=email)
        return cl

    def ticket(self, client, **over):
        data = {"subject": "Invoice export fails", "category": "Billing",
                "description": "The download button does nothing when I click it.", "priority": "Medium"}
        data.update(over)
        return client.post("/api/tickets", json=data)

    def conv(self, client):
        return client.post("/api/conversations", json={}).get_json()["conversation"]["id"]


# ===================================================================================== auth
class AuthTests(Base):
    def test_public_pages(self):
        for p in ("/", "/login", "/register", "/healthz"):
            self.assertEqual(self.c.get(p).status_code, 200, p)

    def test_protected_pages_redirect_to_login(self):
        for p in ("/app", "/app/chat", "/app/help", "/app/tickets", "/app/settings", "/admin"):
            r = self.c.get(p)
            self.assertEqual(r.status_code, 302, p)
            self.assertIn("/login", r.headers["Location"])

    def test_api_requires_login(self):
        self.assertEqual(self.c.get("/api/conversations").status_code, 401)
        self.assertEqual(self.c.get("/api/faqs").status_code, 401)

    def test_register_success_logs_in(self):
        r = self.register()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/app").status_code, 200)

    def test_register_validation(self):
        r = self.c.post("/register", data={"name": "A", "email": "bad", "password": "short", "confirm": "x"})
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        for text in ("name (2 to 60", "valid email", "at least 8 characters"):
            self.assertIn(text, html)

    def test_password_needs_letter_and_number(self):
        r = self.c.post("/register", data={"name": "Sara", "email": "s@t.io", "password": "abcdefgh", "confirm": "abcdefgh"})
        self.assertIn("letter and one number", r.get_data(as_text=True))

    def test_password_mismatch_and_duplicate_email(self):
        r = self.c.post("/register", data={"name": "Sara", "email": "s@t.io", "password": "Passw0rd1", "confirm": "Different1"})
        self.assertIn("do not match", r.get_data(as_text=True))
        self.register(self.app.test_client())
        r = self.register(self.app.test_client())
        self.assertIn("already exists", r.get_data(as_text=True))

    def test_login_logout(self):
        self.register(self.app.test_client())
        r = self.login(self.c, "sara@test.io", "Passw0rd1")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/app").status_code, 200)
        self.c.post("/logout")
        self.assertEqual(self.c.get("/app").status_code, 302)

    def test_login_email_case_insensitive(self):
        self.register(self.app.test_client())
        self.assertEqual(self.login(self.c, "SARA@Test.io", "Passw0rd1").status_code, 302)

    def test_login_wrong_password(self):
        self.register(self.app.test_client())
        r = self.login(self.c, "sara@test.io", "wrong")
        self.assertIn("Incorrect email or password", r.get_data(as_text=True))

    def test_login_rate_limit(self):
        for _ in range(auth.MAX_FAILS):
            self.login(self.c, "sara@test.io", "nope")
        r = self.login(self.c, "sara@test.io", "nope")
        self.assertIn("Too many failed attempts", r.get_data(as_text=True))

    def test_open_redirect_blocked(self):
        self.register(self.app.test_client())
        r = self.login(self.c, "sara@test.io", "Passw0rd1", next="https://evil.example")
        self.assertNotIn("evil.example", r.headers["Location"])
        self.c.post("/logout")
        r = self.login(self.c, "sara@test.io", "Passw0rd1", next="/app/help")
        self.assertTrue(r.headers["Location"].endswith("/app/help"))

    def test_admin_is_seeded_and_lands_on_admin(self):
        r = self.login(self.c, *ADMIN)
        self.assertTrue(r.headers["Location"].endswith("/admin"))

    def test_customer_cannot_open_admin(self):
        cl = self.user_client()
        self.assertEqual(cl.get("/admin").status_code, 403)
        self.assertEqual(cl.get("/admin/tickets").status_code, 403)
        self.assertEqual(cl.post("/api/admin/faqs", json={}).status_code, 403)
        self.assertEqual(cl.patch("/api/admin/users/1", json={"role": "admin"}).status_code, 403)

    def test_deactivated_user_cannot_login_or_continue(self):
        cl = self.user_client()
        admin = self.admin_client()
        uid = self.c.application.test_client()  # noqa: F841
        users = admin.get("/admin/users").get_data(as_text=True)
        self.assertIn("sara@test.io", users)
        r = admin.patch("/api/admin/users/2", json={"is_active": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(cl.get("/app").status_code, 302)
        r = self.login(self.app.test_client(), "sara@test.io", "Passw0rd1")
        self.assertIn("deactivated", r.get_data(as_text=True))


class CsrfTests(Base):
    def setUp(self):
        super().setUp()
        self.app.config["CSRF_ENABLED"] = True

    def test_post_without_token_rejected(self):
        r = self.c.post("/api/conversations", json={})
        self.assertEqual(r.status_code, 400)
        self.assertIn("session expired", r.get_json()["error"])

    def test_post_with_token_accepted(self):
        self.c.get("/login")
        with self.c.session_transaction() as s:
            token = s["csrf"]
        r = self.c.post("/register", data={"name": "Sara", "email": "s@t.io", "password": "Passw0rd1", "confirm": "Passw0rd1", "csrf_token": token})
        self.assertEqual(r.status_code, 302)
        self.c.get("/app")  # the token rotates after sign-up; the page carries the new one
        with self.c.session_transaction() as s:
            token = s["csrf"]
        r = self.c.post("/api/conversations", json={}, headers={"X-CSRF-Token": token})
        self.assertEqual(r.status_code, 201)

    def test_login_form_without_token_rejected(self):
        r = self.c.post("/login", data={"email": ADMIN[0], "password": ADMIN[1]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/admin").status_code, 302)  # still logged out


# ===================================================================================== chat
class ChatTests(Base):
    def setUp(self):
        super().setUp()
        self.u = self.user_client()
        self.cid = self.conv(self.u)

    def send(self, text, cid=None):
        return self.u.post(f"/api/conversations/{cid or self.cid}/messages", json={"message": text})

    def test_pages(self):
        self.assertEqual(self.u.get("/app/chat").status_code, 200)
        self.assertEqual(self.u.get(f"/app/chat/{self.cid}").status_code, 200)
        self.assertEqual(self.u.get("/app/chat/999").status_code, 404)

    def test_validation(self):
        self.assertEqual(self.send("   ").status_code, 400)
        self.assertEqual(self.send("x" * 1501).status_code, 400)

    def test_faq_answer_without_keys(self):
        m = self.send("How do I reset my password?").get_json()["message"]
        self.assertEqual(m["source"], "faq")
        self.assertIn("Forgot password", m["content"])
        self.assertIn("not connected", m["notice"])

    def test_synonyms(self):
        for q, expect in (("I can't sign in", "faq"), ("my card was charged two times", "faq"), ("app keeps freezing", "faq")):
            self.assertEqual(self.send(q).get_json()["message"]["source"], expect, q)

    def test_no_match_suggests_ticket(self):
        m = self.send("banana pizza helicopter").get_json()["message"]
        self.assertEqual(m["source"], "none")
        self.assertTrue(m["suggest_ticket"])

    def test_greeting_and_thanks(self):
        self.assertIn("Hello Sara", self.send("hi").get_json()["message"]["content"])
        self.assertIn("welcome", self.send("thanks a lot").get_json()["message"]["content"].lower())

    def test_ticket_status_question_uses_real_tickets(self):
        self.assertIn("don't have any tickets", self.send("what is the status of my ticket").get_json()["message"]["content"])
        self.ticket(self.u, subject="Broken invoice link")
        self.assertIn("Broken invoice link", self.send("what is the status of my ticket").get_json()["message"]["content"])

    def test_title_set_from_first_message(self):
        r = self.send("How do I reset my password?").get_json()
        self.assertEqual(r["conversation"]["title"], "How do I reset my password?")
        convs = self.u.get("/api/conversations").get_json()["conversations"]
        self.assertEqual(convs[0]["title"], "How do I reset my password?")

    def test_messages_history_and_clear(self):
        self.send("refund")
        data = self.u.get(f"/api/conversations/{self.cid}/messages").get_json()
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant"])
        self.u.post(f"/api/conversations/{self.cid}/clear")
        self.assertEqual(self.u.get(f"/api/conversations/{self.cid}/messages").get_json()["messages"], [])

    def test_regenerate(self):
        self.send("refund")
        r = self.u.post(f"/api/conversations/{self.cid}/regenerate")
        self.assertEqual(r.status_code, 200)
        msgs = self.u.get(f"/api/conversations/{self.cid}/messages").get_json()["messages"]
        self.assertEqual(len(msgs), 2)
        empty = self.conv(self.u)
        self.assertEqual(self.u.post(f"/api/conversations/{empty}/regenerate").status_code, 400)

    def test_delete_conversation(self):
        self.assertEqual(self.u.delete(f"/api/conversations/{self.cid}").status_code, 200)
        self.assertEqual(self.u.get(f"/api/conversations/{self.cid}/messages").status_code, 404)

    def test_conversations_are_private_between_users(self):
        other = self.user_client("Omar", "omar@test.io")
        self.assertEqual(other.get(f"/api/conversations/{self.cid}/messages").status_code, 404)
        self.assertEqual(other.post(f"/api/conversations/{self.cid}/messages", json={"message": "hi"}).status_code, 404)
        self.assertEqual(other.delete(f"/api/conversations/{self.cid}").status_code, 404)
        self.assertEqual(other.get("/api/conversations").get_json()["conversations"], [])
        self.assertEqual(other.get(f"/app/chat/{self.cid}").status_code, 404)

    def test_chat_feedback_toggle_and_privacy(self):
        mid = self.send("refund").get_json()["message"]["id"]
        self.assertEqual(self.u.post("/api/feedback", json={"kind": "chat", "message_id": mid, "rating": "helpful"}).status_code, 201)
        self.assertEqual(self.u.post("/api/feedback", json={"kind": "chat", "message_id": mid, "rating": "not_helpful"}).status_code, 201)
        msgs = self.u.get(f"/api/conversations/{self.cid}/messages").get_json()["messages"]
        self.assertEqual(msgs[-1]["feedback"], "not_helpful")
        other = self.user_client("Omar", "omar@test.io")
        self.assertEqual(other.post("/api/feedback", json={"kind": "chat", "message_id": mid, "rating": "helpful"}).status_code, 404)


class AiProviderTests(Base):
    keys = {"GROQ_API_KEY": "gsk_test", "GEMINI_API_KEY": "AIza_test", "GROQ_MODEL": "g-model", "GEMINI_MODEL": "m-model"}

    def setUp(self):
        super().setUp()
        self.u = self.user_client()
        self.cid = self.conv(self.u)

    def send(self, text="anything at all"):
        return self.u.post(f"/api/conversations/{self.cid}/messages", json={"message": text}).get_json()["message"]

    def patched(self, groq=None, gemini=None):
        return mock.patch.dict(ai.CALLERS, {
            "groq": groq or mock.Mock(return_value="Groq says hi"),
            "gemini": gemini or mock.Mock(return_value="Gemini says hi"),
        })

    def test_auto_prefers_groq(self):
        with self.patched():
            m = self.send()
        self.assertEqual((m["source"], m["content"], m["model"]), ("groq", "Groq says hi", "g-model"))
        self.assertIsNone(m["notice"])

    def test_user_can_prefer_gemini(self):
        self.u.patch("/api/me", json={"ai_provider": "gemini"})
        with self.patched():
            self.assertEqual(self.send()["source"], "gemini")

    def test_groq_failure_falls_back_to_gemini(self):
        with self.patched(groq=mock.Mock(side_effect=ai.AIUnavailable("x"))):
            m = self.send()
        self.assertEqual(m["source"], "gemini")
        self.assertIn("Groq was unavailable", m["notice"])

    def test_both_fail_falls_back_to_help_centre(self):
        boom = mock.Mock(side_effect=ai.AIUnavailable("x"))
        with self.patched(groq=boom, gemini=boom):
            m = self.send("refund")
        self.assertEqual(m["source"], "faq")
        self.assertIn("unavailable", m["notice"])

    def test_history_and_system_prompt_sent_to_provider(self):
        groq = mock.Mock(return_value="ok")
        with self.patched(groq=groq):
            self.send("first question")
            self.send("second question")
        system, history, message, key, model = groq.call_args[0]
        self.assertIn("HELP-CENTRE ARTICLES", system)
        self.assertIn("Sara Khan", system)
        self.assertEqual(message, "second question")
        self.assertEqual(history[0]["content"], "first question")
        self.assertEqual((key, model), ("gsk_test", "g-model"))

    def test_http_errors_become_unavailable(self):
        for status in (401, 404, 429, 500):
            with mock.patch.object(ai.requests, "post", return_value=mock.Mock(status_code=status)):
                with self.assertRaises(ai.AIUnavailable):
                    ai.call_groq("s", [], "m", "k", "model")
                with self.assertRaises(ai.AIUnavailable):
                    ai.call_gemini("s", [], "m", "k", "model")

    def test_network_error_and_bad_json(self):
        with mock.patch.object(ai.requests, "post", side_effect=ai.requests.ConnectionError()):
            with self.assertRaises(ai.AIUnavailable):
                ai.call_groq("s", [], "m", "k", "model")
        bad = mock.Mock(status_code=200)
        bad.json.return_value = {"unexpected": True}
        with mock.patch.object(ai.requests, "post", return_value=bad):
            with self.assertRaises(ai.AIUnavailable):
                ai.call_gemini("s", [], "m", "k", "model")

    def test_groq_and_gemini_request_shape(self):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"choices": [{"message": {"content": " hello "}}]}
        with mock.patch.object(ai.requests, "post", return_value=ok) as post:
            self.assertEqual(ai.call_groq("SYS", [{"role": "user", "content": "a"}], "b", "KEY", "mdl"), "hello")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer KEY")
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0], {"role": "system", "content": "SYS"})
        ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": "hi there"}]}}]}
        with mock.patch.object(ai.requests, "post", return_value=ok) as post:
            self.assertEqual(ai.call_gemini("SYS", [{"role": "assistant", "content": "x"}], "b", "KEY", "mdl"), "hi there")
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "KEY")
        self.assertEqual([c["role"] for c in post.call_args.kwargs["json"]["contents"]], ["user"])  # leading model turn dropped

    def test_placeholder_keys_are_ignored(self):
        for v in ("", "  ", "your_key_here", "paste-your-key", "<key>"):
            self.assertEqual(ai.clean_key(v), "")
        self.assertEqual(ai.clean_key(' "gsk_abc" '), "gsk_abc")

    def test_admin_connection_test(self):
        admin = self.admin_client()
        with mock.patch.object(ai.requests, "post", return_value=mock.Mock(status_code=401)):
            r = admin.post("/api/admin/ai/test", json={"provider": "groq"}).get_json()
        self.assertFalse(r["ok"])
        self.assertIn("rejected", r["message"])
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"choices": [{"message": {"content": "OK"}}]}
        with mock.patch.object(ai.requests, "post", return_value=ok):
            r = admin.post("/api/admin/ai/test", json={"provider": "groq"}).get_json()
        self.assertTrue(r["ok"])
        self.assertEqual(admin.post("/api/admin/ai/test", json={"provider": "nope"}).status_code, 400)
        self.assertEqual(self.u.post("/api/admin/ai/test", json={"provider": "groq"}).status_code, 403)


class ModelFallbackTests(unittest.TestCase):
    def test_retired_model_skipped_to_next(self):
        calls = []

        def fake(system, history, message, key, model):
            calls.append(model)
            if model == "old-model":
                raise ai.AIUnavailable("gone", model_problem=True)
            return "answer from " + model

        with mock.patch.dict(ai.CALLERS, {"groq": fake}):
            text, used = ai.call_models("groq", "s", [], "m", "k", "old-model, new-model")
        self.assertEqual((text, used, calls), ("answer from new-model", "new-model", ["old-model", "new-model"]))

    def test_real_errors_do_not_try_other_models(self):
        fake = mock.Mock(side_effect=ai.AIUnavailable("rate limit", model_problem=False))
        with mock.patch.dict(ai.CALLERS, {"groq": fake}):
            with self.assertRaises(ai.AIUnavailable):
                ai.call_models("groq", "s", [], "m", "k", "a,b")
        self.assertEqual(fake.call_count, 1)

    def test_all_models_retired(self):
        fake = mock.Mock(side_effect=ai.AIUnavailable("gone", model_problem=True))
        with mock.patch.dict(ai.CALLERS, {"gemini": fake}):
            with self.assertRaises(ai.AIUnavailable):
                ai.call_models("gemini", "s", [], "m", "k", "a,b,c")
        self.assertEqual(fake.call_count, 3)

    def test_http_404_and_400_flag_model_problem(self):
        for status in (400, 404):
            with mock.patch.object(ai.requests, "post", return_value=mock.Mock(status_code=status)):
                with self.assertRaises(ai.AIUnavailable) as ctx:
                    ai.call_groq("s", [], "m", "k", "x")
            self.assertTrue(ctx.exception.model_problem)
        with mock.patch.object(ai.requests, "post", return_value=mock.Mock(status_code=429)):
            with self.assertRaises(ai.AIUnavailable) as ctx:
                ai.call_groq("s", [], "m", "k", "x")
        self.assertFalse(ctx.exception.model_problem)

    def test_defaults_are_current_models(self):
        from app import create_app as _c  # noqa: F401
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"GROQ_MODEL": "", "GEMINI_MODEL": ""}):
            a = _c({"TESTING": True, "DATABASE": os.path.join(d, "x.db"), "SECRET_KEY": "k"})
            self.assertNotIn("llama-3.3-70b-versatile", a.config["GROQ_MODEL"])
            self.assertTrue(a.config["GROQ_MODEL"].startswith("openai/gpt-oss"))


class NoKeyAdminTests(Base):
    def test_connection_test_without_key(self):
        r = self.admin_client().post("/api/admin/ai/test", json={"provider": "gemini"}).get_json()
        self.assertFalse(r["ok"])
        self.assertIn(".env", r["message"])


# ===================================================================================== help centre
class FaqTests(Base):
    def setUp(self):
        super().setUp()
        self.u = self.user_client()

    def test_list_filter_search(self):
        self.assertGreaterEqual(self.u.get("/api/faqs").get_json()["count"], 20)
        data = self.u.get("/api/faqs?category=Billing").get_json()
        self.assertTrue(data["faqs"] and all(f["category"] == "Billing" for f in data["faqs"]))
        self.assertIn("refund", self.u.get("/api/faqs?q=refund").get_json()["faqs"][0]["question"].lower())
        self.assertEqual(self.u.get("/api/faqs?q=zzzzqqq").get_json()["count"], 0)
        self.assertEqual(self.u.get("/api/faqs?q=password&category=Billing").get_json()["count"], 0)


# ===================================================================================== tickets
class TicketTests(Base):
    def setUp(self):
        super().setUp()
        self.u = self.user_client()
        self.admin = self.admin_client()

    def test_create_and_view(self):
        r = self.ticket(self.u)
        self.assertEqual(r.status_code, 201)
        t = r.get_json()["ticket"]
        self.assertEqual((t["ref"], t["status"]), ("SS-0001", "Open"))
        self.assertIn("Invoice export fails", self.u.get("/app/tickets").get_data(as_text=True))
        self.assertEqual(self.u.get(f"/app/tickets/{t['id']}").status_code, 200)

    def test_validation_errors(self):
        r = self.u.post("/api/tickets", json={"subject": "hi", "category": "x", "description": "short", "priority": "z"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.get_json()["errors"]), {"subject", "category", "description", "priority"})

    def test_tickets_private_to_owner(self):
        tid = self.ticket(self.u).get_json()["ticket"]["id"]
        other = self.user_client("Omar", "omar@test.io")
        self.assertEqual(other.get(f"/app/tickets/{tid}").status_code, 404)
        self.assertEqual(other.post(f"/api/tickets/{tid}/replies", json={"body": "hello"}).status_code, 404)
        self.assertEqual(other.patch(f"/api/tickets/{tid}", json={"status": "Closed"}).status_code, 404)
        self.assertNotIn("Invoice export", other.get("/app/tickets").get_data(as_text=True))

    def test_status_tabs_filter(self):
        self.ticket(self.u)
        self.assertIn("Invoice export", self.u.get("/app/tickets?status=Open").get_data(as_text=True))
        self.assertNotIn("Invoice export", self.u.get("/app/tickets?status=Resolved").get_data(as_text=True))

    def test_admin_reply_flow_with_unread_badge(self):
        tid = self.ticket(self.u).get_json()["ticket"]["id"]
        r = self.admin.post(f"/api/tickets/{tid}/replies", json={"body": "We are looking into it."})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["status"], "In Progress")  # first staff reply moves Open -> In Progress
        listing = self.u.get("/app/tickets").get_data(as_text=True)
        self.assertIn("New reply", listing)
        self.assertIn("dot-badge", listing)
        detail = self.u.get(f"/app/tickets/{tid}").get_data(as_text=True)
        self.assertIn("We are looking into it.", detail)
        self.assertNotIn("New reply", self.u.get("/app/tickets").get_data(as_text=True))  # read now

    def test_admin_sets_status_with_reply_and_user_reopens(self):
        tid = self.ticket(self.u).get_json()["ticket"]["id"]
        r = self.admin.post(f"/api/tickets/{tid}/replies", json={"body": "Fixed it.", "status": "Resolved"})
        self.assertEqual(r.get_json()["status"], "Resolved")
        r = self.u.post(f"/api/tickets/{tid}/replies", json={"body": "Still broken for me."})
        self.assertEqual(r.get_json()["status"], "Open")

    def test_reply_validation(self):
        tid = self.ticket(self.u).get_json()["ticket"]["id"]
        self.assertEqual(self.u.post(f"/api/tickets/{tid}/replies", json={"body": " "}).status_code, 400)
        self.assertEqual(self.u.post(f"/api/tickets/{tid}/replies", json={"body": "x" * 2001}).status_code, 400)
        self.assertEqual(self.admin.post(f"/api/tickets/{tid}/replies", json={"body": "ok", "status": "Nope"}).status_code, 400)

    def test_user_can_only_close(self):
        tid = self.ticket(self.u).get_json()["ticket"]["id"]
        self.assertEqual(self.u.patch(f"/api/tickets/{tid}", json={"status": "Resolved"}).status_code, 403)
        self.assertEqual(self.u.patch(f"/api/tickets/{tid}", json={"priority": "High"}).status_code, 403)
        self.assertEqual(self.u.patch(f"/api/tickets/{tid}", json={"status": "Closed"}).get_json()["ticket"]["status"], "Closed")

    def test_admin_update_status_and_priority(self):
        tid = self.ticket(self.u).get_json()["ticket"]["id"]
        r = self.admin.patch(f"/api/tickets/{tid}", json={"status": "Resolved", "priority": "High"}).get_json()["ticket"]
        self.assertEqual((r["status"], r["priority"]), ("Resolved", "High"))
        self.assertEqual(self.admin.patch(f"/api/tickets/{tid}", json={"status": "Bad"}).status_code, 400)

    def test_ticket_text_is_escaped_in_pages(self):
        tid = self.ticket(self.u, subject="<script>alert(1)</script>", description="<img src=x onerror=alert(1)> padding text").get_json()["ticket"]["id"]
        for client, url in ((self.u, f"/app/tickets/{tid}"), (self.u, "/app/tickets"), (self.admin, f"/admin/tickets/{tid}"), (self.admin, "/admin/tickets")):
            html = client.get(url).get_data(as_text=True)
            self.assertNotIn("<script>alert(1)</script>", html, url)
            self.assertNotIn("<img src=x", html, url)


# ===================================================================================== admin
class AdminTests(Base):
    def setUp(self):
        super().setUp()
        self.admin = self.admin_client()
        self.u = self.user_client()
        self.ticket(self.u)

    def test_all_admin_pages_render(self):
        for p in ("/admin", "/admin/tickets", "/admin/tickets/1", "/admin/faqs", "/admin/users", "/admin/feedback", "/admin/ai", "/app/settings"):
            self.assertEqual(self.admin.get(p).status_code, 200, p)
        self.assertEqual(self.admin.get("/admin/tickets/999").status_code, 404)

    def test_overview_numbers_and_charts(self):
        cid = self.conv(self.u)
        self.u.post(f"/api/conversations/{cid}/messages", json={"message": "refund"})
        self.u.post("/api/feedback", json={"kind": "experience", "rating": "4"})
        html = self.admin.get("/admin").get_data(as_text=True)
        self.assertIn("Overview", html)
        self.assertIn("4.0", html)
        self.assertIn("No AI keys are connected", html)

    def test_ticket_filters_search_and_pagination(self):
        for i in range(14):
            self.ticket(self.u, subject=f"Bulk ticket number {i:02d}", category="Security", priority="High")
        html = self.admin.get("/admin/tickets").get_data(as_text=True)
        self.assertIn("Page 1 of 2", html)
        self.assertIn("Page 2 of 2", self.admin.get("/admin/tickets?page=2").get_data(as_text=True))
        self.assertIn("Page 2 of 2", self.admin.get("/admin/tickets?page=99").get_data(as_text=True))
        html = self.admin.get("/admin/tickets?q=Invoice export").get_data(as_text=True)
        self.assertIn("Invoice export fails", html)
        self.assertNotIn("Bulk ticket", html)
        self.assertIn("SS-0001", self.admin.get("/admin/tickets?q=SS-0001").get_data(as_text=True))
        self.assertNotIn("Invoice export", self.admin.get("/admin/tickets?category=Security").get_data(as_text=True))
        self.assertIn("No tickets found", self.admin.get("/admin/tickets?priority=Low").get_data(as_text=True))

    def test_faq_crud_affects_help_centre_and_chatbot(self):
        good = {"category": "Billing", "question": "Do you offer student discounts?", "answer": "Yes, students get 20% off with a valid ID.", "keywords": "discount student"}
        r = self.admin.post("/api/admin/faqs", json=good)
        self.assertEqual(r.status_code, 201)
        fid = r.get_json()["faq"]["id"]
        cid = self.conv(self.u)
        m = self.u.post(f"/api/conversations/{cid}/messages", json={"message": "student discount"}).get_json()["message"]
        self.assertIn("20% off", m["content"])
        self.assertEqual(self.admin.put(f"/api/admin/faqs/{fid}", json={**good, "answer": "Now 30% off for students."}).status_code, 200)
        self.assertIn("30% off", self.u.get("/api/faqs?q=student").get_data(as_text=True))
        self.assertEqual(self.admin.delete(f"/api/admin/faqs/{fid}").status_code, 200)
        self.assertEqual(self.admin.delete(f"/api/admin/faqs/{fid}").status_code, 404)

    def test_faq_validation(self):
        r = self.admin.post("/api/admin/faqs", json={"category": "x", "question": "no", "answer": "short"})
        self.assertEqual(set(r.get_json()["errors"]), {"category", "question", "answer"})

    def test_user_management(self):
        self.assertEqual(self.admin.patch("/api/admin/users/2", json={"role": "admin"}).status_code, 200)
        self.assertEqual(self.u.get("/admin").status_code, 200)
        self.assertEqual(self.admin.patch("/api/admin/users/2", json={"role": "wizard"}).status_code, 400)
        self.assertEqual(self.admin.patch("/api/admin/users/1", json={"is_active": False}).status_code, 409)  # not yourself
        self.assertEqual(self.admin.patch("/api/admin/users/99", json={"role": "user"}).status_code, 404)

    def test_feedback_page_lists_items(self):
        self.u.post("/api/feedback", json={"kind": "experience", "rating": "5", "comment": "Love it"})
        html = self.admin.get("/admin/feedback").get_data(as_text=True)
        self.assertIn("Love it", html)


# ===================================================================================== settings
class SettingsTests(Base):
    def setUp(self):
        super().setUp()
        self.u = self.user_client()

    def test_update_profile_and_preferences(self):
        r = self.u.patch("/api/me", json={"name": "Sara K", "email": "new@test.io", "theme": "dark", "text_size": "large", "ai_provider": "auto"})
        self.assertEqual(r.status_code, 200)
        html = self.u.get("/app").get_data(as_text=True)
        self.assertIn('data-theme="dark"', html)
        self.assertIn('data-textsize="large"', html)
        self.assertIn("Hello, Sara", html)
        self.assertEqual(self.login(self.app.test_client(), "new@test.io", "Passw0rd1").status_code, 302)

    def test_validation_and_duplicate_email(self):
        self.user_client("Omar", "omar@test.io")
        r = self.u.patch("/api/me", json={"name": "", "email": "bad", "theme": "pink", "text_size": "huge", "ai_provider": "x"})
        self.assertEqual(set(r.get_json()["errors"]), {"name", "email", "theme", "text_size", "ai_provider"})
        r = self.u.patch("/api/me", json={"email": "omar@test.io"})
        self.assertIn("already uses", r.get_json()["errors"]["email"])

    def test_change_password(self):
        self.assertEqual(self.u.post("/api/me/password", json={"current": "wrong", "new": "NewPass123"}).status_code, 400)
        self.assertEqual(self.u.post("/api/me/password", json={"current": "Passw0rd1", "new": "short"}).status_code, 400)
        self.assertEqual(self.u.post("/api/me/password", json={"current": "Passw0rd1", "new": "NewPass123"}).status_code, 200)
        self.assertEqual(self.login(self.app.test_client(), "sara@test.io", "NewPass123").status_code, 302)
        self.assertIn("Incorrect", self.login(self.app.test_client(), "sara@test.io", "Passw0rd1").get_data(as_text=True))

    def test_delete_account_removes_data(self):
        self.ticket(self.u)
        cid = self.conv(self.u)
        self.u.post(f"/api/conversations/{cid}/messages", json={"message": "hello"})
        self.assertEqual(self.u.delete("/api/me", json={"password": "nope"}).status_code, 400)
        self.assertEqual(self.u.delete("/api/me", json={"password": "Passw0rd1"}).status_code, 200)
        self.assertEqual(self.u.get("/app").status_code, 302)
        self.assertEqual(self.login(self.app.test_client(), "sara@test.io", "Passw0rd1").status_code, 200)
        admin = self.admin_client()
        self.assertNotIn("Invoice export", admin.get("/admin/tickets").get_data(as_text=True))

    def test_last_admin_cannot_delete_self(self):
        r = self.admin_client().delete("/api/me", json={"password": ADMIN[1]})
        self.assertEqual(r.status_code, 409)


class MiscTests(Base):
    def test_404_pages(self):
        r = self.c.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Page not found", r.get_data(as_text=True))
        self.assertEqual(self.c.get("/api/nope").get_json()["error"][:5], "We co")

    def test_landing_changes_when_logged_in(self):
        self.assertIn("Create free account", self.c.get("/").get_data(as_text=True))
        cl = self.user_client()
        self.assertIn("Open dashboard", cl.get("/").get_data(as_text=True))

    def test_private_pages_not_cached(self):
        cl = self.user_client()
        self.assertEqual(cl.get("/app").headers.get("Cache-Control"), "no-store")

    def test_secret_key_persisted_between_runs(self):
        from app import load_secret_key
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"SECRET_KEY": ""}):
                self.assertEqual(load_secret_key(d), load_secret_key(d))

    def test_dashboard_and_pages_render_for_user(self):
        cl = self.user_client()
        for p in ("/app", "/app/chat", "/app/help", "/app/tickets", "/app/settings"):
            self.assertEqual(cl.get(p).status_code, 200, p)


class KnowledgeBaseUnitTests(unittest.TestCase):
    FAQS = [
        {"id": 1, "category": "Billing", "question": "How do I request a refund?", "answer": "Submit a ticket.", "keywords": "refund money"},
        {"id": 2, "category": "Account Access", "question": "How do I reset my password?", "answer": "Use forgot password.", "keywords": "password reset"},
    ]

    def test_tokenize(self):
        self.assertEqual(ai.tokenize("How do I reset my password"), {"reset", "password"})

    def test_ranking(self):
        self.assertEqual(ai.rank_faqs(self.FAQS, "I want my money back refund")[0][1]["id"], 1)

    def test_no_match(self):
        self.assertIsNone(ai.faq_reply(self.FAQS, "purple elephants"))

    def test_provider_order(self):
        cfg = {"GROQ_API_KEY": "a", "GEMINI_API_KEY": "b"}
        self.assertEqual(ai.provider_order(cfg, "auto"), ["groq", "gemini"])
        self.assertEqual(ai.provider_order(cfg, "gemini"), ["gemini", "groq"])
        self.assertEqual(ai.provider_order({"GROQ_API_KEY": "a", "GEMINI_API_KEY": ""}, "gemini"), ["groq"])
        self.assertEqual(ai.provider_order({}, "auto"), [])


if __name__ == "__main__":
    unittest.main()

import base64
import copy
import hashlib
from http.client import HTTPConnection
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch
import tempfile
import threading
import traceback
import unittest
from urllib.parse import urlencode, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa

from chatgpt_auth import ChatGPTPlanError, ChatGPTPlanSession, get_chatgpt_session
from secret_store import DpapiSecretStore, MemorySecretStore, create_secret_store


from tests.support.chatgpt_oauth import (
    b64,
    Response,
    OAuthServer,
    Listener,
)

ISSUER = "https://auth.openai.com"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


class ChatGPTSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "profile"
        self.store = MemorySecretStore()
        self.server = OAuthServer(self.key)
        self.callback = self.server.callback
        self.listeners = []
        self.session = self.make_session()

    def make_session(self):
        def listener_factory():
            listener = Listener(lambda: self.callback())
            self.listeners.append(listener)
            return listener

        return ChatGPTPlanSession(
            self.directory,
            secret_store=self.store,
            http=self.server,
            clock=lambda: self.server.now,
            listener_factory=listener_factory,
        )

    def sign_in(self, **kwargs):
        self.session.sign_in(open_browser=self.server.browser, **kwargs)

    def token_calls(self, grant):
        return [
            call
            for call in self.server.calls
            if (call[2].get("data") or {}).get("grant_type") == grant
        ]

    def assert_code(self, code, action):
        with self.assertRaises(ChatGPTPlanError) as raised:
            action()
        self.assertEqual(raised.exception.code, code)
        self.assertNotIn(
            "SECRET", "".join(traceback.format_exception(raised.exception))
        )

    def test_personal_key_write_cannot_restore_a_rotated_chatgpt_token(self):
        def session():
            return ChatGPTPlanSession(
                self.directory,
                http=self.server,
                clock=lambda: self.server.now,
                listener_factory=lambda: Listener(self.server.callback),
            )

        active = session()
        active.sign_in(open_browser=self.server.browser)
        keys = create_secret_store(self.directory)
        keys.set("openai", "old-api-key")
        loaded, release = threading.Event(), threading.Event()
        original_encode = keys._encode

        def pause_after_loading(entries):
            loaded.set()
            if not release.wait(5):
                raise RuntimeError("key writer timed out")
            return original_encode(entries)

        failures = []

        def write_key():
            try:
                keys.set("openai", "new-api-key")
            except Exception as error:
                failures.append(error)

        with patch.object(keys, "_encode", side_effect=pause_after_loading):
            writer = threading.Thread(target=write_key)
            writer.start()
            try:
                self.assertTrue(loaded.wait(3))
                self.server.now += 3570
                self.assertEqual(active.credential().access_token, "rotated-access")
            finally:
                release.set()
                writer.join(5)
        self.assertFalse(writer.is_alive())
        self.assertFalse(failures)
        self.assertEqual(session().credential().access_token, "rotated-access")
        self.assertEqual(len(self.token_calls("refresh_token")), 1)
        self.assertEqual(
            create_secret_store(self.directory).get("openai"), "new-api-key"
        )

    def test_constructor_and_snapshot_do_not_write(self):
        self.assertEqual(
            self.session.snapshot(),
            {
                "connected": False,
                "planEnabled": False,
                "email": "",
                "accountId": "",
                "accounts": [],
                "generation": 0,
                "planNoticeSeen": False,
            },
        )
        self.assertFalse(self.directory.exists())
        self.assertFalse(self.store.values)
        self.assertFalse(self.server.calls)

    def test_first_authorization_uses_issued_client_and_exact_pkce_redirect(self):
        def browser(url):
            self.assertEqual(len(self.listeners), 1)
            self.assertIn("ext_agent_host_id", json.loads(self.store.get("chatgpt")))
            return self.server.browser(url)

        self.session.sign_in(open_browser=browser)
        query = self.server.query
        self.assertEqual(query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["agent_name_hint"], ["Clarify"])
        self.assertEqual(set(query["scope"][0].split()), set(SCOPES.split()))
        self.assertEqual(query["resource"], ["https://api.openai.com/v1"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        call = self.token_calls("authorization_code")[0]
        data = call[2]["data"]
        self.assertEqual(data["client_id"], "oaiapp_first")
        self.assertEqual(data["redirect_uri"], query["redirect_uri"][0])
        self.assertEqual(
            query["code_challenge"],
            [b64(hashlib.sha256(data["code_verifier"].encode()).digest())],
        )
        self.assertEqual(data["resource"], "https://api.openai.com/v1")
        self.assertTrue(self.listeners[0].closed)
        snapshot = self.session.snapshot()
        self.assertTrue(snapshot["connected"])
        self.assertTrue(snapshot["planEnabled"])
        self.assertNotIn("first-access", json.dumps(snapshot))
        credential = self.session.credential()
        self.assertEqual(credential.access_token, "first-access")
        self.session.check_current(credential.generation)

    def test_failed_initial_exchange_recovers_issued_registration_after_restart(self):
        def session():
            return ChatGPTPlanSession(
                self.directory,
                http=self.server,
                clock=lambda: self.server.now,
                monotonic=lambda: self.server.now,
                listener_factory=lambda: Listener(lambda: self.callback()),
            )

        records_at_exchange = []
        self.server.before_token = lambda: records_at_exchange.append(
            json.loads(
                create_secret_store(
                    self.directory, filename_stem="chatgpt-secrets"
                ).get("chatgpt")
            )
        )
        self.callback = lambda: self.server.callback(code="spent-code")
        self.server.code_error = "invalid_grant"
        first_session = session()
        self.assert_code(
            "authorization_failed",
            lambda: first_session.sign_in(open_browser=self.server.browser),
        )
        first_query = copy.deepcopy(self.server.query)
        self.assertEqual(
            records_at_exchange[0].get("pending_client_id"), "oaiapp_first"
        )
        self.assertEqual(records_at_exchange[0]["active"], "")
        self.assertEqual(records_at_exchange[0]["accounts"], {})
        self.assertFalse(first_session.snapshot()["connected"])
        self.assert_code("sign_in_required", first_session.credential)

        recovered = session()
        self.assertEqual(recovered.snapshot()["accounts"], [])
        self.server.code_error = ""
        self.callback = lambda: self.server.callback(client=False, code="fresh-code")
        recovered.sign_in(open_browser=self.server.browser)
        query = self.server.query
        self.assertEqual(first_query["client_id"], ["dynamic_agent_client"])
        self.assertEqual(query["client_id"], ["oaiapp_first"])
        self.assertEqual(query["ext_agent_host_id"], first_query["ext_agent_host_id"])
        for name in ("state", "nonce", "code_challenge"):
            self.assertNotEqual(query[name], first_query[name])
        for name in ("id_token_hint", "login_hint", "agent_name_hint"):
            self.assertNotIn(name, query)
        calls = self.token_calls("authorization_code")
        self.assertEqual(
            [call[2]["data"]["code"] for call in calls], ["spent-code", "fresh-code"]
        )
        self.assertNotEqual(
            calls[0][2]["data"]["code_verifier"], calls[1][2]["data"]["code_verifier"]
        )
        for call in calls:
            self.assertEqual(call[2]["data"]["client_id"], "oaiapp_first")
        self.assertEqual(records_at_exchange[1]["active"], "")
        self.assertEqual(records_at_exchange[1]["accounts"], {})
        status = recovered.snapshot()
        self.assertTrue(status["connected"])
        self.assertEqual(len(status["accounts"]), 1)
        saved = json.loads(
            create_secret_store(self.directory, filename_stem="chatgpt-secrets").get(
                "chatgpt"
            )
        )
        self.assertFalse(saved.get("pending_client_id"))
        self.assertEqual(
            saved["accounts"][status["accountId"]]["client_id"], "oaiapp_first"
        )

    def test_failed_add_account_preserves_selection_and_resumes_only_when_requested(
        self,
    ):
        self.sign_in()
        before = self.session.snapshot()
        first_record = copy.deepcopy(json.loads(self.store.get("chatgpt"))["accounts"])
        self.server.client = "oaiapp_second"
        self.server.code_error = "invalid_grant"
        self.assert_code("authorization_failed", lambda: self.sign_in(new_account=True))
        host = self.server.query["ext_agent_host_id"]
        self.assertEqual(self.session.snapshot(), before)
        self.assertEqual(
            json.loads(self.store.get("chatgpt"))["accounts"], first_record
        )
        self.assertEqual(self.session.credential().access_token, "first-access")

        self.session = self.make_session()
        self.server.code_error = ""
        self.server.client = "oaiapp_first"
        self.sign_in()
        self.assertEqual(self.server.query["client_id"], ["oaiapp_first"])
        self.assertEqual(
            json.loads(self.store.get("chatgpt"))["pending_client_id"], "oaiapp_second"
        )
        first_record = copy.deepcopy(json.loads(self.store.get("chatgpt"))["accounts"])
        self.server.client = "oaiapp_second"
        self.callback = lambda: self.server.callback(client=False)
        self.sign_in(new_account=True)
        self.assertEqual(self.server.query["client_id"], ["oaiapp_second"])
        self.assertEqual(self.server.query["ext_agent_host_id"], host)
        self.assertNotIn("id_token_hint", self.server.query)
        status = self.session.snapshot()
        self.assertEqual(len(status["accounts"]), 2)
        self.assertNotEqual(status["accountId"], before["accountId"])
        self.assertEqual(
            json.loads(self.store.get("chatgpt"))["accounts"][before["accountId"]],
            first_record[before["accountId"]],
        )

    def test_pending_registration_rejects_callback_and_identity_mismatches(self):
        self.server.code_error = "invalid_grant"
        self.assert_code("authorization_failed", self.sign_in)
        pending = self.store.get("chatgpt")
        before = len(self.token_calls("authorization_code"))
        self.server.code_error = ""
        self.callback = lambda: self.server.callback(client="oaiapp_other")
        self.assert_code("registration_mismatch", self.sign_in)
        self.assertEqual(len(self.token_calls("authorization_code")), before)
        self.callback = lambda: self.server.callback(client=False)
        self.server.claims_override = {"nonce": "wrong"}
        self.assert_code("identity_invalid", self.sign_in)
        self.assertEqual(self.store.get("chatgpt"), pending)
        self.assertEqual(self.session.snapshot()["accounts"], [])
        self.assert_code("sign_in_required", self.session.credential)

    def test_pending_registration_is_retained_when_exchange_is_cancelled(self):
        cancel = threading.Event()
        self.server.before_token = cancel.set
        self.assert_code("cancelled", lambda: self.sign_in(cancel=cancel))
        saved = json.loads(self.store.get("chatgpt"))
        self.assertEqual(saved["pending_client_id"], "oaiapp_first")
        self.assertEqual(saved["active"], "")
        self.assertEqual(saved["accounts"], {})
        self.assertTrue(self.listeners[-1].closed)
        self.server.before_token = None
        self.callback = lambda: self.server.callback(client=False, code="fresh-code")
        self.session = self.make_session()
        self.sign_in()
        self.assertEqual(self.server.query["client_id"], ["oaiapp_first"])
        self.assertEqual(len(self.session.snapshot()["accounts"]), 1)

    def test_cancelled_callback_cannot_save_an_issued_registration(self):
        cancel = threading.Event()

        def callback():
            cancel.set()
            return self.server.callback()

        self.callback = callback
        self.assert_code("cancelled", lambda: self.sign_in(cancel=cancel))
        self.assertFalse(self.token_calls("authorization_code"))
        self.assertFalse(json.loads(self.store.get("chatgpt")).get("pending_client_id"))
        self.assertEqual(self.session.snapshot()["accounts"], [])

    def test_pending_save_failure_stops_before_the_code_is_sent(self):
        original = self.store.set

        def save(provider, value):
            if json.loads(value).get("pending_client_id"):
                raise OSError("SECRET storage diagnostics")
            original(provider, value)

        with patch.object(self.store, "set", side_effect=save):
            self.assert_code("storage_unavailable", self.sign_in)
        self.assertFalse(self.token_calls("authorization_code"))
        self.assertFalse(self.session.snapshot()["connected"])
        self.assertFalse(json.loads(self.store.get("chatgpt")).get("pending_client_id"))
        self.assertTrue(self.listeners[-1].closed)

    def test_pending_field_is_bounded_and_invalid_records_are_not_overwritten(self):
        self.sign_in()
        saved = json.loads(self.store.get("chatgpt"))
        for value in (
            None,
            False,
            1,
            [],
            {},
            "dynamic_agent_client",
            "x" * 1025,
            "bad\nID",
        ):
            with self.subTest(value=value):
                data = copy.deepcopy(saved)
                data["pending_client_id"] = value
                raw = json.dumps(data)
                self.store.set("chatgpt", raw)
                before = len(self.server.calls)
                self.assert_code("storage_invalid", self.session.snapshot)
                self.assert_code("storage_invalid", self.sign_in)
                self.assertEqual(len(self.server.calls), before)
                self.assertEqual(self.store.get("chatgpt"), raw)
        data = copy.deepcopy(saved)
        data.update(
            accounts={},
            active="",
            ext_agent_host_id="",
            pending_client_id="oaiapp_pending",
        )
        self.store.set("chatgpt", json.dumps(data))
        self.assert_code("storage_invalid", self.sign_in)

    def test_other_session_change_rejects_stale_pending_callback_or_tokens(self):
        self.store = create_secret_store(
            self.directory, filename_stem="chatgpt-secrets"
        )
        self.session = self.make_session()
        self.sign_in()
        active = self.session.snapshot()["accountId"]
        other = ChatGPTPlanSession(self.directory)
        self.server.client = "oaiapp_second"
        for phase in ("callback", "exchange"):
            with self.subTest(phase=phase):

                def change_selection():
                    other.select_account(active)

                def callback():
                    change_selection()
                    return self.server.callback()

                self.callback = (
                    callback if phase == "callback" else self.server.callback
                )
                self.server.before_token = (
                    change_selection if phase == "exchange" else None
                )
                before = len(self.token_calls("authorization_code"))
                self.assert_code("cancelled", lambda: self.sign_in(new_account=True))
                saved = json.loads(self.store.get("chatgpt"))
                self.assertEqual(saved["active"], active)
                self.assertEqual(len(saved["accounts"]), 1)
                self.assertEqual(
                    bool(saved.get("pending_client_id")), phase == "exchange"
                )
                self.assertEqual(
                    len(self.token_calls("authorization_code")),
                    before + (phase == "exchange"),
                )
                self.assertTrue(self.listeners[-1].closed)

    def test_plan_notice_is_per_registration_and_persists(self):
        self.assert_code("plan_disabled", self.session.acknowledge_plan_notice)
        self.sign_in()
        self.session.acknowledge_plan_notice()
        self.assertTrue(self.make_session().snapshot()["planNoticeSeen"])
        self.server.client = "oaiapp_second"
        self.sign_in(new_account=True)
        self.assertFalse(self.session.snapshot()["planNoticeSeen"])
        first_id = self.session.snapshot()["accounts"][0]["id"]
        self.session.select_account(first_id)
        self.assertTrue(self.session.snapshot()["planNoticeSeen"])

    def test_callback_validation_precedes_exchange_and_preserves_active(self):
        self.sign_in()
        previous = self.session.snapshot()
        cases = [
            lambda: self.server.callback(state="wrong-state"),
            lambda: self.server.callback(client=False),
            lambda: self.server.callback(client="dynamic_agent_client"),
            lambda: self.server.callback().replace("/auth/callback", "/callback"),
            lambda: self.server.callback().replace("127.0.0.1", "localhost"),
            lambda: self.server.callback() + "&state=duplicate",
            lambda: self.server.callback() + "#fragment",
            lambda: self.server.callback(error="access_denied"),
        ]
        for callback in cases:
            with self.subTest(callback=cases.index(callback)):
                before = len(self.token_calls("authorization_code"))
                self.callback = callback
                self.assert_code(
                    "callback_invalid", lambda: self.sign_in(new_account=True)
                )
                self.assertEqual(self.session.snapshot(), previous)
                self.assertEqual(len(self.token_calls("authorization_code")), before)

    def test_decline_checks_state_and_never_exchanges(self):
        def callback():
            return (
                self.server.query["redirect_uri"][0]
                + "?"
                + urlencode(
                    {
                        "state": self.server.query["state"][0],
                        "error": "access_denied",
                        "error_description": "SECRET untrusted text",
                    }
                )
            )

        self.callback = callback
        self.assert_code("access_denied", self.sign_in)
        self.assertFalse(self.token_calls("authorization_code"))
        self.assertFalse(self.session.snapshot()["connected"])

    def test_actual_signed_claims_are_validated_before_activation(self):
        self.sign_in()
        previous = self.session.snapshot()
        for claims in (
            {"nonce": "wrong"},
            {"aud": "other-client"},
            {"iss": "https://evil.test"},
            {"exp": self.server.now},
            {"exp": True},
            {"sub": ""},
            {"nbf": self.server.now + 100},
            {"aud": ["oaiapp_first", "other-client"]},
            {"azp": "other-client"},
        ):
            with self.subTest(claims=claims):
                self.server.claims_override = claims
                self.assert_code(
                    "identity_invalid", lambda: self.sign_in(new_account=True)
                )
                self.assertEqual(self.session.snapshot(), previous)

    def test_bad_signature_and_unsigned_algorithm_are_rejected(self):
        self.server.token_override = {"id_token": "eyJhbGciOiJub25lIn0.e30.ZmFrZQ"}
        self.assert_code("identity_invalid", self.sign_in)
        self.server.token_override = {}
        original = self.server.id_token

        def tampered():
            header, claims, signature = original().split(".")
            data = json.loads(
                base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4))
            )
            data["email"] = "attacker@example.test"
            return ".".join((header, b64(json.dumps(data).encode()), signature))

        self.server.id_token = tampered
        self.assert_code("identity_invalid", self.sign_in)
        self.assertFalse(self.session.snapshot()["connected"])

    def test_scope_comes_from_token_response_and_id_only_stays_disabled(self):
        self.server.scopes = "openid profile email"
        self.server.token_override = {
            "access_token": "",
            "refresh_token": "",
            "expires_in": 0,
        }
        self.sign_in()
        status = self.session.snapshot()
        self.assertTrue(status["connected"])
        self.assertFalse(status["planEnabled"])
        self.assert_code("plan_disabled", self.session.credential)
        self.assert_code("plan_disabled", self.session.acknowledge_plan_notice)
        self.sign_in()
        self.assertEqual(self.server.query["client_id"], ["oaiapp_first"])
        self.assertEqual(self.server.query["prompt"], ["consent"])
        self.assertNotIn("force_reconsent", self.server.query)

    def test_returning_registration_reuses_host_client_and_fresh_security_values(self):
        self.sign_in()
        first = copy.deepcopy(self.server.query)
        session = self.make_session()
        self.callback = lambda: self.server.callback(client=False)
        session.sign_in(open_browser=self.server.browser)
        query = self.server.query
        self.assertEqual(query["client_id"], ["oaiapp_first"])
        self.assertEqual(query["ext_agent_host_id"], first["ext_agent_host_id"])
        self.assertNotIn("agent_name_hint", query)
        self.assertNotIn("prompt", query)
        self.assertIn("id_token_hint", query)
        self.assertEqual(query["login_hint"], ["same@example.test"])
        for key in ("state", "nonce", "code_challenge"):
            self.assertNotEqual(query[key], first[key])
        self.assertEqual(len(session.snapshot()["accounts"]), 1)

    def test_returning_callback_client_and_subject_cannot_replace_registration(self):
        self.sign_in()
        previous = self.store.get("chatgpt")
        self.callback = lambda: self.server.callback(client="other-client")
        self.assert_code("registration_mismatch", self.sign_in)
        self.callback = self.server.callback
        self.server.subject = "other-subject"
        self.assert_code("registration_mismatch", self.sign_in)
        self.assertEqual(self.store.get("chatgpt"), previous)

    def test_account_selection_uses_registration_not_email_and_invalidates_generation(
        self,
    ):
        self.sign_in()
        first = self.session.snapshot()["accountId"]
        old = self.session.credential()
        self.server.client = "oaiapp_second"
        self.sign_in(new_account=True)
        second = self.session.snapshot()["accountId"]
        self.assertNotEqual(first, second)
        labels = [item["label"] for item in self.session.snapshot()["accounts"]]
        self.assertEqual(len(set(labels)), 2)
        self.assert_code(
            "stale_session", lambda: self.session.check_current(old.generation)
        )
        calls = len(self.server.calls)
        self.session.select_account(first)
        self.assertEqual(len(self.server.calls), calls)
        self.assertEqual(self.session.snapshot()["accountId"], first)
        self.server.client = "oaiapp_first"
        self.sign_in()
        self.assertEqual(self.server.query["client_id"], ["oaiapp_first"])
        self.assertEqual(len(self.session.snapshot()["accounts"]), 2)

    def test_cancellation_after_exchange_does_not_replace_active(self):
        self.sign_in()
        previous = self.session.snapshot()
        cancel = threading.Event()
        self.server.before_token = cancel.set
        self.assert_code(
            "cancelled", lambda: self.sign_in(new_account=True, cancel=cancel)
        )
        self.assertEqual(self.session.snapshot(), previous)
        self.assertTrue(self.listeners[-1].closed)

    def test_signout_during_auth_exchange_prevents_late_activation(self):
        self.sign_in()
        self.server.before_token = self.session.sign_out
        self.assert_code("cancelled", lambda: self.sign_in(new_account=True))
        self.assertFalse(self.session.snapshot()["connected"])

    def test_auth_timeout_and_browser_exception_are_safe_and_close_listener(self):
        now = [0.0]
        self.session._monotonic = lambda: now[0]

        def browser(url):
            self.server.browser(url)
            now[0] = 200

        self.assert_code("timeout", lambda: self.session.sign_in(open_browser=browser))
        self.assertTrue(self.listeners[-1].closed)

        def failed_browser(url):
            raise OSError("SECRET " + url)

        self.assert_code(
            "browser_failed", lambda: self.session.sign_in(open_browser=failed_browser)
        )
        self.assertTrue(self.listeners[-1].closed)

    def test_refresh_rotation_is_serialized_and_persisted_as_one_token_set(self):
        self.sign_in()
        self.server.now += 3570
        self.server.release_refresh = threading.Event()
        values, failures = [], []

        def call():
            try:
                values.append(self.session.credential())
            except Exception as error:
                failures.append(error)

        first = threading.Thread(target=call)
        second = threading.Thread(target=call)
        first.start()
        self.assertTrue(self.server.refresh_started.wait(2))
        second.start()
        self.server.release_refresh.set()
        first.join(3)
        second.join(3)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(
            [value.access_token for value in values], ["rotated-access"] * 2
        )
        self.assertEqual(len(self.token_calls("refresh_token")), 1)
        data = self.token_calls("refresh_token")[0][2]["data"]
        self.assertEqual(
            data,
            {
                "grant_type": "refresh_token",
                "client_id": "oaiapp_first",
                "refresh_token": "first-refresh",
                "resource": "https://api.openai.com/v1",
            },
        )
        self.assertEqual(
            self.make_session().credential().access_token, "rotated-access"
        )
        persisted = json.loads(self.store.get("chatgpt"))
        record = persisted["accounts"][persisted["active"]]
        self.assertEqual(record["tokens"]["refresh_token"], "rotated-refresh")
        self.assertNotIn("refresh_pending", record)

    def test_uncertain_refresh_is_not_retried_or_replaced_even_after_restart(self):
        self.sign_in()
        prior = json.loads(self.store.get("chatgpt"))
        self.server.now += 3570
        self.server.fail_refresh = True
        self.assert_code("refresh_failed", self.session.credential)
        self.assert_code("refresh_failed", self.session.credential)
        self.assert_code("refresh_failed", self.make_session().credential)
        self.assertEqual(len(self.token_calls("refresh_token")), 1)
        data = json.loads(self.store.get("chatgpt"))
        self.assertEqual(
            data["accounts"][data["active"]]["tokens"],
            prior["accounts"][prior["active"]]["tokens"],
        )

    def test_signout_and_cancel_can_interrupt_refresh_without_waiting_for_http(self):
        self.sign_in()
        self.server.now += 3570
        self.server.release_refresh = threading.Event()
        result = []

        def call():
            try:
                self.session.credential()
            except ChatGPTPlanError as error:
                result.append(error.code)

        worker = threading.Thread(target=call)
        worker.start()
        self.assertTrue(self.server.refresh_started.wait(2))
        self.session.sign_out()
        self.assertFalse(self.session.snapshot()["connected"])
        self.server.release_refresh.set()
        worker.join(3)
        self.assertEqual(result, ["stale_session"])
        self.assertFalse(self.make_session().snapshot()["connected"])

    def test_waiting_refresh_checks_cancellation(self):
        self.sign_in()
        cancel = threading.Event()
        cancel.set()
        self.assert_code(
            "cancelled", lambda: self.session.credential(cancel_token=cancel)
        )
        self.assertFalse(self.token_calls("refresh_token"))

    def test_remote_revocation_failure_clears_locally_and_keeps_registration(self):
        self.sign_in()
        host = self.server.query["ext_agent_host_id"]
        old = self.session.credential()
        self.server.fail_revoke = True
        self.assert_code("revocation_failed", self.session.sign_out)
        status = self.session.snapshot()
        self.assertFalse(status["connected"])
        self.assertEqual(len(status["accounts"]), 1)
        self.assert_code(
            "stale_session", lambda: self.session.check_current(old.generation)
        )
        self.assert_code("sign_in_required", self.make_session().credential)
        self.sign_in()
        self.assertEqual(self.server.query["ext_agent_host_id"], host)
        self.assertEqual(self.server.query["client_id"], ["oaiapp_first"])
        self.assertNotIn("id_token_hint", self.server.query)

    def test_successful_revocation_posts_only_selected_refresh(self):
        self.sign_in()
        self.session.sign_out()
        revoke = [call for call in self.server.calls if call[1].endswith("/revoke")]
        self.assertEqual(len(revoke), 1)
        self.assertEqual(
            revoke[0][2]["data"],
            {
                "token": "first-refresh",
                "token_type_hint": "refresh_token",
                "client_id": "oaiapp_first",
            },
        )
        self.assertFalse(self.make_session().snapshot()["connected"])

    def test_getter_is_lazy_and_scoped_to_resolved_profile(self):
        first = get_chatgpt_session(self.directory)
        self.assertIs(first, get_chatgpt_session(self.directory / "."))
        self.assertIsNot(first, get_chatgpt_session(self.directory.parent / "other"))
        self.assertFalse(self.directory.exists())

    def test_transport_cleanup_never_exposes_remote_secrets(self):
        self.sign_in()
        self.server.now += 3570
        original = self.server.request

        def request(*args, **kwargs):
            response = original(*args, **kwargs)

            def close():
                raise OSError("SECRET close failure")

            response.close = close
            return response

        self.server.request = request
        self.assertEqual(self.session.credential().access_token, "rotated-access")

    def test_listener_cleanup_never_exposes_authorization_url(self):
        factory = self.session._listener_factory

        def listener_factory():
            listener = factory()

            def close():
                raise OSError("SECRET callback URL")

            listener.close = close
            return listener

        self.session._listener_factory = listener_factory
        self.sign_in()
        self.assertTrue(self.session.snapshot()["connected"])

    def test_explicit_null_scope_on_refresh_is_not_an_inherited_grant(self):
        self.sign_in()
        self.server.now += 3570
        original = self.server.request

        def request(*args, **kwargs):
            if (kwargs.get("data") or {}).get("grant_type") == "refresh_token":
                return Response(
                    {
                        "access_token": "bad-access",
                        "refresh_token": "bad-refresh",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                        "scope": None,
                    }
                )
            return original(*args, **kwargs)

        self.server.request = request
        self.assert_code("refresh_failed", self.session.credential)

    def test_discovery_and_jwks_are_bounded_and_remain_on_trusted_origin(self):
        original = self.server.request
        for field, value in (
            ("jwks_uri", "https://evil.test/keys"),
            ("issuer", "https://evil.test"),
            ("token_endpoint", ISSUER + "/other-token"),
        ):

            def request(*args, **kwargs):
                response = original(*args, **kwargs)
                payload = json.loads(response.raw)
                payload[field] = value
                return Response(payload)

            self.server.request = request
            self.assert_code("invalid_response", self.sign_in)
        self.server.request = original
        for response in (
            Response(raw=b"x" * (256 * 1024 + 1)),
            Response(raw=b'{"keys":[],"keys":[]}'),
            Response({"keys": []}, status=302),
        ):

            def request(method, url, **kwargs):
                return (
                    response
                    if url.endswith("/jwks")
                    else original(method, url, **kwargs)
                )

            self.server.request = request
            with self.assertRaises(ChatGPTPlanError):
                self.sign_in()
        self.assertFalse(self.session.snapshot()["connected"])
        self.assertFalse(
            any(call[1].startswith("https://evil.test") for call in self.server.calls)
        )

    def test_invalid_token_response_does_not_replace_existing_credentials(self):
        self.sign_in()
        before = self.store.get("chatgpt")
        for changes in (
            {"expires_in": -1},
            {"expires_in": True},
            {"expires_in": float("nan")},
            {"token_type": "Basic"},
            {"refresh_token": ""},
            {"scope": []},
        ):
            self.server.token_override = changes
            self.assert_code("invalid_response", self.sign_in)
            self.assertEqual(self.store.get("chatgpt"), before)

    def test_storage_failure_does_not_open_browser_or_replace_active_tokens(self):
        with patch.object(
            self.store, "set", side_effect=OSError("SECRET store failure")
        ):
            self.assert_code("storage_unavailable", self.sign_in)
        self.assertFalse(self.server.calls)
        self.sign_in()
        before = self.store.get("chatgpt")
        with patch.object(
            self.store, "set", side_effect=OSError("SECRET store failure")
        ):
            self.assert_code("storage_unavailable", self.sign_in)
        self.assertEqual(self.store.get("chatgpt"), before)

    def test_signout_stops_local_access_even_if_storage_write_fails(self):
        self.sign_in()
        with patch.object(
            self.store, "set", side_effect=OSError("SECRET store failure")
        ):
            self.assert_code("storage_unavailable", self.session.sign_out)
        self.assertFalse(self.session.snapshot()["connected"])
        self.assert_code("sign_in_required", self.session.credential)

    def test_second_session_never_replays_refresh_already_claimed_by_first(self):
        self.sign_in()
        other = self.make_session()
        other.snapshot()
        self.server.now += 3570
        self.server.release_refresh = threading.Event()
        values = []

        def call():
            try:
                values.append(self.session.credential())
            except ChatGPTPlanError as error:
                values.append(error.code)

        worker = threading.Thread(target=call)
        worker.start()
        self.assertTrue(self.server.refresh_started.wait(2))
        self.assert_code("refresh_failed", other.credential)
        self.server.release_refresh.set()
        worker.join(3)
        self.assertEqual(len(self.token_calls("refresh_token")), 1)
        self.assertEqual(values[0].access_token, "rotated-access")

    def test_real_loopback_is_bound_before_browser_and_rejects_wrong_path_or_host(self):
        session = ChatGPTPlanSession(
            self.directory,
            secret_store=self.store,
            http=self.server,
            clock=lambda: self.server.now,
        )
        callback_port = []

        def browser(url):
            self.server.browser(url)
            parsed = urlsplit(self.server.callback())
            callback_port.append(parsed.port)
            connection = HTTPConnection("127.0.0.1", parsed.port, timeout=2)
            connection.request("GET", "/wrong?code=SECRET")
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertNotIn(b"SECRET", response.read())
            connection.close()
            connection = HTTPConnection("127.0.0.1", parsed.port, timeout=2)
            connection.request(
                "GET", parsed.path + "?" + parsed.query, headers={"Host": "localhost"}
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.close()
            connection = HTTPConnection("127.0.0.1", parsed.port, timeout=2)
            connection.request("GET", parsed.path + "?" + parsed.query)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            self.assertNotIn(b"test-code", response.read())
            connection.close()
            return True

        log = StringIO()
        with redirect_stderr(log):
            session.sign_in(open_browser=browser)
        self.assertEqual(log.getvalue(), "")
        self.assertTrue(session.snapshot()["planEnabled"])
        connection = HTTPConnection("127.0.0.1", callback_port[0], timeout=0.2)
        try:
            with self.assertRaises(OSError):
                connection.connect()
        finally:
            connection.close()

    def test_refresh_uses_response_lifetime_and_respects_earliest_refresh(self):
        self.server.token_override = {
            "expires_in": 120,
            "earliest_refresh_at": self.server.now + 100,
        }
        self.sign_in()
        self.server.now += 80
        self.assertEqual(self.session.credential().access_token, "first-access")
        self.assertFalse(self.token_calls("refresh_token"))
        self.server.now += 21
        self.assertEqual(self.session.credential().access_token, "rotated-access")
        self.assertEqual(len(self.token_calls("refresh_token")), 1)

    def test_cancel_while_waiting_for_another_refresh_returns_without_send(self):
        self.sign_in()
        self.server.now += 3570
        cancel, finished = threading.Event(), threading.Event()
        result = []
        self.session._refresh_lock.acquire()

        def call():
            try:
                self.session.credential(cancel_token=cancel)
            except ChatGPTPlanError as error:
                result.append(error.code)
            finally:
                finished.set()

        worker = threading.Thread(target=call)
        try:
            worker.start()
            cancel.set()
            self.assertTrue(finished.wait(2))
            self.assertEqual(result, ["cancelled"])
            self.assertFalse(self.token_calls("refresh_token"))
        finally:
            self.session._refresh_lock.release()
            worker.join(2)

    def test_slow_jwks_has_total_deadline_not_only_an_inactivity_timeout(self):
        now = [0.0]
        self.session._monotonic = lambda: now[0]
        original = self.server.request

        def request(method, url, **kwargs):
            response = original(method, url, **kwargs)
            if url.endswith("/jwks"):

                def chunks(chunk_size):
                    self.assertEqual(chunk_size, 1)
                    for value in response.raw:
                        now[0] += 11
                        yield bytes([value])

                response.iter_content = chunks
            return response

        self.server.request = request
        self.assert_code("timeout", self.sign_in)
        self.assertFalse(self.session.snapshot()["connected"])

    def test_later_authorization_wins_and_earlier_response_is_discarded(self):
        self.sign_in()
        self.server.client = "oaiapp_later"

        def later_signin():
            self.server.before_token = None
            self.sign_in(new_account=True)

        self.server.before_token = later_signin
        self.assert_code("cancelled", lambda: self.sign_in(new_account=True))
        status = self.session.snapshot()
        self.assertTrue(status["connected"])
        self.assertEqual(len(status["accounts"]), 2)
        selected = json.loads(self.store.get("chatgpt"))
        self.assertEqual(
            selected["accounts"][status["accountId"]]["client_id"], "oaiapp_later"
        )

    def test_unknown_persisted_schema_fails_closed_without_overwrite(self):
        self.store.set("chatgpt", '{"version":999,"secret":"SECRET"}')
        self.assert_code("storage_invalid", self.session.snapshot)
        self.assert_code("storage_invalid", self.sign_in)
        self.assertEqual(self.store.get("chatgpt"), '{"version":999,"secret":"SECRET"}')

    def test_confirmed_terminal_refresh_clears_tokens_but_retains_registration(self):
        for code in (
            "invalid_grant",
            "invalid_refresh_token",
            "token_expired",
            "refresh_token_expired",
            "refresh_token_invalidated",
            "refresh_token_reused",
        ):
            self.server.now = 1000000.0
            self.sign_in()
            before = self.session.snapshot()
            host = self.server.query["ext_agent_host_id"]
            self.server.now += 3570
            original = self.server.request

            def request(method, url, **kwargs):
                if (kwargs.get("data") or {}).get("grant_type") == "refresh_token":
                    return Response(
                        {"error": code, "error_description": "SECRET remote text"},
                        status=400,
                    )
                return original(method, url, **kwargs)

            self.server.request = request
            self.assert_code("sign_in_required", self.session.credential)
            after = self.session.snapshot()
            self.assertFalse(after["connected"])
            self.assertEqual(after["accounts"], before["accounts"])
            self.assertEqual(after["accountId"], before["accountId"])
            self.assertGreater(after["generation"], before["generation"])
            self.assert_code("sign_in_required", self.make_session().credential)
            self.server.request = original
            self.sign_in()
            self.assertEqual(self.server.query["client_id"], ["oaiapp_first"])
            self.assertEqual(self.server.query["ext_agent_host_id"], host)
            self.assertNotIn("id_token_hint", self.server.query)

    def test_http_5xx_or_invalid_client_does_not_clear_or_retry_refresh(self):
        for status, error in (
            (503, "invalid_grant"),
            (400, "invalid_client"),
            (400, "unknown_SECRET"),
        ):
            self.server.now = 1000000.0
            self.sign_in()
            before = json.loads(self.store.get("chatgpt"))
            self.server.now += 3570
            original = self.server.request
            sends = []

            def request(method, url, **kwargs):
                if (kwargs.get("data") or {}).get("grant_type") == "refresh_token":
                    sends.append(1)
                    return Response({"error": error}, status=status)
                return original(method, url, **kwargs)

            self.server.request = request
            self.assert_code("refresh_failed", self.session.credential)
            self.assert_code("refresh_failed", self.session.credential)
            after = json.loads(self.store.get("chatgpt"))
            self.assertEqual(
                after["accounts"][after["active"]]["tokens"],
                before["accounts"][before["active"]]["tokens"],
            )
            self.assertEqual(len(sends), 1)
            self.server.request = original

    def test_unchanged_file_does_not_decrypt_each_stream_generation_check(self):
        def protect(value):
            return bytes(byte ^ 0xA5 for byte in value)

        reads = []

        def unprotect(value):
            reads.append(1)
            return protect(value)

        path = self.directory / "secrets.dpapi.json"
        self.store = DpapiSecretStore(path, protect, unprotect)
        self.session = self.make_session()
        self.sign_in()
        credential = self.session.credential()
        count = len(reads)
        for _ in range(100):
            self.session.check_current(credential.generation)
        self.assertEqual(len(reads), count)
        other = ChatGPTPlanSession(
            self.directory,
            secret_store=DpapiSecretStore(path, protect, protect),
            http=self.server,
        )
        other.sign_out()
        self.assert_code(
            "stale_session", lambda: self.session.check_current(credential.generation)
        )
        self.assertGreater(len(reads), count)

    def test_external_reselection_invalidates_generation_even_if_identity_is_same(self):
        def protect(value):
            return bytes(byte ^ 0xA5 for byte in value)

        path = self.directory / "secrets.dpapi.json"
        self.store = DpapiSecretStore(path, protect, protect)
        self.session = self.make_session()
        self.sign_in()
        credential = self.session.credential()
        other = ChatGPTPlanSession(
            self.directory, secret_store=DpapiSecretStore(path, protect, protect)
        )
        other.select_account(self.session.snapshot()["accountId"])
        self.assert_code(
            "stale_session", lambda: self.session.check_current(credential.generation)
        )


if __name__ == "__main__":
    unittest.main()

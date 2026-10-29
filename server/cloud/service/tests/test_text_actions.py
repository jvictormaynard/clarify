import uuid
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.db import close_old_connections, connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from cloud.service import groq, ledger
from cloud.service.models import Allowance, FundingEntry, Operation, WeeklyQuota
from .test_api import client_for, fund_hosted
from . import test_dictation


ACTION = {
    "id": "summary",
    "name": "Summary",
    "prompt": "Summarize in one sentence. Keep literal {braces} and {lang} safe.",
    "kind": "custom",
    "enabled": True,
}


def completion(text="Summary."):
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": text}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
    }


class CatalogTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("actions@example.test")

    def put(self, actions, revision=0, **extra):
        return self.client.put(
            "/v1/text-actions",
            {"expected_revision": revision, "actions": actions, **extra},
            format="json",
        )

    def test_seed_once_empty_catalog_cas_and_account_isolation(self):
        initial = self.client.get("/v1/text-actions")
        self.assertEqual(initial.status_code, 200)
        initial = initial.json()
        self.assertEqual(initial["revision"], 0)
        self.assertEqual(
            [a["id"] for a in initial["actions"]], ["rewrite", "translation"]
        )
        self.assertTrue(all(a["revision"] == 1 for a in initial["actions"]))
        saved = self.put([])
        self.assertEqual(saved.json(), {"revision": 1, "actions": []})
        self.assertEqual(self.client.get("/v1/text-actions").json(), saved.json())
        stale = self.put([ACTION])
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(
            stale.json(), {"code": "text_actions_conflict", **saved.json()}
        )
        _, other = client_for("other-actions@example.test")
        self.assertEqual(other.get("/v1/text-actions").json(), initial)

    def test_definition_revisions_change_only_for_edits_and_never_reuse_deleted_revision(
        self,
    ):
        first = self.put([ACTION]).json()
        self.assertEqual(first["actions"][0]["revision"], 1)
        same = self.put([ACTION], 1).json()
        self.assertEqual((same["revision"], same["actions"][0]["revision"]), (2, 1))
        changed = self.put([{**ACTION, "name": "Short summary"}], 2).json()
        self.assertEqual(changed["actions"][0]["revision"], 2)
        self.assertEqual(self.put([], 3).status_code, 200)
        recreated = self.put([ACTION], 4).json()
        self.assertEqual(recreated["actions"][0]["revision"], 3)

    def test_strict_definition_types_fields_and_byte_bounds_are_atomic(self):
        invalid = [
            [{**ACTION, "id": "non ascii é"}],
            [{**ACTION, "id": "x" * 65}],
            [{**ACTION, "name": " "}],
            [{**ACTION, "name": "x" * 81}],
            [{**ACTION, "prompt": " "}],
            [{**ACTION, "prompt": "é" * 4097}],
            [{**ACTION, "kind": "chat"}],
            [{**ACTION, "enabled": 1}],
            [{**ACTION, "name": 5}],
            [{**ACTION, "prompt": []}],
            [{**ACTION, "revision": 1}],
            [{**ACTION, "model": "other"}],
            [{**ACTION, "url": "https://example.test"}],
            [{**ACTION, "shortcut": "Ctrl+A"}],
            [{**ACTION, "credentials": {}}],
            [ACTION, ACTION],
            [{**ACTION, "id": str(i)} for i in range(65)],
            [{**ACTION, "id": str(i), "prompt": "x" * 8192} for i in range(33)],
        ]
        for entries in invalid:
            with self.subTest(entries=str(entries)[:70]):
                self.assertEqual(self.put(entries).status_code, 400)
        for revision in (True, -1, "0", None):
            self.assertEqual(self.put([ACTION], revision).status_code, 400)
        self.assertEqual(self.put([ACTION], provider="groq").status_code, 400)
        self.assertEqual(self.client.get("/v1/text-actions").json()["revision"], 0)
        self.assertFalse(Operation.objects.exists())

    def test_authentication_and_verified_email_are_required(self):
        from allauth.account.models import EmailAddress
        from rest_framework.test import APIClient

        self.assertIn(APIClient().get("/v1/text-actions").status_code, (401, 403))
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        self.assertIn(self.client.get("/v1/text-actions").status_code, (401, 403))

    def test_exact_complete_library_limit_and_overflow_leave_revisions_atomic(self):
        actions = [
            {**ACTION, "id": str(index), "prompt": "p" * 8192} for index in range(31)
        ]
        actions.append({**ACTION, "id": "last", "prompt": "p"})
        expected = {
            "revision": 1,
            "actions": [{**item, "revision": 1} for item in actions],
        }
        remaining = 256 * 1024 - len(
            json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining + 1, 8192)
        actions[-1]["prompt"] += "p" * remaining
        saved = self.put(actions)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(
            len(
                json.dumps(
                    saved.json(), ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
            ),
            256 * 1024,
        )
        actions[-1]["name"] += "x"
        self.assertEqual(self.put(actions, 1).status_code, 400)
        self.assertEqual(self.client.get("/v1/text-actions").json(), saved.json())
        actions[-1]["prompt"] = actions[-1]["prompt"][:-10]
        accepted = self.put(actions, 1)
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertEqual(accepted.json()["actions"][-1]["revision"], 2)


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class ExecutionTests(TestCase):
    def setUp(self):
        self.user, self.client = client_for("execute-actions@example.test")
        fund_hosted(self.user)
        self.client.put(
            "/v1/text-actions",
            {"expected_revision": 0, "actions": [ACTION]},
            format="json",
        )

    def send(self, operation_id=None, **changes):
        return self.client.post(
            "/v1/text-actions/execute",
            {
                "operation_id": str(operation_id or uuid.uuid4()),
                "action_id": "summary",
                "action_revision": 1,
                "text": "Source text.",
                "language": "auto",
                **changes,
            },
            format="json",
        )

    @patch("cloud.service.groq.perform", return_value=completion())
    def test_custom_prompt_snapshot_and_funded_idempotency_survive_edit_and_delete(
        self, provider
    ):
        operation_id = uuid.uuid4()

        def edit_during_call(*args, **kwargs):
            self.client.put(
                "/v1/text-actions",
                {
                    "expected_revision": 1,
                    "actions": [{**ACTION, "prompt": "Different task."}],
                },
                format="json",
            )
            return completion()

        provider.side_effect = edit_during_call
        first = self.send(operation_id)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["text"], "Summary.")
        self.assertEqual(
            {
                k: first.json()[k]
                for k in ("action_id", "action_name", "action_revision")
            },
            {"action_id": "summary", "action_name": "Summary", "action_revision": 1},
        )
        system = provider.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn(ACTION["prompt"], system)
        self.assertNotIn("not summarization", system)
        self.assertNotIn("Different task", system)
        self.assertEqual(
            provider.call_args.kwargs["json"]["model"], "openai/gpt-oss-20b"
        )
        self.assertEqual(self.send(operation_id).json(), first.json())
        self.client.put(
            "/v1/text-actions", {"expected_revision": 2, "actions": []}, format="json"
        )
        self.assertEqual(self.send(operation_id).json(), first.json())
        self.assertEqual(self.send(operation_id, text="Changed.").status_code, 409)
        Operation.objects.filter(user=self.user).update(
            result_expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.send(operation_id).status_code, 410)
        provider.assert_called_once()
        op = Operation.objects.get(user=self.user)
        self.assertEqual(op.cost, Decimal("0.000010500"))
        self.assertEqual(op.quota_debit, op.cost)
        self.assertEqual(WeeklyQuota.objects.get(user=self.user).used_usd, op.cost)
        self.assertEqual(Allowance.objects.get(user=self.user).used_ms, 0)
        self.assertEqual(FundingEntry.objects.filter(source="ledger").count(), 1)

    @patch("cloud.service.groq.perform")
    def test_missing_disabled_stale_and_other_account_actions_never_reserve(
        self, provider
    ):
        for changes, code, status in (
            ({"action_id": "missing"}, "text_action_missing", 404),
            ({"action_revision": 2}, "text_action_stale", 409),
        ):
            response = self.send(**changes)
            self.assertEqual(
                (response.status_code, response.json()["code"]), (status, code)
            )
        self.client.put(
            "/v1/text-actions",
            {"expected_revision": 1, "actions": [{**ACTION, "enabled": False}]},
            format="json",
        )
        self.assertEqual(
            self.send(action_revision=2).json()["code"], "text_action_disabled"
        )
        _, self.client = client_for("foreign-actions@example.test")
        self.assertEqual(self.send().json()["code"], "text_action_missing")
        provider.assert_not_called()
        self.assertFalse(Operation.objects.exists())
        self.assertFalse(Allowance.objects.exists())

    @patch("cloud.service.api.take_rate", return_value=True)
    @patch("cloud.service.groq.perform")
    def test_invalid_execution_controls_source_language_and_revision_never_reserve(
        self, provider, _rate
    ):
        for fields in (
            {"model": "other"},
            {"provider": "other"},
            {"url": "https://example.test"},
            {"prompt": "other"},
            {"language": "xx"},
            {"language": []},
            {"text": "é" * 8001},
            {"text": " "},
            {"action_revision": True},
            {"action_revision": 0},
            {"action_revision": "1"},
            {"action_id": []},
        ):
            self.assertEqual(self.send(**fields).status_code, 400, fields)
        provider.assert_not_called()
        self.assertFalse(Operation.objects.exists())

    @patch("cloud.service.groq.perform", return_value=completion("Translated."))
    def test_translation_uses_explicit_target_without_formatting_user_braces(
        self, provider
    ):
        self.client.put(
            "/v1/text-actions",
            {
                "expected_revision": 1,
                "actions": [
                    {
                        **ACTION,
                        "kind": "translation",
                        "prompt": "Translate to {lang}. Literal {unknown}.",
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(
            self.send(action_revision=2).json()["code"], "text_action_language_required"
        )
        response = self.send(action_revision=2, language="de")
        self.assertEqual(response.status_code, 200, response.content)
        messages = provider.call_args.kwargs["json"]["messages"]
        self.assertIn("German", messages[0]["content"])
        self.assertIn("{unknown}", messages[0]["content"])
        self.assertIn("German", messages[1]["content"])

    @patch("cloud.service.groq.perform")
    def test_provider_failure_and_output_bounds_keep_safe_diagnostics_and_settle(
        self, provider
    ):
        for answer in (
            groq.ProviderFailure("private provider payload"),
            completion("é" * 32001),
            completion(" "),
        ):
            if isinstance(answer, Exception):
                provider.side_effect = answer
            else:
                provider.side_effect, provider.return_value = None, answer
            response = self.send()
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.json()["code"], "text_processing_failed")
            self.assertNotIn("private provider payload", response.content.decode())
        for op in Operation.objects.all():
            self.assertNotEqual(op.state, "running")
            self.assertGreater(op.cost, 0)
            self.assertLessEqual(op.cost, op.authorized_cost)

    @patch("cloud.service.groq.perform")
    def test_missing_funding_blocks_provider(self, provider):
        FundingEntry.objects.all().delete()
        self.assertEqual(self.send().status_code, 503)
        provider.assert_not_called()

    @patch("cloud.service.middleware.time")
    @patch("cloud.service.groq.perform", return_value=completion())
    def test_new_and_legacy_actions_share_the_text_processing_rate_limit(
        self, provider, clock
    ):
        clock.time.return_value = 1793275200
        for index in range(6):
            if index % 2:
                response = self.client.post(
                    "/v1/text",
                    {
                        "operation_id": str(uuid.uuid4()),
                        "action": "rewrite",
                        "text": "Source.",
                        "language": "auto",
                    },
                    format="json",
                )
            else:
                response = self.send()
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.send().status_code, 429)
        self.assertEqual(provider.call_count, 6)

    @patch("cloud.service.groq.perform")
    def test_late_provider_result_cannot_succeed_after_operation_expires(
        self, provider
    ):
        def expire_during_call(*args, **kwargs):
            Operation.objects.filter(user=self.user).update(
                lease_until=timezone.now() - timedelta(seconds=1)
            )
            ledger.expire_leases()
            return completion()

        provider.side_effect = expire_during_call
        response = self.send()
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["code"], "operation_expired")
        self.assertNotIn("text", response.json())


@override_settings(
    CLARIFY_FUNDED_ENABLED=True,
    CLARIFY_GROQ_KEY="test-only",
    CLARIFY_MONTHLY_BUDGET_USD="1",
)
class DictationActionTests(TestCase):
    send = test_dictation.DictationTests.send

    def setUp(self):
        self.user, self.client = client_for("dictation-actions@example.test")
        fund_hosted(self.user)
        self.client.put(
            "/v1/text-actions",
            {"expected_revision": 0, "actions": [ACTION]},
            format="json",
        )

    @patch("cloud.service.groq.perform")
    def test_action_runs_once_after_expansion_and_can_summarize_with_style(
        self, provider
    ):
        self.client.put(
            "/v1/snippets",
            {
                "revision": 0,
                "entries": [{"trigger": "my token", "replacement": "expanded token"}],
            },
            format="json",
        )
        raw = "My token. " + "A distinct requirement. " * 30
        provider.side_effect = [{"text": raw}, completion("Brief.")]
        operation_id = uuid.uuid4()
        fields = {
            "text_action_id": "summary",
            "text_action_revision": "1",
            "writing_style": "organized",
            "cleanup_level": "clarity",
        }
        response = self.send(operation_id, **fields)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Brief.")
        self.assertEqual(response.json()["transcript"], raw)
        self.assertEqual(response.json()["text_action_revision"], 1)
        self.assertEqual(response.json()["writing_style_status"], "applied")
        self.assertTrue(response.json()["rewritten"])
        messages = provider.call_args_list[1].kwargs["json"]["messages"]
        self.assertIn("expanded token", messages[1]["content"])
        self.assertNotIn("Do not invent information, summarize", messages[0]["content"])
        self.client.put(
            "/v1/text-actions", {"expected_revision": 1, "actions": []}, format="json"
        )
        self.assertEqual(self.send(operation_id, **fields).json(), response.json())
        self.assertEqual(
            self.send(
                operation_id, **{**fields, "text_action_language": "en"}
            ).status_code,
            409,
        )
        self.assertEqual(provider.call_count, 2)

    @patch("cloud.service.groq.perform")
    def test_translation_snapshot_and_target_survive_an_edit_during_transcription(
        self, provider
    ):
        self.client.put(
            "/v1/text-actions",
            {
                "expected_revision": 1,
                "actions": [
                    {
                        **ACTION,
                        "kind": "translation",
                        "prompt": "Translate to {lang}. Keep {literal}.",
                    }
                ],
            },
            format="json",
        )

        def respond(path, **kwargs):
            if path == "audio/transcriptions":
                self.client.put(
                    "/v1/text-actions",
                    {"expected_revision": 2, "actions": []},
                    format="json",
                )
                return {"text": "Original transcript."}
            return completion("Übersetzt.")

        provider.side_effect = respond
        response = self.send(
            uuid.uuid4(),
            text_action_id="summary",
            text_action_revision="2",
            text_action_language="de",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text_action_revision"], 2)
        self.assertEqual(response.json()["text"], "Übersetzt.")
        messages = provider.call_args.kwargs["json"]["messages"]
        self.assertIn("Translate to German. Keep {literal}.", messages[0]["content"])
        self.assertIn("German", messages[1]["content"])
        self.assertEqual(provider.call_count, 2)

    @patch("cloud.service.groq.perform")
    def test_oversized_action_output_recovers_original_with_known_cost(self, provider):
        provider.side_effect = [{"text": "Original."}, completion("é" * 32001)]
        response = self.send(
            uuid.uuid4(), text_action_id="summary", text_action_revision="1"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Original.")
        self.assertTrue(response.json()["refinement_failed"])
        op = Operation.objects.get(user=self.user)
        self.assertFalse(op.cost_estimated)
        self.assertEqual(op.cost, ledger.asr_cost(1000) + Decimal("0.000010500"))

    @patch("cloud.service.groq.perform")
    def test_failed_action_returns_expanded_original_and_accounts_for_paid_work(
        self, provider
    ):
        provider.side_effect = [
            {"text": "Original transcript."},
            groq.ProviderFailure("private"),
        ]
        response = self.send(
            uuid.uuid4(), text_action_id="summary", text_action_revision="1"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["text"], "Original transcript.")
        self.assertTrue(response.json()["refinement_failed"])
        op = Operation.objects.get(user=self.user)
        self.assertTrue(op.cost_estimated)
        self.assertEqual(op.cost, op.authorized_cost)

    @patch("cloud.service.groq.perform")
    def test_standalone_snippet_and_preserve_cleanup_bypass_action(self, provider):
        self.client.put(
            "/v1/snippets",
            {
                "revision": 0,
                "entries": [{"trigger": "my token", "replacement": "saved text"}],
            },
            format="json",
        )
        provider.return_value = {"text": "My token."}
        response = self.send(
            uuid.uuid4(), text_action_id="summary", text_action_revision="1"
        )
        self.assertEqual(response.json()["text"], "saved text")
        provider.assert_called_once()
        provider.reset_mock()
        provider.return_value = {"text": "Original."}
        response = self.send(
            uuid.uuid4(),
            text_action_id="summary",
            text_action_revision="1",
            cleanup_level="preserve",
        )
        self.assertEqual(response.json()["text"], "Original.")
        provider.assert_called_once()

    @patch("cloud.service.api.take_rate", return_value=True)
    @patch("cloud.service.groq.perform")
    @patch("cloud.service.audio.decode")
    def test_invalid_or_stale_action_rejected_before_decode_or_provider(
        self, decode, provider, _rate
    ):
        for fields, status in (
            ({"text_action_id": "summary"}, 400),
            ({"text_action_revision": "1"}, 400),
            ({"text_action_id": "summary", "text_action_revision": "2"}, 409),
            ({"text_action_id": "foreign", "text_action_revision": "1"}, 404),
            ({"text_action_language": "en"}, 400),
        ):
            self.assertEqual(self.send(uuid.uuid4(), **fields).status_code, status)
        decode.assert_not_called()
        provider.assert_not_called()
        self.assertFalse(Operation.objects.exists())


class CatalogConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL row locks required")
        self.user, _ = client_for("cas-actions@example.test")

    def test_first_creation_and_competing_replacement_have_one_cas_winner(self):
        from cloud.service import text_actions

        barrier = Barrier(2)

        def replace(name):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return text_actions.replace(
                        self.user, 0, [{**ACTION, "name": name}]
                    )["revision"]
                except text_actions.Conflict:
                    return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(replace, ["First", "Second"]))
        self.assertCountEqual(results, [1, "conflict"])
        current = text_actions.read(self.user)
        self.assertEqual(current["revision"], 1)
        self.assertEqual(len(current["actions"]), 1)

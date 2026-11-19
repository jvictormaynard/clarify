import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import close_old_connections, connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from cloud.service.models import Operation
from .test_api import client_for


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


class ActionInstructionTests(SimpleTestCase):
    def test_known_saved_defaults_use_one_current_rewrite_policy(self):
        from cloud.service.text_actions import Snapshot, instruction
        from shared.rewrite_prompts import (
            _LEGACY_SELECTED_TEXT_REWRITE_INSTRUCTION,
            _PREVIOUS_LEGACY_SELECTED_TEXT_REWRITE_INSTRUCTION,
            _PREVIOUS_SELECTED_TEXT_REWRITE_INSTRUCTION,
            SELECTED_TEXT_REWRITE_INSTRUCTION,
        )

        for saved, expected in (
            (
                _PREVIOUS_SELECTED_TEXT_REWRITE_INSTRUCTION,
                SELECTED_TEXT_REWRITE_INSTRUCTION,
            ),
            (SELECTED_TEXT_REWRITE_INSTRUCTION, SELECTED_TEXT_REWRITE_INSTRUCTION),
            (
                _PREVIOUS_LEGACY_SELECTED_TEXT_REWRITE_INSTRUCTION,
                _LEGACY_SELECTED_TEXT_REWRITE_INSTRUCTION,
            ),
        ):
            with self.subTest(saved=saved[:60]):
                action = Snapshot("saved", "Saved", saved, "rewrite", True, 1)
                self.assertEqual(instruction(action, "en"), expected)
                self.assertEqual(action.prompt, saved)

    def test_saved_rewrite_receives_current_policy_without_changing_saved_prompt(self):
        from cloud.service.text_actions import Snapshot, instruction
        from shared.output_preferences import LANGUAGES
        from shared.rewrite_prompts import SELECTED_TEXT_REWRITE_INSTRUCTION

        # Existing libraries retain their saved prompts across application updates.
        saved_prompt = "Keep my technical vocabulary and literal {braces}."
        for kind in ("rewrite", "custom", "translation"):
            action = Snapshot("saved", "Saved", saved_prompt, kind, True, 1)
            for language in ("auto", *LANGUAGES):
                with self.subTest(kind=kind, language=language):
                    system = instruction(action, language)
                    self.assertEqual(action.prompt, saved_prompt)
                    self.assertIn(saved_prompt, system)
                    self.assertEqual(
                        SELECTED_TEXT_REWRITE_INSTRUCTION in system, kind == "rewrite"
                    )


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

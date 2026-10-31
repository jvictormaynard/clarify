"""Reusable text actions fixtures. This module defines no test cases."""

from pathlib import Path

from tempfile import TemporaryDirectory

from types import SimpleNamespace

from unittest.mock import Mock

from repositories import LocalConfigRepository

from secret_store import MemorySecretStore

from text_actions import TextAction

from text_action_service import TextActionService


from provider_registry import PROVIDER_REGISTRY, ProviderRegistry


from provider_types import RewriteResult

from workflow_provider import WorkflowProviderService

from clarify_account import AccountService


class HostedFixture:
    def __init__(self):
        self.revision = 0
        self.actions = [
            TextAction(
                "rewrite", "Account rewrite", "Account instruction.", "rewrite"
            ).definition()
            | {"revision": 1}
        ]
        self.calls = []
        self.accepted = {}
        self.on_put = None

    def library(self):
        return {"revision": self.revision, "actions": [dict(a) for a in self.actions]}

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        status, result = 200, self.library()
        if method == "PUT":
            body = kwargs["json"]
            if self.on_put:
                self.on_put(body)
            if body["expected_revision"] != self.revision:
                status, result = (
                    409,
                    {"code": "text_actions_conflict", **self.library()},
                )
            else:
                old = {a["id"]: a for a in self.actions}
                self.actions = [
                    dict(
                        a,
                        revision=old[a["id"]]["revision"]
                        + (
                            a
                            != {
                                k: v for k, v in old[a["id"]].items() if k != "revision"
                            }
                        )
                        if a["id"] in old
                        else 1,
                    )
                    for a in body["actions"]
                ]
                self.revision += 1
                result = self.library()
        elif method == "POST":
            body = kwargs["json"]
            previous = self.accepted.get(body["operation_id"])
            if previous is not None:
                result = previous
            else:
                action = next(
                    (a for a in self.actions if a["id"] == body["action_id"]), None
                )
                if action is None or action["revision"] != body["action_revision"]:
                    status, result = 409, {"code": "text_action_stale"}
                else:
                    result = {
                        "text": "Hosted result",
                        "action_id": action["id"],
                        "action_name": action["name"],
                        "action_revision": action["revision"],
                        "usage": {},
                    }
                    self.accepted[body["operation_id"]] = result
        return SimpleNamespace(
            status_code=status, content=b"fixture", json=lambda: result
        )


class HostedServiceFixture:
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.repo = LocalConfigRepository(
            self.directory / "config.json",
            environment={},
            secret_store=MemorySecretStore(),
        )
        self.server = HostedFixture()
        self.account = AccountService(
            self.directory, secrets=MemorySecretStore(), request=self.server
        )
        self.account._state = {
            "endpoint": "https://account.invalid",
            "user_id": "11111111-1111-4111-8111-111111111111",
            "mode": "hosted",
        }
        self.account.secrets.set("clarify_account", "fixture-token")
        self.applier = Mock()
        self.service = TextActionService(
            self.repo, self.account, apply_bindings=self.applier
        )
        self.service.refresh()

    def save(self, value):
        state = self.service.projection()
        return self.service.save(
            value, state["textActionContext"], state["textActionsRevision"]
        )


class LocalServiceFixture:
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.repo = LocalConfigRepository(
            Path(self.directory) / "config.json",
            environment={},
            secret_store=MemorySecretStore(),
        )
        self.applier = Mock()
        self.service = TextActionService(self.repo, apply_bindings=self.applier)

    def save(self, action):
        state = self.service.projection()
        return self.service.save(
            action, state["textActionContext"], state["textActionsRevision"]
        )

    def custom(self, **changes):
        return TextAction(
            "summary", "Summary", "Summarize this text.", **changes
        ).to_mapping()

    def provider(self):
        registry = Mock(spec=ProviderRegistry)
        registry.describe.side_effect = PROVIDER_REGISTRY.describe
        registry.connection_for_route.side_effect = (
            PROVIDER_REGISTRY.connection_for_route
        )
        registry.rewrite.return_value = RewriteResult(
            "Summary result", "openai", "gpt-4o-mini"
        )
        config = SimpleNamespace(
            current=self.repo.load,
            workflow=lambda scope: self.repo.load().workflow(scope),
        )
        provider = WorkflowProviderService(
            config, Mock(), registry=registry, text_actions=self.service
        )
        return provider, registry


class WorkflowActionFixture:
    setUp = LocalServiceFixture.setUp

    save = LocalServiceFixture.save

    custom = LocalServiceFixture.custom

    provider = LocalServiceFixture.provider

    def workflow(self, provider):
        from tests.support.workflows import (
            FakeAudio,
            FakeClipboard,
            FakeConfig,
            FakeStatistics,
            FakeClock,
            ManualScheduler,
        )
        from workflows import WorkflowService

        self.scheduler = ManualScheduler()
        self.clipboard = FakeClipboard()
        self.statistics = FakeStatistics()
        self.workflow_service = WorkflowService(
            provider,
            FakeAudio(),
            self.clipboard,
            FakeConfig(),
            self.statistics,
            self.scheduler,
            FakeClock(),
        )
        return self.workflow_service

    def drain(self):
        for _ in range(15):
            if not self.scheduler.soon and not self.scheduler.background:
                return
            while self.scheduler.soon:
                self.scheduler.soon.pop(0)()
            if self.scheduler.background:
                self.scheduler.background.pop(0)()
        self.fail("Workflow did not finish")

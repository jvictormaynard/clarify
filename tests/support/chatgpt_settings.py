"""Reusable chatgpt settings fixtures. This module defines no test cases."""

import threading


from types import SimpleNamespace


from provider_types import ProviderCapability, ProviderMetadata


class FakeChatGPTSession:
    """Synthetic identities only. No browser, network or credential storage."""

    def __init__(self):
        self.state = dict(
            connected=False,
            planEnabled=False,
            email="",
            accountId="",
            accounts=[],
            generation=0,
            planNoticeSeen=False,
        )
        self.wait = None
        self.cancelled = threading.Event()
        self.calls = []

    def snapshot(self):
        return {**self.state, "access_token": "must-never-cross-rpc"}

    def sign_in(self, *, open_browser, cancel=None, new_account=False):
        self.calls.append(("sign_in", new_account))
        if self.wait is not None:
            while not self.wait.wait(0.01):
                if cancel.is_set():
                    self.cancelled.set()
                    return
        accounts = [dict(id="personal", label="demo@example.test · Personal")]
        account = "personal"
        if new_account:
            accounts.append(dict(id="second", label="demo@example.test · Second"))
            account = "second"
        self.state.update(
            connected=True,
            planEnabled=True,
            email="demo@example.test",
            accountId=account,
            accounts=accounts,
            generation=self.state["generation"] + 1,
        )

    def select_account(self, account_id):
        self.calls.append(("select_account", account_id))
        self.state.update(accountId=account_id, generation=self.state["generation"] + 1)

    def sign_out(self):
        self.calls.append(("sign_out",))
        self.state.update(
            connected=False,
            planEnabled=False,
            email="",
            accountId="",
            accounts=[],
            generation=self.state["generation"] + 1,
        )

    def acknowledge_plan_notice(self):
        self.calls.append(("dismiss_notice",))
        self.state["planNoticeSeen"] = True


class FakeChatGPTAdapter:
    metadata = ProviderMetadata(
        provider_id="chatgpt",
        display_name="ChatGPT (subscription)",
        capabilities=frozenset(
            {ProviderCapability.TEXT_GENERATION, ProviderCapability.MODEL_DISCOVERY}
        ),
        default_base_url="https://api.openai.com/v1",
        audio_model_key="chatgpt_audio_model",
        text_model_key="chatgpt_text_model",
        default_audio_model="",
        default_text_model="",
        authentication="oauth",
    )

    def __init__(self, session):
        self.session = session
        self.calls = []

    def with_session(self, session):
        if self.session is session:
            return self
        adapter = FakeChatGPTAdapter(session)
        adapter.calls = self.calls
        return adapter

    def discover_models(self, connection, cancel_token=None):
        self.calls.append(connection)
        prefix = self.session.state["accountId"]
        models = (f"{prefix}-z", f"{prefix}-a")
        return SimpleNamespace(
            audio_models=(),
            text_models=models,
            display_names={
                models[0]: "First account model",
                models[1]: "Second account model",
            },
        )

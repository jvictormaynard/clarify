"""Durable, account-scoped history cache and bounded synchronization.

Legacy and guest records remain in HistoryStore. A separate atomic document
keeps account records, native metadata, cursor and pending work together.
No network or profile access occurs at import time.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import threading
import time
import uuid

from clarify_account import AccountError, HistoryIdentity
from history_store import HistoryRecord, HistoryStoreError, _atomic_write_text


MAX_BATCH_BYTES = 400 * 1024
MAX_BURST = 5
_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}\Z")


def _wire(value):
    if not isinstance(value, dict) or set(value) != {
        "id",
        "createdAt",
        "transcript",
        "text",
        "rewritten",
        "sourceDevice",
    }:
        raise ValueError("Invalid history entry")
    if not isinstance(value["id"], str) or not _ID.fullmatch(value["id"]):
        raise ValueError("Invalid history ID")
    timestamp = value["createdAt"]
    if (
        isinstance(timestamp, bool)
        or not isinstance(timestamp, (int, float))
        or not math.isfinite(timestamp)
        or not 0 < timestamp < 4102444800
    ):
        raise ValueError("Invalid history timestamp")
    for key in ("transcript", "text"):
        if not isinstance(value[key], str) or len(value[key].encode("utf-8")) > 32768:
            raise ValueError("Invalid history text")
    if (
        not value["text"].strip()
        or not isinstance(value["rewritten"], bool)
        or value["sourceDevice"] not in ("desktop", "mobile")
    ):
        raise ValueError("Invalid history result")
    return dict(value)


def _entry(record, final_text=None):
    return _wire(
        {
            "id": record.id,
            "createdAt": record.timestamp.timestamp(),
            "transcript": record.raw_text or "",
            "text": final_text
            if final_text is not None
            else (
                record.refined_text
                if record.refined_text is not None
                else record.raw_text or ""
            ),
            "rewritten": record.refined_text is not None,
            "sourceDevice": record.source_device or "desktop",
        }
    )


class AccountHistory:
    def __init__(self, account, local, *, clock=time.monotonic):
        self.account, self.local = account, local
        self.clock = clock
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._last_attempt = {}
        self._retry_after = {}

    def _path(self, owner):
        key = hashlib.sha256(
            (owner.endpoint + "\n" + owner.user_id).encode()
        ).hexdigest()
        return self.account.directory / "account-history" / key / "history.json"

    def _read(self, owner):
        path = self._path(owner)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "version": 1,
                "cursor": 0,
                "records": {},
                "pending": {},
                "deleted": [],
                "tombstones": [],
                "clearID": None,
            }
        except (OSError, ValueError) as error:
            raise HistoryStoreError(
                "The account history file is unavailable"
            ) from error
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "version",
                "cursor",
                "records",
                "pending",
                "deleted",
                "tombstones",
                "clearID",
            }
            or type(value.get("version")) is not int
            or value["version"] != 1
            or type(value.get("cursor")) is not int
            or value["cursor"] < 0
        ):
            raise HistoryStoreError("Unsupported account history schema")
        if (
            not isinstance(value.get("records"), dict)
            or not isinstance(value.get("pending"), dict)
            or not isinstance(value.get("deleted"), list)
            or not isinstance(value.get("tombstones"), list)
        ):
            raise HistoryStoreError("Invalid account history document")
        try:
            for key, item in value["records"].items():
                if (
                    key != _wire(item["wire"])["id"]
                    or HistoryRecord.from_mapping(item["record"]).id != key
                ):
                    raise ValueError()
            for key, item in value["pending"].items():
                if (
                    _wire(item)["id"] != key
                    or key not in value["records"]
                    or item != value["records"][key]["wire"]
                    or key in value["tombstones"]
                ):
                    raise ValueError()
            for item in value["deleted"] + value["tombstones"]:
                if not isinstance(item, str) or not _ID.fullmatch(item):
                    raise ValueError()
            if value.get("clearID") is not None:
                if not isinstance(value["clearID"], str):
                    raise ValueError()
                uuid.UUID(value["clearID"])
        except (KeyError, TypeError, ValueError) as error:
            raise HistoryStoreError("Invalid account history document") from error
        return value

    def _save(self, owner, value):
        _atomic_write_text(
            self._path(owner), json.dumps(value, ensure_ascii=False) + "\n"
        )

    def append(
        self, record: HistoryRecord, owner: HistoryIdentity | None, *, final_text=None
    ):
        # Hold the account lock through persistence so sign-out cannot turn an
        # account result into a guest result or race account-cache deletion.
        with self.account._lock, self._lock:
            if owner is None or owner != self.account.history_identity():
                return False
            record = replace(record, source_device="desktop")
            wire = _entry(record, final_text)
            state = self._read(owner)
            if record.id in state["tombstones"]:
                return False
            existing = state["records"].get(record.id)
            if existing:
                if existing["wire"] != wire:
                    raise ValueError("Immutable history conflict")
                return True
            state["records"][record.id] = {"record": record.to_mapping(), "wire": wire}
            state["pending"][record.id] = wire
            self._save(owner, state)
            return True

    def list_items(self, *, display=False):
        with self.account._lock, self._lock:
            owner = self.account.history_identity()
            records = []
            if owner:
                records = [
                    (
                        "account:",
                        replace(
                            HistoryRecord.from_mapping(item["record"]),
                            refined_text=item["wire"]["text"],
                        )
                        if display
                        else HistoryRecord.from_mapping(item["record"]),
                    )
                    for item in self._read(owner)["records"].values()
                ]
            # Reading old records does not change the guest recording choice or
            # prune pre-upgrade records merely because the account was opened.
            records.extend(
                ("local:", record) for record in self.local.list_preserved_records()
            )
            return sorted(records, key=lambda item: item[1].timestamp, reverse=True)

    def list_records(self):
        return [record for _, record in self.list_items()]

    def delete(self, item_id):
        with self.account._lock, self._lock:
            if item_id.startswith("local:"):
                self.local.delete(item_id.removeprefix("local:"))
                return
            owner = self.account.history_identity()
            if not owner:
                return
            record_id = item_id.removeprefix("account:")
            state = self._read(owner)
            if record_id not in state["records"]:
                return
            state["records"].pop(record_id)
            state["pending"].pop(record_id, None)
            for key in ("deleted", "tombstones"):
                if record_id not in state[key]:
                    state[key].append(record_id)
            self._save(owner, state)

    def clear(self):
        with self.account._lock, self._lock:
            owner = self.account.history_identity()
            if owner:
                state = self._read(owner)
                state["tombstones"] = list(
                    dict.fromkeys([*state["tombstones"], *state["records"]])
                )
                state.update(
                    records={}, pending={}, deleted=[], clearID=str(uuid.uuid4())
                )
                self._save(owner, state)
            # This device's legacy records are cleared locally, never uploaded.
            self.local.delete_all()

    def remove_account(self, owner):
        if owner is not None:
            with self._lock:
                self._path(owner).unlink(missing_ok=True)

    @staticmethod
    def _batch(state):
        batch = {"cursor": state["cursor"], "upserts": [], "deletes": []}
        if state["clearID"]:
            batch["clearID"] = state["clearID"]
            return batch
        batch["deletes"] = state["deleted"][:50]
        for item in list(state["pending"].values())[:50]:
            batch["upserts"].append(item)
            # requests' JSON encoder uses ASCII escapes; count the bytes sent.
            if len(json.dumps(batch).encode()) > MAX_BATCH_BYTES:
                batch["upserts"].pop()
                break
        return batch

    @staticmethod
    def _page(result, cursor):
        new_cursor = result.get("cursor")
        if (
            isinstance(new_cursor, bool)
            or not isinstance(new_cursor, int)
            or new_cursor < cursor
            or not isinstance(result.get("hasMore"), bool)
        ):
            raise ValueError("Invalid history cursor")
        entries, deleted = result.get("entries"), result.get("deleted")
        if (
            not isinstance(entries, list)
            or not isinstance(deleted, list)
            or len(entries) + len(deleted) > 20
        ):
            raise ValueError("Invalid history page")
        if result["hasMore"] and new_cursor <= cursor:
            raise ValueError("History page made no progress")
        if (entries or deleted) and new_cursor <= cursor:
            raise ValueError("History changes did not advance the cursor")
        entries = [_wire(item) for item in entries]
        if any(not isinstance(key, str) or not _ID.fullmatch(key) for key in deleted):
            raise ValueError("Invalid history deletion")
        return new_cursor, entries, deleted

    def sync_safely(self, *, force=False):
        try:
            self.sync(force=force)
        except (AccountError, HistoryStoreError, OSError, ValueError):
            # A sync problem must not fail dictation or acquire the microphone.
            pass

    def sync(self, *, force=False):
        owner = self.account.history_identity()
        if not owner or not self._sync_lock.acquire(blocking=False):
            return
        try:
            key = owner
            now = self.clock()
            if now < self._retry_after.get(key, float("-inf")) or (
                not force and now - self._last_attempt.get(key, float("-inf")) < 60
            ):
                return
            self._last_attempt[key] = now
            for _ in range(MAX_BURST):
                with self.account._lock, self._lock:
                    if owner != self.account.history_identity():
                        raise AccountError("A conta mudou. O resultado foi descartado.")
                    batch = self._batch(self._read(owner))
                code, result = self.account._request(
                    "POST", "/v1/history/sync", expected_identity=owner, json=batch
                )
                if code != 200:
                    raise AccountError("Não foi possível sincronizar o histórico.")
                cursor, entries, deleted = self._page(result, batch["cursor"])
                with self.account._lock, self._lock:
                    if owner != self.account.history_identity():
                        raise AccountError("A conta mudou. O resultado foi descartado.")
                    state = self._read(owner)
                    # An in-flight response acknowledges only the submitted work.
                    if batch.get("clearID") == state["clearID"]:
                        state["clearID"] = None
                    for item in batch["upserts"]:
                        if state["pending"].get(item["id"]) == item:
                            state["pending"].pop(item["id"])
                    state["deleted"] = [
                        key for key in state["deleted"] if key not in batch["deletes"]
                    ]
                    for record_id in deleted:
                        state["records"].pop(record_id, None)
                        state["pending"].pop(record_id, None)
                        if record_id not in state["tombstones"]:
                            state["tombstones"].append(record_id)
                    for item in entries:
                        if state["clearID"] or item["id"] in state["tombstones"]:
                            continue
                        old = state["records"].get(item["id"])
                        if old and old["wire"] != item:
                            raise ValueError("Immutable history conflict")
                        if not old:
                            record = HistoryRecord(
                                record_id=item["id"],
                                timestamp=datetime.fromtimestamp(
                                    item["createdAt"], timezone.utc
                                ),
                                raw_text=item["transcript"],
                                refined_text=item["text"]
                                if item["rewritten"]
                                or item["text"] != item["transcript"]
                                else None,
                                source_device=item["sourceDevice"],
                            )
                            state["records"][item["id"]] = {
                                "record": record.to_mapping(),
                                "wire": item,
                            }
                    state["cursor"] = cursor
                    self._save(owner, state)
                    if (
                        not result["hasMore"]
                        and not state["pending"]
                        and not state["deleted"]
                        and not state["clearID"]
                    ):
                        break
        except Exception:
            self._retry_after[owner] = self.clock() + 60
            raise
        finally:
            self._sync_lock.release()

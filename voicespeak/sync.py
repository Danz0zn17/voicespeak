"""Cloud sync (Supabase REST) plus offline fallback.

Reads the CURRENT live schema (categories + phrases) and adapts it into the
generalised Board/Cell model, so the device keeps working with today's
dashboard while the schema migration to boards/cells happens separately.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

import requests

from .config import DEFAULT_BOARDS, LOCAL_BOARDS
from .models import Board, Cell


def _boards_to_json(boards: list[Board]) -> list[dict]:
    return [
        {"name": b.name, "cells": [vars(c) for c in b.cells]}
        for b in boards
    ]


def _boards_from_json(data: list[dict]) -> list[Board]:
    return [
        Board(name=b["name"], cells=[Cell(**c) for c in b.get("cells", [])])
        for b in data
    ]


def boards_digest(boards: list[Board]) -> str:
    """Stable content hash, so a resync only swaps boards when they changed."""
    blob = json.dumps(_boards_to_json(boards), sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _save_local(boards: list[Board]) -> None:
    LOCAL_BOARDS.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_BOARDS, "w") as f:
        json.dump(_boards_to_json(boards), f, indent=2)


def fetch_from_supabase() -> list[Board]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    token = os.environ.get("DEVICE_TOKEN", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")

    if url and token:
        # Paired device: one call returns this family's content and doubles
        # as the heartbeat (last_seen) for the dashboard.
        r = requests.post(
            f"{url}/functions/v1/device-sync",
            json={"device_token": token}, timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("claimed"):
            raise RuntimeError("Device not claimed yet - claim it from the dashboard")
        return _adapt(data["categories"], data["phrases"])

    if not url or not key:
        raise EnvironmentError(
            "Set SUPABASE_URL plus DEVICE_TOKEN (paired device) "
            "or SUPABASE_ANON_KEY (legacy direct access)"
        )

    # Legacy direct table access (pre-pairing installs).
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    cats = requests.get(
        f"{url}/rest/v1/categories?select=*&order=display_order",
        headers=headers, timeout=10,
    )
    cats.raise_for_status()
    phs = requests.get(
        f"{url}/rest/v1/phrases?select=*", headers=headers, timeout=10,
    )
    phs.raise_for_status()
    return _adapt(cats.json(), phs.json())


def _adapt(cats: list[dict], phrases: list[dict]) -> list[Board]:
    """Categories + phrases rows -> the generalised Board/Cell model."""
    by_cat: dict[str, list[dict]] = {}
    for p in phrases:
        by_cat.setdefault(p["category_id"], []).append(p)

    boards: list[Board] = []
    for cat in cats:
        cp = by_cat.get(cat["id"], [])
        button_x = next((p["text"] for p in cp if p["input_type"] == "button_x"), "")
        button_o = next((p["text"] for p in cp if p["input_type"] == "button_o"), "")
        analog = [p["text"] for p in cp if p["input_type"] == "analog_left"]

        cells: list[Cell] = []
        if button_x:
            cells.append(Cell(label="X", phrase=button_x, position=0))
        if button_o:
            cells.append(Cell(label="O", phrase=button_o, position=1))
        for i, text in enumerate(analog):
            cells.append(Cell(label=text, phrase=text, position=len(cells) + i))
        boards.append(Board(name=cat["name"], cells=cells))

    boards = [b for b in boards if b.cells]
    if not boards:
        raise RuntimeError("Cloud returned no usable boards")
    return boards


def load_boards() -> list[Board]:
    """Cloud first, then last-good local cache, then bundled defaults."""
    try:
        print("Syncing from cloud...")
        boards = fetch_from_supabase()
        _save_local(boards)
        print(f"Loaded {len(boards)} boards from cloud.")
        return boards
    except Exception as e:  # noqa: BLE001 - offline is an expected state
        print(f"Cloud sync failed ({e}). Trying offline data.")

    for path in (LOCAL_BOARDS, DEFAULT_BOARDS):
        if Path(path).exists():
            with open(path) as f:
                boards = _boards_from_json(json.load(f))
            if boards:
                print(f"Loaded {len(boards)} boards from {path}.")
                return boards

    raise RuntimeError("No cloud connection and no local board data available.")


def _sync_state(error: Exception | None) -> str:
    if error is None:
        return "online"
    if "not claimed" in str(error):
        return "unclaimed"
    return "offline"


class BackgroundSync:
    """Re-fetch from the cloud every `interval` seconds on a daemon thread.

    Never blocks speech: new phrases are pre-cached before the swap, and the
    swap itself is one locked call on the engine. Logs only when the online
    state changes, not every tick. Failures keep the current boards.
    """

    def __init__(
        self,
        interval: float,
        current: list[Board],
        apply: Callable[[list[Board]], None],
        precache: Callable[[list[str]], None] | None = None,
        fetch: Callable[[], list[Board]] = fetch_from_supabase,
    ):
        self.interval = interval
        self.digest = boards_digest(current)
        self.apply = apply
        self.precache = precache
        self.fetch = fetch
        self.state = ""
        self._stop = threading.Event()

    def tick(self) -> bool:
        """One sync attempt. Returns True if boards changed and were applied."""
        try:
            boards = self.fetch()
        except Exception as e:  # noqa: BLE001 - offline is an expected state
            self._set_state(_sync_state(e), e)
            return False
        self._set_state("online")
        digest = boards_digest(boards)
        if digest == self.digest:
            return False
        if self.precache:
            self.precache([c.phrase for b in boards for c in b.cells if c.phrase])
        _save_local(boards)
        self.apply(boards)
        self.digest = digest
        print(f"Phrases updated from cloud ({len(boards)} boards).")
        return True

    def _set_state(self, state: str, error: Exception | None = None) -> None:
        if state == self.state:
            return
        self.state = state
        if state == "online":
            print("Cloud sync: online.")
        else:
            print(f"Cloud sync: {state} ({error}). Using current phrases.")

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the thread must never die
                print(f"Background sync error: {e}")

    def start(self) -> None:
        if self.interval > 0:
            threading.Thread(target=self._run, name="sync", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

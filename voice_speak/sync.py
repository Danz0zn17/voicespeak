"""Cloud sync (Supabase REST) plus offline fallback.

Reads the CURRENT live schema (categories + phrases) and adapts it into the
generalised Board/Cell model, so the device keeps working with today's
dashboard while the schema migration to boards/cells happens separately.
"""

from __future__ import annotations

import json
import os
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


def _save_local(boards: list[Board]) -> None:
    LOCAL_BOARDS.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCAL_BOARDS, "w") as f:
        json.dump(_boards_to_json(boards), f, indent=2)


def fetch_from_supabase() -> list[Board]:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_ANON_KEY must be set")

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

    by_cat: dict[str, list[dict]] = {}
    for p in phs.json():
        by_cat.setdefault(p["category_id"], []).append(p)

    boards: list[Board] = []
    for cat in cats.json():
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

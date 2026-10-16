"""Hard rule 1: only allowlisted books ever reach storage, the consensus, the raw
cache or any printed output. The synthetic payload carries OFF_LIST_BOOK on
every market (plus in broadcasts and links) to prove it is dropped everywhere."""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd
import pytest

from nba_cold_start import config
from nba_cold_start.cli import main
from nba_cold_start.consensus import consensus_by_player
from nba_cold_start.ingest import save_raw
from nba_cold_start.pipeline import snapshot_from_file, snapshot_slate
from nba_cold_start.sgo_client import filter_event, off_list_book_count
from nba_cold_start.storage import SCHEMA, OffListBookError
from tests.conftest import FakeTransport
from tests.fixtures.synthetic import EVENT_ID, FETCHED, OFF_LIST_BOOK, events_response, synthetic_event


def all_string_values(storage) -> list[str]:
    values = []
    for table, cols in SCHEMA.items():
        for col, typ in cols.items():
            if typ == "VARCHAR":
                values += storage.query(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")[col].astype(str).tolist()
    return values


def test_allowlist_roles_are_disjoint_and_complete():
    assert not (config.REFERENCE_BOOKS & config.TARGET_VENUES)
    assert not (config.REFERENCE_BOOKS & config.UNPRICED_BOOKS)
    assert not (config.TARGET_VENUES & config.UNPRICED_BOOKS)
    assert config.ALLOWED_BOOKS == config.REFERENCE_BOOKS | config.TARGET_VENUES | config.UNPRICED_BOOKS
    assert not config.is_allowed_book(OFF_LIST_BOOK)


def test_request_filter_uses_discovered_books_only(tmp_path):
    # The API rejects (HTTP 400, still billed) a bookmakerID the plan can't see,
    # so the request filter is the discovered books, never the whole allowlist.
    path = tmp_path / "books.json"
    assert config.request_bookmaker_filter(path) is None                  # before `cli books`
    path.write_text(json.dumps({"discovered_at": "x", "reference": ["draftkings", "espnbet", OFF_LIST_BOOK],
                                "target": ["kalshi"], "unpriced": []}))
    assert config.request_bookmaker_filter(path) == "draftkings,espnbet,kalshi"


def test_parse_time_filter_drops_off_list_books_and_consensus_fields():
    raw = synthetic_event()
    assert off_list_book_count(raw) == 1
    ev = filter_event(raw)
    blob = json.dumps(ev)
    assert OFF_LIST_BOOK not in blob
    for odd in ev["odds"].values():
        assert set(odd["byBookmaker"]) <= config.ALLOWED_BOOKS
        for field in ("fairOdds", "bookOdds", "fairOverUnder", "bookOverUnder"):
            assert field not in odd                     # hard rule 2


def test_api_snapshot_stores_no_off_list_book_anywhere(storage, make_client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    config.BOOKS_FILE.write_text(json.dumps({"discovered_at": "x", "reference": ["draftkings", "espnbet"],
                                             "target": ["kalshi"], "unpriced": ["prizepicks"]}))
    transport = FakeTransport()
    client = make_client(transport, storage=storage)
    out = snapshot_slate(client, storage, FETCHED.date(), FETCHED)

    events_call = [c for c in transport.calls if c[0].endswith("/events/")][0]
    assert events_call[1]["bookmakerID"] == "draftkings,espnbet,kalshi,prizepicks"   # request-time filter
    assert storage.count("odds_snapshots") > 0
    assert set(storage.query("SELECT DISTINCT book FROM odds_snapshots").book) <= config.ALLOWED_BOOKS
    assert not any(OFF_LIST_BOOK in v for v in all_string_values(storage))
    raw_text = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    assert raw_text and OFF_LIST_BOOK not in raw_text
    assert out["objects"] == 1


def test_consensus_uses_reference_books_only(storage):
    snapshot_from_file(storage, events_response([synthetic_event()]), FETCHED)
    cons = consensus_by_player(storage, EVENT_ID, as_of=FETCHED + timedelta(minutes=1))
    used = {b.book for c in cons.values() for b in c.books}
    assert used and used <= config.REFERENCE_BOOKS
    assert "kalshi" not in used and "prizepicks" not in used
    # The absurd precomputed fields (fairOverUnder 99.5) never leak in.
    assert all(c.mean is None or c.mean < 40 for c in cons.values())


def test_storage_refuses_off_list_book(storage):
    row = {"event_id": "e", "odd_id": "o", "player_id": "p", "side": "over", "book": OFF_LIST_BOOK,
           "line": 1.5, "odds_american": -110.0, "available": True}
    with pytest.raises(OffListBookError):
        storage.append("odds_snapshots", [row])
    with pytest.raises(OffListBookError):
        storage.append("signals", [{"event_id": "e", "player_id": "p", "books": f"draftkings,{OFF_LIST_BOOK}"}])
    assert storage.count("odds_snapshots") == 0 and storage.count("signals") == 0


def test_raw_cache_writer_gets_filtered_events(tmp_path):
    path = save_raw([filter_event(synthetic_event())], FETCHED, "t", raw_dir=tmp_path)
    assert OFF_LIST_BOOK not in path.read_text()


def test_cli_output_never_names_off_list_book(tmp_path, capsys):
    payload = tmp_path / "slate.json"
    payload.write_text(json.dumps(events_response([synthetic_event()])))
    db = str(tmp_path / "t.duckdb")
    now = FETCHED.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert main(["--db", db, "--now", now, "snapshot", "--from-file", str(payload)]) == 0
    assert main(["--db", db, "--now", now, "project", "--date", "2026-10-21"]) == 0
    assert main(["--db", db, "--now", now, "signals", "--date", "2026-10-21"]) == 0
    printed = capsys.readouterr().out
    assert printed and OFF_LIST_BOOK not in printed
    df = pd.read_csv(config.PLAYERS_CSV)
    assert not df.astype(str).apply(lambda c: c.str.contains(OFF_LIST_BOOK)).any().any()

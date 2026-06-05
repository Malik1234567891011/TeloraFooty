import store


def make_game(duration=100.0):
    game = store.new_game("Test Game", {"kind": "local", "url": None})
    game["durationSec"] = duration
    game["status"] = "ready"
    store.save_game(game)
    return game


def test_clamp_clip_normal():
    assert store.clamp_clip(50.0, 100.0) == (20.0, 60.0)


def test_clamp_clip_near_start():
    assert store.clamp_clip(15.0, 100.0) == (0.0, 25.0)


def test_clamp_clip_near_end():
    assert store.clamp_clip(95.0, 100.0) == (65.0, 100.0)


def test_new_game_persists(data_dir):
    game = make_game()
    loaded = store.load_game(game["id"])
    assert loaded["title"] == "Test Game"
    assert loaded["status"] == "ready"
    assert store.list_games()[0]["id"] == game["id"]


def test_create_event_computes_clip_bounds(data_dir):
    game = make_game(duration=100.0)
    ev = store.create_event(game["id"], "goal", 50.0)
    assert ev["clipStart"] == 20.0
    assert ev["clipEnd"] == 60.0
    assert ev["source"] == "manual"
    assert store.load_events(game["id"]) == [ev]


def test_events_sorted_by_timestamp(data_dir):
    game = make_game()
    store.create_event(game["id"], "shot", 80.0)
    store.create_event(game["id"], "goal", 10.0)
    times = [e["timestamp"] for e in store.load_events(game["id"])]
    assert times == [10.0, 80.0]


def test_update_event_recomputes_bounds(data_dir):
    game = make_game()
    ev = store.create_event(game["id"], "shot", 50.0)
    updated = store.update_event(game["id"], ev["id"], {"type": "goal", "timestamp": 95.0})
    assert updated["type"] == "goal"
    assert updated["clipEnd"] == 100.0


def test_delete_event(data_dir):
    game = make_game()
    ev = store.create_event(game["id"], "shot", 50.0)
    assert store.delete_event(game["id"], ev["id"]) is True
    assert store.load_events(game["id"]) == []
    assert store.delete_event(game["id"], "evt_nope") is False

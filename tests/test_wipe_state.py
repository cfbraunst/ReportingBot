from reporter.wipe_state import AlertStore


def test_sent_alert_survives_reopen_and_can_be_cleared(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    store = AlertStore(path)
    store.mark_sent(1, 2, 3, frozenset({"✅", "⏰"}))
    store.close()

    reopened = AlertStore(path)
    assert reopened.active_users(1, 2) == {3}
    reopened.clear_except(1, 2, set())
    assert reopened.active_users(1, 2) == set()
    reopened.close()


def test_keys_are_per_guild_message_and_user(tmp_path):
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.mark_sent(1, 2, 3, frozenset({"✅", "⏰"}))
    store.mark_sent(1, 2, 3, frozenset({"✅", "⏰"}))
    store.mark_sent(1, 4, 3, frozenset({"✅", "❌"}))
    store.mark_sent(5, 2, 3, frozenset({"⏰", "❌"}))

    assert store.active_users(1, 2) == {3}
    store.clear_message(1, 2)
    assert store.active_users(1, 2) == set()
    assert store.active_users(1, 4) == {3}
    assert store.active_users(5, 2) == {3}
    store.close()

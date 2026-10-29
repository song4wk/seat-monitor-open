import os
import sys

os.environ.setdefault("BASE", "https://example.invalid")
os.environ.setdefault("USER_ID", "u")
os.environ.setdefault("PASSWORD", "p")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import seat_watch  # noqa: E402

HTML = """
<table>
<tr><td class="Head">10/30</td><td class="Free">o</td><td class="Full">x</td><td class="Free">o</td></tr>
<tr><td class="Head">10/31</td><td class="Full">x</td></tr>
</table>
"""


def test_find_free_slots():
    assert seat_watch.find_free_slots(HTML) == ["10/30 8:05", "10/30 9:55"]


def test_get_hidden_fields_missing_form():
    assert seat_watch.get_hidden_fields("<html></html>", "LOGIN") == {}


def test_render_summary_ok_has_counts_only():
    stats = seat_watch.new_stats()
    stats.update(checks=8, max_free=2, notified_new=2, notified_repeat=2)
    md = seat_watch.render_summary(stats)
    assert "✅" in md and "| 检查次数 | 8 |" in md and "| 本轮最多空位数 | 2 |" in md
    assert "10/30" not in md and "8:05" not in md


def test_render_summary_skipped_and_error():
    skipped = seat_watch.new_stats()
    skipped["result"] = "skipped"
    assert "⏭️" in seat_watch.render_summary(skipped)

    err = seat_watch.new_stats()
    err.update(result="error", reason="账号或密码错误")
    md = seat_watch.render_summary(err)
    assert "❌" in md and "账号或密码错误" in md


def test_write_summary_appends_to_file(tmp_path, monkeypatch):
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    seat_watch.write_summary(seat_watch.new_stats())
    assert "本轮监控" in path.read_text()


def test_fail_sets_stats_and_prints_error_annotation(capsys):
    seat_watch.STATS.update(seat_watch.new_stats())
    assert seat_watch.fail("x") == 1
    assert seat_watch.STATS["result"] == "error"
    assert "::error title=监控失败::x" in capsys.readouterr().out


def test_new_slot_repeat_then_cooldown_then_gone():
    split = seat_watch.split_new_and_remind
    state = {}
    assert split(["a"], state, 1000) == (["a"], [], [])

    # 下一次检查：再发一次 critical
    assert split(["a"], state, 1120) == ([], ["a"], [])

    # 之后冷却期内不再通知
    assert split(["a"], state, 1240) == ([], [], [])

    # 冷却期满：降级提醒
    assert split(["a"], state, 1120 + seat_watch.REMIND_COOLDOWN) == ([], [], ["a"])

    seat_watch.split_new_and_remind([], state, 5000)
    assert state == {}


def test_build_run_record_has_counts_and_no_slots():
    from datetime import datetime
    stats = seat_watch.new_stats()
    stats.update(checks=8, last_free=1)
    rec = seat_watch.build_run_record(stats, datetime(2026, 10, 29, 14, 15, 0), "https://x/run/1")
    assert rec["time"] == "2026-10-29T14:15:00" and rec["last_free"] == 1
    assert rec["run_url"] == "https://x/run/1" and "slots" not in rec


def test_merge_run_newest_first_and_capped():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import update_status
    status = {}
    for i in range(5):
        status = update_status.merge_run(status, {"n": i}, max_runs=3)
    assert [r["n"] for r in status["runs"]] == [4, 3, 2]


def test_failed_delivery_does_not_consume_repeat(monkeypatch, tmp_path):
    from unittest.mock import Mock
    monkeypatch.setattr(seat_watch, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(seat_watch, 'RECIPIENTS', {'admin': 'a', 'user2': 'b'})
    monkeypatch.setattr(seat_watch, 'STATS', seat_watch.new_stats())
    send = Mock(side_effect=[True, False, True, True])
    monkeypatch.setattr(seat_watch, '_send_bark', send)
    state = {}
    seat_watch.handle_slots(['slot'], state, '')
    assert state['slot'] == {'admin': {'count': 1, 'ts': state['slot']['admin']['ts']}}
    assert seat_watch.STATS['notified_new'] == 1
    seat_watch.handle_slots(['slot'], state, '')
    assert state['slot']['admin']['count'] == 2
    assert state['slot']['user2']['count'] == 1
    assert seat_watch.STATS['notified_new'] == 2
    seat_watch.handle_slots([], state, '')
    assert state == {}


def test_bark_checks_http_and_business_result(monkeypatch):
    from unittest.mock import Mock
    import requests
    for response in (Mock(json=Mock(return_value={'code': 400})),
                     Mock(raise_for_status=Mock(side_effect=requests.HTTPError()))):
        monkeypatch.setattr(seat_watch.requests, 'post', Mock(return_value=response))
        assert seat_watch._send_bark('secret', 'title', 'body') is False
    monkeypatch.setattr(seat_watch.requests, 'post',
                        Mock(return_value=Mock(json=Mock(return_value={'code': 200}))))
    assert seat_watch._send_bark('secret', 'title', 'body') is True


def test_run_final_refresh_errors_are_failure(monkeypatch, tmp_path):
    from unittest.mock import Mock
    import requests
    monkeypatch.setattr(seat_watch, 'STATS', seat_watch.new_stats())
    monkeypatch.setattr(seat_watch, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(seat_watch, 'RECIPIENTS', {})
    monkeypatch.setattr(seat_watch, 'should_run', lambda: True)
    monkeypatch.setattr(seat_watch, 'make_session', Mock())
    monkeypatch.setattr(seat_watch, 'login_and_get_reserve_page', lambda s: HTML)
    monkeypatch.setattr(seat_watch, 'MAX_REFRESH_CYCLES', 2)
    monkeypatch.setattr(seat_watch.time, 'sleep', Mock())
    monkeypatch.setattr(seat_watch, 'refresh_page', Mock(side_effect=requests.Timeout()))
    monkeypatch.setattr(seat_watch, 'notify_admin', Mock())
    assert seat_watch.run() == 1
    assert seat_watch.STATS['last_checked_at'] is not None
    assert seat_watch.STATS['checks'] == 1


def test_refresh_retries_gateway_response(monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(seat_watch.time, 'sleep', Mock())
    session = Mock()
    session.post.side_effect = [Mock(status_code=503), Mock(status_code=502), Mock(status_code=200)]
    assert seat_watch.refresh_page(session, {}).status_code == 200
    assert session.post.call_count == 3


def test_run_record_is_not_in_notified_cache(monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(seat_watch, 'STATE_FILE', tmp_path / 'cache' / 'state.json')
    monkeypatch.setenv('RUN_RECORD_FILE', str(tmp_path / 'run.json'))
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    seat_watch.write_run_record(seat_watch.new_stats())
    record = json.loads((tmp_path / 'run.json').read_text())
    assert record['run_id'] == '123' and record['run_attempt'] == '2'
    assert record['last_free'] is None
    assert not (tmp_path / 'cache').exists()


def test_status_rejects_stale_record_and_deduplicates(monkeypatch, tmp_path):
    import json
    from scripts import update_status
    for name, value in {'GITHUB_RUN_ID': 'new', 'GITHUB_RUN_ATTEMPT': '1',
                        'GITHUB_SERVER_URL': 'https://github.com',
                        'GITHUB_REPOSITORY': 'owner/repo'}.items():
        monkeypatch.setenv(name, value)
    record_path = tmp_path / 'missing.json'
    update_status.main(record_path, tmp_path)
    record = json.loads((tmp_path / 'status.json').read_text())['runs'][0]
    assert record['result'] == 'error' and record['run_id'] == 'new'
    record_path.write_text(json.dumps({'run_id': 'old', 'run_attempt': '1', 'result': 'ok'}))
    update_status.main(record_path, tmp_path)
    runs = json.loads((tmp_path / 'status.json').read_text())['runs']
    assert len(runs) == 1 and runs[0]['result'] == 'error'

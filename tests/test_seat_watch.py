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

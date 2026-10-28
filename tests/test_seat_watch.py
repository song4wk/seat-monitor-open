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

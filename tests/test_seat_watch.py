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


def test_new_slot_then_cooldown_then_gone():
    state = {}
    new, remind = seat_watch.split_new_and_remind(["a"], state, 1000)
    assert (new, remind) == (["a"], [])

    new, remind = seat_watch.split_new_and_remind(["a"], state, 1100)
    assert (new, remind) == ([], [])

    new, remind = seat_watch.split_new_and_remind(["a"], state, 1000 + seat_watch.REMIND_COOLDOWN)
    assert (new, remind) == ([], ["a"])

    seat_watch.split_new_and_remind([], state, 5000)
    assert state == {}

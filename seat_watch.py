"""
seat_watch.py
驾校课表空位检测脚本（单次运行版，供 GitHub Actions 定时触发）
系统错误只通知管理员（BARK_KEY_1），有空位通知全员
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = os.environ["BASE"]
LOGIN_URL = f"{BASE}/login.asp"
CARTYPE_URL = f"{BASE}/cartype.asp"
RESERVE_URL = f"{BASE}/ReserveList.asp"

USER_ID = os.environ["USER_ID"]
PASSWORD = os.environ["PASSWORD"]
CARTYPE = "002"  # ＡＴ

TZ = ZoneInfo("Asia/Tokyo")
ADMIN_KEY = os.environ.get("BARK_KEY_1", "")

ALL_KEYS = [
    os.environ.get("BARK_KEY_1", ""),
    os.environ.get("BARK_KEY_2", "")
]
ALL_KEYS = [k for k in ALL_KEYS if k]

TIME_SLOTS = ["8:05", "9:00", "9:55", "10:50", "11:45", "13:30",
              "14:25", "15:20", "16:15", "17:15", "18:10", "19:05", "20:00"]

POLL_INTERVAL = 120
MAX_REFRESH_CYCLES = 7
MAX_CONSECUTIVE_REFRESH_ERRORS = 3

# 已通知空位的状态文件（由 workflow 的 actions/cache 在各次运行间保存）
STATE_FILE = Path(os.environ.get("STATE_FILE", ".state/notified.json"))
CRITICAL_REPEATS = 2  # 每个空位最多发 2 次 critical（防止第一次没听到）
REMIND_COOLDOWN = 30 * 60  # 之后空位持续存在时，每 30 分钟降级提醒一次


def now_in_jst():
    return datetime.now(TZ)


def log(message):
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {message}")


def describe(exc):
    # requests 的异常文本含完整 URL（BASE 是 secret），公开仓库的日志里只记录类型
    return type(exc).__name__


def should_run():
    now = now_in_jst()
    hour = now.hour
    if 6 <= hour <= 23:
        return True
    if 0 <= hour <= 5:
        return hour in (0, 2, 4)
    return False


def make_session():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    retry = Retry(total=2, backoff_factor=1, status_forcelist=(502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_hidden_fields(html, form_name=None):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"name": form_name}) if form_name else soup
    fields = {}
    if form is None:
        return fields
    for inp in form.find_all("input", {"type": "hidden"}):
        name = inp.get("name")
        if name:
            fields[name] = inp.get("value", "").strip()
    return fields


def login_and_get_reserve_page(session):
    try:
        r0 = session.get(LOGIN_URL, timeout=15)
        r0.encoding = "shift_jis"
    except Exception as exc:
        log(f"❌ 登录页面请求失败: {describe(exc)}")
        return None

    if "操作回数制限" in r0.text:
        log("⛔ 登录页面提示操作次数已达上限")
        return "LIMIT_EXCEEDED"

    login_hidden = get_hidden_fields(r0.text, "LOGIN")
    login_payload = {"USERID": USER_ID, "USERPASSWD": PASSWORD, **login_hidden}

    try:
        r1 = session.post(CARTYPE_URL, data=login_payload, timeout=15)
        r1.encoding = "shift_jis"
    except Exception as exc:
        log(f"❌ 登录提交失败: {describe(exc)}")
        return None

    if "操作回数制限" in r1.text:
        log("⛔ 登录过程中提示操作次数已达上限")
        return "LIMIT_EXCEEDED"
    if "不正です" in r1.text:
        log("❌ 登录失败：账号或密码错误")
        return "BAD_CREDENTIALS"
    if "個人情報" not in r1.text:
        log("❌ 登录后页面不符合预期（可能是页面结构变更）")
        return None

    cartype_hidden = get_hidden_fields(r1.text, "TypeSelect")
    reserve_payload = {"CARTYPE": CARTYPE, **cartype_hidden}

    try:
        r2 = session.post(RESERVE_URL, data=reserve_payload, timeout=15)
        r2.encoding = "shift_jis"
    except Exception as exc:
        log(f"❌ 进入 reserve 列表失败: {describe(exc)}")
        return None

    if "最新の内容に更新する" in r2.text or "空きあり" in r2.text:
        return r2.text

    log("❌ reserve 列表页面异常，返回内容不符合预期")
    return None


def find_free_slots(html):
    soup = BeautifulSoup(html, "html.parser")
    slots = []
    for row in soup.find_all("tr"):
        head = row.find("td", class_="Head")
        if not head:
            continue
        date = head.get_text(strip=True)
        cells = row.find_all("td")[1:]
        for i, td in enumerate(cells):
            if "Free" in td.get("class", []):
                time_label = TIME_SLOTS[i] if i < len(TIME_SLOTS) else "?"
                slots.append(f"{date} {time_label}")
    return slots


def _send_bark(key, title, body, critical=True):
    payload = {"device_key": key, "title": title, "body": body}
    if critical:
        payload.update({"level": "critical", "call": "1", "sound": "alarm"})
    try:
        requests.post("https://api.day.app/push", json=payload, timeout=5)
    except Exception as exc:
        log(f"通知发送失败: {describe(exc)}")


def notify_admin(title, body):
    if ADMIN_KEY:
        _send_bark(ADMIN_KEY, title, body)


def notify_all(title, body, critical=True):
    for key in ALL_KEYS:
        _send_bark(key, title, body, critical)


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))
    except OSError as exc:
        log(f"状态保存失败: {describe(exc)}")


def split_new_and_remind(slots, state, now_ts):
    """返回 (新出现, 二次 critical, 降级提醒)，并更新 state（只保留当前空位）。

    state: {slot: {"ts": 上次通知时间, "count": 已发 critical 次数}}
    第一次没听到的话，下一次检查（约 2 分钟后）空位仍在就再发一次 critical，之后按冷却时间降级提醒。
    """
    current = set(slots)
    new, repeat, remind = [], [], []
    for s in slots:
        entry = state.get(s)
        if not isinstance(entry, dict):
            state[s] = {"ts": now_ts, "count": 1}
            new.append(s)
        elif entry["count"] < CRITICAL_REPEATS:
            entry["count"] += 1
            entry["ts"] = now_ts
            repeat.append(s)
        elif now_ts - entry["ts"] >= REMIND_COOLDOWN:
            entry["ts"] = now_ts
            remind.append(s)
    for s in list(state):
        if s not in current:
            del state[s]
    return new, repeat, remind


def handle_slots(slots, state, tag):
    new, repeat, remind = split_new_and_remind(slots, state, time.time())
    save_state(state)
    if slots:
        log(f"{tag} 🎉 发现空位: {'、'.join(slots)}"
            f"（新增 {len(new)}，二次 {len(repeat)}，提醒 {len(remind)}）")
    else:
        log(f"{tag} 空位数: 0")
    if new:
        notify_all("有空位！", "、".join(new))
    if repeat:
        notify_all("有空位！（再次通知）", "、".join(repeat))
    if remind:
        notify_all("仍有空位", "、".join(remind), critical=False)


def get_refresh_payload(html):
    payload = get_hidden_fields(html, "reload")
    if payload:
        return payload
    return get_hidden_fields(html)


def run():
    """返回进程退出码：0 正常，1 异常（让 Actions 显示红色）。"""
    log("========================================")
    log("🚀 开始执行本轮课表空位检测")
    log(f"当前时间: {now_in_jst().strftime('%Y-%m-%d %H:%M:%S')} JST")

    if not should_run():
        log("⏭️ 当前时间不在执行窗口，跳过本轮任务")
        log("========================================")
        return 0

    session = make_session()

    html = login_and_get_reserve_page(session)
    if html == "LIMIT_EXCEEDED":
        log("⛔ 今日操作次数已用尽，退出任务")
        notify_admin("⚠️ 监控失败", "今日操作次数已用尽")
        return 1
    if html == "BAD_CREDENTIALS":
        notify_admin("⚠️ 监控失败", "账号或密码错误")
        return 1
    if not html:
        log("❌ 登录或 reserve 页面获取失败，退出任务")
        notify_admin("⚠️ 监控异常", "登录或 reserve 页面获取失败")
        return 1

    log("✅ 登录成功，开始本轮短任务监控")

    state = load_state()
    payload = get_refresh_payload(html)
    handle_slots(find_free_slots(html), state, "[首次]")

    errors = 0
    for idx in range(1, MAX_REFRESH_CYCLES + 1):
        time.sleep(POLL_INTERVAL)
        now = datetime.now(TZ).strftime("%H:%M:%S")
        try:
            r = session.post(RESERVE_URL, data=payload, timeout=15)
            r.encoding = "shift_jis"
        except Exception as exc:
            errors += 1
            log(f"[{now}] ❌ 第 {idx} 次刷新发生网络异常: {describe(exc)}")
            if errors >= MAX_CONSECUTIVE_REFRESH_ERRORS:
                notify_admin("⚠️ 监控中断", f"连续 {errors} 次刷新网络异常")
                return 1
            continue
        errors = 0

        if "最新の内容に更新する" not in r.text:
            log(f"[{now}] ❌ 第 {idx} 次刷新失败，页面返回异常")
            notify_admin("⚠️ 监控中断", f"第 {idx} 次刷新失败")
            return 1

        payload = get_refresh_payload(r.text)
        handle_slots(find_free_slots(r.text), state, f"[{now}] [{idx}]")

    log("✅ 本轮任务完成")
    return 0


def main():
    try:
        code = run()
    except Exception as exc:
        log(f"❌ 未预期的异常: {describe(exc)}")
        notify_admin("⚠️ 监控崩溃", describe(exc))
        code = 1
    log("========================================")
    sys.exit(code)


if __name__ == "__main__":
    main()

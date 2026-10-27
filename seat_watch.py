"""
course_watch.py
驾校课表空位检测脚本（单次运行版，供 GitHub Actions 定时触发）
系统错误只通知管理员（BARK_KEY_1），有空位通知全员
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://dk.ncors.com/pic/ncors"
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


def now_in_jst():
    return datetime.now(TZ)


def log(message):
    print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {message}")


def should_run():
    now = now_in_jst()
    hour = now.hour
    if 6 <= hour <= 23:
        return True
    if 0 <= hour <= 5:
        return hour in (0, 2, 4)
    return False


def get_hidden_fields(html, form_name=None):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", {"name": form_name}) if form_name else soup
    fields = {}
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
        log(f"❌ 登录页面请求失败: {exc}")
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
        log(f"❌ 登录提交失败: {exc}")
        return None

    if "操作回数制限" in r1.text:
        log("⛔ 登录过程中提示操作次数已达上限")
        return "LIMIT_EXCEEDED"
    if "不正です" in r1.text or "個人情報" not in r1.text:
        log("❌ 登录失败：账号或密码异常")
        return None

    cartype_hidden = get_hidden_fields(r1.text, "TypeSelect")
    reserve_payload = {"CARTYPE": CARTYPE, **cartype_hidden}

    try:
        r2 = session.post(RESERVE_URL, data=reserve_payload, timeout=15)
        r2.encoding = "shift_jis"
    except Exception as exc:
        log(f"❌ 进入 reserve 列表失败: {exc}")
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


def _send_bark(key, title, body):
    try:
        requests.get(
            f"https://api.day.app/{key}/{title}/{body}",
            params={"level": "critical", "call": "1", "sound": "alarm"},
            timeout=5,
        )
    except Exception as exc:
        log(f"通知发送失败 (key: {key[:6]}...): {exc}")


def notify_admin(title, body):
    if ADMIN_KEY:
        _send_bark(ADMIN_KEY, title, body)


def notify_all(title, body):
    for key in ALL_KEYS:
        _send_bark(key, title, body)


def get_refresh_payload(html):
    payload = get_hidden_fields(html, "reload")
    if payload:
        return payload
    return get_hidden_fields(html)


def main():
    log("========================================")
    log("🚀 开始执行本轮课表空位检测")
    log(f"当前时间: {now_in_jst().strftime('%Y-%m-%d %H:%M:%S')} JST")

    if not should_run():
        log("⏭️ 当前时间不在执行窗口，跳过本轮任务")
        log("========================================")
        return

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    html = login_and_get_reserve_page(session)
    if html == "LIMIT_EXCEEDED":
        log("⛔ 今日操作次数已用尽，退出任务")
        notify_admin("⚠️ 监控失败", "今日操作次数已用尽")
        log("========================================")
        return
    if not html:
        log("❌ 登录或 reserve 页面获取失败，退出任务")
        notify_admin("⚠️ 监控异常", "登录或 reserve 页面获取失败")
        log("========================================")
        return

    log("✅ 登录成功，开始本轮短任务监控")

    payload = get_refresh_payload(html)
    slots = find_free_slots(html)

    if slots:
        msg = "、".join(slots)
        log(f"🎉 首次检测发现空位: {msg}")
        notify_all("有空位！", msg)
    else:
        log("首次检测... 空位数: 0")

    for idx in range(1, MAX_REFRESH_CYCLES + 1):
        time.sleep(POLL_INTERVAL)
        now = datetime.now(TZ).strftime("%H:%M:%S")
        try:
            r = session.post(RESERVE_URL, data=payload, timeout=15)
            r.encoding = "shift_jis"
        except Exception as exc:
            log(f"[{now}] ❌ 第 {idx} 次刷新发生网络异常: {exc}")
            continue

        if "最新の内容に更新する" not in r.text:
            log(f"[{now}] ❌ 第 {idx} 次刷新失败，页面返回异常")
            notify_admin("⚠️ 监控中断", f"第 {idx} 次刷新失败")
            log("========================================")
            return

        payload = get_refresh_payload(r.text)
        slots = find_free_slots(r.text)
        if slots:
            msg = "、".join(slots)
            log(f"[{now}] [{idx}] 🎉 检测中... 发现空位: {msg}")
            notify_all("有空位！", msg)
        else:
            log(f"[{now}] [{idx}] 检测中... 空位数: 0")

    log("✅ 本轮任务完成")
    log("========================================")


if __name__ == "__main__":
    main()

"""把 本轮 last_run.json 合并进 status 分支工作区的 status.json，并放入状态页 index.html。

用法: python scripts/update_status.py <last_run.json> <status 分支工作区目录>
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import shutil
import sys
from pathlib import Path

MAX_RUNS = 200


def merge_run(status, record, max_runs=MAX_RUNS):
    """新记录放最前，只保留最近 max_runs 条。"""
    runs = [r for r in status.get("runs", [])
            if not (record.get("run_id") and
                    (r.get("run_id"), r.get("run_attempt")) ==
                    (record.get("run_id"), record.get("run_attempt")))]
    runs.insert(0, record)
    return {"runs": runs[:max_runs]}


def main(record_path, out_dir):
    out = Path(out_dir)
    status_file = out / "status.json"
    try:
        status = json.loads(status_file.read_text())
        if not isinstance(status, dict):
            status = {}
    except (OSError, ValueError):
        status = {}
    try:
        record = json.loads(Path(record_path).read_text())
        if not isinstance(record, dict):
            record = {}
    except (OSError, ValueError):
        record = {}
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if run_id and (record.get("run_id"), record.get("run_attempt")) != (run_id, attempt):
        record = {
            "time": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
            "run_id": run_id, "run_attempt": attempt,
            "run_url": f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}",
            "result": "error", "reason": "本轮未生成有效记录，监控异常中断",
            "checks": 0, "last_free": None, "last_checked_at": None,
            "notified_new": 0, "notified_repeat": 0, "notified_remind": 0,
        }
    status_file.write_text(json.dumps(merge_run(status, record), ensure_ascii=False))
    shutil.copy(Path(__file__).parent.parent / "site" / "index.html", out / "index.html")
    (out / ".nojekyll").touch()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

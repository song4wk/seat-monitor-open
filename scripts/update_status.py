"""把 .state/last_run.json 合并进 status 分支工作区的 status.json，并放入状态页 index.html。

用法: python scripts/update_status.py <last_run.json> <status 分支工作区目录>
"""

import json
import shutil
import sys
from pathlib import Path

MAX_RUNS = 200


def merge_run(status, record, max_runs=MAX_RUNS):
    """新记录放最前，只保留最近 max_runs 条。"""
    runs = [record] + list(status.get("runs", []))
    return {"runs": runs[:max_runs]}


def main(record_path, out_dir):
    out = Path(out_dir)
    status_file = out / "status.json"
    try:
        status = json.loads(status_file.read_text())
    except (OSError, ValueError):
        status = {}
    record = json.loads(Path(record_path).read_text())
    status_file.write_text(json.dumps(merge_run(status, record), ensure_ascii=False))
    shutil.copy(Path(__file__).parent.parent / "site" / "index.html", out / "index.html")
    (out / ".nojekyll").touch()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

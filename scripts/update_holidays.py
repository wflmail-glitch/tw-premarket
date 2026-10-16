"""更新證交所休市日 → data/holidays.json（每年跑一次；fetch_market 發現缺年度會自動呼叫）。"""
import json
import sys

from common import ROOT, http_get, write_json


def update(year):
    p = ROOT / "data" / "holidays.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"years": [], "closed": []}
    j = http_get(f"https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&queryYear={year}")
    closed = set(cur["closed"])
    for d, name, *_ in j.get("data", []):
        if "開始交易" in name or "最後交易" in name:
            continue
        closed.add(d)
    cur["closed"] = sorted(closed)
    cur["years"] = sorted(set(cur["years"]) | {int(year)})
    write_json(p, cur)
    return cur


if __name__ == "__main__":
    y = sys.argv[1] if len(sys.argv) > 1 else None
    if not y:
        from common import today_tpe
        y = today_tpe().year
    print(update(int(y)))

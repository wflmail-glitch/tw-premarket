"""抓證交所公開資料 → data/<今天>/market.json

用法：python3 scripts/fetch_market.py [--today YYYY-MM-DD]
- 今天休市（週末或 data/holidays.json）→ status=closed
- 資料日 = 今天之前最近一個有資料的交易日
- 只打 4~5 支請求、每支間隔數秒；被擋則等待重試，最後仍失敗就標「無資料」
"""
import argparse
import datetime as dt
import json
import re
import sys

from common import ROOT, http_get, load_config, num, roc_date, sign_of, today_tpe, watch_codes, write_json

BASE = "https://www.twse.com.tw/rwd/zh"


def load_holidays(year):
    p = ROOT / "data" / "holidays.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"years": [], "closed": []}
    if year not in cur.get("years", []):
        try:
            from update_holidays import update
            cur = update(year)
        except Exception as e:  # noqa: BLE001
            print(f"  ! 休市日更新失敗，只用週末判斷：{e}")
    return set(cur.get("closed", []))


def is_closed(d, holidays):
    return d.weekday() >= 5 or d.isoformat() in holidays


def get(url, cfg):
    m = cfg["market"]
    return http_get(url, gap=m["request_gap_seconds"], retry_waits=m["retry_wait_seconds"])


def tables_of(j):
    return {(t.get("title") or ""): t for t in j.get("tables", []) if t.get("data")}


def find_table(tables, keyword):
    for title, t in tables.items():
        if keyword in title:
            return t
    return None


def parse_all(j, cfg):
    """MI_INDEX type=ALLBUT0999：指數、成交、漲跌家數、類股、個股收盤。"""
    tbs = tables_of(j)
    out = {}
    price = find_table(tbs, "價格指數(臺灣證券交易所)")
    sectors = []
    for r in price["data"]:
        name = r[0]
        # 注意：漲跌點數不帶號、漲跌百分比已帶號 → 一律取絕對值再乘方向
        close, pts, pct = num(r[1]), abs(num(r[3]) or 0), abs(num(r[4]) or 0)
        s = sign_of(r[2])
        if name == "發行量加權股價指數":
            out["taiex"] = {"close": close, "chg": s * pts, "pct": s * pct}
        if name.endswith("類指數") and "未含" not in name and "不含" not in name and name != "電子工業類指數":
            sectors.append({"name": name.replace("類指數", ""), "pct": s * pct})
    sectors.sort(key=lambda x: x["pct"], reverse=True)
    n = cfg["market"]["sector_top_n"]
    out["sector_top"] = sectors[:n]
    out["sector_bottom"] = list(reversed(sectors[-n:]))

    stat = find_table(tbs, "大盤統計資訊")
    for r in stat["data"]:
        if r[0].startswith("證券合計"):
            out["turnover"] = num(r[1])
    ud = find_table(tbs, "漲跌證券數合計")
    def split(cell):
        m = re.match(r"([\d,]+)(?:\(([\d,]+)\))?", cell)
        return num(m.group(1)), (num(m.group(2)) if m.group(2) else None)
    for r in ud["data"]:
        a, b = split(r[2])  # 「股票」欄
        if r[0].startswith("上漲"):
            out["up"], out["limit_up"] = a, b
        elif r[0].startswith("下跌"):
            out["down"], out["limit_down"] = a, b
        elif r[0].startswith("持平"):
            out["flat"] = a

    quotes = find_table(tbs, "每日收盤行情")
    watch = watch_codes(cfg)
    q = {}
    for r in quotes["data"]:
        if r[0] in watch:
            s = sign_of(r[9])
            close, diff = num(r[8]), num(r[10]) or 0.0
            prev = close - s * diff if close is not None else None
            q[r[0]] = {
                "name": r[1].strip(), "close": close, "chg": s * diff,
                "pct": (s * diff / prev * 100) if prev else None,
                "vol_lots": round(num(r[2]) / 1000),
            }
    out["quotes"] = q
    return out


def parse_bfi(j):
    rows = {r[0]: num(r[3]) for r in j["data"]}
    dealer = (rows.get("自營商(自行買賣)") or 0) + (rows.get("自營商(避險)") or 0)
    foreign = (rows.get("外資及陸資(不含外資自營商)") or 0) + (rows.get("外資自營商") or 0)
    return {"foreign": foreign, "trust": rows.get("投信"), "dealer": dealer, "total": rows.get("合計")}


def parse_margin(j):
    t = j["tables"][0]["data"]
    rows = {r[0]: r for r in t}
    fin = rows["融資(交易單位)"]; short = rows["融券(交易單位)"]; amt = rows["融資金額(仟元)"]
    return {
        "fin_lots": num(fin[5]), "fin_lots_chg": num(fin[5]) - num(fin[4]),
        "short_lots": num(short[5]), "short_lots_chg": num(short[5]) - num(short[4]),
        "fin_amt": num(amt[5]) * 1000, "fin_amt_chg": (num(amt[5]) - num(amt[4])) * 1000,
    }


def parse_t86(j, cfg):
    rows = []
    for r in j["data"]:
        rows.append({"code": r[0].strip(), "name": r[1].strip(),
                     "foreign": round(num(r[4]) / 1000), "trust": round(num(r[10]) / 1000),
                     "dealer": round(num(r[11]) / 1000)})
    n = cfg["market"]["foreign_top_n"]
    by_f = sorted(rows, key=lambda x: x["foreign"], reverse=True)
    watch = set(watch_codes(cfg))
    return {
        "foreign_buy_top": by_f[:n],
        "foreign_sell_top": list(reversed(by_f[-n:])),
        "watch": {r["code"]: r for r in rows if r["code"] in watch},
    }


def parse_exdiv(j, today, cfg):
    watch = set(watch_codes(cfg))
    soon, today_cnt = [], 0
    for r in j.get("data", []):
        m = re.match(r"(\d+)年(\d+)月(\d+)日", r[0])
        if not m:
            continue
        d = dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
        if d == today:
            today_cnt += 1
        if r[1] in watch and today <= d <= today + dt.timedelta(days=20):
            cash = num(r[7])
            soon.append({"date": d.isoformat(), "code": r[1], "name": r[2], "type": r[3], "cash": cash})
    return {"today_count": today_cnt, "watch_upcoming": sorted(soon, key=lambda x: x["date"])}


def reparse(today, cfg):
    outdir = ROOT / "data" / today.isoformat()
    old = json.loads((outdir / "market.json").read_text(encoding="utf-8"))
    raw = outdir / "raw"
    rd = lambda n: json.loads((raw / f"{n}.json").read_text(encoding="utf-8"))  # noqa: E731
    res = {k: old[k] for k in ("today", "status", "data_date")}
    res.update({"missing": [], "errors": []})
    res.update(parse_all(rd("MI_INDEX"), cfg))
    for key, parser in (("institutional", parse_bfi), ("margin", parse_margin),
                        ("t86", lambda j: parse_t86(j, cfg)), ("exdiv", lambda j: parse_exdiv(j, today, cfg))):
        if (raw / f"{key}.json").exists():
            res[key] = parser(rd(key))
        else:
            res["missing"].append(key)
    write_json(outdir / "market.json", res)
    print("reparse OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    ap.add_argument("--data-date", help="強制指定資料日（測試用）")
    ap.add_argument("--reparse", action="store_true", help="不連網，用已存的 raw/ 重算")
    a = ap.parse_args()
    cfg = load_config()
    today = dt.date.fromisoformat(a.today) if a.today else today_tpe()
    if a.reparse:
        return reparse(today, cfg)
    holidays = load_holidays(today.year)
    outdir = ROOT / "data" / today.isoformat()
    result = {"today": today.isoformat(), "status": "ok", "missing": [], "errors": []}

    if is_closed(today, holidays) and not a.data_date:
        result["status"] = "closed"
        write_json(outdir / "market.json", result)
        print("今天休市"); return

    # 找資料日
    cands = []
    if a.data_date:
        cands = [dt.date.fromisoformat(a.data_date)]
    else:
        d = today - dt.timedelta(days=1)
        while len(cands) < 3:
            if not is_closed(d, holidays):
                cands.append(d)
            d -= dt.timedelta(days=1)
    allj, data_date = None, None
    for d in cands:
        ds = d.strftime("%Y%m%d")
        try:
            j = get(f"{BASE}/afterTrading/MI_INDEX?response=json&date={ds}&type=ALLBUT0999", cfg)
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"MI_INDEX {ds}: {e}")
            break
        if j.get("stat") == "OK" and j.get("tables"):
            allj, data_date = j, d
            break
        result["errors"].append(f"MI_INDEX {ds}: {j.get('stat')}（可能為未列入的休市日）")
    if not allj:
        result["status"] = "fetch_failed"
        write_json(outdir / "market.json", result)
        print("抓資料失敗：", result["errors"]); sys.exit(2)

    ds = data_date.strftime("%Y%m%d")
    result["data_date"] = data_date.isoformat()
    raw = outdir / "raw"
    write_json(raw / "MI_INDEX.json", allj)
    result.update(parse_all(allj, cfg))

    steps = [
        ("institutional", f"{BASE}/fund/BFI82U?response=json&dayDate={ds}&type=day", lambda j: parse_bfi(j)),
        ("margin", f"{BASE}/marginTrading/MI_MARGN?response=json&date={ds}&selectType=MS", parse_margin),
        ("t86", f"{BASE}/fund/T86?response=json&date={ds}&selectType=ALLBUT0999", lambda j: parse_t86(j, cfg)),
        ("exdiv", f"{BASE}/exRight/TWT48U?response=json", lambda j: parse_exdiv(j, today, cfg)),
    ]
    for key, url, parser in steps:
        try:
            j = get(url, cfg)
            if j.get("stat") not in (None, "OK"):
                raise ValueError(j.get("stat"))
            write_json(raw / f"{key}.json", j)
            result[key] = parser(j)
        except Exception as e:  # noqa: BLE001
            result["missing"].append(key)
            result["errors"].append(f"{key}: {type(e).__name__}: {str(e)[:120]}")
    write_json(outdir / "market.json", result)
    print(f"OK 資料日 {data_date}（{roc_date(data_date)}），缺：{result['missing'] or '無'}")


if __name__ == "__main__":
    main()

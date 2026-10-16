"""新聞：候選清單與讀內文。

  python3 scripts/news.py fetch  [--today YYYY-MM-DD]        → data/<today>/news_candidates.json
  python3 scripts/news.py select N1 N2 ... [--today ...]     → 讀內文 → data/<today>/news_selected.json
來源：Yahoo股市、經濟日報、鉅亨網。單一來源失敗不影響其他來源，記為「無資料」。
"""
import argparse
import datetime as dt
import html
import json
import re
from email.utils import parsedate_to_datetime

from common import ROOT, TPE, http_get, load_config, today_tpe, write_json

FEEDS = {
    "yahoo": [("Yahoo股市", "https://tw.stock.yahoo.com/rss?category=tw-market")],
    "udn": [("經濟日報", "https://money.udn.com/rssfeed/news/1001/5590?ch=money"),
            ("經濟日報", "https://money.udn.com/rssfeed/news/1001/5607?ch=money")],
    "cnyes": [("鉅亨網", "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=40")],
}


def strip_tags(s):
    s = html.unescape(s or "")
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_rss(src, body):
    out = []
    for it in re.findall(r"<item>(.*?)</item>", body, re.S):
        def tag(t):
            m = re.search(rf"<{t}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{t}>", it, re.S)
            return m.group(1).strip() if m else ""
        try:
            t = parsedate_to_datetime(tag("pubDate")).astimezone(TPE)
        except Exception:  # noqa: BLE001
            t = None
        out.append({"source": src, "title": strip_tags(tag("title")), "link": strip_tags(tag("link")),
                    "time": t.isoformat() if t else None, "summary": strip_tags(tag("description"))[:300]})
    return out


def parse_cnyes(src, j):
    out = []
    for it in j.get("items", {}).get("data", []):
        t = dt.datetime.fromtimestamp(it["publishAt"], TPE)
        out.append({"source": src, "title": it.get("title", ""),
                    "link": f"https://news.cnyes.com/news/id/{it['newsId']}",
                    "time": t.isoformat(), "summary": strip_tags(it.get("summary") or it.get("content"))[:300],
                    "_body": strip_tags(it.get("content"))[:4000]})
    return out


def cmd_fetch(today):
    cfg = load_config()
    now = dt.datetime.now(TPE)
    since = now - dt.timedelta(hours=cfg["news"]["lookback_hours"])
    mj = ROOT / "data" / today.isoformat() / "market.json"
    if mj.exists():  # 從資料日收盤（13:30）起算，週一才不會漏掉週五盤後新聞
        m = json.loads(mj.read_text(encoding="utf-8"))
        if m.get("data_date"):
            close = dt.datetime.combine(dt.date.fromisoformat(m["data_date"]), dt.time(13, 30), TPE)
            since = min(since, close)
    items, missing = [], []
    for key in cfg["news"]["sources"]:
        got = 0
        for src, url in FEEDS[key]:
            try:
                if key == "cnyes":
                    items += (r := parse_cnyes(src, http_get(url, gap=1, retry_waits=(5, 15))))
                else:
                    items += (r := parse_rss(src, http_get(url, gap=1, retry_waits=(5, 15), expect_json=False)))
                got += len(r)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {src} 失敗：{e}")
        if not got:
            missing.append(key)
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["time"] or "", reverse=True):
        k = re.sub(r"\W", "", it["title"])[:18]
        if k in seen or not it["title"]:
            continue
        if it["time"] and dt.datetime.fromisoformat(it["time"]) < since:
            continue
        seen.add(k)
        uniq.append(it)
    for i, it in enumerate(uniq, 1):
        it["id"] = i
    outdir = ROOT / "data" / today.isoformat()
    write_json(outdir / "news_candidates.json", {"missing": missing, "items": uniq})
    print(f"候選新聞 {len(uniq)} 則，缺來源：{missing or '無'}")
    for it in uniq:
        print(f"[{it['id']:>3}] {it['source']} {(it['time'] or '')[5:16]} {it['title']}")


def read_body(it):
    if it.get("_body"):
        return it["_body"]
    page = http_get(it["link"], gap=1, retry_waits=(5,), expect_json=False)
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
            ld = ld[0] if isinstance(ld, list) else ld
            if ld.get("articleBody"):
                return strip_tags(ld["articleBody"])[:4000]
        except Exception:  # noqa: BLE001
            pass
    # 從正文容器開始切，避免把網站選單當內文（Yahoo: atoms；經濟日報: article-body）
    for marker in ('class="atoms"', 'id="article_body"', 'class="article-body"'):
        if marker in page:
            page = page[page.index(marker):]
            break
    paras = [strip_tags(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", page, re.S)]
    junk = ("版權", "Copyright", "轉貼", "訂戶獨享", "凱衛資訊", "自動切換深淺", "本站元件")
    paras = [p for p in paras if len(p) > 25 and not any(j in p for j in junk)]
    return " ".join(paras)[:4000]


def cmd_select(today, ids):
    outdir = ROOT / "data" / today.isoformat()
    cands = {it["id"]: it for it in json.loads((outdir / "news_candidates.json").read_text(encoding="utf-8"))["items"]}
    sel = []
    for i in ids:
        it = dict(cands[i])
        try:
            body = read_body(it)
            for stop in ("檢視留言", "相關內容", "其他人也在看", "更多FTNN", "更多太報"):
                body = body.split(stop)[0]
            it["body"] = body.strip()
        except Exception as e:  # noqa: BLE001
            it["body"] = ""
            it["body_error"] = str(e)[:120]
        it.pop("_body", None)
        sel.append(it)
        print(f"[{i}] {it['title']}（內文 {len(it['body'])} 字）")
    write_json(outdir / "news_selected.json", sel)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "select"])
    ap.add_argument("ids", nargs="*", type=int)
    ap.add_argument("--today")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else today_tpe()
    cmd_fetch(today) if a.cmd == "fetch" else cmd_select(today, a.ids)

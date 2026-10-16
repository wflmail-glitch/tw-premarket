"""數字核對：AI 段落裡的每個數字都要找得到出處。

規則
- 今日重點：數字只能來自 market.json（證交所），不准用新聞的數字
- 新聞／今天要注意：數字可來自 market.json 或已讀的新聞內文
- 程式渲染的數字區塊：逐項與 market.json 重新計算比對（計數 N/N）
不通過 → exit 1，並列出找不到出處的數字。
"""
import argparse
import datetime as dt
import json
import re
import sys

from build_report import parse_ai
from common import ROOT, today_tpe

# 注意：不能用 \w 當邊界——中文字在 Python 也算 \w，會漏抓「重挫2202.18點」這種數字
NUM_RE = re.compile(r"(?<![0-9A-Za-z.])[-+−]?\d[\d,]*(?:\.\d+)?")


def norm(s):
    s = s.replace(",", "").replace("−", "-").lstrip("+-")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def variants(v):
    out = set()
    if isinstance(v, bool) or v is None:
        return out
    if isinstance(v, str):
        for x in NUM_RE.findall(v):
            out.add(norm(x))
        return out
    v = abs(float(v))
    for scale in (1, 1e8, 1e4, 1e3, 1e12):
        x = v / scale
        for d in (0, 1, 2):
            out.add(norm(f"{x:.{d}f}"))
    return out


def walk(o, acc):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(k, acc) if isinstance(k, str) else None
            walk(v, acc)
    elif isinstance(o, list):
        for v in o:
            walk(v, acc)
    else:
        acc |= variants(o)
    return acc


def nums_in(text):
    out = []
    for x in NUM_RE.findall(text):
        n = norm(x)
        if "." not in n and len(n) <= 2:   # 日期、名次、檔數等小整數不核對
            continue
        out.append((x, n))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else today_tpe()
    dd = ROOT / "data" / today.isoformat()
    m = json.loads((dd / "market.json").read_text(encoding="utf-8"))
    if m["status"] != "ok":
        print("非交易資料日，略過核對"); return
    facts = walk(m, set())
    facts |= {str(today.year), str(today.year - 1911)}
    news = set()
    sel = dd / "news_selected.json"
    if sel.exists():
        for it in json.loads(sel.read_text(encoding="utf-8")):
            news |= variants(it.get("title", "")) | variants(it.get("body", "")) | variants(it.get("summary", ""))
    ai = parse_ai((dd / "ai.md").read_text(encoding="utf-8"))

    bad, total = [], 0
    for sec, text in ai.items():
        allowed = facts if sec == "今日重點" else (facts | news)
        for raw, n in nums_in(text):
            total += 1
            if n not in allowed:
                hint = "（新聞裡有，但今日重點只能用證交所數字）" if (sec == "今日重點" and n in news) else ""
                bad.append(f"[{sec}] {raw}{hint}")

    # 渲染區塊：把報告裡程式產生的數字也逐一對回 market.json
    rep = (ROOT / "reports" / f"{today.isoformat()}.md").read_text(encoding="utf-8")
    block = rep.split("【大盤】", 1)[1].split("【新聞】", 1)[0]
    rb = nums_in("【大盤】" + block)
    ok_rb = sum(1 for _, n in rb if n in facts)
    print(f"數字區塊（程式產生）：{ok_rb}/{len(rb)} 對得上證交所資料")
    print(f"AI 段落數字：{total - len(bad)}/{total} 有出處")
    miss_rb = [raw for raw, n in rb if n not in facts]
    if miss_rb:
        print("  數字區塊對不上：", miss_rb)
    if bad:
        print("  找不到出處：")
        for b in bad:
            print("   -", b)
    result = {"render_ok": ok_rb, "render_total": len(rb), "ai_ok": total - len(bad), "ai_total": total,
              "problems": bad + miss_rb}
    (dd / "verify.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(1 if (bad or miss_rb) else 0)


if __name__ == "__main__":
    main()

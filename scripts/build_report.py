"""組報告：程式渲染數字區塊 + AI 寫的 ai.md（今日重點／新聞／今天要注意）→ reports/<today>.md

  python3 scripts/build_report.py [--today YYYY-MM-DD]
數字區塊完全由程式從 market.json 產生；AI 只寫文字段落，且其數字要過 verify_report.py。
"""
import argparse
import datetime as dt
import json
import re

from common import ROOT, load_config, today_tpe, watch_codes
from holdings import compute as compute_holdings

WD = "一二三四五六日"
EXCLUDE_SECTORS = {"電子工業", "電子"}


def d_label(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.isoformat()}（{WD[d.weekday()]}）"


def yi(v, d=1):
    return f"{v / 1e8:+,.{d}f}"


def lots(v):
    return f"{v:+,.0f}"


def wan(v):
    return f"{abs(v) / 10000:.2f}萬張" if abs(v) >= 10000 else f"{abs(v):,.0f}張"


def render_market(m, cfg):
    L = []
    miss = set(m.get("missing", []))
    t = m["taiex"]
    L.append("【大盤】")
    L.append(f"加權指數 {t['close']:,.2f}（{t['chg']:+,.2f}，{t['pct']:+.2f}%）")
    L.append(f"股票成交金額 {m['turnover'] / 1e8:,.1f} 億")
    L.append(f"上漲 {m['up']:,.0f} 家（漲停 {m['limit_up']:,.0f}）／下跌 {m['down']:,.0f} 家（跌停 {m['limit_down']:,.0f}）／平盤 {m['flat']:,.0f} 家")

    L.append("")
    L.append("【三大法人】（億元）")
    if "institutional" in miss:
        L.append("無資料")
    else:
        i = m["institutional"]
        L.append(f"外資 {yi(i['foreign'])}｜投信 {yi(i['trust'])}｜自營商 {yi(i['dealer'])}｜合計 {yi(i['total'])}")
    if "t86" not in miss:
        tb = m["t86"]
        L.append("外資買超：" + "、".join(f"{r['name']} {wan(r['foreign'])}" for r in tb["foreign_buy_top"]))
        L.append("外資賣超：" + "、".join(f"{r['name']} {wan(r['foreign'])}" for r in tb["foreign_sell_top"]))

    L.append("")
    L.append("【融資融券】")
    if "margin" in miss:
        L.append("無資料")
    else:
        g = m["margin"]
        L.append(f"融資餘額 {g['fin_amt'] / 1e8:,.1f} 億（{g['fin_amt_chg'] / 1e8:+,.1f} 億）")
        L.append(f"融資 {g['fin_lots']:,.0f} 張（{lots(g['fin_lots_chg'])}）／融券 {g['short_lots']:,.0f} 張（{lots(g['short_lots_chg'])}）")

    L.append("")
    L.append("【類股】")
    top = [s for s in m["sector_top"] if s["name"] not in EXCLUDE_SECTORS]
    bot = [s for s in m["sector_bottom"] if s["name"] not in EXCLUDE_SECTORS]
    L.append("最強：" + "、".join(f"{s['name']} {s['pct']:+.2f}%" for s in top))
    L.append("最弱：" + "、".join(f"{s['name']} {s['pct']:+.2f}%" for s in bot))

    t86w = m.get("t86", {}).get("watch", {})
    if cfg.get("holdings"):
        h = compute_holdings(cfg, m)
        L.append("")
        L.append("【我的持股】（收盤價計，已扣預估賣出手續費＋交易稅）")
        L.append(f"總市值 {h['total_value']:,.0f}｜預估損益 {h['total_pnl']:+,.0f}（{h['total_ret']:+.2f}%）｜當日 {h['day_pnl']:+,.0f}")
        for r in h["rows"]:
            if r.get("missing"):
                L.append(f"{r['code']} {r['name']} 無資料"); continue
            f = t86w.get(r["code"], {})
            fi = f"｜外資 {lots(f['foreign'])}" if f else ""
            L.append(f"{r['name']} {r['close']:,.2f}（{r['pct']:+.2f}%）市值 {r['value']:,} 損益 {r['pnl']:+,}（{r['ret']:+.2f}%）{fi}")

    L.append("")
    L.append("【觀察清單】")
    held = {x["code"] for x in cfg.get("holdings", [])}
    watch = [c for c in watch_codes(cfg) if c not in held]
    for code in watch:
        q = m["quotes"].get(code)
        if not q:
            L.append(f"{code} 無資料")
            continue
        line = f"{code} {q['name']} {q['close']:,.2f}（{q['chg']:+,.2f}，{q['pct']:+.2f}%）量 {q['vol_lots']:,} 張"
        f = t86w.get(code)
        if f:
            line += f"｜外資 {lots(f['foreign'])}｜投信 {lots(f['trust'])}"
        L.append(line)
    return "\n".join(L)


def render_exdiv(m):
    if "exdiv" in m.get("missing", []) or "exdiv" not in m:
        return ["除權息：無資料"]
    e = m["exdiv"]
    out = [f"今日除權息共 {e['today_count']} 檔"]
    for r in e["watch_upcoming"]:
        cash = f"現金 {r['cash']:.4g} 元" if r["cash"] else "金額待公告"
        out.append(f"觀察清單：{r['code']} {r['name']} {r['date'][5:].replace('-', '/')} 除{r['type']}（{cash}）")
    return out


def parse_ai(text):
    secs, cur = {}, None
    for line in text.splitlines():
        h = re.match(r"^##\s*(.+?)\s*$", line)
        if h:
            cur = h.group(1)
            secs[cur] = []
        elif cur:
            secs[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in secs.items()}


def build(today):
    cfg = load_config()
    dd = ROOT / "data" / today.isoformat()
    m = json.loads((dd / "market.json").read_text(encoding="utf-8"))
    if m["status"] == "closed":
        return f"📴 {d_label(today.isoformat())} 今天休市"
    if m["status"] != "ok":
        return f"⚠️ 台股盤前整理｜{d_label(today.isoformat())}\n抓資料失敗：\n" + "\n".join(m.get("errors", []))
    ai = parse_ai((dd / "ai.md").read_text(encoding="utf-8")) if (dd / "ai.md").exists() else {}
    news_missing = []
    nc = dd / "news_candidates.json"
    if nc.exists():
        news_missing = json.loads(nc.read_text(encoding="utf-8")).get("missing", [])

    parts = [f"📊 台股盤前整理｜{d_label(today.isoformat())}", f"資料日：{d_label(m['data_date'])}", ""]
    parts += ["【今日重點】", ai.get("今日重點", "（AI 未產出）"), ""]
    parts += [render_market(m, cfg), ""]
    parts += ["【新聞】", ai.get("新聞", "無資料"), ""]
    parts += ["【今天要注意】", *render_exdiv(m)]
    if ai.get("今天要注意"):
        parts.append(ai["今天要注意"])
    lack = list(m.get("missing", [])) + [f"news:{x}" for x in news_missing]
    parts += ["", f"今日缺少：{('、'.join(lack)) if lack else '無'}", "只整理公開資訊，不構成投資建議"]
    return "\n".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else today_tpe()
    rep = build(today)
    out = ROOT / "reports" / f"{today.isoformat()}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(rep + "\n", encoding="utf-8")
    print(rep)

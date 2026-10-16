"""持股損益：市值 − 總成本 − 預估賣出成本（手續費＋交易稅），算法與券商「預估損益」一致。"""


def compute(cfg, market):
    fee = cfg["fees"]
    rows, tc, tv, tp = [], 0.0, 0.0, 0.0
    for h in cfg.get("holdings", []):
        q = market.get("quotes", {}).get(h["code"])
        cost_total = round(h["shares"] * h["cost"])
        if not q or q["close"] is None:
            rows.append({**h, "missing": True, "cost_total": cost_total})
            continue
        value = round(h["shares"] * q["close"])
        tax = {"etf": fee["tax_etf"], "dr": fee["tax_dr"]}.get(h["type"], fee["tax_stock"])
        sell_cost = int(value * fee["broker_fee"]) + int(value * tax)
        pnl = value - cost_total - sell_cost
        day = round(h["shares"] * q["chg"])
        rows.append({**h, "close": q["close"], "chg": q["chg"], "pct": q["pct"], "cost_total": cost_total,
                     "value": value, "pnl": pnl, "ret": pnl / cost_total * 100, "day_pnl": day})
        tc += cost_total; tv += value; tp += pnl
    day_total = sum(r.get("day_pnl", 0) for r in rows)
    return {"rows": rows, "total_cost": tc, "total_value": tv, "total_pnl": tp,
            "total_ret": (tp / tc * 100) if tc else None, "day_pnl": day_total}

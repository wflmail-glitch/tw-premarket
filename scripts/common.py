"""共用工具：設定、時間、HTTP（節流＋被擋重試）、數字格式。只用標準函式庫。"""
import datetime as dt
import json
import os
import re
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPE = dt.timezone(dt.timedelta(hours=8))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def load_config():
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def load_secrets():
    """環境變數優先，其次 .secrets.env（KEY=VALUE）。"""
    env = {}
    p = ROOT / ".secrets.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith(("TELEGRAM_", "LINE_"))})
    return env


def today_tpe():
    return dt.datetime.now(TPE).date()


class Blocked(Exception):
    pass


_last_call = [0.0]


def http_get(url, gap=5, retry_waits=(20, 45, 90), expect_json=True, timeout=30):
    """節流 GET。證交所被擋時回 HTML 安全頁 → 等待後重試。"""
    waits = list(retry_waits)
    attempt = 0
    while True:
        elapsed = time.time() - _last_call[0]
        if elapsed < gap:
            time.sleep(gap - elapsed)
        _last_call[0] = time.time()
        attempt += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", errors="replace")
            if expect_json:
                if "FOR SECURITY REASONS" in body or body.lstrip().startswith("<"):
                    raise Blocked(f"被擋（安全頁）: {url}")
                return json.loads(body)
            return body
        except Exception as e:  # noqa: BLE001
            if not waits:
                raise
            w = waits.pop(0)
            print(f"  ! 第{attempt}次失敗（{type(e).__name__}: {str(e)[:80]}），{w}s 後重試", flush=True)
            time.sleep(w)


def num(s):
    """'1,234.5' / '<p ...>-</p>' 等 → float；空值 None。"""
    if s is None:
        return None
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    if s in ("", "--", "-", "X"):
        return None
    m = re.match(r"^-?\d+(\.\d+)?", s)
    return float(m.group(0)) if m else None


def sign_of(cell):
    """證交所漲跌欄位：'<p style= color:red>+</p>' → +1；green '-' → -1。"""
    t = re.sub(r"<[^>]+>", "", str(cell)).strip()
    return -1 if t == "-" else (1 if t == "+" else 0)


def yi(v, d=1):
    """元 → 億，帶正負號字串。"""
    return f"{v / 1e8:+,.{d}f}"


def fmt_signed(v, d=2):
    return f"{v:+,.{d}f}"


def roc_date(d):
    return f"{d.year - 1911}年{d.month:02d}月{d.day:02d}日"


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def watch_codes(cfg):
    """持股優先，再加額外觀察清單（去重、保序）。"""
    codes = [h["code"] for h in cfg.get("holdings", [])]
    codes += cfg["watchlist"].get("etfs", []) + cfg["watchlist"].get("stocks", [])
    return list(dict.fromkeys(codes))

"""推播報告。通道由 config.toml [notify].channel 決定（telegram / line）。

  python3 scripts/send.py [--today YYYY-MM-DD] [--text "單行訊息"] [--dry-run]
憑證：環境變數或 .secrets.env
  telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  line:     LINE_CHANNEL_TOKEN, LINE_TO（userId 或 groupId）
"""
import argparse
import datetime as dt
import json
import sys
import urllib.request

from common import ROOT, load_config, load_secrets, today_tpe


def chunks(text, size):
    out, cur = [], ""
    for para in text.split("\n\n"):
        piece = (cur + "\n\n" + para) if cur else para
        if len(piece) <= size:
            cur = piece
        else:
            if cur:
                out.append(cur)
            while len(para) > size:
                out.append(para[:size]); para = para[size:]
            cur = para
    if cur:
        out.append(cur)
    return out


def post(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode()


def send_telegram(text, s):
    tok, chat = s.get("TELEGRAM_BOT_TOKEN"), s.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        sys.exit("缺 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
    for c in chunks(text, 4000):
        st, body = post(f"https://api.telegram.org/bot{tok}/sendMessage",
                        {"chat_id": chat, "text": c, "disable_web_page_preview": True})
        print("telegram", st, body[:80])


def send_line(text, s):
    tok, to = s.get("LINE_CHANNEL_TOKEN"), s.get("LINE_TO")
    if not tok or not to:
        sys.exit("缺 LINE_CHANNEL_TOKEN / LINE_TO")
    msgs = [{"type": "text", "text": c} for c in chunks(text, 4900)][:5]
    st, body = post("https://api.line.me/v2/bot/message/push", {"to": to, "messages": msgs},
                    {"Authorization": f"Bearer {tok}"})
    print("line", st, body[:80])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--today")
    ap.add_argument("--text")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today) if a.today else today_tpe()
    text = a.text or (ROOT / "reports" / f"{today.isoformat()}.md").read_text(encoding="utf-8").strip()
    ch = load_config()["notify"]["channel"]
    if a.dry_run:
        for i, c in enumerate(chunks(text, 4000 if ch == "telegram" else 4900), 1):
            print(f"--- 第{i}則（{len(c)} 字）")
        sys.exit(0)
    (send_telegram if ch == "telegram" else send_line)(text, load_secrets())

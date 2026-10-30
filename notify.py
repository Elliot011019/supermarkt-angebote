"""读 docs/data.json，把今天的特价摘要发到 Telegram。

需要两个环境变量（在 GitHub 仓库的 Settings → Secrets 里设置）：
    TELEGRAM_BOT_TOKEN   机器人 token（@BotFather 给的）
    TELEGRAM_CHAT_ID     你的聊天 ID（@userinfobot 查到的数字）

本地预览，不发送：
    python notify.py --dry-run
"""
import html, json, os, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).parent
PAGE = "https://elliot011019.github.io/supermarkt-angebote/"
TZ = ZoneInfo("Europe/Berlin")
WEEKDAY = "一二三四五六日"
UNIT_ORDER = {"kg": 0, "l": 1}


def when(iso):
    return datetime.fromisoformat(iso) if iso else None


def eur(v):
    return f"{v:.2f}".replace(".", ",") if v is not None else ""


def off(o):
    return round((1 - o["price"] / o["oldPrice"]) * 100) if o.get("oldPrice") and o.get("price") and o["oldPrice"] > o["price"] else 0


def line(o):
    """一行：名称 价格（单价）超市 [App]"""
    ref = f"（{eur(o['refPrice'])} €/{o['unit']}）" if o.get("refPrice") and o.get("unit") else ""
    app = " 📱" if o.get("loyalty") else ""
    return f"{html.escape(o['name'])} <b>{eur(o['price'])} €</b>{ref} · {o['store']}{app}"


def build(data, now):
    alive = [o for o in data["offers"] if not o["to"] or when(o["to"]) >= now]
    today = [o for o in alive if not o["from"] or when(o["from"]) <= now]
    soon = [o for o in alive if o["from"] and when(o["from"]) > now]
    local = now.astimezone(TZ)
    out = [f"🛒 <b>今日特价</b> · {local.month}月{local.day}日（周{WEEKDAY[local.weekday()]}）"]

    # 每个类别里 A 级、单价最低的一条（按 kg / l 单价比，没有单价就比价格）
    best = []
    for cat in data["categories"]:
        a = [o for o in today if cat in o["cats"] and (o.get("nut") or {}).get("grade") == "A"]
        if a:
            o = min(a, key=lambda o: (UNIT_ORDER.get(o["unit"], 2), o.get("refPrice") or o["price"] or 1e9))
            best.append(f"{cat}｜{line(o)}")
    if best:
        out += ["", "💪 <b>A 级好货</b>（每类单价最低）", *best]

    top = sorted((o for o in today if off(o)), key=off, reverse=True)[:5]
    if top:
        out += ["", "🔥 <b>折扣最大</b>", *(f"-{off(o)}% {line(o)}" for o in top)]

    if soon:
        first = min(when(o["from"]) for o in soon).astimezone(TZ)
        per_store = Counter(o["store"] for o in soon)
        out += ["", f"🔜 {first.month}月{first.day}日起还有 {len(soon)} 条：" + " · ".join(f"{s} {n}" for s, n in per_store.most_common())]

    out += ["", f"👉 <a href=\"{PAGE}\">打开完整列表</a>"]
    return "\n".join(out)


def main():
    data = json.loads((ROOT / "docs" / "data.json").read_text(encoding="utf-8"))
    text = build(data, datetime.now(timezone.utc))
    if "--dry-run" in sys.argv:
        print(text)
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("没有设置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，跳过发送。")
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    if not r.ok:
        # 只打印 Telegram 的错误说明，不打印 token
        raise RuntimeError(f"Telegram 发送失败：{r.status_code} {r.json().get('description', '')}")
    print("已发送到 Telegram。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("通知失败：", e, file=sys.stderr)
        sys.exit(1)

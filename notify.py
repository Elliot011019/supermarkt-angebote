"""读 docs/data.json，把今天的特价摘要发到 Telegram：先发一组 A 级好货的相册，再发文字摘要。

需要两个环境变量（在 GitHub 仓库的 Settings → Secrets 里设置）：
    TELEGRAM_BOT_TOKEN   机器人 token（@BotFather 给的）
    TELEGRAM_CHAT_ID     你的聊天 ID（@userinfobot 查到的数字）

本地预览，不发送（会试着下载图片，检查哪些商品有图）：
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
NUM = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
ALBUM_MAX = 10   # Telegram 一个相册最多 10 张
UA = {"User-Agent": "Mozilla/5.0 (personal deal tracker)"}


def when(iso):
    return datetime.fromisoformat(iso) if iso else None


def eur(v):
    return f"{v:.2f}".replace(".", ",") if v is not None else ""


def line(o):
    """一行：名称 价格（单价）超市 [App]"""
    ref = f"（{eur(o['refPrice'])} €/{o['unit']}）" if o.get("refPrice") and o.get("unit") else ""
    app = " 📱" if o.get("loyalty") else ""
    return f"{html.escape(o['name'])} <b>{eur(o['price'])} €</b>{ref} · {o['store']}{app}"


def build(data, now):
    """返回 (文字摘要, A 级好货列表)。列表每项是 (带编号的一行, 商品)。"""
    alive = [o for o in data["offers"] if not o["to"] or when(o["to"]) >= now]
    today = [o for o in alive if not o["from"] or when(o["from"]) <= now]
    soon = [o for o in alive if o["from"] and when(o["from"]) > now]
    local = now.astimezone(TZ)
    out = [f"🛒 <b>今日特价</b> · {local.month}月{local.day}日（周{WEEKDAY[local.weekday()]}）"]

    # 每个类别里 A 级、单价最低的一条（按 kg / l 单价比，没有单价就比价格）
    picks = []
    for cat in data["categories"]:
        a = [o for o in today if cat in o["cats"] and (o.get("nut") or {}).get("grade") == "A"]
        if a:
            o = min(a, key=lambda o: (UNIT_ORDER.get(o["unit"], 2), o.get("refPrice") or o["price"] or 1e9))
            picks.append((f"{NUM[len(picks)]} {cat}｜{line(o)}", o))
    if picks:
        out += ["", "💪 <b>A 级好货</b>（每类单价最低）", *(t for t, _ in picks)]

    if soon:
        first = min(when(o["from"]) for o in soon).astimezone(TZ)
        per_store = Counter(o["store"] for o in soon)
        out += ["", f"🔜 {first.month}月{first.day}日起还有 {len(soon)} 条：" + " · ".join(f"{s} {n}" for s, n in per_store.most_common())]

    out += ["", f"👉 <a href=\"{PAGE}\">打开完整列表</a>"]
    return "\n".join(out), picks


def photos(picks):
    """下载 A 级好货的商品图。没图或下载失败的跳过。返回 [(文件名, 图片字节, 图注)]。"""
    got = []
    for caption, o in picks:
        if not o.get("img") or len(got) >= ALBUM_MAX:
            continue
        try:
            r = requests.get(o["img"], headers=UA, timeout=30)
            if r.ok and r.headers.get("content-type", "").startswith("image/"):
                got.append((f"p{len(got)}.jpg", r.content, caption))
        except requests.RequestException:
            pass
    return got


def send(token, method, **kw):
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", timeout=60, **kw)
    if not r.ok:
        # 只打印 Telegram 的错误说明，不打印 token
        raise RuntimeError(f"{method} 失败：{r.status_code} {r.json().get('description', '')}")


def main():
    data = json.loads((ROOT / "docs" / "data.json").read_text(encoding="utf-8"))
    text, picks = build(data, datetime.now(timezone.utc))
    pics = photos(picks)
    if "--dry-run" in sys.argv:
        print(f"[相册 {len(pics)} 张]")
        for _, img, cap in pics:
            print(f"  {cap}（{len(img) // 1024} KB）")
        print(text)
        return

    # 粘贴 Secret 时容易带上空格或换行，去掉
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        print("没有设置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，跳过发送。")
        return

    # 慕尼黑时间 0–7 点发的消息静音：照常收到，但半夜不响铃不震动
    quiet = datetime.now(TZ).hour < 7

    # 先发相册；相册失败也照发文字，最后再报错
    album_error = None
    if pics:
        media = [{"type": "photo", "media": f"attach://{name}", "caption": cap, "parse_mode": "HTML"}
                 for name, _, cap in pics]
        try:
            if len(media) == 1:   # 只有一张时 sendMediaGroup 不接受，改用 sendPhoto
                name, img, cap = pics[0]
                send(token, "sendPhoto", data={"chat_id": chat, "caption": cap, "parse_mode": "HTML", "disable_notification": str(quiet).lower()},
                     files={"photo": (name, img)})
            else:
                send(token, "sendMediaGroup", data={"chat_id": chat, "media": json.dumps(media, ensure_ascii=False),
                                                       "disable_notification": str(quiet).lower()},
                     files={name: (name, img) for name, img, _ in pics})
        except Exception as e:
            album_error = e

    send(token, "sendMessage", json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                     "disable_web_page_preview": True, "disable_notification": quiet})
    print(f"已发送到 Telegram（相册 {len(pics)} 张 + 文字摘要{'，静音' if quiet else ''}）。")
    if album_error:
        raise RuntimeError(f"相册没发出去：{album_error}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("通知失败：", e, file=sys.stderr)
        sys.exit(1)

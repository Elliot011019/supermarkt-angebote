"""抓取 marktguru 上 5 家超市的特价，按 config.yaml 的类别过滤，写入 docs/data.json。

注意：marktguru 的接口是非官方的，随时可能变。抓取失败时不会覆盖旧数据，
并以非零状态退出——GitHub 会给你发失败邮件，你就知道该修了。

本地运行：
    pip install requests pyyaml
    python fetch.py            # 正常运行
    python fetch.py --dump     # 额外把原始返回存到 raw.json，方便排查
"""
import json, re, sys, time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import os

import requests
import yaml

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data.json"
API = "https://api.marktguru.de/api/v1/offers/search"
UA = {"User-Agent": "Mozilla/5.0 (personal deal tracker)"}

# 超市识别：拿 advertiser 的 uniqueName 和 name 去匹配
STORES = {
    "Lidl":     ["lidl"],
    "Kaufland": ["kaufland"],
    "REWE":     ["rewe"],
    "EDEKA":    ["edeka", "e-center"],
    "ALDI SÜD": ["aldi-sued", "aldi süd", "aldi sued", "aldi sud"],
}
NOT_STORES = ["aldi-nord", "aldi nord"]


def get_keys():
    """先看环境变量（GitHub Secrets），没有就从 marktguru 首页里读。"""
    ak, ck = os.environ.get("MG_API_KEY"), os.environ.get("MG_CLIENT_KEY")
    if ak and ck:
        return ak, ck
    html = requests.get("https://www.marktguru.de/", headers=UA, timeout=30).text
    for blob in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.S):
        try:
            cfg = json.loads(blob).get("config", {})
        except (json.JSONDecodeError, AttributeError):
            continue
        if cfg.get("apiKey") and cfg.get("clientKey"):
            return cfg["apiKey"], cfg["clientKey"]
    raise RuntimeError("在 marktguru 首页没找到 apiKey/clientKey。见 README 的“手动设置密钥”。")


def search(session, query, zip_code):
    r = session.get(API, params={"as": "web", "q": query, "limit": 500,
                                 "offset": 0, "zipCode": zip_code}, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])


def norm(s):
    return (s or "").lower()


def store_of(offer):
    for adv in offer.get("advertisers") or []:
        key = norm(adv.get("uniqueName")) + " " + norm(adv.get("name"))
        if any(n in key for n in NOT_STORES):
            continue
        for store, needles in STORES.items():
            if any(n in key for n in needles):
                return store
    return None


def matches(offer, cat):
    name = norm((offer.get("product") or {}).get("name"))
    brand = norm((offer.get("brand") or {}).get("name"))
    desc = norm(offer.get("description"))
    head = f"{name} {brand}"
    included = any(k.lower() in head for k in cat.get("include", []))
    cond = cat.get("include_if_desc")
    if not included and cond:
        # 这些词只有描述也对得上才算（比如鱼名 + “Dose”= 鱼罐头）
        included = (any(k.lower() in head for k in cond["words"])
                    and any(k.lower() in desc for k in cond["desc"]))
    if not included:
        return False
    if any(k.lower() in head for k in cat.get("exclude", [])):
        return False
    for w in cat.get("exclude_words", []):
        if re.search(rf"(?<![a-zäöüß]){re.escape(w.lower())}(?![a-zäöüß])", head):
            return False
    if any(k.lower() in desc for k in cat.get("exclude_desc", [])):
        return False
    cat_names = " ".join(norm(c.get("name")) for c in offer.get("categories") or [])
    if any(k.lower() in cat_names for k in cat.get("exclude_categories", [])):
        return False
    return True


def clean_brand(b):
    # 数据源对无品牌商品会填占位符 "thisisnobrand123"
    return "" if not b or b.lower().startswith("thisisnobrand") else b


def is_app_deal(offer):
    desc = norm(offer.get("description"))
    return bool(offer.get("requiresLoyalityMembership")) or bool(re.search(r"mit\s.{0,25}app", desc))


def dedupe(items):
    """同一家超市常把同一个特价放进好几份区域传单，ID 不同但内容一样。
    按 超市 + 名称（去掉空格和连字符）+ 品牌 + 价格 + 截止日 合并。"""
    seen = {}
    for it in items:
        key = (it["store"], re.sub(r"[^a-zäöüß]", "", it["name"].lower()),
               it["brand"].lower(), it["price"], (it["to"] or "")[:10])
        if key in seen:
            kept = seen[key]
            kept["cats"] = sorted(set(kept["cats"]) | set(it["cats"]), key=(kept["cats"] + it["cats"]).index)
            kept["loyalty"] = kept["loyalty"] or it["loyalty"]
        else:
            seen[key] = it
    return list(seen.values())


def produce_grade(rule, pcfg):
    """果蔬：热量、糖、膳食纤维、维生素 C 各按 nutrition.yaml 的分档打分，总分换成等级。"""
    score = 0
    for key, bands in pcfg["points"].items():
        v = rule[key]
        if "max" in bands:
            score += next((pts for limit, pts in bands["max"] if v <= limit), 0)
        else:
            score += next((pts for limit, pts in bands["min"] if v >= limit), 0)
    grade = next(g["grade"] for g in pcfg["grades"] if score >= g.get("min_score", 0))
    return {"scale": "produce", "label": rule["label"], "kcal": rule["kcal"], "sugar": rule["sugar"],
            "fiber": rule["fiber"], "vitc": rule["vitc"], "score": score, "grade": grade}


def nutrition(item, ncfg):
    """按 nutrition.yaml 给商品配上每 100 g 的参考营养值和增肌减脂等级。没有规则命中时返回 None。"""
    name, desc = item["name"].lower(), item["desc"].lower()
    for rule in ncfg["rules"].get(item["cats"][0], []):
        if "name" in rule and not any(k.lower() in name for k in rule["name"]):
            continue
        if "desc" in rule and not any(k.lower() in desc for k in rule["desc"]):
            continue
        if "vitc" in rule:
            return produce_grade(rule, ncfg["produce"])
        p, f, c = rule["p"], rule["f"], rule["c"]
        kcal = 4 * p + 9 * f + 4 * c
        p_pct, f_pct = round(400 * p / kcal), round(900 * f / kcal)
        grade = next(g["grade"] for g in ncfg["grades"]
                     if p_pct >= g.get("min_protein_pct", 0) and f_pct < g.get("max_fat_pct", 101))
        return {"label": rule["label"], "p": p, "f": f, "c": c, "kcal": round(kcal),
                "pPct": p_pct, "grade": grade}
    return None


def slim(offer, store):
    oid = offer.get("id")
    validity = offer.get("validityDates") or [{}]
    imgs = offer.get("images") or {}
    return {
        "id": oid,
        "store": store,
        "name": (offer.get("product") or {}).get("name") or "",
        "brand": clean_brand((offer.get("brand") or {}).get("name")),
        "desc": offer.get("description") or "",
        "price": offer.get("price"),
        "oldPrice": offer.get("oldPrice"),
        "refPrice": offer.get("referencePrice"),
        "unit": (offer.get("unit") or {}).get("shortName") or "",
        "from": validity[0].get("from"),
        "to": validity[-1].get("to"),
        "loyalty": is_app_deal(offer),
        "img": (f"https://mg2de.b-cdn.net/api/v1/offers/{oid}/images/default/0/medium.jpg"
                if imgs.get("count", 1) else None),
        "cats": [],
    }


def main():
    dump = "--dump" in sys.argv
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    zip_code = str(cfg["zip"])

    ak, ck = get_keys()
    s = requests.Session()
    s.headers.update({**UA, "x-apikey": ak, "x-clientkey": ck})

    offers, raw, unmatched = {}, {}, Counter()
    for cat in cfg["categories"]:
        for q in cat["queries"]:
            results = search(s, q, zip_code)
            raw[q] = results
            for o in results:
                store = store_of(o)
                if not store:
                    for a in o.get("advertisers") or []:
                        unmatched[a.get("name")] += 1
                    continue
                if not matches(o, cat):
                    continue
                item = offers.setdefault(o["id"], slim(o, store))
                if cat["name"] not in item["cats"]:
                    item["cats"].append(cat["name"])
            time.sleep(1)  # 别给人家服务器添麻烦

    raw_count = len(offers)
    offers = {o["id"]: o for o in dedupe(offers.values())}

    if not offers:
        raise RuntimeError("一条特价都没抓到，多半是接口变了。旧数据保持不变。")

    ncfg = yaml.safe_load((ROOT / "nutrition.yaml").read_text(encoding="utf-8"))
    for o in offers.values():
        o["nut"] = nutrition(o, ncfg)

    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zip": zip_code,
        "stores": list(STORES),
        "categories": [c["name"] for c in cfg["categories"]],
        "grades": [{"grade": g["grade"], "note": g["note"]} for g in ncfg["grades"]],
        "produceGrades": [{"grade": g["grade"], "note": g["note"]} for g in ncfg["produce"]["grades"]],
        "offers": sorted(offers.values(), key=lambda x: (x["store"], x["name"])),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if dump:
        (ROOT / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    per_store = Counter(o["store"] for o in offers.values())
    print(f"写入 {len(offers)} 条特价（去重前 {raw_count} 条）：", dict(per_store))
    per_cat = Counter(c for o in offers.values() for c in o["cats"])
    print("各类别：", dict(per_cat))
    print("营养等级：", dict(sorted(Counter(o["nut"]["grade"] for o in offers.values() if o["nut"]).items())))
    no_nut = [o["name"] for o in offers.values() if not o["nut"]]
    if no_nut:
        print("没有营养规则：", ", ".join(no_nut))
    if unmatched:
        print("其他商家（已忽略）：", ", ".join(f"{n}({c})" for n, c in unmatched.most_common(10)))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("抓取失败：", e, file=sys.stderr)
        sys.exit(1)

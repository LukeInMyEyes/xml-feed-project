#!/usr/bin/env python3
"""toyota_price_sync.py — refresh Toyota feed prices + MM codes from Toyota SA's
official pricing API (no scraping, no login).

Toyota SA exposes a public, no-key pricing API — the live source behind
toyota.co.za/toyota-price-list:

    https://api-toyota.azure-api.net/vehicle-models/range-name/<Range Name>

It returns every current variant for a model with its MM code, price (incl VAT),
spec basics and image URLs. This script maps each feed model to its API
range-name, pulls current pricing, updates the feed's model + variant prices
(and stamps the MM code onto each variant), and prints a readable diff.

Dry-run by default — nothing is written until you pass --write.

    python3 toyota_price_sync.py                        # dry-run vs the source feed
    python3 toyota_price_sync.py --write                # apply to the source feed
    python3 toyota_price_sync.py --write \
        --also ~/dev/clients/east-toyota/src/data/toyota-feed.json   # + a site snapshot
    python3 toyota_price_sync.py --feed path/to/toyota.json --json changes.json

Notes
-----
* Model-level price_from/price_to/price_range are always taken from the API
  (min/max across current variants) — this is the reliable headline fix.
* Variant prices + MM codes are updated only on a *strong* name match
  (token Jaccard >= MATCH_THRESHOLD); weaker/unmatched variants are flagged for
  a human, never blindly re-priced.
* GR Supra is intentionally absent from the map — Toyota dropped it from the
  online range, so it should not be on the feed either.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api-toyota.azure-api.net/vehicle-models/range-name/"
UA = {"User-Agent": "Mozilla/5.0"}
DEFAULT_FEED = os.path.expanduser("~/dev/tools/sa_new_car_feed/output/brands/toyota.json")
VAT = 1.15
MATCH_THRESHOLD = 0.5   # min token-Jaccard to auto-update a variant's price

# feed slug -> Toyota API range-name(s). The API takes the range name with
# spaces; a handful need a "Toyota " prefix, and LC79 is two ranges we merge.
SLUG_MAP = {
    "bz4x": ["bZ4X"],
    "coaster": ["Coaster"],
    "corolla": ["Corolla"],
    "corolla-cross": ["Corolla Cross"],
    "corolla-hatch": ["Corolla Hatch"],
    "fortuner": ["Fortuner"],
    "gr-corolla": ["GR Corolla"],
    "gr-yaris": ["GR Yaris"],
    "gr86": ["GR86"],
    "hiace": ["Hiace"],
    "hiace-sesfikile": ["Hiace Ses'fikile"],
    "hilux-double-cab": ["Hilux Double Cab"],
    "hilux-single-cab": ["Hilux Single Cab"],
    "hilux-xtra-cab": ["Hilux Xtra Cab"],
    "land-cruiser-300": ["Land Cruiser 300"],
    "land-cruiser-76": ["Land Cruiser 76"],
    "land-cruiser-79": ["Land Cruiser 79 Single Cab", "Land Cruiser 79 Double Cab"],
    "land-cruiser-fj": ["Land Cruiser FJ"],
    "land-cruiser-prado": ["Land Cruiser Prado"],
    "quantum-bus": ["Quantum Bus"],
    "quantum-panel-van": ["Quantum Panel Van"],
    "rav4": ["RAV4"],
    "rumion": ["Toyota Rumion"],
    "starlet": ["Toyota Starlet"],
    "starlet-cross": ["Toyota Starlet Cross"],
    "urban-cruiser": ["Toyota Urban Cruiser"],
    "vitz": ["Toyota Vitz"],
}

# ansi
def c(txt, code):
    return f"\033[{code}m{txt}\033[0m" if sys.stdout.isatty() else txt


def rands(p):
    return "R" + format(int(round(p)), ",").replace(",", " ")


def fetch(rangename):
    url = API + urllib.parse.quote(rangename)
    req = urllib.request.Request(url, headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return data if isinstance(data, list) else []


def api_variants(rangenames):
    """Fetch + merge the current variants for one feed model."""
    out = []
    for rn in rangenames:
        for v in fetch(rn):
            try:
                out.append({
                    "name": v.get("name", ""),
                    "price": int(float(v["price"])),
                    "code": v.get("code", ""),
                    "monthly": int(float(v["monthlyFromPrice"])) if v.get("monthlyFromPrice") else None,
                })
            except (KeyError, ValueError, TypeError):
                continue
    return out


# Canonicalise the two vocabularies (feed uses words, Toyota's API uses codes)
# to a shared token language so the same variant matches across both.
SYNONYMS = [
    (r"gr[\s-]*sport|gr[\s-]*s\b", " grs "),
    (r"gr[\s-]*four", " gr4 "),
    (r"raised body|\brb\b", " rb "),
    (r"station wagon|\bs\s*/?\s*w\b", " sw "),
    (r"single cab|\bs\s*/?\s*c\b", " sc "),
    (r"double cab|\bd\s*/?\s*c\b", " dc "),
    (r"chassis cab", " chassiscab "),
    (r"flat deck", " flatdeck "),
    (r"panel van|\bpv\b", " pv "),
    (r"crew cab|\bcc\b", " cc "),
    (r"\b48v\b|mhev", " mhev "),
    (r"plug[\s-]*in|phev", " phev "),
    (r"\bhybrid\b|\bhev\b", " hev "),
    (r"e[\s-]*four", " efour "),
    (r"gd[\s-]*6", " gd6 "),
    (r"d[\s-]*4d", " d4d "),
    (r"\bmanual\b|\b\d*mt\b", " mt "),
    (r"\bauto(?:matic)?\b|\b\d*at\b|gr[\s-]*dat", " at "),
    (r"(\d)\.(\d)\s*l\b", r" \1\2 "),               # 1.5L -> 15
    (r"(\d)\.(\d)", r" \1\2 "),                       # 1.5  -> 15
    (r"(\d+)\s*-?\s*seater|(\d+)\s*-?\s*s\b", r" \1s "),
]


def tokens(name, model_name):
    s = " " + name.lower() + " "
    for pat, rep in SYNONYMS:
        s = re.sub(pat, rep, s)
    for w in re.split(r"[\s-]+", model_name.lower()):
        if len(w) > 2:                               # drop model words (fortuner, cruiser, 300...)
            s = re.sub(r"\b" + re.escape(w) + r"\b", " ", s)
    s = s.replace("toyota", " ").replace("lc", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    # ignore bare cab-count digits that survived (they add noise, grade carries the signal)
    return {t for t in s.split() if t and t not in {"cab"}}


def jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_match(feed_var, api_vars, model_name):
    ft = tokens(feed_var.get("name", ""), model_name)
    best, best_j = None, 0.0
    for av in api_vars:
        j = jaccard(ft, tokens(av["name"], model_name))
        if j > best_j:
            best, best_j = av, j
    return best, best_j


def sync_model(m, report):
    slug, name = m.get("slug"), m.get("name", "")
    rangenames = SLUG_MAP.get(slug)
    if not rangenames:
        report.append(("skip", slug, "no API slug mapping"))
        return False
    try:
        avs = api_variants(rangenames)
    except Exception as e:  # noqa: BLE001
        report.append(("error", slug, f"API fetch failed: {e}"))
        return False
    if not avs:
        report.append(("error", slug, "API returned no variants"))
        return False

    prices = [a["price"] for a in avs]
    new_from, new_to = min(prices), max(prices)
    old_from, old_to = m.get("price_from"), m.get("price_to")

    changed = False
    delta = (new_from - old_from) if isinstance(old_from, (int, float)) else 0
    if new_from != old_from or new_to != old_to:
        changed = True
    m["price_from"], m["price_to"] = new_from, new_to
    m["price_range"] = rands(new_from) if new_from == new_to else f"{rands(new_from)} – {rands(new_to)}"

    # variant-level: strong-match by name, stamp price + MM code
    updated, flagged = 0, []
    matched_api = set()
    api_by_code = {a["code"]: a for a in avs if a.get("code")}
    for fv in m.get("variants", []):
        # Prefer an exact MM-code match (stamped by a previous run); otherwise
        # fall back to fuzzy name matching. Code matching makes repeat runs solid.
        if fv.get("mm_code") and fv["mm_code"] in api_by_code:
            av, j = api_by_code[fv["mm_code"]], 1.0
        else:
            av, j = best_match(fv, avs, name)
        if av and j >= MATCH_THRESHOLD:
            if fv.get("price_incl") != av["price"]:
                updated += 1
            fv["price_incl"] = av["price"]
            fv["price_excl"] = int(round(av["price"] / VAT))
            fv["price_display"] = rands(av["price"])
            if av["monthly"]:
                fv["monthly_estimate"] = av["monthly"]
            fv["mm_code"] = av["code"]
            matched_api.add(id(av))
        else:
            flagged.append(fv.get("name", "?"))
    new_api = [a["name"] for a in avs if id(a) not in matched_api]

    report.append(("ok", slug, {
        "old_from": old_from, "new_from": new_from, "delta": delta,
        "variants": len(m.get("variants", [])), "updated": updated,
        "flagged": flagged, "api_count": len(avs), "new_api": new_api,
    }))
    return changed


def main():
    ap = argparse.ArgumentParser(description="Sync Toyota feed prices + MM codes from Toyota SA's pricing API.")
    ap.add_argument("--feed", default=DEFAULT_FEED, help="source toyota.json (brand feed)")
    ap.add_argument("--also", nargs="*", default=[], help="extra target files to write the same feed to (e.g. a site snapshot)")
    ap.add_argument("--write", action="store_true", help="apply changes (default is a dry-run)")
    ap.add_argument("--json", help="write a machine-readable diff report to this path")
    args = ap.parse_args()

    with open(args.feed) as f:
        feed = json.load(f)

    report = []
    price_changes = 0
    for m in feed.get("models", []):
        if sync_model(m, m_report := []):
            price_changes += 1
        report.extend(m_report)

    # recompute brand headline
    froms = [m["price_from"] for m in feed["models"]]
    feed["price_from"] = min(froms)
    feed["price_to"] = max(m["price_to"] for m in feed["models"])

    # ---- report ----
    print(c("\nToyota price sync — Toyota SA API vs feed\n", "1"))
    ok = [r for r in report if r[0] == "ok"]
    for _, slug, d in sorted(ok, key=lambda r: -abs(r[2]["delta"])):
        if d["delta"]:
            arrow = c(f"{'+' if d['delta'] > 0 else ''}{rands(abs(d['delta'])) if d['delta']<0 else rands(d['delta'])}", "33")
            head = c(f"{slug:<22}", "1") + f" {rands(d['old_from'])} -> {rands(d['new_from'])}  ({arrow})"
        else:
            head = c(f"{slug:<22}", "2") + f" {rands(d['new_from'])}  (no change)"
        extra = f"  [{d['updated']}/{d['variants']} variants repriced"
        if d["flagged"]:
            extra += c(f", {len(d['flagged'])} flagged", "31")
        if d["new_api"]:
            extra += c(f", {len(d['new_api'])} new on API", "36")
        extra += "]"
        print(head + extra)
        if d["flagged"]:
            print("      flagged (no strong match): " + ", ".join(d["flagged"]))
        if d["new_api"]:
            print(c("      NEW on Toyota's list (not in feed): ", "36") + ", ".join(d["new_api"]))

    for kind, slug, msg in report:
        if kind in ("skip", "error"):
            print(c(f"{slug:<22} {kind.upper()}: {msg}", "31"))

    print(c(f"\n{price_changes} model(s) with price changes; {len(ok)}/{len(feed['models'])} resolved via API.", "1"))

    if args.json:
        json.dump({"changes": [r for r in report]}, open(args.json, "w"), default=str, indent=2)
        print(f"Diff written to {args.json}")

    if args.write:
        for path in [args.feed, *args.also]:
            with open(path, "w") as f:
                json.dump(feed, f, ensure_ascii=False, indent=2)
            print(c(f"WROTE {path}", "32"))
    else:
        print(c("\nDry-run — no files written. Re-run with --write to apply.", "33"))


if __name__ == "__main__":
    main()

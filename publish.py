#!/usr/bin/env python3
"""
publish.py — Publish compiled feeds to the dealer-assets repo (git lane) + purge jsDelivr.

This is the keystone of the "feeds auto-update" system. Until now the dealer-assets
repo (github.com/LukeInMyEyes/dealer-assets, served via jsDelivr) was updated by hand.
This script makes it repeatable so a scheduled run can refresh every dealer site without
anyone touching git.

Git lane = low-churn bundles served via jsDelivr CDN:
  new-car per-brand   output/brands/{brand}.json                      -> dealer-assets/feed/{brand}.json
  new-car per-dealer  output/dealers/{dealer}.json                    -> dealer-assets/feed/{dealer}.json
  specials per-dealer ../sa_specials_feed/output/dealers/*.specials.json
                                                                      -> dealer-assets/feed/{dealer}.specials.json

Flow: copy changed JSON -> git add/commit/push dealer-assets -> purge jsDelivr cache for
each changed file (https://purge.jsdelivr.net/gh/<repo>@main/<path>) so updates go live in
minutes instead of waiting out jsDelivr's ~12h @main cache.

Used-car stock is deliberately NOT handled here — it's high-churn (hourly) and would bloat
git forever; it goes to Supabase instead (publish_usedcars.py, separate "live lane").

Usage:
  python3 publish.py                 # publish feed + specials, commit, push, purge
  python3 publish.py --what feed     # new-car only
  python3 publish.py --what specials # specials only
  python3 publish.py --no-push       # stage + commit locally, skip push/purge (dry-ish run)
  python3 publish.py --no-purge      # commit + push but skip CDN purge
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
NEWCAR_BRANDS = ROOT / "output" / "brands"
NEWCAR_DEALERS = ROOT / "output" / "dealers"
SPECIALS_DEALERS = ROOT.parent / "sa_specials_feed" / "output" / "dealers"

ASSETS_REPO = Path.home() / "dev" / "dealer-assets"
ASSETS_FEED = ASSETS_REPO / "feed"
GH_SLUG = "LukeInMyEyes/dealer-assets"
PURGE_BASE = f"https://purge.jsdelivr.net/gh/{GH_SLUG}@main"


def _sources(what: str) -> list[Path]:
    """Collect source JSON files to publish for the requested lane(s)."""
    files: list[Path] = []
    if what in ("feed", "all"):
        files += sorted(NEWCAR_BRANDS.glob("*.json"))
        if NEWCAR_DEALERS.exists():
            files += sorted(NEWCAR_DEALERS.glob("*.json"))
    if what in ("specials", "all"):
        if SPECIALS_DEALERS.exists():
            files += sorted(SPECIALS_DEALERS.glob("*.specials.json"))
        else:
            print(f"  ! specials output not found at {SPECIALS_DEALERS} — skipping")
    return files


# Top-level keys that change every pipeline run without the data changing. Ignored when
# deciding whether a file is "really" different, so scheduled runs don't spam the git
# history (and jsDelivr purges) with timestamp-only commits.
VOLATILE_KEYS = ("updated_at", "generated", "scraped_at", "compiled_at")


def _meaningful(raw: bytes) -> str:
    """JSON content with volatile timestamp keys stripped, for change comparison."""
    try:
        data = json.loads(raw)
    except Exception:
        return raw.decode("utf-8", "replace")
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in VOLATILE_KEYS}
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _copy_changed(sources: list[Path]) -> list[str]:
    """Copy sources into dealer-assets/feed/ when content meaningfully differs.

    Returns changed relpaths. A change in only the updated_at/generated timestamp is not a
    change — the file is left untouched so no commit or purge is triggered.
    """
    ASSETS_FEED.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    for src in sources:
        dest = ASSETS_FEED / src.name
        new = src.read_bytes()
        if dest.exists() and _meaningful(dest.read_bytes()) == _meaningful(new):
            continue
        dest.write_bytes(new)
        changed.append(f"feed/{src.name}")
    return changed


def _git(*args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ASSETS_REPO), *args],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{out.stderr.strip()}")
    return out.stdout.strip()


def _commit_message(changed: list[str]) -> str:
    brands = sorted({c.split("/")[-1].replace(".specials.json", "").replace(".json", "")
                     for c in changed})
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    head = f"Refresh feed JSON ({len(changed)} files) — {stamp}"
    return head + "\n\n" + "\n".join(f"- {c}" for c in changed) + \
        f"\n\nTouched: {', '.join(brands)}"


def _purge(changed: list[str]) -> None:
    """Hit jsDelivr's purge endpoint for each changed file so the CDN serves fresh data."""
    for rel in changed:
        url = f"{PURGE_BASE}/{rel}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                status = r.status
            print(f"  purged {rel} ({status})")
        except Exception as e:  # purge is best-effort; never fail the publish over it
            print(f"  ! purge failed for {rel}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish compiled feeds to dealer-assets + jsDelivr")
    ap.add_argument("--what", choices=["feed", "specials", "all"], default="all")
    ap.add_argument("--no-push", action="store_true", help="commit locally, skip push + purge")
    ap.add_argument("--no-purge", action="store_true", help="push but skip jsDelivr purge")
    args = ap.parse_args()

    if not ASSETS_REPO.exists():
        print(f"ERROR: dealer-assets repo not found at {ASSETS_REPO}", file=sys.stderr)
        return 1

    sources = _sources(args.what)
    if not sources:
        print("Nothing to publish — no source feed files found.")
        return 0

    changed = _copy_changed(sources)
    if not changed:
        print(f"Up to date — {len(sources)} files checked, none changed. Nothing to publish.")
        return 0

    print(f"Changed {len(changed)} file(s):")
    for c in changed:
        print(f"  {c}")

    _git("add", *changed)
    _git("commit", "-m", _commit_message(changed))
    print("Committed to dealer-assets.")

    if args.no_push:
        print("--no-push set: committed locally only. Skipping push + purge.")
        return 0

    _git("push", "origin", "HEAD")
    print("Pushed to origin.")

    if args.no_purge:
        print("--no-purge set: skipping jsDelivr purge (CDN may serve stale for ~12h).")
        return 0

    print("Purging jsDelivr cache...")
    _purge(changed)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

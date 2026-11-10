#!/usr/bin/env python3
"""Small local idea registry with exact normalized duplicate protection."""
import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNELS_FILE = ROOT / "config" / "channels.json"
REGISTRY_FILE = ROOT / "data" / "ideas" / "registry.json"

def normalize(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[إأآٱ]", "ا", value)
    value = re.sub(r"[ى]", "ي", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.casefold().split())

def fingerprint(channel_id, title):
    raw = channel_id + "|" + normalize(title)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def read_json(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))

def save_registry(data):
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="Add a new idea unless its normalized title already exists for this channel.")
    add.add_argument("--channel-id", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--summary", default="")
    add.add_argument("--source", action="append", default=[])
    listing = sub.add_parser("list", help="List registered ideas.")
    listing.add_argument("--channel-id")
    args = parser.parse_args()

    channel_doc = read_json(CHANNELS_FILE, {"channels": []})
    channel_ids = {c["id"] for c in channel_doc.get("channels", [])}
    if args.command == "add" and args.channel_id not in channel_ids:
        parser.error("Unknown channel ID. Check config/channels.json.")

    data = read_json(REGISTRY_FILE, {"version": 1, "ideas": []})
    if args.command == "add":
        key = fingerprint(args.channel_id, args.title)
        for idea in data["ideas"]:
            if idea.get("channel_id") == args.channel_id and idea.get("fingerprint") == key:
                print("DUPLICATE: an idea with this normalized title already exists for this channel.")
                return 2
        idea_id = hashlib.sha256((key + "|" + str(len(data["ideas"]))).encode()).hexdigest()[:16]
        data["ideas"].append({
            "idea_id": idea_id,
            "channel_id": args.channel_id,
            "title": args.title.strip(),
            "summary": args.summary.strip(),
            "sources": args.source,
            "status": "proposed",
            "fingerprint": key,
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        save_registry(data)
        print(f"ADDED: {idea_id}")
        return 0

    ideas = data.get("ideas", [])
    if args.channel_id:
        ideas = [item for item in ideas if item.get("channel_id") == args.channel_id]
    if not ideas:
        print("No ideas registered.")
    for idea in ideas:
        print(f'{idea.get("channel_id")} | {idea.get("status")} | {idea.get("title")} | {idea.get("idea_id")}')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

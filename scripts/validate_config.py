#!/usr/bin/env python3
"""Validate project configuration using only the Python standard library."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_json(path):
    with (ROOT / path).open(encoding="utf-8") as stream:
        return json.load(stream)

def main():
    document = load_json("config/channels.json")
    pipeline = load_json("config/pipeline.json")
    channels = document.get("channels", [])
    errors = []
    ids = [item.get("id") for item in channels]
    if len(channels) != 7:
        errors.append(f"Expected 7 channels, found {len(channels)}.")
    if len(ids) != len(set(ids)):
        errors.append("Channel IDs must be unique.")
    for item in channels:
        for field in ("id", "name_ar", "name_en", "topic_scope", "voice", "visual"):
            if not item.get(field):
                errors.append(f"{item.get('id', '<unknown>')}: missing {field}.")
    video = pipeline.get("video", {})
    if video.get("min_seconds", 0) > video.get("max_seconds", 0):
        errors.append("Video duration range is invalid.")
    if video.get("scene_change_seconds_min", 0) > video.get("scene_change_seconds_max", 0):
        errors.append("Scene-change range is invalid.")
    if pipeline.get("publishing", {}).get("enabled") is not False:
        errors.append("Publishing must remain disabled during initial setup.")
    if errors:
        print("CONFIGURATION CHECK: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("CONFIGURATION CHECK: PASSED")
    print(f"Validated {len(channels)} independent channel configurations.")
    print("No external services contacted; publishing remains disabled.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

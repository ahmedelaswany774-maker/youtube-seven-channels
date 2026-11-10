#!/usr/bin/env python3
"""Build a channel-specific, QC-gated Shorts production package.

This stage prepares a storyboard and voice instructions. It does not call a TTS
provider, render a video, or publish to YouTube.
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNELS_PATH = ROOT / "config" / "channels.json"
PIPELINE_PATH = ROOT / "config" / "pipeline.json"
REGISTRY_PATH = ROOT / "data" / "ideas" / "registry.json"


def load_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def normalize(value):
    value = unicodedata.normalize("NFKC", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = re.sub(r"[إأآٱ]", "ا", value)
    value = re.sub(r"[ى]", "ي", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.casefold().split())


def subtitle_word_count(text):
    return len((text or "").split())


def validate_package(source, channel, pipeline, registry):
    errors = []
    video = pipeline["video"]
    duration = source.get("duration_seconds")
    if not isinstance(duration, (int, float)) or not video["min_seconds"] <= duration <= video["max_seconds"]:
        errors.append(f"duration_seconds must be between {video['min_seconds']} and {video['max_seconds']}.")

    if source.get("editorial_status") != "approved":
        errors.append("editorial_status must be approved before production.")
    if source.get("rights_status") != "approved":
        errors.append("rights_status must be approved before production.")
    if source.get("original_script") is not True:
        errors.append("original_script must be true.")

    sources = source.get("sources", [])
    if pipeline["quality_gates"].get("require_source_review") and not sources:
        errors.append("At least one source record is required.")
    for index, item in enumerate(sources, 1):
        if not item.get("title") or not item.get("url") or item.get("review_status") != "verified":
            errors.append(f"source #{index} needs title, url, and review_status=verified.")

    scenes = source.get("scenes", [])
    if not scenes:
        errors.append("At least one scene is required.")
    min_scene = video["scene_change_seconds_min"]
    max_scene = video["scene_change_seconds_max"]
    total_scene_time = 0.0
    for index, scene in enumerate(scenes, 1):
        seconds = scene.get("duration_seconds")
        if not isinstance(seconds, (int, float)) or not min_scene <= seconds <= max_scene:
            errors.append(f"scene #{index}: duration_seconds must be between {min_scene} and {max_scene}.")
        else:
            total_scene_time += seconds
        if not scene.get("narration", "").strip():
            errors.append(f"scene #{index}: narration is required.")
        caption = scene.get("subtitle", "")
        words = subtitle_word_count(caption)
        if not video["subtitle_words_min"] <= words <= video["subtitle_words_max"]:
            errors.append(f"scene #{index}: subtitle must contain {video['subtitle_words_min']}-{video['subtitle_words_max']} words.")
        if not scene.get("visual_prompt", "").strip():
            errors.append(f"scene #{index}: visual_prompt is required.")

    if isinstance(duration, (int, float)) and abs(total_scene_time - duration) > 0.15:
        errors.append(f"scene durations total {total_scene_time:.2f}s, not duration_seconds {duration:.2f}s.")

    channel_id = channel["id"]
    title_key = normalize(source.get("title", ""))
    for idea in registry.get("ideas", []):
        if idea.get("channel_id") == channel_id and normalize(idea.get("title", "")) == title_key:
            errors.append("Duplicate title found in the channel idea registry.")
            break
    return errors


def build(source, channel, pipeline):
    return {
        "package_version": 1,
        "channel": {
            "id": channel["id"],
            "name_ar": channel["name_ar"],
            "visual_style": channel.get("visual", {}).get("style"),
            "visual_palette": channel.get("visual", {}).get("palette", [])
        },
        "content": {
            "content_id": hashlib.sha256((channel["id"] + "|" + normalize(source["title"])).encode("utf-8")).hexdigest()[:20],
            "title": source["title"],
            "hook": source["hook"],
            "description": source.get("description", ""),
            "duration_seconds": source["duration_seconds"],
            "editorial_status": source["editorial_status"],
            "rights_status": source["rights_status"],
            "sources": source.get("sources", [])
        },
        "voice": channel["voice"],
        "audio_mix": pipeline["audio"],
        "scenes": source["scenes"],
        "production_status": "ready_for_voice_provider_selection",
        "publishing": {"enabled": False, "visibility": "private"}
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-id", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    channels = load_json(CHANNELS_PATH)["channels"]
    channel = next((item for item in channels if item["id"] == args.channel_id), None)
    if channel is None:
        print(f"Unknown channel ID: {args.channel_id}", file=sys.stderr)
        return 2
    if not channel.get("enabled", False):
        print("Channel is disabled.", file=sys.stderr)
        return 2

    source = load_json(args.input)
    pipeline = load_json(PIPELINE_PATH)
    registry = load_json(REGISTRY_PATH) if REGISTRY_PATH.exists() else {"ideas": []}
    errors = validate_package(source, channel, pipeline, registry)
    if errors:
        print("PRODUCTION PACKAGE: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1

    package = build(source, channel, pipeline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PRODUCTION PACKAGE: READY | {channel['name_ar']} | {package['content']['content_id']}")
    print("Voice profile attached. No audio generated and no video uploaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

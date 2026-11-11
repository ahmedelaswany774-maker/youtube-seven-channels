#!/usr/bin/env python3
"""Free-tier educational Shorts factory. One idea -> Arabic voice -> 9:16 MP4."""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
IDEAS_FILE = ROOT / "ideas.csv"
USED_FILE = ROOT / "used.txt"
PROMPT_FILE = ROOT / "prompts" / "system_prompt.txt"
OUTPUT_DIR = ROOT / "output"
WORK_DIR = ROOT / ".work"
WIDTH, HEIGHT, FPS, TARGET_SECONDS = 1080, 1920, 30, 45
FISH_API_KEY = os.getenv("FISH_API_KEY", "").strip()
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "").strip()
FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_MODEL = "s2.1-pro-free"
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
IMAGE_BASE = "https://image.pollinations.ai/prompt/"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "kombo-city-factory/1.0"})


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def require_tools() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise RuntimeError("أدوات ناقصة: " + ", ".join(missing) + ". ثبّت FFmpeg وأعد التشغيل.")


def load_used() -> set[str]:
    if not USED_FILE.exists():
        return set()
    return {line.strip() for line in USED_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def choose_idea() -> dict:
    with IDEAS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    used = load_used()
    available = [r for r in rows if r.get("id") and r["id"] not in used and r.get("status", "unused") != "used"]
    if not available:
        raise RuntimeError("انتهت الأفكار المتاحة. أضف أفكارًا جديدة إلى ideas.csv.")
    return sorted(available, key=lambda r: int(r["id"]))[0]


def gemini_json(idea: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY غير موجود في GitHub Secrets.")
    template = PROMPT_FILE.read_text(encoding="utf-8")
    prompt = template.replace("{idea}", idea)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.75}
    }
    last_error = None
    for attempt in range(4):
        try:
            response = SESSION.post(url, params={"key": api_key}, json=payload, timeout=90)
            if response.status_code in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Gemini HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = re.sub(r"^\s*```(?:json)?|\s*```\s*$", "", text, flags=re.I)
            result = json.loads(text)
            required = ("script", "image1", "image2", "image3", "image4", "title", "caption", "srt_parts")
            if any(not result.get(k) for k in required) or len(result["srt_parts"]) != 4:
                raise ValueError("Gemini returned incomplete JSON fields.")
            words = result["script"].split()
            if not 65 <= len(words) <= 115:
                raise ValueError(f"طول النص غير مناسب: {len(words)} كلمة (المطلوب 65–115).")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"تعذر توليد السيناريو بعد المحاولات: {last_error}")


def fallback_image(path: Path, scene: int) -> None:
    """Create a clean original illustrated city frame if image service is unavailable."""
    img = Image.new("RGB", (WIDTH, HEIGHT), (20 + scene * 4, 36, 76))
    d = ImageDraw.Draw(img)
    # Soft sky and simple city skyline
    for y in range(0, HEIGHT, 8):
        t = y / HEIGHT
        color = (int(18 + 25*t), int(35 + 35*t), int(75 + 45*t))
        d.rectangle((0, y, WIDTH, y+8), fill=color)
    for i, x in enumerate(range(-40, WIDTH, 180)):
        h = 360 + ((i * 137 + scene * 71) % 520)
        d.rounded_rectangle((x, HEIGHT-650-h, x+135, HEIGHT-500), radius=22, fill=(38, 76, 120), outline=(85, 160, 210), width=5)
        for wy in range(HEIGHT-620-h+35, HEIGHT-530, 85):
            d.rectangle((x+30, wy, x+52, wy+32), fill=(255, 213, 112))
            d.rectangle((x+82, wy, x+104, wy+32), fill=(115, 210, 245))
    # Same blue robot silhouette in all fallback scenes
    cx, cy = WIDTH//2, HEIGHT//2 + 120
    d.ellipse((cx-145, cy-190, cx+145, cy+100), fill=(42, 165, 230), outline=(185, 238, 255), width=12)
    d.rounded_rectangle((cx-185, cy+30, cx+185, cy+350), radius=90, fill=(25, 126, 198), outline=(185, 238, 255), width=12)
    d.ellipse((cx-85, cy-90, cx-25, cy-20), fill=(245, 255, 255))
    d.ellipse((cx+25, cy-90, cx+85, cy-20), fill=(245, 255, 255))
    d.arc((cx-65, cy-5, cx+65, cy+65), 10, 170, fill=(255,255,255), width=9)
    img.save(path, quality=92)


def generate_image(prompt: str, destination: Path, scene: int) -> None:
    fixed = ("original cute small blue helper robot with round glowing eyes, identical character design, "
             "miniature futuristic city, polished family-friendly 3D animated film look, vibrant colors, "
             "cinematic soft lighting, vertical 9:16 composition, no text, no letters, no logo. ")
    full_prompt = fixed + prompt
    url = IMAGE_BASE + quote(full_prompt, safe="") + "?width=768&height=1365&nologo=true"
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=100)
            r.raise_for_status()
            if not r.headers.get("content-type", "").startswith("image/") or len(r.content) < 10_000:
                raise ValueError("Image provider returned invalid or tiny data.")
            destination.write_bytes(r.content)
            with Image.open(destination) as im:
                im.verify()
            return
        except Exception:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    print(f"تحذير: تعذر تنزيل صورة المشهد {scene}؛ سيتم إنشاء بديل محلي.")
    fallback_image(destination, scene)


def make_tts(text: str, output: Path) -> None:
    """Generate narration with the configured Fish Audio cloned voice; never silently fall back."""
    if not FISH_API_KEY:
        raise RuntimeError("FISH_API_KEY غير مضبوط في GitHub Secrets.")
    if not FISH_VOICE_ID:
        raise RuntimeError("FISH_VOICE_ID غير مضبوط في GitHub Secrets.")

    chunks = []
    sentences = re.split(r"(?<=[.!؟?])\\s+|\\n+", text.strip())
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 > 1400 and current:
            chunks.append(current)
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        chunks.append(current)
    if not chunks:
        raise ValueError("نص التعليق الصوتي فارغ.")

    headers = {
        "Authorization": f"Bearer {FISH_API_KEY}",
        "Content-Type": "application/json",
        "model": FISH_MODEL,
    }
    generated = []
    try:
        for index, chunk in enumerate(chunks, start=1):
            response = SESSION.post(
                FISH_TTS_URL, headers=headers,
                json={"text": chunk, "reference_id": FISH_VOICE_ID, "format": "mp3"},
                timeout=180,
            )
            response.raise_for_status()
            part = WORK_DIR / f"fish_voice_{index:03d}.mp3"
            part.write_bytes(response.content)
            if part.stat().st_size < 1000:
                raise RuntimeError(f"Fish Audio returned invalid audio chunk {index}.")
            generated.append(part)
            print(f"Fish Audio: الجزء {index}/{len(chunks)}")
        if len(generated) == 1:
            shutil.copy2(generated[0], output)
        else:
            concat = WORK_DIR / "fish_voice_concat.txt"
            concat.write_text("".join(f"file '{p.resolve().as_posix()}'\\n" for p in generated), encoding="utf-8")
            run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                 "-c:a", "libmp3lame", "-q:a", "2", str(output)])
        if not output.exists() or output.stat().st_size < 1000:
            raise RuntimeError("تعذر إنشاء ملف الصوت النهائي من Fish Audio.")
    finally:
        for part in generated:
            part.unlink(missing_ok=True)
        (WORK_DIR / "fish_voice_concat.txt").unlink(missing_ok=True)


def media_duration(path: Path) -> float:
    result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(result.stdout.strip())


def split_script(script: str, parts: list[str]) -> list[str]:
    cleaned = [re.sub(r"\s+", " ", str(p)).strip() for p in parts]
    if len(cleaned) == 4 and all(cleaned):
        return cleaned
    words = script.split()
    return [" ".join(words[round(i*len(words)/4):round((i+1)*len(words)/4)]) for i in range(4)]


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def create_captions(script: str, parts: list[str], duration: float, output: Path) -> None:
    chunks = split_script(script, parts)
    lines = []
    for i, caption in enumerate(chunks):
        start, end = i * duration / 4, (i + 1) * duration / 4
        lines.extend([str(i + 1), f"{srt_time(start)} --> {srt_time(end)}", caption, ""])
    output.write_text("\n".join(lines), encoding="utf-8-sig")


def build_video(images: list[Path], audio: Path, script: str, captions: Path, output: Path) -> None:
    """Render exactly 45 seconds, 1080x1920, 30fps, four Ken Burns scenes."""
    audio_len = media_duration(audio)
    if audio_len < 20:
        raise RuntimeError(f"الصوت أقصر من المتوقع: {audio_len:.1f} ثانية.")
    # Fit narration to 45s within a conservative tempo range; reject extreme mismatches.
    tempo = audio_len / TARGET_SECONDS
    if not 0.72 <= tempo <= 1.35:
        raise RuntimeError(f"مدة التعليق {audio_len:.1f}s بعيدة عن 45s؛ عدّل طول النص بدل قص الكلام.")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    scene_files = []
    for i, image_path in enumerate(images):
        scene = WORK_DIR / f"scene_{i+1}.mp4"
        frames = int(TARGET_SECONDS / 4 * FPS)
        vf = (f"scale=1200:2134:force_original_aspect_ratio=increase,"
              f"crop=1200:2134,zoompan=z='min(zoom+0.00055,1.15)':"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={FPS},"
              f"setsar=1,format=yuv420p")
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-t", str(TARGET_SECONDS/4),
             "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-r", str(FPS), str(scene)])
        scene_files.append(scene)
    concat_file = WORK_DIR / "concat.txt"
    concat_file.write_text("".join(f"file '{p.as_posix()}'\n" for p in scene_files), encoding="utf-8")
    joined = WORK_DIR / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(joined)])

    # Burn readable Arabic captions using the system Noto Naskh/Cairo-compatible font.
    subtitle_path = captions.as_posix().replace(":", r"\:")
    font_dir = "/usr/share/fonts/truetype"
    vf_sub = (f"subtitles='{subtitle_path}':fontsdir='{font_dir}':"
              "force_style='FontName=DejaVu Sans,FontSize=19,Bold=1,"
              "PrimaryColour=&H0000D7FF,OutlineColour=&H00101010,BorderStyle=1,"
              "Outline=3,Shadow=1,Alignment=2,MarginV=230'")
    music = ROOT / "assets" / "music.mp3"
    cmd = ["ffmpeg", "-y", "-i", str(joined), "-i", str(audio)]
    if music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        filter_complex = (f"[1:a]atempo={tempo:.5f},apad,atrim=0:{TARGET_SECONDS},volume=1.0[voice];"
                          f"[2:a]volume=0.10,afade=t=in:st=0:d=2,afade=t=out:st=40:d=5[music];"
                          "[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]")
    else:
        filter_complex = (f"[1:a]atempo={tempo:.5f},apad,atrim=0:{TARGET_SECONDS},volume=1.0[aout]")
    cmd += ["-filter_complex", filter_complex, "-vf", vf_sub, "-map", "0:v:0", "-map", "[aout]",
            "-t", str(TARGET_SECONDS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-movflags", "+faststart", str(output)]
    run(cmd)
    # Hard validation: duration, streams, dimensions, and non-trivial size.
    probe = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", str(output)]).stdout)
    video = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)
    audio_stream = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
    duration = float(probe["format"]["duration"])
    if not video or not audio_stream or int(video["width"]) != WIDTH or int(video["height"]) != HEIGHT:
        raise RuntimeError("فشل فحص مسارات الفيديو أو أبعاد 1080x1920.")
    if abs(duration - TARGET_SECONDS) > 0.6 or output.stat().st_size < 100_000:
        raise RuntimeError(f"فشل فحص الفيديو النهائي: duration={duration:.2f}s, size={output.stat().st_size}.")


def safe_slug(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE).strip("_")
    return value[:55] or "kombo"


def mark_used(idea_id: str) -> None:
    used = load_used()
    if idea_id not in used:
        with USED_FILE.open("a", encoding="utf-8") as f:
            f.write(idea_id + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--one", action="store_true", help="Generate one unused idea.")
    parser.add_argument("--scheduled-guard", action="store_true", help="Run only at 08:00 Cairo time.")
    args = parser.parse_args()
    if args.scheduled_guard:
        now = datetime.now(ZoneInfo("Africa/Cairo"))
        if now.hour != 8:
            print(f"تخطي التشغيل: الوقت في القاهرة الآن {now:%H:%M} وليس 08:00.")
            return 0
    require_tools()
    OUTPUT_DIR.mkdir(exist_ok=True)
    WORK_DIR.mkdir(exist_ok=True)
    idea = choose_idea()
    print(f"الفكرة #{idea['id']}: {idea['idea']}")
    data = gemini_json(idea["idea"])
    (WORK_DIR / "script.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (WORK_DIR / "script.txt").write_text(data["script"], encoding="utf-8")
    images = []
    for i in range(1, 5):
        image_path = WORK_DIR / f"image_{i}.jpg"
        generate_image(data[f"image{i}"], image_path, i)
        images.append(image_path)
    audio = WORK_DIR / "audio.mp3"
    make_tts(data["script"], audio)
    captions = WORK_DIR / "captions.srt"
    create_captions(data["script"], data["srt_parts"], TARGET_SECONDS, captions)
    stamp = datetime.now(ZoneInfo("Africa/Cairo")).strftime("%Y%m%d_%H%M%S")
    output = OUTPUT_DIR / f"video_{int(idea['id']):02d}_{safe_slug(data['title'])}_{stamp}.mp4"
    build_video(images, audio, data["script"], captions, output)
    # A successful validated render is the only point at which the idea is consumed.
    mark_used(idea["id"])
    (OUTPUT_DIR / (output.stem + ".json")).write_text(json.dumps({
        "idea_id": idea["id"], "idea": idea["idea"], "title": data["title"],
        "caption": data["caption"], "script": data["script"], "duration_seconds": TARGET_SECONDS,
        "voice": "Fish Audio cloned voice", "image_provider": "Pollinations with local fallback"
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    gh_output = os.getenv("GITHUB_OUTPUT")
    if gh_output:
        meta_path = OUTPUT_DIR / (output.stem + ".json")
        with open(gh_output, "a", encoding="utf-8") as gh:
            gh.write(f"video=kombo-city-factory/output/{output.name}\n")
            gh.write(f"metadata=kombo-city-factory/output/{meta_path.name}\n")
    print(f"نجاح: {output} ({output.stat().st_size} bytes)")
    print("العنوان:", data["title"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)

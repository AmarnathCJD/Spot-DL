from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import re
import subprocess
import tempfile

import requests
from PIL import Image, ImageEnhance, ImageDraw, ImageFilter, ImageFont

LOGGER = logging.getLogger("spot-dl-server")


_FONT_CANDIDATES = [
    os.environ.get("SPOTDL_FONT_PATH"),
    os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts/Inter-SemiBold.ttf"),
    os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts/InterVariable.ttf"),
    os.path.expanduser("~/AppData/Local/Microsoft/Windows/Fonts/Inter.ttc"),
    "C:/Windows/Fonts/Inter-SemiBold.ttf",
    "C:/Windows/Fonts/InterVariable.ttf",
    "C:/Windows/Fonts/Inter.ttc",
    os.path.expanduser("~/.local/share/fonts/Inter-SemiBold.ttf"),
    os.path.expanduser("~/.local/share/fonts/InterVariable.ttf"),
    os.path.expanduser("~/.local/share/fonts/Inter.ttc"),
    "/usr/local/share/fonts/inter/Inter-SemiBold.ttf",
    "/usr/local/share/fonts/inter/InterVariable.ttf",
    "/usr/local/share/fonts/inter/Inter.ttc",
    "/usr/share/fonts/truetype/inter/Inter-SemiBold.ttf",
    "/usr/share/fonts/truetype/inter/InterVariable.ttf",
    "/usr/share/fonts/truetype/inter/Inter.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/bahnschrift.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_FONT_FAMILY_BY_BASENAME = {
    "inter-semibold.ttf": "Inter",
    "intervariable.ttf": "Inter",
    "inter.ttc": "Inter",
    "bahnschrift.ttf": "Bahnschrift",
    "segoeuib.ttf": "Segoe UI",
    "arialbd.ttf": "Arial",
    "DejaVuSans-Bold.ttf": "DejaVu Sans",
    "LiberationSans-Bold.ttf": "Liberation Sans",
    "Helvetica.ttc": "Helvetica",
    "Arial Bold.ttf": "Arial",
}


def _resolve_font():
    for p in _FONT_CANDIDATES:
        if p and os.path.isfile(p):
            family = _FONT_FAMILY_BY_BASENAME.get(os.path.basename(p), "Sans")
            return p, family, os.path.dirname(p)
    raise RuntimeError(
        "No usable TTF font found. Set SPOTDL_FONT_PATH or install dejavu/liberation fonts."
    )


FONT_PATH, FONT_FAMILY, FONT_DIR = _resolve_font()
LOGGER.info(f"using font: {FONT_FAMILY} from {FONT_PATH}")


LRC_RE = re.compile(r"^\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)$")


def _parse_lrc(lrc: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line in lrc.splitlines():
        m = LRC_RE.match(line.strip())
        if not m:
            continue
        mm, ss, ms, words = m.groups()
        t = int(mm) * 60_000 + int(ss) * 1000 + int(ms.ljust(3, "0"))
        out.append((t, words.strip()))
    return out


def _ass_time(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, cs = divmod(rem, 1000)
    return f"{h:d}:{m:02d}:{s:02d}.{cs // 10:02d}"


def _ass_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _font_for_size(font_size: int):
    return ImageFont.truetype(FONT_PATH, font_size)


def _text_width(font, text: str) -> float:
    try:
        return font.getlength(text)
    except AttributeError:
        return font.getbbox(text)[2]


def _split_long_word(word: str, font, max_width: int) -> list[str]:
    chunks: list[str] = []
    cur = ""
    for ch in word:
        candidate = cur + ch
        if cur and _text_width(font, candidate) > max_width:
            chunks.append(cur)
            cur = ch
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks or [word]


def _wrap_lines(text: str, font_size: int, max_width: int) -> list[str]:
    """Soft-wrap `text` by rendered pixel width, breaking long words when needed."""
    font = _font_for_size(font_size)
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        parts = (
            _split_long_word(word, font, max_width)
            if _text_width(font, word) > max_width
            else [word]
        )
        for part in parts:
            candidate = part if not cur else f"{cur} {part}"
            if not cur or _text_width(font, candidate) <= max_width:
                cur = candidate
            else:
                lines.append(cur)
                cur = part
    if cur:
        lines.append(cur)
    return lines or [""]


def _ffmpeg_filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:")


def _write_wrapped_text_file(path: str, text: str, font_size: int, max_width: int) -> list[str]:
    lines = _wrap_lines(text, font_size, max_width)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return lines


def _prepare_metadata_text_files(
    td: str,
    meta: dict,
    max_width: int = 500,
    title_size: int = 44,
    artist_size: int = 30,
    title_y: int = 98,
) -> dict:
    title_path = os.path.join(td, "title.txt")
    artist_path = os.path.join(td, "artist.txt")
    title_lines = _write_wrapped_text_file(title_path, meta["name"], title_size, max_width)
    artist_lines = _write_wrapped_text_file(artist_path, meta["artist"], artist_size, max_width)
    title_stride = int(title_size * 1.25)
    artist_stride = int(artist_size * 1.30)
    artist_y = title_y + len(title_lines) * title_stride + max(10, title_size // 4)
    safe_bottom = artist_y + len(artist_lines) * artist_stride + max(18, artist_size // 2)
    return {
        "title_arg": _ffmpeg_filter_path(title_path),
        "artist_arg": _ffmpeg_filter_path(artist_path),
        "title_y": title_y,
        "artist_y": artist_y,
        "safe_bottom": safe_bottom,
    }


def _ass_color(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _build_fireworks_ass(duration_ms: int, width: int, height: int) -> str:
    """Decorative spark/burst overlay layered behind the lyrics."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Spark,{FONT_FAMILY},24,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    colors = [
        (255, 220, 80),
        (255, 120, 90),
        (120, 210, 255),
        (180, 255, 150),
        (255, 150, 230),
    ]
    centers = [
        (1020, 120),
        (1160, 260),
        (850, 250),
        (1080, 470),
        (740, 95),
    ]
    events: list[str] = []
    burst_gap = 2400
    start = 400
    burst_index = 0
    while start < duration_ms:
        cx, cy = centers[burst_index % len(centers)]
        color = _ass_color(colors[burst_index % len(colors)])
        start_s = _ass_time(start)
        end_s = _ass_time(min(start + 1300, duration_ms))
        for ray in range(12):
            angle = (ray / 12) * 6.2831853
            dist = 56 + (ray % 4) * 14
            x2 = int(cx + dist * math.cos(angle))
            y2 = int(cy + dist * math.sin(angle))
            size = 18 + (ray % 3) * 4
            events.append(
                "Dialogue: 0,{},{},Spark,,0,0,0,,"
                "{{\\move({},{},{},{})\\fs{}\\c{}\\alpha&H20&\\fad(80,620)}}*".format(
                    start_s, end_s, cx, cy, x2, y2, size, color
                )
            )
        burst_index += 1
        start += burst_gap
    return header + "\n".join(events) + "\n"


def _build_lyric_ass(lrc_lines, duration_ms: int, width: int, height: int,
                     lyric_x: int, max_text_width: int, title_safe_bottom: int = 230) -> str:
    """Build prev/current/next stacked-lyric ASS subtitle file.

    Each line is pre-wrapped by pixel width so libass doesn't have to. The
    `title_safe_bottom` boundary keeps prev-line text from colliding with the
    title/artist drawtext above it.
    """
    prev_size = 38
    curr_size = 58
    next_size = 38
    lyric_gap = 36
    prev_line_h = int(prev_size * 1.22)
    curr_line_h = int(curr_size * 1.22)
    next_line_h = int(next_size * 1.22)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Prev,{FONT_FAMILY},{prev_size},&H80FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,1,0,1,0,3,4,0,0,0,1
Style: Curr,{FONT_FAMILY},{curr_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,100,100,1,0,1,0,4,4,0,0,0,1
Style: Next,{FONT_FAMILY},{next_size},&H80FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,1,0,1,0,3,4,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    y_curr = int(height * 0.58)
    events: list[str] = []
    n = len(lrc_lines)
    for i, (t, words) in enumerate(lrc_lines):
        end = lrc_lines[i + 1][0] if i + 1 < n else duration_ms
        start_s = _ass_time(t)
        end_s = _ass_time(end)
        curr_lines = _wrap_lines(words, curr_size, max_text_width)
        prev_lines = _wrap_lines(lrc_lines[i - 1][1], prev_size, max_text_width) if i > 0 else []
        next_lines = _wrap_lines(lrc_lines[i + 1][1], next_size, max_text_width) if i + 1 < n else []
        curr = "\\N".join(_ass_escape(l) for l in curr_lines)
        prev = "\\N".join(_ass_escape(l) for l in prev_lines)
        nxt = "\\N".join(_ass_escape(l) for l in next_lines)
        curr_h = len(curr_lines) * curr_line_h
        prev_h = len(prev_lines) * prev_line_h
        next_h = len(next_lines) * next_line_h
        y_prev = max(title_safe_bottom + prev_h // 2, y_curr - curr_h // 2 - lyric_gap - prev_h // 2)
        y_next = min(height - 56 - next_h // 2, y_curr + curr_h // 2 + lyric_gap + next_h // 2)
        if prev:
            events.append(f"Dialogue: 0,{start_s},{end_s},Prev,,0,0,0,,{{\\pos({lyric_x},{y_prev})}}{prev}")
        events.append(f"Dialogue: 0,{start_s},{end_s},Curr,,0,0,0,,{{\\pos({lyric_x},{y_curr})}}{curr}")
        if nxt:
            events.append(f"Dialogue: 0,{start_s},{end_s},Next,,0,0,0,,{{\\pos({lyric_x},{y_next})}}{nxt}")
    return header + "\n".join(events) + "\n"


def _dominant_color(img_bytes: bytes) -> tuple[int, int, int]:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB").resize((64, 64))
    pixels = list(img.getdata())
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    return max(r // 3, 8), max(g // 3, 8), max(b // 3, 8)


def _make_rounded_cover(img_bytes: bytes, size: int, radius: int, shadow: int = 24) -> bytes:
    """PNG of the cover scaled to `size`px with rounded corners and soft drop shadow.

    Output canvas is (size + 2*shadow) per side so the shadow halo has room.
    """
    src = Image.open(io.BytesIO(img_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    src.putalpha(mask)

    pad = shadow
    canvas = Image.new("RGBA", (size + 2 * pad, size + 2 * pad), (0, 0, 0, 0))
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow_layer).rounded_rectangle(
        (pad, pad + 6, pad + size, pad + size + 6),
        radius=radius, fill=(0, 0, 0, 160),
    )
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow * 0.6))
    canvas = Image.alpha_composite(canvas, shadow_layer)
    canvas.alpha_composite(src, (pad, pad))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _make_blurred_bg(img_bytes: bytes, w: int, h: int, blur: int = 60, darken: float = 0.45) -> bytes:
    """Cover-fit + Gaussian-blur + darken the album art into a WxH JPEG."""
    src = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    src_ratio = src.width / src.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    scaled = src.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    cropped = scaled.crop((left, top, left + w, top + h))

    blurred = cropped.filter(ImageFilter.GaussianBlur(blur))
    blurred = ImageEnhance.Brightness(blurred).enhance(darken)

    buf = io.BytesIO()
    blurred.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


async def build_video_stream(ogg_bytes: bytes, meta: dict):
    """Async generator yielding fragmented MP4 chunks as ffmpeg produces them.

    Layout: 1920x1080 frame with blurred album art bg, rounded cover top-left,
    title/artist + scrolling lyrics on the right, audio waveform across the
    bottom. Encoded as H.264 + AAC in fragmented MP4 so the response is
    playable while still being written.

    `meta` keys consumed: name, artist, cover, lyrics, bg_color.
    """
    W, H = 1920, 1080
    cover_bytes = await asyncio.to_thread(
        lambda: requests.get(meta["cover"]).content if meta.get("cover") else b""
    )

    if meta.get("bg_color"):
        r, g, b = meta["bg_color"]
    elif cover_bytes:
        r, g, b = _dominant_color(cover_bytes)
    else:
        r, g, b = (20, 20, 30)

    lrc = _parse_lrc(meta.get("lyrics") or "")
    if not lrc:
        lrc = [(0, meta["name"]), (3000, meta["artist"]), (6000, "(instrumental)")]

    td = tempfile.mkdtemp(prefix="vtrack_")
    try:
        audio_path = os.path.join(td, "audio.ogg")
        with open(audio_path, "wb") as f:
            f.write(ogg_bytes)

        dur_out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True,
        )
        duration_ms = int(float(dur_out.stdout.strip() or "180") * 1000)

        COVER_SIZE = 800
        COVER_RADIUS = 42
        COVER_SHADOW = 54
        COVER_X = 160
        TEXT_X = 1080
        TITLE_FONT = 64
        ARTIST_FONT = 44

        if cover_bytes:
            bg_jpg = _make_blurred_bg(cover_bytes, W, H, blur=90, darken=0.42)
            cover_png = _make_rounded_cover(cover_bytes, COVER_SIZE, COVER_RADIUS, shadow=COVER_SHADOW)
        else:
            bg_jpg = io.BytesIO()
            Image.new("RGB", (W, H), (r, g, b)).save(bg_jpg, "JPEG", quality=82)
            bg_jpg = bg_jpg.getvalue()
            cover_png = None

        bg_path = os.path.join(td, "bg.jpg")
        with open(bg_path, "wb") as f:
            f.write(bg_jpg)
        cover_path = os.path.join(td, "cover.png")
        if cover_png:
            with open(cover_path, "wb") as f:
                f.write(cover_png)

        ass_path = os.path.join(td, "lyrics.ass")
        text_pane_width = W - TEXT_X - 80
        metadata_text = _prepare_metadata_text_files(
            td, meta, max_width=text_pane_width,
            title_size=TITLE_FONT, artist_size=ARTIST_FONT, title_y=140,
        )
        fireworks_path = os.path.join(td, "fireworks.ass")
        with open(fireworks_path, "w", encoding="utf-8") as f:
            f.write(_build_fireworks_ass(duration_ms, W, H))
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(_build_lyric_ass(
                lrc, duration_ms, W, H, lyric_x=TEXT_X, max_text_width=text_pane_width,
                title_safe_bottom=metadata_text["safe_bottom"],
            ))

        ass_arg = _ffmpeg_filter_path(ass_path)
        fireworks_arg = _ffmpeg_filter_path(fireworks_path)
        font_arg = _ffmpeg_filter_path(FONT_PATH)
        fonts_dir_arg = _ffmpeg_filter_path(FONT_DIR)
        title_arg = metadata_text["title_arg"]
        artist_arg = metadata_text["artist_arg"]

        WAVE_H = 180
        WAVE_W = W - 320
        WAVE_X = (W - WAVE_W) // 2
        WAVE_Y = H - WAVE_H - 80
        wave_chain_tmpl = (
            f"[{{audio_idx}}:a]showwaves=s={WAVE_W}x{WAVE_H}:mode=cline:"
            f"colors=white|white:rate=30,format=rgba,"
            f"colorchannelmixer=aa=0.45[wave]"
        )

        inputs = ["-loop", "1", "-i", bg_path]
        audio_idx = 1
        if cover_png:
            inputs += ["-loop", "1", "-i", cover_path]
            audio_idx = 2
        inputs += ["-i", audio_path]

        wave_chain = wave_chain_tmpl.format(audio_idx=audio_idx)

        if cover_png:
            filter_complex = (
                f"[0:v]scale={W}:{H},setsar=1[bg];"
                f"[bg]subtitles='{fireworks_arg}':fontsdir='{fonts_dir_arg}'[bgfx];"
                f"[1:v]format=rgba[cv];"
                f"[bgfx][cv]overlay={COVER_X - COVER_SHADOW}:(H-{COVER_SIZE + 2*COVER_SHADOW})/2[bgc];"
                f"{wave_chain};"
                f"[bgc][wave]overlay={WAVE_X}:{WAVE_Y}[bgw];"
                f"[bgw]drawtext=fontfile='{font_arg}':textfile='{title_arg}':fontcolor=white:fontsize={TITLE_FONT}:x={TEXT_X}:y={metadata_text['title_y']}:line_spacing=6:shadowcolor=black@0.65:shadowx=0:shadowy=3,"
                f"drawtext=fontfile='{font_arg}':textfile='{artist_arg}':fontcolor=0xDDDDDD:fontsize={ARTIST_FONT}:x={TEXT_X}:y={metadata_text['artist_y']}:line_spacing=4:shadowcolor=black@0.65:shadowx=0:shadowy=3,"
                f"subtitles='{ass_arg}':fontsdir='{fonts_dir_arg}'[v]"
            )
        else:
            filter_complex = (
                f"[0:v]scale={W}:{H},setsar=1[bg];"
                f"[bg]subtitles='{fireworks_arg}':fontsdir='{fonts_dir_arg}'[bgfx];"
                f"{wave_chain};"
                f"[bgfx][wave]overlay={WAVE_X}:{WAVE_Y}[bgw];"
                f"[bgw]drawtext=fontfile='{font_arg}':textfile='{title_arg}':fontcolor=white:fontsize={TITLE_FONT}:x={TEXT_X}:y={metadata_text['title_y']}:line_spacing=6:shadowcolor=black@0.65:shadowx=0:shadowy=3,"
                f"drawtext=fontfile='{font_arg}':textfile='{artist_arg}':fontcolor=0xDDDDDD:fontsize={ARTIST_FONT}:x={TEXT_X}:y={metadata_text['artist_y']}:line_spacing=4:shadowcolor=black@0.65:shadowx=0:shadowy=3,"
                f"subtitles='{ass_arg}':fontsdir='{fonts_dir_arg}'[v]"
            )

        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", f"{audio_idx}:a",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof",
            "-frag_duration", "1000000",
            "-f", "mp4",
            "pipe:1",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            while True:
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
            await proc.wait()
            if proc.returncode != 0:
                err = (await proc.stderr.read()).decode(errors="ignore")[-400:]
                LOGGER.error(f"ffmpeg exit {proc.returncode}: {err}")
        finally:
            if proc.returncode is None:
                proc.kill()
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)

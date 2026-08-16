from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import requests
from mutagen.id3 import (
    APIC,
    ID3,
    ID3NoHeaderError,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TSRC,
    USLT,
)

__all__ = [
    "safe_component",
    "split_title",
    "build_filename",
    "id3_values",
    "metadata_sidecar_values",
    "encode_mp3",
    "fetch_cover",
    "write_tagged",
    "download_dir",
    "set_download_dir",
    "normalize_audio_format",
    "UnsupportedLosslessExport",
]

_UNSAFE = re.compile(r'[<>:"/\\|?*]')
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_SPACES = re.compile(r"\s+")
_TRAILING_GROUPS = re.compile(r"^(.*?)\s*((?:\([^()]*\)\s*)+)$")
_GROUP = re.compile(r"\(([^()]*)\)")
_DASH_SUFFIX = re.compile(r"^(.*\S)\s+-\s+(\S.*)$")

SEPARATOR = " - "
DOWNLOAD_DIR = Path("downloads")
_download_dir_override: Path | None = None
MAX_NAME_BYTES = 255
MIN_NAME_BYTES = 60
LOSSLESS_EXPORT_ERROR = (
    "Spotify Lossless export is not supported; this app writes MP3 files plus "
    "same-basename metadata JSON sidecars."
)
_MP3_FORMATS = frozenset({"", "mp3", "audio/mpeg", "mpeg"})
_LOSSLESS_FORMATS = frozenset({"lossless", "flac", "wav", "alac", "aiff", "aif"})


class UnsupportedLosslessExport(ValueError):
    pass


def safe_component(s: str) -> str:
    """Strip path-hostile characters and collapse whitespace in one name part."""
    return _SPACES.sub(" ", _UNSAFE.sub("_", _CONTROL.sub("", s))).strip()


def _blen(s: str) -> int:
    return len(s.encode("utf-8"))


def _clamp(s: str, limit: int) -> str:
    """Cut a string to at most `limit` UTF-8 bytes without splitting a character."""
    if limit <= 0:
        return ""
    encoded = s.encode("utf-8")
    if len(encoded) <= limit:
        return s
    return encoded[:limit].decode("utf-8", "ignore").rstrip()


def _clamp_qualifier(qual: str, limit: int) -> str:
    """Clamp a ` (…)` group, keeping its closing parenthesis."""
    if _blen(qual) <= limit:
        return qual
    trimmed = _clamp(qual, limit - 1)
    if not trimmed.strip(" ("):
        return ""
    return trimmed if trimmed.endswith(")") else trimmed + ")"


def _fit(artist: str, name: str, qual: str, budget: int) -> tuple[str, str, str]:
    """Trim the song name down to a floor, then the qualifier, then the artist.

    The song name is only cut below `MIN_NAME_BYTES` as a last resort, so a long
    feature list never swallows the title it belongs to.
    """
    floor = min(_blen(name), MIN_NAME_BYTES)
    budget -= _blen(SEPARATOR)

    def over() -> int:
        return _blen(artist) + _blen(name) + _blen(qual) - budget

    if over() > 0:
        name = _clamp(name, max(floor, _blen(name) - over()))
    if over() > 0:
        qual = _clamp_qualifier(qual, _blen(qual) - over())
    if over() > 0:
        artist = _clamp(artist, _blen(artist) - over())
    if over() > 0:
        name = _clamp(name, _blen(name) - over())
    return artist, name, qual


def split_title(name: str) -> tuple[str, list[str]]:
    """Split a Spotify title into its base and its qualifier groups.

    `Strobe (Michael Woods Remix)` and `Strobe - Michael Woods Remix` both
    yield `("Strobe", ["Michael Woods Remix"])`.
    """
    name = name.strip()
    m = _TRAILING_GROUPS.match(name)
    if m and m.group(1):
        return m.group(1).strip(), [g.strip() for g in _GROUP.findall(m.group(2)) if g.strip()]
    m = _DASH_SUFFIX.match(name)
    if m:
        return m.group(1).strip(), [m.group(2).strip()]
    return name, []


def build_filename(meta: dict) -> str:
    """`ARTIST - SONG NAME (additional artists or remix style) YEAR.mp3`.

    The qualifier comes from the title's own parentheses, else a ` - ` suffix,
    else the featured artists. It is dropped entirely when none of those exist,
    and so is the year when the album date is unknown. When the name would
    exceed the filesystem limit the qualifier is shortened before the song name
    loses more than `MIN_NAME_BYTES`; the year and the extension always survive.
    """
    artists = meta.get("artists") or ([meta["artist"]] if meta.get("artist") else [])
    base, groups = split_title(meta.get("name", ""))
    if not groups and len(artists) > 1:
        groups = ["feat. " + " & ".join(artists[1:])]

    artist = safe_component(artists[0]) if artists else "Unknown Artist"
    name = safe_component(base) or "Untitled"
    qual = "".join(f" ({safe_component(g)})" for g in groups if safe_component(g))
    year = safe_component(str(meta.get("year") or ""))
    suffix = f" {year}.mp3" if year else ".mp3"
    sidecar_suffix = f" {year}.json" if year else ".json"

    artist, name, qual = _fit(artist, name, qual, MAX_NAME_BYTES - max(_blen(suffix), _blen(sidecar_suffix)))
    return artist + SEPARATOR + name + qual + suffix


def normalize_audio_format(value: object) -> str:
    if value is None:
        return "mp3"
    if not isinstance(value, str):
        raise ValueError("format must be a string")
    fmt = value.strip().lower()
    if fmt in _MP3_FORMATS:
        return "mp3"
    if fmt in _LOSSLESS_FORMATS:
        raise UnsupportedLosslessExport(LOSSLESS_EXPORT_ERROR)
    raise ValueError(f"unsupported format: {value}")


def id3_values(meta: dict) -> dict[str, str]:
    """Map track metadata onto ID3v2 frame names, dropping empty frames."""
    artists = meta.get("artists") or ([meta["artist"]] if meta.get("artist") else [])
    values = {
        "TIT2": meta.get("name", ""),
        "TPE1": "; ".join(artists),
        "TALB": meta.get("album", ""),
        "TPE2": meta.get("album_artist") or (artists[0] if artists else ""),
        "TDRC": str(meta.get("year") or ""),
        "TRCK": str(meta.get("track_number") or ""),
        "TPOS": str(meta.get("disc_number") or ""),
        "TCON": meta.get("genre", ""),
        "TSRC": meta.get("isrc", ""),
        "TPUB": meta.get("label", ""),
    }
    return {k: v for k, v in values.items() if v and v != "0"}


_FRAMES = {
    "TIT2": TIT2, "TPE1": TPE1, "TALB": TALB, "TPE2": TPE2, "TDRC": TDRC,
    "TRCK": TRCK, "TPOS": TPOS, "TCON": TCON, "TSRC": TSRC, "TPUB": TPUB,
}


def _json_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        items = [_json_value(v) for v in value]
        items = [v for v in items if v is not None]
        return items or None
    if isinstance(value, dict):
        items = {str(k): _json_value(v) for k, v in value.items()}
        items = {k: v for k, v in items.items() if v is not None}
        return items or None
    return str(value)


def metadata_sidecar_values(meta: dict) -> dict:
    values = {str(k): _json_value(v) for k, v in meta.items()}
    return {k: v for k, v in values.items() if v is not None}


def _write_metadata_sidecar(path: Path, meta: dict) -> Path:
    sidecar = path.with_suffix(".json")
    sidecar.write_text(
        json.dumps(metadata_sidecar_values(meta), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return sidecar


def encode_mp3(ogg: bytes, bitrate: str = "320k") -> bytes:
    """Transcode decrypted Ogg/Vorbis bytes to CBR MP3 bytes with ffmpeg."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-vn", "-codec:a", "libmp3lame",
         "-b:a", bitrate, "-f", "mp3", "pipe:1"],
        input=ogg, capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg exit {proc.returncode}: {proc.stderr.decode(errors='ignore')[-300:]}")
    return proc.stdout


def fetch_cover(url: str) -> bytes:
    if not url:
        return b""
    resp = requests.get(url, timeout=15)
    if resp.status_code != 200:
        return b""
    return resp.content


def download_dir() -> Path:
    target = _download_dir_override or DOWNLOAD_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def set_download_dir(path: Path | str | None) -> None:
    global _download_dir_override
    if path is None:
        _download_dir_override = None
        return
    _download_dir_override = Path(path)



def write_tagged(mp3_bytes: bytes, meta: dict, cover: bytes, directory: Path | None = None) -> Path:
    """Write the MP3 under its schema filename with full ID3v2 tags + artwork.

    Re-downloading a track overwrites its previous file: the filename is derived
    from the track's own metadata, so a collision is the same song.
    """
    directory = directory or download_dir()
    path = directory / build_filename(meta)
    path.write_bytes(mp3_bytes)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    for frame, value in id3_values(meta).items():
        tags.add(_FRAMES[frame](encoding=3, text=value))
    lyrics = meta.get("lyrics") or ""
    if lyrics and lyrics != "You'd have to guess this one":
        tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    tags.update_to_v23()
    tags.save(path, v2_version=3)
    _write_metadata_sidecar(path, meta)
    return path

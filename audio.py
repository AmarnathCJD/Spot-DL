from __future__ import annotations

from Cryptodome.Cipher import AES
from Cryptodome.Util import Counter

__all__ = ["AES_IV", "decrypt_stream", "decrypt"]

AES_IV: bytes = bytes.fromhex("72e067fbddcbcf77ebe8bc643f630d93")

_OGG_S = b"OggS"
_OGG_START = b"\x00\x02"
_VORBIS_START = b"\x01\x1e\x01vorbis"
_CHANNELS = b"\x02"
_SAMPLE_RATE = b"\x44\xac\x00\x00"
_BIT_RATE = b"\x00\xe2\x04\x00"
_PACKET_SIZES = b"\xb8\x01"
_ZEROES_10 = b"\x00" * 10


def _fix_ogg_header(buf: bytearray) -> None:
    """Rewrite the scrambled first Ogg page header in-place.

    Spotify zeroes specific byte ranges in the first Ogg page before
    encryption. After AES-CTR decrypt the Vorbis payload is intact but the
    container header must be rewritten. Every Spotify 320kbps track is
    2-channel 44.1 kHz Vorbis, so the rebuilt fields are constants.
    `buf` must be at least 76 bytes (always true for a real track).
    """
    buf[0:4] = _OGG_S
    buf[4:6] = _OGG_START
    buf[6:16] = _ZEROES_10
    buf[14:18] = bytes(buf[72:76])
    buf[18:28] = _ZEROES_10

    buf[26:35] = _VORBIS_START
    buf[35:45] = _ZEROES_10
    buf[39:40] = _CHANNELS
    buf[40:44] = _SAMPLE_RATE
    buf[48:52] = _BIT_RATE
    buf[56:58] = _PACKET_SIZES

    buf[58:62] = _OGG_S
    buf[62:72] = _ZEROES_10


def decrypt_stream(encrypted: bytes, key: bytes) -> bytes:
    """Decode one Spotify-encrypted audio stream into playable Ogg bytes.

    :param encrypted: raw bytes from the Spotify CDN URL
    :param key: 16-byte AES key returned by `Session.audio_key().get_audio_key()`
    :returns: complete Ogg/Vorbis file as bytes — write directly to disk or
              pipe into ffmpeg
    :raises ValueError: if `key` is not 16 bytes
    """
    if len(key) != 16:
        raise ValueError(f"AES key must be 16 bytes, got {len(key)}")

    iv_int = int.from_bytes(AES_IV, "big")
    cipher = AES.new(
        key=key,
        mode=AES.MODE_CTR,
        counter=Counter.new(128, initial_value=iv_int),
    )
    buf = bytearray(cipher.decrypt(encrypted))
    _fix_ogg_header(buf)
    return bytes(buf)


decrypt = decrypt_stream

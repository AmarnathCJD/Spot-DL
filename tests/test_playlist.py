import pytest

import spotify

REF_CASES = [
    ("playlist-web-url-with-si",
     "https://open.spotify.com/playlist/7xeQp9BIVJjCariTYXdRK3?si=06c5cf5df07848bd",
     ("playlist", "7xeQp9BIVJjCariTYXdRK3")),
    ("track-web-url",
     "https://open.spotify.com/track/3KrXbna4rv7YXkZHagRtHK",
     ("track", "3KrXbna4rv7YXkZHagRtHK")),
    ("localised-track-url",
     "https://open.spotify.com/intl-de/track/3KrXbna4rv7YXkZHagRtHK",
     ("track", "3KrXbna4rv7YXkZHagRtHK")),
    ("playlist-uri",
     "spotify:playlist:7xeQp9BIVJjCariTYXdRK3",
     ("playlist", "7xeQp9BIVJjCariTYXdRK3")),
    ("track-uri",
     "spotify:track:3KrXbna4rv7YXkZHagRtHK",
     ("track", "3KrXbna4rv7YXkZHagRtHK")),
    ("bare-id-is-a-track",
     "3KrXbna4rv7YXkZHagRtHK",
     ("track", "3KrXbna4rv7YXkZHagRtHK")),
    ("free-text-is-not-a-ref", "daft punk around the world", None),
    ("album-url-is-not-supported",
     "https://open.spotify.com/album/2noRn2Aes5aoNVsU6iWThc", None),
    ("too-short-id", "3KrXbna4rv7YXkZHagRt", None),
]

PLAYLIST_IDS = [
    "3KrXbna4rv7YXkZHagRtHK",
    "1LY3GhF0zxIVgbYEQjCbUO",
    "2bf7wxuRxN2tkNoPH7z1an",
    "4PCUyejIMnQs6mYrR90QFp",
    "1u2SUX1QkFAlaPKg2nvMbT",
]

PREFIX_CASES = [
    ("three-from-the-top", 3, PLAYLIST_IDS[:3]),
    ("one", 1, PLAYLIST_IDS[:1]),
    ("exactly-all", 5, PLAYLIST_IDS),
    ("more-than-available", 9999, PLAYLIST_IDS),
    ("zero-selects-nothing", 0, []),
    ("negative-selects-nothing", -4, []),
]


@pytest.mark.parametrize(
    "text,expected", [pytest.param(t, e, id=i) for i, t, e in REF_CASES],
)
def test_parse_spotify_ref(text, expected):
    assert spotify.parse_spotify_ref(text) == expected


@pytest.mark.parametrize(
    "count,expected", [pytest.param(c, e, id=i) for i, c, e in PREFIX_CASES],
)
def test_select_prefix(count, expected):
    assert spotify.select_prefix(PLAYLIST_IDS, count) == expected


def test_select_prefix_does_not_reorder():
    shuffled = list(reversed(PLAYLIST_IDS))
    assert spotify.select_prefix(shuffled, 3) == shuffled[:3]

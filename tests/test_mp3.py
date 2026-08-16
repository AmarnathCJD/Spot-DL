import json

import pytest
from mutagen.id3 import ID3

import mp3

FILENAME_CASES = [
    (
        "feat-in-title",
        {"name": "Way 2 Sexy (feat. Future & Young Thug)", "artist": "Drake",
         "artists": ["Drake", "Future", "Young Thug"], "year": "2021"},
        "Drake - Way 2 Sexy (feat. Future & Young Thug) 2021.mp3",
    ),
    (
        "remix-dash-suffix",
        {"name": "Strobe - Michael Woods Remix", "artist": "deadmau5",
         "artists": ["deadmau5"], "year": "2010"},
        "deadmau5 - Strobe (Michael Woods Remix) 2010.mp3",
    ),
    (
        "no-qualifier-no-features",
        {"name": "Around the World", "artist": "Daft Punk",
         "artists": ["Daft Punk"], "year": "1997"},
        "Daft Punk - Around the World 1997.mp3",
    ),
    (
        "features-only-in-metadata",
        {"name": "Feel So Close", "artist": "Calvin Harris",
         "artists": ["Calvin Harris", "Example"], "year": "2011"},
        "Calvin Harris - Feel So Close (feat. Example) 2011.mp3",
    ),
    (
        "unknown-year",
        {"name": "Untagged Demo", "artist": "Some Artist",
         "artists": ["Some Artist"], "year": ""},
        "Some Artist - Untagged Demo.mp3",
    ),
    (
        "two-qualifier-groups",
        {"name": "Song (feat. X) (Extended Mix)", "artist": "A",
         "artists": ["A", "X"], "year": "2003"},
        "A - Song (feat. X) (Extended Mix) 2003.mp3",
    ),
    (
        "path-hostile-characters",
        {"name": 'Back?: In "Black"/Live', "artist": "AC/DC",
         "artists": ["AC/DC"], "year": "1980"},
        'AC_DC - Back__ In _Black__Live 1980.mp3',
    ),
    (
        "control-characters-dropped",
        {"name": "Song\x00null\nline", "artist": "A", "artists": ["A"], "year": "2000"},
        "A - Songnull line 2000.mp3",
    ),
    (
        "bidi-override-dropped",
        {"name": "Song\u202egpm.exe", "artist": "A", "artists": ["A"], "year": "2000"},
        "A - Songgpm.exe 2000.mp3",
    ),
]

LONG_META = {
    "name": "Symphony No. 9 in D Minor Op. 125 Choral " + "Allegro assai vivace " * 12,
    "artist": "Ludwig van Beethoven",
    "artists": ["Ludwig van Beethoven", "Berliner Philharmoniker"],
    "year": "1963",
}

OVERSIZE_CASES = [
    ("long-song-name", LONG_META),
    ("long-artist", {**LONG_META, "name": "Short", "artist": "A" * 300,
                     "artists": ["A" * 300, "Berliner Philharmoniker"]}),
    ("many-featured-artists", {**LONG_META, "name": "Short",
                               "artists": ["Lead"] + [f"Featured Artist {i}" for i in range(20)]}),
    ("long-qualifier", {**LONG_META, "name": f"Short ({'x' * 300})",
                        "artists": ["Lead"]}),
    ("multi-group-qualifier", {**LONG_META, "name": "Closer (feat. Halsey) (T-Mix)",
                               "artist": "A" * 220, "artists": ["A" * 220]}),
    ("long-multibyte-name", {**LONG_META, "name": "Sinfonía número nueve á é í ó ú " * 12}),
]

TAG_META = {
    "name": "Strobe - Michael Woods Remix",
    "artist": "deadmau5",
    "artists": ["deadmau5", "Michael Woods"],
    "album": "For Lack of a Better Name",
    "album_artist": "deadmau5",
    "year": "2010",
    "track_number": 7,
    "disc_number": 1,
    "isrc": "GBCEN0900123",
    "label": "mau5trap",
    "genre": "progressive house",
}


@pytest.mark.parametrize(
    "meta,expected",
    [pytest.param(m, e, id=i) for i, m, e in FILENAME_CASES],
)
def test_build_filename(meta, expected):
    assert mp3.build_filename(meta) == expected


def test_build_filename_without_qualifier_has_no_parentheses():
    assert "(" not in mp3.build_filename(FILENAME_CASES[2][1])


def test_build_filename_without_year_has_no_dangling_separator():
    name = mp3.build_filename(FILENAME_CASES[4][1])
    assert name.endswith(".mp3")
    assert " .mp3" not in name
    assert "0000" not in name


def test_build_filename_clamps_the_song_name_to_the_filesystem_limit():
    name = mp3.build_filename(LONG_META)
    assert len(name.encode("utf-8")) <= mp3.MAX_NAME_BYTES
    assert name.startswith("Ludwig van Beethoven - Symphony No. 9 in D Minor")
    assert name.endswith("(feat. Berliner Philharmoniker) 1963.mp3")


@pytest.mark.parametrize(
    "meta", [pytest.param(m, id=i) for i, m in OVERSIZE_CASES],
)
def test_build_filename_keeps_a_song_name_and_stays_well_formed(meta):
    name = mp3.build_filename(meta)
    assert len(name.encode("utf-8")) <= mp3.MAX_NAME_BYTES
    assert name.endswith(" 1963.mp3")
    assert name.encode("utf-8").decode("utf-8") == name
    assert "  " not in name
    assert name.count("(") == name.count(")")
    stem = name[: -len(" 1963.mp3")]
    assert stem.split(" - ", 1)[1].split(" (")[0].strip()


def test_write_tagged_overwrites_the_same_song(tmp_path):
    meta = {**LONG_META, "album": "Live", "track_number": 4, "disc_number": 1}
    first = mp3.write_tagged(b"\xff\xfb\x90\x00" + b"\x00" * 4000, meta, b"", tmp_path)
    second = mp3.write_tagged(b"\xff\xfb\x90\x00" + b"\x00" * 8000, meta, b"", tmp_path)
    assert first == second
    sidecar = first.with_suffix(".json")
    assert sorted(tmp_path.iterdir()) == sorted([first, sidecar])
    assert len(first.name.encode("utf-8")) <= mp3.MAX_NAME_BYTES
    assert len(sidecar.name.encode("utf-8")) <= mp3.MAX_NAME_BYTES
    assert first.name.endswith(" 1963.mp3")


def test_write_tagged_writes_metadata_json_sidecar(tmp_path):
    meta = {
        **TAG_META,
        "id": "3KrXbna4rv7YXkZHagRtHK",
        "tc": "3KrXbna4rv7YXkZHagRtHK",
        "duration": 654321,
        "cover": "https://i.scdn.co/image/abc",
        "lyrics": "hold on",
        "bg_color": (12, 34, 56),
        "release_date": {"year": 2010, "month": 9, "day": 3},
        "audio_formats": ["OGG_VORBIS_320", "FLAC_FLAC"],
        "empty_field": "",
        "empty_list": [],
    }

    path = mp3.write_tagged(b"\xff\xfb\x90\x00" + b"\x00" * 4000, meta, b"", tmp_path)
    sidecar = path.with_suffix(".json")

    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar.name == "deadmau5 - Strobe (Michael Woods Remix) 2010.json"
    assert data["id"] == "3KrXbna4rv7YXkZHagRtHK"
    assert data["artists"] == ["deadmau5", "Michael Woods"]
    assert data["release_date"] == {"year": 2010, "month": 9, "day": 3}
    assert data["audio_formats"] == ["OGG_VORBIS_320", "FLAC_FLAC"]
    assert data["bg_color"] == [12, 34, 56]
    assert "empty_field" not in data
    assert "empty_list" not in data


def test_write_tagged_keeps_id3v23_year_on_disk(tmp_path):
    path = mp3.write_tagged(b"\xff\xfb\x90\x00" + b"\x00" * 4000, TAG_META, b"", tmp_path)

    tags = ID3(path, translate=False)
    assert tags.version == (2, 3, 0)
    assert tags.get("TYER").text[0] == "2010"
    assert tags.get("TDRC") is None


def test_id3_values_maps_every_populated_frame():
    assert mp3.id3_values(TAG_META) == {
        "TIT2": "Strobe - Michael Woods Remix",
        "TPE1": "deadmau5; Michael Woods",
        "TALB": "For Lack of a Better Name",
        "TPE2": "deadmau5",
        "TDRC": "2010",
        "TRCK": "7",
        "TPOS": "1",
        "TCON": "progressive house",
        "TSRC": "GBCEN0900123",
        "TPUB": "mau5trap",
    }


def test_id3_values_drops_unknown_fields():
    values = mp3.id3_values({"name": "X", "artist": "Y", "artists": ["Y"],
                             "album": "", "year": "", "track_number": 0, "disc_number": 0})
    assert values == {"TIT2": "X", "TPE1": "Y", "TPE2": "Y"}

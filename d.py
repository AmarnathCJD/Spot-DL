import os
import binascii
from libspot.proto import StorageResolve_pb2 as StorageResolve

from libspot.core import Session
from libspot.metadata import TrackId

if os.path.isfile("credentials.json"):
    session = Session.Builder().stored_file().create()

def get_track(track_id: str, quality: str = "320"):
    track_id = TrackId.from_base62(track_id)
    song = session.api().get_metadata_4_track(track_id)
    key = session.audio_key().get_audio_key(song.gid, song.file[0].file_id, True)
    resp = session.api().send("GET", "/storage-resolve/files/audio/interactive/{}".format(binascii.hexlify(song.file[0].file_id).decode()), None, None)
    storage_resolve_response = StorageResolve.StorageResolveResponse()
    storage_resolve_response.ParseFromString(resp.content)
    print(storage_resolve_response)
    print(key)

get_track("0GQngE2rOYvlKwEQjTAsP8")
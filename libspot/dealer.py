from __future__ import annotations
from libspot.core import ApResolver
from libspot.metadata import AlbumId, ArtistId, EpisodeId, ShowId, TrackId
from libspot.proto import Connect_pb2 as Connect, Metadata_pb2 as Metadata
from libspot.structure import Closeable
import logging
import requests
import typing

if typing.TYPE_CHECKING:
    from libspot.core import Session

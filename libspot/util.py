from Cryptodome import Random
import binascii
import math

from librespot import util
from librespot.crypto import Packet
from librespot.structure import Closeable, PacketsReceiver
from libspot.proto.Keyexchange_pb2 import BuildInfo, Platform, Product, ProductFlags
import platform
import io
import logging
import math
import queue
import struct
import threading


def bytes_to_hex(buffer: bytes) -> str:
    return binascii.hexlify(buffer).decode()


def hex_to_bytes(s: str) -> bytes:
    return binascii.unhexlify(s)


def int_to_bytes(i: int):
    width = i.bit_length()
    width += 8 - ((width % 8) or 8)
    fmt = "%%0%dx" % (width // 4)
    return b"\x00" if i == 0 else binascii.unhexlify(fmt % i)


def random_hex_string(length: int):
    buffer = Random.get_random_bytes(int(length / 2))
    return bytes_to_hex(buffer)


class Base62:
    standard_base = 256
    target_base = 62
    alphabet: bytes
    lookup: bytearray

    def __init__(self, alphabet: bytes):
        self.alphabet = alphabet
        self.create_lookup_table()

    @staticmethod
    def create_instance_with_inverted_character_set():
        return Base62(Base62.CharacterSets.inverted)

    def encode(self, message: bytes, length: int = -1):
        indices = self.convert(message, self.standard_base, self.target_base, length)
        return self.translate(indices, self.alphabet)

    def decode(self, encoded: bytes, length: int = -1):
        prepared = self.translate(encoded, self.lookup)
        return self.convert(prepared, self.target_base, self.standard_base, length)

    def translate(self, indices: bytes, dictionary: bytes):
        translation = bytearray(len(indices))
        for i in range(len(indices)):
            translation[i] = dictionary[int.from_bytes(bytes([indices[i]]), "big")]
        return translation

    def convert(self, message: bytes, source_base: int, target_base: int, length: int):
        estimated_length = (
            self.estimate_output_length(len(message), source_base, target_base)
            if length == -1
            else length
        )
        out = b""
        source = message
        while len(source) > 0:
            quotient = b""
            remainder = 0
            for b in source:
                accumulator = int(b & 0xFF) + remainder * source_base
                digit = int((accumulator - (accumulator % target_base)) / target_base)
                remainder = int(accumulator % target_base)
                if len(quotient) > 0 or digit > 0:
                    quotient += bytes([digit])
            out += bytes([remainder])
            source = quotient
        if len(out) < estimated_length:
            size = len(out)
            for _ in range(estimated_length - size):
                out += bytes([0])
            return self.reverse(out)
        if len(out) > estimated_length:
            return self.reverse(out[:estimated_length])
        return self.reverse(out)

    def estimate_output_length(
        self, input_length: int, source_base: int, target_base: int
    ):
        return int(
            math.ceil((math.log(source_base) / math.log(target_base)) * input_length)
        )

    def reverse(self, arr: bytes):
        length = len(arr)
        reversed_arr = bytearray(length)
        for i in range(length):
            reversed_arr[length - i - 1] = arr[i]
        return bytes(reversed_arr)

    def create_lookup_table(self):
        self.lookup = bytearray(256)
        for i in range(len(self.alphabet)):
            self.lookup[self.alphabet[i]] = i & 0xFF

    class CharacterSets:
        gmp = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        inverted = b"0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class AudioKeyManager(PacketsReceiver, Closeable):
    audio_key_request_timeout = 20
    logger = logging.getLogger("AudioKeyManager")
    __callbacks = {}
    __seq_holder = 0
    __seq_holder_lock = threading.Condition()
    __session = None
    __zero_short = b"\x00\x00"

    def __init__(self, session):
        self.__session = session

    def dispatch(self, packet: Packet) -> None:
        payload = io.BytesIO(packet.payload)
        seq = struct.unpack(">i", payload.read(4))[0]
        callback = self.__callbacks.get(seq)
        if callback is None:
            self.logger.warning("Couldn't find callback for seq: {}".format(seq))
            return
        if packet.is_cmd(Packet.Type.aes_key):
            key = payload.read(16)
            callback.key(key)
        elif packet.is_cmd(Packet.Type.aes_key_error):
            code = struct.unpack(">H", payload.read(2))[0]
            callback.error(code)
        else:
            self.logger.warning(
                "Couldn't handle packet, cmd: {}, length: {}".format(
                    packet.cmd, len(packet.payload)
                )
            )

    def get_audio_key(self, gid: bytes, file_id: bytes, retry: bool = True) -> bytes:
        seq: int
        with self.__seq_holder_lock:
            seq = self.__seq_holder
            self.__seq_holder += 1
        out = io.BytesIO()
        out.write(file_id)
        out.write(gid)
        out.write(struct.pack(">i", seq))
        out.write(self.__zero_short)
        out.seek(0)
        self.__session.send(Packet.Type.request_key, out.read())
        callback = AudioKeyManager.SyncCallback(self)
        self.__callbacks[seq] = callback
        key = callback.wait_response()
        if key is None:
            if retry:
                return self.get_audio_key(gid, file_id, False)
            raise RuntimeError(
                "Failed fetching audio key! gid: {}, fileId: {}".format(
                    util.bytes_to_hex(gid), util.bytes_to_hex(file_id)
                )
            )
        return key

    class Callback:

        def key(self, key: bytes) -> None:
            raise NotImplementedError

        def error(self, code: int) -> None:
            raise NotImplementedError

    class SyncCallback(Callback):
        __audio_key_manager = None
        __reference = queue.Queue()
        __reference_lock = threading.Condition()

        def __init__(self, audio_key_manager):
            self.__audio_key_manager = audio_key_manager

        def key(self, key: bytes) -> None:
            with self.__reference_lock:
                self.__reference.put(key)
                self.__reference_lock.notify_all()

        def error(self, code: int) -> None:
            self.__audio_key_manager.logger.fatal(
                "Audio key error, code: {}".format(code)
            )
            with self.__reference_lock:
                self.__reference.put(None)
                self.__reference_lock.notify_all()

        def wait_response(self) -> bytes:
            with self.__reference_lock:
                self.__reference_lock.wait(AudioKeyManager.audio_key_request_timeout)
                return self.__reference.get(block=False)


class Version:
    version_name = "0.0.9"

    @staticmethod
    def platform():
        if platform.system() == "Windows":
            return Platform.PLATFORM_WIN32_X86
        if platform.system() == "Darwin":
            return Platform.PLATFORM_OSX_X86
        return Platform.PLATFORM_LINUX_X86

    @staticmethod
    def version_string():
        return "librespot-python " + Version.version_name

    @staticmethod
    def system_info_string():
        return (
            Version.version_string()
            + "; Python "
            + platform.python_version()
            + "; "
            + platform.system()
        )

    @staticmethod
    def standard_build_info():
        return BuildInfo(
            product=Product.PRODUCT_CLIENT,
            product_flags=[ProductFlags.PRODUCT_FLAG_NONE],
            platform=Version.platform(),
            version=117300517,
        )

import time
from Crypto.Cipher import AES
from Crypto.Util import Counter

hex_key = input("Enter the decryption key: ")
file_path = input("CDN URL: ")

def decrypt_audio_file(file_path: str, hex_key: str) -> bytes:
    key = bytes.fromhex(hex_key)
    
    with open(file_path, 'rb') as f:
        buffer = f.read()
    
    audio_aes_iv = bytes.fromhex("72e067fbddcbcf77ebe8bc643f630d93")
    iv_int = int.from_bytes(audio_aes_iv, "big")
    cipher = AES.new(
        key=key,
        mode=AES.MODE_CTR,
        counter=Counter.new(128, initial_value=iv_int)
    )

    start_time = time.time_ns()
    decrypted_buffer = cipher.decrypt(buffer)

    decrypt_time = (time.time_ns() - start_time) / 1_000_000
    print(f"Decryption time: {decrypt_time:.2f} ms")

    return decrypted_buffer

import requests
with requests.get(file_path) as r:
    with open("encrypted.ogg", "wb") as f:
        f.write(r.content)

file_path = "encrypted.ogg"
decrypted_data = decrypt_audio_file(file_path, hex_key)

with open("decrypted.ogg", "wb") as out_file:
    out_file.write(decrypted_data)

OggS = b"OggS"
OggStart = b"\x00\x02"
Zeroes = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
VorbisStart = b"\x01\x1E\x01vorbis"
Channels = b"\x02"
SampleRate = b"\x44\xAC\x00\x00"
BitRate = b"\x00\xE2\x04\x00"
PacketSizes = b"\xB8\x01"

def rebuild_ogg(filename):
    with open(filename, "r+b") as ogg_file:
            ogg_file.write(OggS)
            ogg_file.seek(4)
            ogg_file.write(OggStart)
            ogg_file.seek(6)
            ogg_file.write(Zeroes)
            
            ogg_file.seek(72)
            buffer = ogg_file.read(4)
            ogg_file.seek(14)
            ogg_file.write(buffer)
            ogg_file.seek(18)
            ogg_file.write(Zeroes)
            ogg_file.seek(26)
            ogg_file.write(VorbisStart)

            ogg_file.seek(35)
            ogg_file.write(Zeroes)
            ogg_file.seek(39)
            ogg_file.write(Channels)
            ogg_file.seek(40)
            ogg_file.write(SampleRate)
            ogg_file.seek(48)
            ogg_file.write(BitRate)
    
            ogg_file.seek(56)
            ogg_file.write(PacketSizes)
            ogg_file.seek(58)
            ogg_file.write(OggS)
            ogg_file.seek(62)
            ogg_file.write(Zeroes)

rebuild_ogg("decrypted.ogg")

from decrypt import decrypt_audio_file, rebuild_ogg
import subprocess
import os

def process_audio(enc_filename, dec_filename, key_hex, audio_format):
    decrypted_data = decrypt_audio_file(enc_filename, key_hex)
    with open(dec_filename, "wb") as out_file:
        out_file.write(decrypted_data)
    print(f"Decrypted and saved to {dec_filename}")
    rebuild_ogg(dec_filename)
    print(f"Rebuilt OGG headers for {dec_filename}")
    os.remove(enc_filename)
    print(f"Deleted encrypted file {enc_filename}")
    if audio_format == "mp3":
        mp3_filename = dec_filename.replace('.ogg', '.mp3')
        cmd = [
            "ffmpeg", "-y", "-i", dec_filename,
            "-codec:a", "libmp3lame", "-q:a", "2", mp3_filename
        ]
        try:
            subprocess.run(cmd, check=True)
            print(f"Converted to MP3: {mp3_filename}")
            os.remove(dec_filename)
            print(f"Deleted original ogg file {dec_filename}")
        except Exception as e:
            print(f"Error converting to mp3: {e}")

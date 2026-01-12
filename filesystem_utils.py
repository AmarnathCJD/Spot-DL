import os
import re
import shutil

def move_artist_folder(artist, config):
    safe_artist = re.sub(r'[^a-zA-Z0-9 _\-]', '', artist)
    src_dir = f"./tmp/{safe_artist}"
    print("Source directory:", src_dir)
    print("Artist name:", artist)
    print("Artist safe name:", safe_artist)
    dst_dir = os.path.join(config.get('library_path'), safe_artist)
    if os.path.exists(src_dir):
        if not os.path.exists(config.get('library_path')):
            os.makedirs(config.get('library_path'), exist_ok=True)
        shutil.move(src_dir, dst_dir)
        print(f"Moved {src_dir} to {dst_dir}")

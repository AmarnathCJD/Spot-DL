from mutagen.id3 import ID3, SYLT, Encoding

from mutagen.id3 import ID3
audio = ID3('a.mp3')

for tag, value in audio.items():
    with open('a.txt', 'w') as f:
        f.write(f"{tag}: {value}\n")
        f.close()

exit(0)


def lrc_to_set(lrc_path):
    with open(lrc_path, "r") as f:
        lrc = f.read()
    lrc = lrc.split("\n")
    lrc = [line for line in lrc if line]
    lrc = [line.split("]") for line in lrc]
    lrc = [(line[1], time_to_millisecond(line[0][1:])) for line in lrc]
    return lrc

def time_to_millisecond(time):
    minute = int(time[:2])
    second = int(time[3:5])
    millisecond = int(time[6:])
    return (minute * 60 + second) * 1000 + millisecond
lyrics_path = "0mJTAdmY8olbGQjopDYff3.lrc"  # Path to your LRC or text file
sync_lrc = lrc_to_set(lyrics_path)

tag = ID3("a.mp3")
tag.setall("SYLT", [SYLT(encoding=Encoding.UTF8, lang='eng', format=2, type=1, text=sync_lrc)])
tag.save(v2_version=3)
print("Lyrics synced successfully!")
# Usage
mp3_path = "a.mp3"  # Path to your MP3 file



print(sync_lrc)
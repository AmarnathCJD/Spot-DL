from libspot.zeroconf import ZeroconfServer
import time
import logging
import pathlib

zs = ZeroconfServer.Builder().create()
logging.warning("Transfer playback from desktop client to nigga via Spotify Connect in order to store session")

while True:
    time.sleep(1)
    if zs._ZeroconfServer__session:
        logging.warning(f"Grabbed {zs._ZeroconfServer__session} for {zs._ZeroconfServer__session.username()}")
        
        if pathlib.Path("credentials.json").exists():
            logging.warning("Session stored in credentials.json. Now you can Ctrl+C")
            break

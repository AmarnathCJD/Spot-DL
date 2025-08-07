# Spotify Connect-Based Implementation

A minimal implementation that enables search and download of songs from spotify (320Kbps).
**Note:** A Spotify **Premium** account is required.

---

## Features

* Integrates with Spotify Connect to control playback from local devices
* Supports Spotify Desktop Clients on Windows and Linux
* Simple authentication flow with persistent credential storage

---

## How to Obtain `credentials.json`

1. Run the `auth.py` script:

   ```bash
   python auth.py
   ```

2. Open the **Spotify Desktop App** on your Windows or Linux system.

3. In Spotify, open **Spotify Connect** and select the device named `spotify-connect-local`.

4. Once authenticated, a file named `credentials.json` will be created in the working directory.

---

## Disclaimer

> This tool is provided **strictly for educational and personal use only**. It is not affiliated with, endorsed by, or supported by Spotify AB or any of its partners.

By using this tool, you agree to the following:

1. **Legal Compliance**
   You will not use this tool to engage in any unlawful activity, including unauthorized access, reproduction, or distribution of copyrighted content.

2. **User Responsibility**
   The authors of this tool accept no responsibility for misuse, legal issues, or damages resulting from its use. All usage is at your own risk.

3. **No Affiliation**
   This is an independent tool and is in no way associated with Spotify or its services.

> Use this tool responsibly and at your own discretion.

## License
This project is released under the MIT License. See [LICENSE](LICENSE) for more information.

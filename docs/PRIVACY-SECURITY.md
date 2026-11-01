# Privacy and security

**What leaves the Pi:** nothing until the wake phrase is heard (Vosk recognises it offline). During a
conversation your microphone audio and Kevin's answers go to Google's Gemini Live API under **your** API key. On
Google's free tier, Google may use what you send to improve its products; on a paid tier it does not. Read
Google's current [Gemini API terms](https://ai.google.dev/gemini-api/terms) and check availability and limits
in your country. Weather lookups go to Open-Meteo (your town only). Updates come from this repository. YouTube
searches go to YouTube (through yt-dlp, no account); the TV guide asks the BBC's public schedule service.

**What is kept:** settings, facts you asked Kevin to remember (`/var/lib/bob-assistant/notes.json`), skills, and
logs of which tools ran. Conversations are not recorded.

**Secrets:** the Gemini key and the settings-page password hash are in `/etc/bob/secrets.json`, readable only by
the `bob-assistant` user. The setup app's first-boot files on the SD card (which hold the passwords, the key and
the Wi-Fi password) are wiped by the installer once it has used them.

**Isolation:** Kevin runs as `bob-assistant`, skills as `bob-skill` (no access to Kevin's files or key), the updater
as root in its own folder that only root can write. The settings page may only restart Kevin and start an update check (one
sudoers line). Installing or deleting a skill needs your confirmed yes. The Pi user created by the setup app can
use `sudo` without a password (as Raspberry Pi Imager's users can); change that with `sudo visudo` if you prefer.

**The settings page** is plain HTTP on your home network. It has no password unless you set one (in the setup
app or on the page itself; PBKDF2, at most 10 wrong passwords per 10 minutes): anyone on your Wi-Fi can open it, so set
one if you share your network. It only answers to the Pi's own name and addresses, and refuses requests from other
web sites. Do not expose port 8080 to the internet; for remote access use a VPN such as Tailscale (open the Pi by its
Tailscale IP address: the page only answers to the Pi's own names and addresses).

**Report a problem:** open a GitHub issue, or for anything sensitive use GitHub's private vulnerability reporting.

## Help run KindleHub
Off by default. When switched on, the Pi connects out to kindlehub.pro and plays chess moves, nothing else, as its
own user with no access to Kevin's files or key. Details: [HELP-RUN-KINDLEHUB.md](HELP-RUN-KINDLEHUB.md).

## Chess camera
Off by default (`chess_camera` empty). When you set it to a camera, Kevin opens it only while reading the board
(calibrate, read a move, look, train) and closes it straight after. Everything is worked out on the Pi; no picture
is sent anywhere or saved. What is kept in `/var/lib/bob-assistant/`: the board's four corners
(`chess_board_calib.json`), a small 256x256 flattened copy of the board from the last move (`chess_board_ref.npy`),
and, if you train it, a few numbers per square (`chess_train.npz`). "Forget the chess training" deletes the last two.
Details: [CHESS.md](CHESS.md).

## Gmail
Off by default. It only works with a Google OAuth client **you** create in your own Google Cloud project; this
repository contains no Google credentials. The only permission asked for is `gmail.readonly`: Kevin can list
senders and subjects, never send, delete or change anything. Your client id/secret and refresh token are stored in
`/etc/bob/secrets.json` (0600). Senders and subjects Kevin reads go to Gemini as part of the conversation, like
anything else he says. Disconnect with `python -m bob.gmail forget` and remove access in your Google account.
Details: [GMAIL.md](GMAIL.md).

## Health checks and self-healing
`bob-assistant-health.timer` runs as root every 5 minutes: it checks Kevin's services, temperature, disk and memory,
restarts a failed or stopped Kevin service (only the units in the `health_units` setting, at most once per 30
minutes each; turn off with `self_heal: false`), and notes new Python crashes from those services' logs in
`/var/lib/bob-assistant/bugs.jsonl` (the error and file/line only). Lines that could hold what you said are dropped
before anything reads them. Nothing is sent anywhere.

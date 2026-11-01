# Chess

## Play by voice

Kevin plays chess against you with Stockfish, on the Pi itself (nothing leaves it). The installer puts Stockfish
and python-chess in.

- "Let's play chess" (you are white) · "Let's play chess, I'm black, at 1500"
- Say moves as squares: "e2 to e4", "g1 f3", "e7 e8 queen". Kevin says his reply in standard notation (Nf6, O-O).
- "Where are the pieces?" · "Give me a hint" · "Take that back" · "Play stronger" (400-3190 Elo)

The game is saved in `/var/lib/bob-assistant/chess.json`, so it survives a restart.

## The chess camera (optional, off by default)

A webcam above a real board lets Kevin read your moves: make your move, say "your turn", and he plays his reply
(move his piece for him on the board).

1. Install OpenCV: `sudo apt install python3-opencv` (or `pip install opencv-python-headless numpy` in
   `/opt/bob-assistant/venv`).
2. Fix a USB webcam looking down at the board (straight above is best; an angle works). Find its device with
   `v4l2-ctl --list-devices` (or try `/dev/video0`).
3. Set `"chess_camera": "/dev/video0"` in `/etc/bob/config.json` and restart Kevin
   (`sudo systemctl restart bob-assistant`). Kevin's user needs to be in the `video` group:
   `sudo usermod -aG video bob-assistant`.
4. "Calibrate the chess board". With an empty board Kevin finds the corners by himself. With pieces on, give the
   corners as percentages of the picture (a1, h1, h8, a8), e.g. "corners 20,80 80,80 80,20 20,20". If white ends
   up on the wrong side, calibrate again with "rotate 1" (2, 3).
5. Start a game with the pieces in place, then play. After each of your moves say "your turn" / "my move is done".

Reading a move compares the board with the last look; only the legal moves of the game are considered, so a shadow
cannot invent a move. If Kevin is unsure he asks you to say the move.

**Training (optional):** with the board matching the game, say "train the chess camera" now and then (about five
different positions). After that Kevin recognises empty / white / black squares by himself, which copes better
with changing light, and "look at the board" tells you any squares that do not match the game.

Privacy: the camera is opened only while reading the board; no picture is sent anywhere or saved (see
[PRIVACY-SECURITY.md](PRIVACY-SECURITY.md)). Turn it off by setting `chess_camera` back to `""`.

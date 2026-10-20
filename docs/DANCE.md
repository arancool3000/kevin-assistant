# Dance mode

Say **"Hey Kevin, dance"** (or "stop dancing") and put music on. Kevin listens through the microphone he already
uses, finds the beat, and dances.

## On a screen

Open **`http://<pi-name>.local:8080/dance`** on a TV, a tablet, or the Pi's own HDMI output. Kevin's face bounces on
every beat, squashes when he lands, sways, travels round the floor a bar at a time, blinks on the snare and glances
after the hi-hats. The colours move on with every bar.

For a Pi with a screen attached, open it full screen when the desktop starts:

```bash
chromium --kiosk http://localhost:8080/dance
```

(If you set a password for the settings page, sign in once in that browser first.)

## Add your own

The screen is just one thing that follows the beat. Everything else is up to you: LEDs, a servo, a robot, a lamp,
another computer. Kevin publishes the beat about twenty times a second:

- **over HTTP**: `GET http://<pi-name>.local:8080/api/dance`
- **on the Pi**: the file `/var/lib/bob-assistant/dance.json` (handy for a skill)

```json
{"live": true, "n": 128, "bpm": 122, "glow": 0.8, "hue": 210, "kick": 1.0, "snare": 0.0, "hat": 0.4,
 "snares": 41, "hats": 260, "loud": 0.6, "at": 1760000000.0}
```

| field | what it means | good for |
|---|---|---|
| `live` | dance mode is on and music is being heard | start / stop |
| `n` | beats so far: it goes up by one on each beat | the moment to move a motor or step a pattern |
| `bpm` | tempo (fast songs count at half speed, the speed bodies dance at) | how long a move should take |
| `kick`, `snare`, `hat` | 0 to 1: jumps to 1 on that drum, then fades | brightness of three lights |
| `snares`, `hats` | counters that go up on each snare / hi-hat | a flash or a little twitch |
| `glow` | how hard the last beat hit | size of the move |
| `loud` | loudness against the song's recent peak | calm verses vs big choruses |
| `hue` | a colour (0 to 360) that moves on every bar | anything that lights up |

The page in `bob/dancepage.py` is a complete example: about thirty lines of JavaScript that poll `/api/dance` and
move things when `n`, `snares` or `hats` change.

### Example: an ESP32 / Arduino with Wi-Fi

Poll the JSON every 50 ms, and when `n` changes, move a servo; set an LED's brightness to `kick * 255`.

### Example: a skill on the Pi

Ask Kevin to make one: *"Hey Kevin, make a skill that flashes the LED on pin 17 on every beat in dance mode, reading
/var/lib/bob-assistant/dance.json."*

## Notes

- Nothing is recorded: the same 100 ms chunks the wake word listener reads are turned into numbers and dropped.
- The beat comes from the microphone, so it works with any music in the room: Kevin's own radio, a phone, a record.
- Quiet music or a mic far from the speaker means fewer beats. Move the mic closer, or turn the music up.

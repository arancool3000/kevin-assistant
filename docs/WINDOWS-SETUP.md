# Setting up with Kevin-Setup.exe (Windows)

## You need
- The microSD card in your PC (a USB card reader is fine). Everything on it will be erased.
- **Kevin-Setup.exe** from the [latest release](https://github.com/arancool3000/kevin-assistant/releases/latest)
  (a `.sha256` checksum is next to it)
- Your Wi-Fi name and password (an ordinary home network: not hidden, not "enterprise" or a hotel login page),
  and a free [Gemini API key](https://aistudio.google.com/apikey)
- About 600 MB of internet download (the Raspberry Pi OS image; nothing is kept on your PC afterwards)

## Steps
1. Open **Kevin-Setup.exe**. Windows SmartScreen may warn about an unknown app (it isn't code-signed yet):
   *More info → Run anyway*. Then say **Yes** when Windows asks to let it make changes: writing a card needs
   administrator rights.
2. Follow the steps down the left side. *Next* checks each step before moving on, and your answers (never your
   passwords or key) are remembered if you close the app and come back.
   - **Welcome:** choose *A new Pi* (write the card for me), *I already wrote the card with Raspberry Pi Imager*
     (with no customisation: only the settings are added), or *My Pi is already running*.
   - **Wi-Fi:** filled in from the network this PC is on. *Use this PC's saved password* fills the password too;
     the country comes from Windows.
   - **Kevin:** paste your Gemini key (*Get a free key* opens the page) and press **Test key**. Choose his name,
     wake phrase and voice, and your town (*Check* finds it on the map).
   - **Logins:** the Pi's name on your network (`kevin`), a user name and password for the Pi, and a password for
     Kevin's settings page. *Make one* creates a strong password; write them down.
   - **Extras:** links for connecting your Claude or ChatGPT account and for the bedside screen, and the optional
     *Help run KindleHub*.
   - **Set up:** choose the card (press *Refresh* after putting it in), press **Write the card**, and type
     **ERASE**. Each stage is ticked off: download, write, check, settings, eject.
3. The app downloads **Raspberry Pi OS Lite (64-bit)** straight from raspberrypi.com, writes it, reads the whole
   card back to check it, adds your settings, and ejects the card. Only SD cards and USB card readers from
   4 GB to 512 GB are offered; the disk Windows runs from never is. If Windows pops up "you need to format the
   disk", click **Cancel**, never format it.
4. Put the card in the Pi, connect the USB speakerphone, and power on. **Done** waits for Kevin to appear on
   your network (10–20 minutes the first time: he joins your Wi-Fi, sets the clock and installs himself, then
   plays a **rising three-note chime**), and then offers **Open Kevin's settings** and the **Phone remote**.
5. Say **"Hey Kevin"**. If `.local` names don't work on your phone, use the Pi's IP address from your router's
   device list: `http://192.168.x.y:8080`.

## Installing on a Pi that's already running
On *Welcome* choose **My Pi is already running**. On *Logins* enter the user name and password the Pi **already**
has and its address (`kevin.local` or its IP). The first time, the app shows the Pi's key fingerprint and asks
you to confirm. *Show details* on the *Set up* step shows the installer's progress line by line.

## Sounds Kevin makes
| Sound | Meaning |
|---|---|
| Rising three notes | Ready (after starting up or installing) |
| Two quick notes | Listening — talk now |
| Low falling two notes | That didn't work (no internet, or a key problem) |
| Three high notes, three times | A timer finished |

Kevin can't be interrupted while he is speaking (the mic is muted so he never hears himself): let him finish.

## If something goes wrong
| Problem | Fix |
|---|---|
| No chime after 25 minutes, no settings page | Probably Wi-Fi: check the name/password (capitals matter) and country. Run Kevin Setup again and write the card again. |
| Settings page opens but Kevin is silent | No sound device at install time. Plug in the speakerphone and run the installer again (see *Sound* in HARDWARE.md). |
| See whether it is still installing | SSH in (`ssh pi@kevin.local` in PowerShell, with your user name) and run `tail -f /var/log/bob-install.log`. Also `/var/log/cloud-init-output.log`. |
| `kevin.local` doesn't open | Use the Pi's IP address from your router: `http://192.168.x.y:8080`. |
| He doesn't hear you | Settings page → Wake sensitivity up a little; speak towards the speakerphone. |
| He hears you but plays the low tone | Check the Gemini key on the settings page. |
| "Run as administrator" message | Close the app, right-click **Kevin-Setup.exe** → *Run as administrator*. |
| "the card did not read back what was written" | The card is faulty or fake (common with very cheap cards): use another, ideally a known brand. |
| What happened? | `sudo journalctl -u bob-assistant -n 50` |

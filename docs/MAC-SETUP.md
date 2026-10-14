# Set up Kevin from a Mac

**Kevin Setup for Mac** does everything the Windows app does: writes the microSD card (Raspberry Pi OS Lite
64-bit, downloaded from raspberrypi.com and checked), adds your Wi-Fi and settings, or installs Kevin on a Pi that
is already running. Then it waits for Kevin to come online.

## Get it

From the [latest release](https://github.com/arancool3000/kevin-assistant/releases/latest):

- **Kevin-Setup-mac-apple-silicon.zip** for Macs with an M1, M2, M3, M4 or M5 chip
- **Kevin-Setup-mac-intel.zip** for older Intel Macs

( → About This Mac shows which you have.) Double-click the zip, then drag **Kevin Setup** into Applications.

## The first time you open it

The app isn't signed by Apple yet, so macOS says it "can't be opened" or "can't check it for malicious software":

1. Click **Done** (not *Move to Bin*).
2. Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to *Kevin Setup*.
3. Enter your Mac password, then **Open**. You only do this once.

## Using it

Exactly as on Windows ([WINDOWS-SETUP.md](WINDOWS-SETUP.md)): follow the steps down the left side.

- **Wi-Fi:** newer macOS versions hide the Wi-Fi name from apps, so you may need to type it. *Use the saved
  password* asks your keychain (macOS shows its own prompt: your choice).
- **Writing the card:** after you type **ERASE**, macOS asks for your Mac password. That lets a small helper
  write the card; nothing else gets administrator rights. Only external SD cards and USB card readers are offered,
  never your Mac's own disk.
- If Finder says the disk "is not readable" while it writes, click **Ignore**, never *Initialise*.

## Something went wrong?

| Problem | Do this |
|---|---|
| No card in the list | Put the card in (or plug in the reader), wait a few seconds, press **Refresh**. |
| "the password was not given" | Press **Write the card** again and enter your Mac password. |
| It stops at "the card did not read back" | The card may be faulty or fake: try another one. |
| The boot partition didn't appear | Take the card out and back in, then choose *I already wrote the card*. |

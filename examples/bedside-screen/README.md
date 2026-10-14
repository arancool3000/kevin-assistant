# Bedside screen

A tiny screen for Kevin by your bed: the time, the weather, your timers and alarms, and a button that talks to him.

`18:42 Wed 14 ☁17°` / `⏳ pasta     4:32`

## Parts (about £10)

- Arduino Nano (or Uno) and its USB cable
- 16×2 LCD with an I²C backpack (the 4-pin kind: GND, VCC, SDA, SCL)
- A joystick module (5 pins: GND, +5V, VRx, VRy, SW)
- Optional: a buzzer (a *passive* one plays notes, an *active* one just beeps)

## Wiring

| Part | Pin | Nano |
|---|---|---|
| LCD | GND / VCC | GND / 5V |
| LCD | SDA / SCL | A4 / A5 |
| Joystick | GND / +5V | GND / 5V |
| Joystick | VRx / VRy | A0 / A1 |
| Joystick | SW | D2 |
| Buzzer | + / − | D3 / GND |

Unplug USB while you wire. Never swap VCC and GND on the LCD.

## Set up

1. Open `bedside-screen.ino` in the Arduino IDE (no extra libraries needed) and upload it. The LCD says *Kevin screen
   / waiting for Pi*. If it stays blank, turn the little blue contrast screw on the backpack.
2. Plug the Nano into the Pi.
3. On Kevin's settings page, the *Bedside screen* line lists the USB devices plugged in, such as
   `usb-1a86_USB_Serial-if00-port0` or `usb-FTDI_FT232R_USB_UART_A50xxxxx-if00-port0`. Copy the serial part
   (`A50xxxxx`, or `1a86_USB_Serial` for a CH340 Nano) into the box and save.

## Using it

| Joystick | Does |
|---|---|
| left / right | pages: Home, Weather, Timers, Kevin |
| press | talk to Kevin (press again to stop him) |
| down | stop a ringing alarm, otherwise stop the music |
| up | back to Home |
| hold 2 s | screen off / on |

It dims in quiet hours (settings page) and lights up for 15 seconds when you touch it. When an alarm rings, Home
shows it straight away.

Only the serial number you enter is ever opened: opening an Arduino's port restarts it, so Kevin never touches an
Arduino a skill is using.

// Kevin's bedside screen: an Arduino Nano (or Uno) + a 16x2 LCD with an I2C backpack + a joystick + a buzzer.
// Plug it into the Pi by USB, put its USB serial number in Kevin's settings ("Bedside screen"), done.
// No extra libraries: the LCD is driven over Wire directly. Protocol: see bob/bedside.py.
//
// Wiring (Nano)            LCD backpack: GND, VCC -> 5V, SDA -> A4, SCL -> A5
//                          Joystick:     GND, +5V -> 5V, VRx -> A0, VRy -> A1, SW -> D2
//                          Buzzer:       + -> D3, - -> GND  (a passive one plays notes; an active one just beeps)
#include <Wire.h>

const uint8_t PIN_X = A0, PIN_Y = A1, PIN_SW = 2, PIN_BUZZ = 3;
uint8_t lcdAddr = 0, light = 0x08;          // backpack bit 3 = backlight

// ---- LCD over a PCF8574 backpack (P0 RS, P1 RW, P2 E, P3 backlight, P4-P7 D4-D7) ----
void expWrite(uint8_t v) { Wire.beginTransmission(lcdAddr); Wire.write(v | light); Wire.endTransmission(); }
void nibble(uint8_t n, uint8_t rs) { uint8_t v = (n << 4) | rs; expWrite(v | 4); delayMicroseconds(1); expWrite(v); delayMicroseconds(50); }
void lcdSend(uint8_t b, uint8_t rs) { nibble(b >> 4, rs); nibble(b & 15, rs); }
void lcdCmd(uint8_t c) { lcdSend(c, 0); if (c < 4) delay(2); }

bool lcdBegin() {
  const uint8_t tries[] = {0x27, 0x3F, 0x20, 0x26, 0x38};
  for (uint8_t a : tries) { Wire.beginTransmission(a); if (Wire.endTransmission() == 0) { lcdAddr = a; break; } }
  if (!lcdAddr) return false;
  delay(50); expWrite(0); delay(5);
  for (uint8_t i = 0; i < 3; i++) { nibble(3, 0); delay(5); }       // into 4-bit mode
  nibble(2, 0);
  lcdCmd(0x28); lcdCmd(0x0C); lcdCmd(0x06); lcdCmd(0x01);
  return true;
}

void lcdLine(uint8_t row, const uint8_t *s) {   // 16 characters; codes 8-15 are the custom icons
  lcdCmd(0x80 | (row ? 0x40 : 0));
  for (uint8_t i = 0; i < 16; i++) lcdSend(s[i], 1);
}

// ---- joystick: one event per push (l r u d), p = press, h = held 2 s ----
char joystick() {
  static char last = 0; static bool down = false, held = false; static unsigned long t0;
  bool sw = !digitalRead(PIN_SW);
  if (sw && !down) { down = true; held = false; t0 = millis(); }
  if (sw && down && !held && millis() - t0 > 2000) { held = true; return 'h'; }
  if (!sw && down) { down = false; if (!held && millis() - t0 > 30) return 'p'; }
  int x = analogRead(PIN_X), y = analogRead(PIN_Y);
  char now = x < 250 ? 'l' : x > 770 ? 'r' : y < 250 ? 'u' : y > 770 ? 'd' : 0;
  if (now != last) { last = now; return now; }
  return 0;
}

int readByte() {                                 // wait up to 200 ms for one byte of a command
  unsigned long t = millis();
  while (!Serial.available()) if (millis() - t > 200) return -1;
  return Serial.read();
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_SW, INPUT_PULLUP);
  pinMode(PIN_BUZZ, OUTPUT);
  Wire.begin();
  if (lcdBegin()) { const uint8_t a[] = "  Kevin screen  ", b[] = "waiting for Pi  "; lcdLine(0, a); lcdLine(1, b); }
}

void loop() {
  char k = joystick();
  if (k) Serial.write(k);
  if (!Serial.available()) { delay(10); return; }
  uint8_t c = Serial.read(), buf[17];
  uint8_t n = c == 'T' ? 17 : c == 'G' ? 9 : c == 'B' ? 1 : c == 'Z' ? 2 : 0;
  for (uint8_t i = 0; i < n; i++) { int v = readByte(); if (v < 0) return; buf[i] = v; }
  if (c == 'H') Serial.write('K');                                       // hello
  else if (c == 'T' && lcdAddr) lcdLine(buf[0] & 1, buf + 1);            // a line of text
  else if (c == 'G' && lcdAddr) { lcdCmd(0x40 | (buf[0] & 7) << 3); for (uint8_t i = 1; i < 9; i++) lcdSend(buf[i], 1); lcdCmd(0x80); }
  else if (c == 'B') { light = buf[0] ? 0x08 : 0; if (lcdAddr) expWrite(0); }   // this backpack is on/off only
  else if (c == 'Z') { if (buf[1]) tone(PIN_BUZZ, 50000UL / buf[1], buf[0] * 10UL); delay(buf[0] * 10UL); }
}

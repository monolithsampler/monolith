/*
  Sampler controller - Arduino Uno (v7)
  16 piezo pads (CD4067 multiplexer), 4 Q-link pots, 24 buttons (three 74HC165 shift registers), VU meter + status lights (WS2812)
  -> USB serial <-> Raspberry Pi

  Serial protocol, 115200 baud, one text line per event:
    P,<pad 1-16>,<velocity 1-127>      pad hit
    K,<knob 0-3>,<value 0-127>         pot moved
    B,<button 0-23>,<1 pressed|0 released>
  From the Pi (lights on the rear strip):
    V,<left 0-255>,<right 0-255>       VU meter levels (12 pixels per channel)
    S,<bits>                           bit0 = PLAY light, bit1 = REC light
    buttons: 0 REC  1 OVERDUB  2 STOP  3 PLAY  4 PLAY START
             5 MAIN 6 GRID 7 MUTE 8 LOAD 9 PROG 10 SAMPLE 11 CHOP 12 MIXER 13 FX
             14 SHIFT 15 ERASE 16 UNDO 17 TAP 18 (free: no key on the panel) 19 REPEAT 20 F1 21 F2 22 F3 23 F4
  (The D-pad, its centre OK key and the jog wheel do NOT go through the Arduino: they are wired to the Raspberry Pi.)

  Wiring (see wiring_diagram.svg):
    CD4067: A->D6  B->D7  C->D8  D->D9  COM->A0  INH->GND  VDD->5V  VSS->GND
            I0..I15 -> pad 1..16 (piezo + 1M resistor + 5.1V zener to GND)
    Pots:   wipers -> A1 A2 A3 A4   (outer legs 5V and GND)
    74HC165 x3, daisy-chained:  SH/LD (pin 1) of all three -> D2   CLK (pin 2) of all three -> D3
            QH (pin 9) of chip 1 -> D4 ;  SER (pin 10) of chip 1 <- QH of chip 2 ;  SER of chip 2 <- QH of chip 3 ;  SER of chip 3 -> GND
            CLK INH (pin 15) -> GND, VCC (16) -> 5V, GND (8) -> GND, 100 nF across VCC/GND at each chip
            Inputs A..H = pins 11,12,13,14,3,4,5,6.  Each input has a 10k pull-up to 5V and its switch to GND.
            Button n sits on chip (n div 8), input letter (n mod 8):  A = 0 ... H = 7   (chip 1 = buttons 0-7, chip 2 = 8-15, chip 3 = 16-23)
    Lights: WS2812 data -> D5 through a 330 ohm resistor. 26 pixels in one chain: 0-11 VU left, 12-23 VU right, 24 PLAY, 25 REC.
            Feed the strip from the Pi's 5V (not through the Arduino's regulator) if you raise LED_BRIGHT; 100-470 uF across the strip's 5V/GND.
            A plain green power LED (5V -> 330 ohm -> LED -> GND) is separate.
    Needs the Adafruit NeoPixel library (Arduino Library Manager).
*/

const uint8_t SEL[4]  = {6, 7, 8, 9};
const uint8_t SIG     = A0;
const uint8_t POT[4]  = {A1, A2, A3, A4};
const uint8_t PIN_LATCH = 2, PIN_CLK = 3, PIN_DATA = 4;
const uint8_t NCHIP = 3, NBTN = 24;

#include <Adafruit_NeoPixel.h>
const uint8_t PIN_LEDS = 5, NPIX = 26, VU_N = 12;
const uint8_t LED_BRIGHT = 30;       // 0-255: low on purpose, the strip is fed from the Arduino's USB supply
Adafruit_NeoPixel strip(NPIX, PIN_LEDS, NEO_GRB + NEO_KHZ800);
uint8_t vuL = 0, vuR = 0, statusBits = 0;
bool lightsDirty = true;
uint32_t lightsTime = 0;

// ---- tune these ----
const int      THRESHOLD   = 30;    // 0-1023: raise if pads false-trigger, lower if soft hits are missed
const int      PEAK_MAX    = 600;   // reading that counts as a full-force hit
const uint8_t  PEAK_SCANS  = 3;     // scans spent finding the peak after a hit (~7 ms)
const uint16_t RETRIGGER_MS = 45;   // ignore a pad this long after a hit (kills ringing)
// --------------------

uint8_t  state[16];                 // 0 idle, 1 measuring peak
int      peakVal[16];
uint8_t  scansLeft[16];
uint32_t lockUntil[16];

bool     btnLast[NBTN];             // true = released (pull-up)
uint32_t btnTime[NBTN];
int      potLast[4];
uint32_t potTime = 0;

void selectChannel(uint8_t ch) {
  for (uint8_t b = 0; b < 4; b++) digitalWrite(SEL[b], (ch >> b) & 1);
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(SEL[i], OUTPUT);
    potLast[i] = -10;
  }
  pinMode(PIN_LATCH, OUTPUT); pinMode(PIN_CLK, OUTPUT); pinMode(PIN_DATA, INPUT);
  digitalWrite(PIN_LATCH, HIGH); digitalWrite(PIN_CLK, LOW);
  for (uint8_t i = 0; i < NBTN; i++) btnLast[i] = true;
  strip.begin(); strip.setBrightness(LED_BRIGHT); strip.show();
}

void scanPads() {
  uint32_t now = millis();
  for (uint8_t ch = 0; ch < 16; ch++) {
    selectChannel(ch);
    delayMicroseconds(15);           // let the multiplexer settle
    int v = analogRead(SIG);
    if (state[ch] == 0) {
      if (v > THRESHOLD && now >= lockUntil[ch]) {
        state[ch] = 1; peakVal[ch] = v; scansLeft[ch] = PEAK_SCANS;
      }
    } else {
      if (v > peakVal[ch]) peakVal[ch] = v;
      if (--scansLeft[ch] == 0) {
        float n = (float)(peakVal[ch] - THRESHOLD) / (float)(PEAK_MAX - THRESHOLD);
        if (n < 0) n = 0; if (n > 1) n = 1;
        int vel = 1 + (int)(126.0 * sqrt(n));       // sqrt curve = more natural feel
        Serial.print("P,"); Serial.print(ch + 1); Serial.print(','); Serial.println(vel);
        state[ch] = 0;
        lockUntil[ch] = now + RETRIGGER_MS;
      }
    }
  }
}

// Reads all 24 inputs. After the latch pulse the first bit out of chip 1 is its input H, then G ... A, then chip 2's H ... and so on.
void readButtons(bool pressed[NBTN]) {
  digitalWrite(PIN_LATCH, LOW); delayMicroseconds(5);
  digitalWrite(PIN_LATCH, HIGH); delayMicroseconds(5);
  for (uint8_t chip = 0; chip < NCHIP; chip++) {
    for (int8_t bit = 7; bit >= 0; bit--) {
      bool level = digitalRead(PIN_DATA);                      // HIGH = not pressed (pull-up)
      pressed[chip * 8 + bit] = !level;
      digitalWrite(PIN_CLK, HIGH); delayMicroseconds(2);
      digitalWrite(PIN_CLK, LOW);  delayMicroseconds(2);
    }
  }
}

void scanButtons() {
  static uint32_t last = 0;
  uint32_t now = millis();
  if (now - last < 3) return;                                   // scan about every 3 ms
  last = now;
  bool pressed[NBTN];
  readButtons(pressed);
  for (uint8_t i = 0; i < NBTN; i++) {
    bool released = !pressed[i];
    if (released != btnLast[i] && now - btnTime[i] > 15) {      // 15 ms debounce
      btnLast[i] = released; btnTime[i] = now;
      Serial.print("B,"); Serial.print(i); Serial.print(','); Serial.println(pressed[i] ? 1 : 0);
    }
  }
}

void scanPots() {
  uint32_t now = millis();
  if (now - potTime < 15) return;
  potTime = now;
  for (uint8_t i = 0; i < 4; i++) {
    int raw = analogRead(POT[i]);
    if (abs(raw - potLast[i]) > 6) {                            // hysteresis stops jitter
      potLast[i] = raw;
      Serial.print("K,"); Serial.print(i); Serial.print(','); Serial.println(raw >> 3);  // 0-127
    }
  }
}

// ---- lights: the Pi sends "V,l,r" and "S,bits" lines; we parse them without blocking ----
uint32_t barColor(uint8_t i) { return i < 8 ? strip.Color(0, 255, 0) : (i < 10 ? strip.Color(255, 200, 0) : strip.Color(255, 0, 0)); }

void showLights() {
  uint32_t now = millis();
  if (!lightsDirty || now - lightsTime < 40) return;            // at most 25 updates a second (strip.show() blocks interrupts for about 1 ms)
  lightsTime = now; lightsDirty = false;
  for (uint8_t i = 0; i < VU_N; i++) {
    strip.setPixelColor(i, i < vuL ? barColor(i) : 0);
    strip.setPixelColor(VU_N + i, i < vuR ? barColor(i) : 0);
  }
  strip.setPixelColor(24, (statusBits & 1) ? strip.Color(0, 255, 0) : 0);
  strip.setPixelColor(25, (statusBits & 2) ? strip.Color(255, 0, 0) : 0);
  strip.show();
}

void readSerial() {
  static char buf[24]; static uint8_t n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      buf[n] = 0; n = 0;
      int a = 0, b = 0;
      if (buf[0] == 'V' && sscanf(buf, "V,%d,%d", &a, &b) == 2) {
        uint8_t l = (a * VU_N + 127) / 255, r = (b * VU_N + 127) / 255;
        if (l != vuL || r != vuR) { vuL = l; vuR = r; lightsDirty = true; }
      } else if (buf[0] == 'S' && sscanf(buf, "S,%d", &a) == 1) {
        if ((uint8_t)a != statusBits) { statusBits = a; lightsDirty = true; }
      }
    } else if (n < sizeof(buf) - 1) buf[n++] = c;
  }
}

void loop() {
  scanPads();
  scanButtons();
  scanPots();
  readSerial();
  showLights();
}

#define MIC_PIN A0
#define BAUD_RATE 115200

// Calibration
#define CALIBRATION_MS 1000
#define SAMPLES_PER_WINDOW 50
#define WINDOW_MS 50

// Detection
#define BLOW_MULTIPLIER 2.5   // threshold = baseline * this
#define MIN_THRESHOLD 40      // never set threshold below this
#define LEVEL_REPORT_MS 100   // how often to send LEVEL,x,y

int baseline = 0;
int threshold = 0;
unsigned long lastLevelReport = 0;

// Returns peak-to-peak amplitude over a WINDOW_MS sampling window
int peakToPeak() {
  int lo = 1023, hi = 0;
  unsigned long start = millis();
  while (millis() - start < WINDOW_MS) {
    int v = analogRead(MIC_PIN);
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return hi - lo;
}

void setup() {
  Serial.begin(BAUD_RATE);
  delay(300); // let serial settle

  // Calibrate: take several windows, use the max as baseline
  int maxAmplitude = 0;
  unsigned long start = millis();
  while (millis() - start < CALIBRATION_MS) {
    int amp = peakToPeak();
    if (amp > maxAmplitude) maxAmplitude = amp;
  }

  baseline = maxAmplitude;
  threshold = max((int)(baseline * BLOW_MULTIPLIER), MIN_THRESHOLD);

  Serial.print("BASELINE,");
  Serial.println(baseline);
}

void loop() {
  int level = peakToPeak();

  // Report level periodically
  if (millis() - lastLevelReport >= LEVEL_REPORT_MS) {
    Serial.print("LEVEL,");
    Serial.print(level);
    Serial.print(",");
    Serial.println(threshold);
    lastLevelReport = millis();
  }

  if (level >= threshold) {
    Serial.println("BLOW");
    delay(200); // short debounce — cooldown handled by Python (4s)
  }
}

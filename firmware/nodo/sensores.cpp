#include "sensores.h"

#include <DHT.h>

#include "config.h"

static DHT dht(PIN_DHT, DHT11);

void iniciarSensores() {
  dht.begin();

  // Suelo: atenuación de 11 dB para medir hasta ~3,1 V
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_SUELO, ADC_11db);

#if SUELO_ALIM_GPIO >= 0
  pinMode(SUELO_ALIM_GPIO, OUTPUT);
  digitalWrite(SUELO_ALIM_GPIO, LOW);  // apagada hasta la primera lectura
#endif
}

// ---------------------------------------------------------------------------
// Aire (DHT11). La librería no vuelve a consultar el sensor antes de 2 s:
// temperatura y humedad salen de la misma medición.
// ---------------------------------------------------------------------------
LecturaAire leerAire() {
  LecturaAire r;
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t)) {
    r.tempValida = true;
    r.temp = t;
  }
  if (!isnan(h)) {
    r.humValida = true;
    r.hum = h;
  }
  return r;
}

// ---------------------------------------------------------------------------
// Suelo (YL-69 + LM393 en AO). El ADC del ESP32 no es lineal: se usa
// analogReadMilliVolts (corregido de fábrica) y un promedio.
// ---------------------------------------------------------------------------
MedicionSuelo medirSuelo(int muestras) {
  MedicionSuelo m;
  if (muestras < 1) muestras = 1;

#if SUELO_ALIM_GPIO >= 0
  digitalWrite(SUELO_ALIM_GPIO, HIGH);
  delay(SUELO_ESPERA_ALIM_MS);  // espera corta para que la sonda se estabilice
#endif

  uint32_t suma = 0;
  int minimo = INT_MAX, maximo = 0;
  for (int i = 0; i < muestras; i++) {
    int mv = (int)analogReadMilliVolts(PIN_SUELO);
    suma += mv;
    if (mv < minimo) minimo = mv;
    if (mv > maximo) maximo = mv;
    delayMicroseconds(500);
  }

#if SUELO_ALIM_GPIO >= 0
  digitalWrite(SUELO_ALIM_GPIO, LOW);
#endif

  m.mv = (int)((suma + muestras / 2) / muestras);
  m.mvMin = minimo;
  m.mvMax = maximo;
  m.valida = m.mv >= SUELO_MV_MIN_VALIDO;
  return m;
}

bool sueloCalibrado() {
  return SUELO_MV_MOJADO >= 0 && SUELO_MV_SECO > SUELO_MV_MOJADO;
}

int sueloPorcentaje(int mv) {
  if (!sueloCalibrado()) return -1;
  // Más agua = menos voltaje: seco -> 0 %, mojado -> 100 %
  long num = (long)(SUELO_MV_SECO - mv) * 100L;
  long den = (long)(SUELO_MV_SECO - SUELO_MV_MOJADO);
  long pct = (num + den / 2) / den;  // redondeo al entero más cercano
  if (num < 0) pct = 0;
  return (int)constrain(pct, 0L, 100L);
}

LecturaSuelo leerSuelo() {
  LecturaSuelo r;
  MedicionSuelo m = medirSuelo(MUESTRAS_SUELO);
  if (!m.valida) return r;
  r.mvValido = true;
  r.mv = m.mv;
  int pct = sueloPorcentaje(m.mv);
  if (pct >= 0) {
    r.pctValido = true;
    r.pct = pct;
  }
  return r;
}

Lectura leerTodo() {
  Lectura l;
  l.aire = leerAire();    // si un sensor falla, los demás se leen igual
  l.suelo = leerSuelo();
  return l;
}

#include "led.h"

#include <Arduino.h>

#include "config.h"

static const uint32_t MEDIO_PERIODO_LENTO_MS = 1000;  // 1 s encendido, 1 s apagado

static ModoLed modoActual = ModoLed::APAGADO;
static bool encendido = false;
static uint32_t ultimoCambio = 0;

static void escribir(bool valor) {
  encendido = valor;
  digitalWrite(PIN_LED, valor ? HIGH : LOW);
}

void iniciarLed() {
  pinMode(PIN_LED, OUTPUT);
  escribir(false);
}

void ponerModoLed(ModoLed modo) {
  if (modo == modoActual) return;
  modoActual = modo;
  ultimoCambio = millis();
  escribir(modo == ModoLed::FIJO || modo == ModoLed::PARPADEO_LENTO);
}

ModoLed modoLed() { return modoActual; }

void actualizarLed() {
  if (modoActual != ModoLed::PARPADEO_LENTO) return;
  uint32_t ahora = millis();
  if (ahora - ultimoCambio >= MEDIO_PERIODO_LENTO_MS) {
    ultimoCambio = ahora;
    escribir(!encendido);
  }
}

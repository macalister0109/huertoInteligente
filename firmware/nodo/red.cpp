#include "red.h"

#include <WiFi.h>

#include "config.h"

// Espera entre intentos de conexión (crece si sigue fallando, hasta 1 min)
static const uint32_t REINTENTO_MIN_MS = 10000;
static const uint32_t REINTENTO_MAX_MS = 60000;

static uint32_t ultimoIntento = 0;
static uint32_t esperaActual = REINTENTO_MIN_MS;
static bool estabaConectado = false;

void iniciarRed() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname("huerto-" NODO_ID);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);  // no espera: la conexión sigue en segundo plano
  ultimoIntento = millis();
  Serial.printf("[WiFi] Conectando a \"%s\"...\n", WIFI_SSID);
}

void actualizarRed() {
  bool conectado = WiFi.status() == WL_CONNECTED;

  if (conectado != estabaConectado) {
    estabaConectado = conectado;
    if (conectado) {
      esperaActual = REINTENTO_MIN_MS;
      Serial.printf("[WiFi] Conectado. IP %s, señal %d dBm\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
      Serial.println(F("[WiFi] Se perdió la conexión. Las lecturas se guardan en la memoria."));
      ultimoIntento = millis();
    }
  }
  if (conectado) return;

  uint32_t ahora = millis();
  if (ahora - ultimoIntento < esperaActual) return;
  ultimoIntento = ahora;
  esperaActual = min(esperaActual * 2, REINTENTO_MAX_MS);
  Serial.printf("[WiFi] Reintentando conectar a \"%s\" (estado %d)\n", WIFI_SSID, WiFi.status());
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

bool wifiConectado() { return WiFi.status() == WL_CONNECTED; }

int rssiWifi() { return wifiConectado() ? WiFi.RSSI() : 0; }

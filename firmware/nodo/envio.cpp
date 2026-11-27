#include "envio.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>

#include "ca_letsencrypt.h"  // CA_LETS_ENCRYPT, para usar en API_CA_CERT
#include "config.h"
#include "hora.h"

static const uint16_t TIEMPO_CONEXION_MS = 4000;
static const uint16_t TIEMPO_RESPUESTA_MS = 6000;

size_t armarJson(const Registro &r, char *destino, size_t largo) {
  char medido[24];
  formatearIsoUtc(r.medidoEn, medido, sizeof(medido));

  JsonDocument doc;
  doc["nodo_id"] = NODO_ID;
  doc["seq"] = r.seq;
  doc["medido_en"] = medido;
  // Un sensor que falla va como null y no bloquea a los demás
  if (r.temp10 == SIN_VALOR) doc["temp"] = nullptr;
  else doc["temp"] = r.temp10 / 10.0;
  if (r.hum10 == SIN_VALOR) doc["hum_aire"] = nullptr;
  else doc["hum_aire"] = r.hum10 / 10.0;
  if (r.sueloPct == SIN_VALOR) doc["suelo_pct"] = nullptr;
  else doc["suelo_pct"] = r.sueloPct;
  if (r.sueloMv == SIN_VALOR) doc["suelo_mv"] = nullptr;
  else doc["suelo_mv"] = r.sueloMv;
  doc["luz"] = nullptr;  // sin sensor de luz en el prototipo 1
  return serializeJson(doc, destino, largo);
}

static bool esHttps() { return strncmp(API_URL, "https://", 8) == 0; }

ResultadoEnvio enviarLectura(const Registro &r) {
  char cuerpo[256];
  armarJson(r, cuerpo, sizeof(cuerpo));

  WiFiClient clientePlano;
  WiFiClientSecure clienteSeguro;
  WiFiClient *cliente = &clientePlano;
  if (esHttps()) {
    const char *ca = API_CA_CERT;
    if (ca != nullptr) {
      clienteSeguro.setCACert(ca);
    } else {
      static bool avisado = false;
      if (!avisado) {
        Serial.println(F("[API] AVISO: https sin API_CA_CERT: cifrado pero sin verificar el servidor"));
        avisado = true;
      }
      clienteSeguro.setInsecure();
    }
    cliente = &clienteSeguro;
  }

  HTTPClient http;
  http.setConnectTimeout(TIEMPO_CONEXION_MS);
  http.setTimeout(TIEMPO_RESPUESTA_MS);
  http.setReuse(false);
  if (!http.begin(*cliente, API_URL)) {
    Serial.println(F("[API] ERROR: API_URL no es válida (revisa config.h)"));
    return {-1, AccionEnvio::REINTENTAR};
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " API_TOKEN);

  int codigo = http.POST((uint8_t *)cuerpo, strlen(cuerpo));
  String respuesta = codigo > 0 ? http.getString() : String();
  http.end();

  ResultadoEnvio res = {codigo, AccionEnvio::REINTENTAR};
  if (codigo == 201 || codigo == 200) {
    Serial.printf("[API] seq=%lu -> HTTP %d %s\n", (unsigned long)r.seq, codigo,
                  codigo == 201 ? "guardada" : "ya estaba (duplicada)");
    res.accion = AccionEnvio::BORRAR;
  } else if (codigo == 400 || codigo == 409 || codigo == 413) {
    // Reenviarla daría el mismo error: se descarta para no trancar el buffer
    Serial.printf("[API] seq=%lu -> HTTP %d RECHAZADA (se descarta): %s\n", (unsigned long)r.seq,
                  codigo, respuesta.c_str());
    res.accion = AccionEnvio::BORRAR;
  } else if (codigo == 401 || codigo == 403) {
    Serial.printf("[API] seq=%lu -> HTTP %d: token inválido. Revisa API_TOKEN y NODO_ID en config.h\n",
                  (unsigned long)r.seq, codigo);
  } else if (codigo > 0) {
    Serial.printf("[API] seq=%lu -> HTTP %d (se reintentará): %s\n", (unsigned long)r.seq, codigo,
                  respuesta.c_str());
  } else {
    Serial.printf("[API] seq=%lu -> sin respuesta (%s). Se reintentará.\n", (unsigned long)r.seq,
                  HTTPClient::errorToString(codigo).c_str());
  }
  return res;
}

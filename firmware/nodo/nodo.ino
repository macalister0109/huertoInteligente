/*
 * Huerto Inteligente — firmware del nodo (prototipo 1).
 *
 *   ESP32 -> WiFi -> HTTP POST con JSON -> API Flask -> base de datos
 *
 * El ESP32 nunca se conecta directo a la base de datos. La pantalla OLED
 * funciona siempre, haya o no red.
 *
 * Montaje (verificado):
 *   DHT11 (KY-015)   S -> GPIO 4  · + -> V (3.3 V) · - -> G
 *   YL-69 + LM393    AO -> GPIO 34 · VCC -> V (3.3 V) · GND -> G · DO libre
 *   OLED SSD1306     SDA -> GPIO 21 · SCL -> GPIO 22 · dirección 0x3C
 *   LED integrado    GPIO 2
 *
 * Cómo viaja una lectura:
 *   1. Cada INTERVALO_MS se mide y recibe un número `seq` (guardado en NVS,
 *      no se repite aunque el ESP32 se reinicie).
 *   2. Se guarda en el buffer de la memoria flash (LittleFS).
 *   3. Cuando hay WiFi, se envían en orden, de la más antigua a la más nueva.
 *      Solo se borra del buffer cuando la API confirma (201 o 200).
 *   Si aún no hay hora de internet (NTP), la lectura espera en memoria y se
 *   le pone la hora real apenas se sincroniza (nunca una hora inventada).
 *
 * Monitor Serie a 115200 baudios, con "Nueva línea". Comandos:
 *   CAL (calibrar suelo) · LEER (medir ahora) · ESTADO (red y buffer)
 */

#if !__has_include("config.h")
#error "Falta config.h: copia config.example.h como config.h en esta carpeta y edítalo."
#endif

#include <Preferences.h>

#include "config.h"
#include "buffer.h"
#include "calibracion.h"
#include "envio.h"
#include "hora.h"
#include "led.h"
#include "pantalla.h"
#include "red.h"
#include "sensores.h"
#include "sistema.h"

// El DHT11 necesita ~1 s tras encender antes de la primera lectura
static const uint32_t ESPERA_PRIMERA_LECTURA_MS = 2500;
// El DHT11 no admite más de una lectura por segundo: usamos 2 s como mínimo
static const uint32_t INTERVALO_MINIMO_MS = 2000;
static const uint32_t INTERVALO_EFECTIVO_MS =
  INTERVALO_MS < INTERVALO_MINIMO_MS ? INTERVALO_MINIMO_MS : INTERVALO_MS;
static const uint32_t REFRESCO_EFECTIVO_MS =
  REFRESCO_PANTALLA_MS < INTERVALO_MINIMO_MS ? INTERVALO_MINIMO_MS : REFRESCO_PANTALLA_MS;

// Envío: pausa entre lecturas del buffer y espera tras un fallo (crece hasta 1 min)
static const uint32_t PAUSA_ENTRE_ENVIOS_MS = 300;
static const uint32_t REINTENTO_ENVIO_MIN_MS = 5000;
static const uint32_t REINTENTO_ENVIO_MAX_MS = 60000;

// Lecturas tomadas antes de tener hora NTP (quedan en RAM: 240 = 2 h a 30 s)
static const uint16_t MAX_SIN_HORA = 240;

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------

static Preferences preferencias;
static uint32_t siguienteSeq = 1;

struct SinHora {
  Registro registro;
  uint32_t medidoMillis;
};
static SinHora sinHora[MAX_SIN_HORA];
static uint16_t cantidadSinHora = 0;

static uint32_t ultimaLectura = 0;
static bool primeraHecha = false;
static uint32_t ultimoRefresco = 0;
static LecturaAire ultimoAire;
static LecturaSuelo ultimoSuelo;

static uint32_t proximoEnvio = 0;
static uint32_t esperaEnvio = REINTENTO_ENVIO_MIN_MS;
static bool errorApi = false;
static bool wifiAlgunaVez = false;
static int ultimoCodigoHttp = 0;

// ---------------------------------------------------------------------------
// seq persistente (Preferences / NVS)
// ---------------------------------------------------------------------------

static void cargarSeq() {
  preferencias.begin("huerto", false);
  siguienteSeq = preferencias.getUInt("seq", 1);
  if (siguienteSeq == 0) siguienteSeq = 1;
}

static uint32_t tomarSeq() {
  uint32_t seq = siguienteSeq++;
  preferencias.putUInt("seq", siguienteSeq);  // se guarda antes de usarlo
  return seq;
}

// ---------------------------------------------------------------------------
// Lecturas
// ---------------------------------------------------------------------------

static int16_t aDecimas(bool valido, float valor) {
  return valido ? (int16_t)lroundf(valor * 10.0f) : SIN_VALOR;
}

static Registro armarRegistro(const Lectura &l) {
  Registro r;
  r.seq = tomarSeq();
  r.medidoEn = 0;
  r.temp10 = aDecimas(l.aire.tempValida, l.aire.temp);
  r.hum10 = aDecimas(l.aire.humValida, l.aire.hum);
  r.sueloPct = l.suelo.pctValido ? (int16_t)l.suelo.pct : SIN_VALOR;
  r.sueloMv = l.suelo.mvValido ? (int16_t)l.suelo.mv : SIN_VALOR;
  return r;
}

static void encolar(const Registro &r) {
  if (guardarEnBuffer(r)) return;
  // La memoria flash falló: al menos se intenta enviar al tiro
  Serial.println(F("[Buffer] ERROR al guardar: se intenta enviar sin buffer"));
  if (wifiConectado()) enviarLectura(r);
}

static void tomarLectura() {
  Lectura l = leerTodo();
  ultimoAire = l.aire;
  ultimoSuelo = l.suelo;
  Registro r = armarRegistro(l);

  char json[256];
  if (horaValida()) {
    r.medidoEn = ahoraUtc();
    armarJson(r, json, sizeof(json));
    Serial.printf("[Lectura] %s\n", json);
    encolar(r);
  } else if (cantidadSinHora < MAX_SIN_HORA) {
    sinHora[cantidadSinHora++] = { r, millis() };
    Serial.printf("[Lectura] seq=%lu guardada en espera: aún no hay hora de internet (NTP)\n",
                  (unsigned long)r.seq);
  } else {
    Serial.printf("[Lectura] seq=%lu PERDIDA: más de 2 h sin hora de internet\n",
                  (unsigned long)r.seq);
  }
  if (l.aire.tempValida && l.aire.temp <= 0) {
    Serial.println(F("[Lectura] AVISO: Temperatura en el límite del sensor (0 °C o menos)"));
  }
}

// Apenas hay hora NTP, las lecturas en espera reciben su hora real:
// la de ahora menos el tiempo que pasó desde que se midieron.
static void fecharLecturasEnEspera() {
  if (cantidadSinHora == 0 || !horaValida()) return;
  uint32_t ahora = ahoraUtc();
  uint32_t ahoraMs = millis();
  for (uint16_t i = 0; i < cantidadSinHora; i++) {
    Registro r = sinHora[i].registro;
    r.medidoEn = ahora - (ahoraMs - sinHora[i].medidoMillis) / 1000;
    encolar(r);
  }
  Serial.printf("[Hora] Sincronizada. %u lecturas en espera pasan al buffer con su hora real.\n",
                cantidadSinHora);
  cantidadSinHora = 0;
}

// ---------------------------------------------------------------------------
// Envío del buffer
// ---------------------------------------------------------------------------

static void enviarPendientes() {
  if (!wifiConectado() || pendientesEnBuffer() == 0) return;
  if ((int32_t)(millis() - proximoEnvio) < 0) return;

  Registro r;
  if (!primeroDelBuffer(r)) return;
  ResultadoEnvio res = enviarLectura(r);
  ultimoCodigoHttp = res.codigoHttp;

  if (res.accion == AccionEnvio::BORRAR) {
    sacarPrimeroDelBuffer();
    errorApi = false;
    esperaEnvio = REINTENTO_ENVIO_MIN_MS;
    proximoEnvio = millis() + PAUSA_ENTRE_ENVIOS_MS;
  } else {
    errorApi = true;
    proximoEnvio = millis() + esperaEnvio;
    esperaEnvio = min(esperaEnvio * 2, REINTENTO_ENVIO_MAX_MS);
  }
}

// ---------------------------------------------------------------------------
// Pantalla, LED y Serial
// ---------------------------------------------------------------------------

static EstadoRed estadoRed() {
  if (!wifiConectado()) return wifiAlgunaVez ? EstadoRed::SIN_WIFI : EstadoRed::CONECTANDO;
  return errorApi ? EstadoRed::ERROR_API : EstadoRed::WIFI_OK;
}

static uint16_t pendientesTotales() {
  return pendientesEnBuffer() + cantidadSinHora;
}

static void actualizarIndicadores() {
  EstadoRed red = estadoRed();
  mostrarLectura(ultimoAire, ultimoSuelo, red, pendientesTotales());

  // LED: parpadeo lento = sin conexión con el equipo central,
  //      fijo = suelo fuera del rango ideal, apagado = todo bien
  bool fueraDeRango = ultimoSuelo.pctValido && (ultimoSuelo.pct < SUELO_MIN || ultimoSuelo.pct > SUELO_MAX);
  if (red != EstadoRed::WIFI_OK) ponerModoLed(ModoLed::PARPADEO_LENTO);
  else if (fueraDeRango) ponerModoLed(ModoLed::FIJO);
  else ponerModoLed(ModoLed::APAGADO);
}

static void refrescarPantalla() {
  ultimoAire = leerAire();
#if SUELO_ALIM_GPIO < 0
  // Con VCC fijo se puede medir seguido. Si la sonda se alimenta por GPIO,
  // solo se mide en cada lectura (para que se corroa menos).
  ultimoSuelo = leerSuelo();
#endif
  actualizarIndicadores();
}

static void imprimirEstado() {
  char hora[6];
  formatearHoraLocal(hora, sizeof(hora));
  Serial.println(F("---------------- ESTADO ----------------"));
  Serial.printf(" Nodo: %s · próximo seq: %lu\n", NODO_ID, (unsigned long)siguienteSeq);
  Serial.printf(" Red: %s · señal %d dBm · hora local %s%s\n", textoEstadoRed(estadoRed()),
                rssiWifi(), hora, horaValida() ? "" : " (sin NTP)");
  Serial.printf(" API: %s · último código HTTP %d\n", API_URL, ultimoCodigoHttp);
  Serial.printf(" Buffer: %u pendientes · %u esperando hora · %lu descartadas por buffer lleno\n",
                pendientesEnBuffer(), cantidadSinHora,
                (unsigned long)descartadasPorBufferLleno());
  Serial.println(F("----------------------------------------"));
}

static void atenderSerial() {
  String comando;
  if (!leerComando(comando)) return;

  if (enModoCal() && atenderComandoCal(comando)) {
    if (!enModoCal()) actualizarIndicadores();  // salió con FIN: vuelve la pantalla normal
    return;
  }
  if (comando == "CAL") {
    if (!enModoCal()) entrarModoCal();
  } else if (comando == "LEER") {
    tomarLectura();
    actualizarIndicadores();
  } else if (comando == "ESTADO") {
    imprimirEstado();
  } else {
    Serial.printf("Comando desconocido: %s. Usa CAL, LEER, ESTADO%s\n", comando.c_str(),
                  enModoCal() ? ", SECO, MOJADO o FIN" : "");
  }
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(200);  // da tiempo a que el Monitor Serie se conecte

  iniciarLed();
  ponerModoLed(ModoLed::PARPADEO_LENTO);
  iniciarPantalla();
  iniciarSensores();
  iniciarWatchdog(WATCHDOG_S);

  Serial.println();
  Serial.println(F("========================================"));
  Serial.println(F(" Huerto Inteligente — nodo " NODO_ID));
  Serial.println(F("========================================"));
  Serial.printf(" Motivo del último reinicio: %s\n", motivoReinicio());
  Serial.printf(" Intervalo de lectura: %lu s · API: %s\n",
                (unsigned long)(INTERVALO_EFECTIVO_MS / 1000), API_URL);
  Serial.printf(" Sonda de suelo: seco=%d mV, mojado=%s\n", SUELO_MV_SECO,
                sueloCalibrado() ? String(SUELO_MV_MOJADO).c_str() : "SIN CALIBRAR");
#if SUELO_ALIM_GPIO >= 0
  Serial.printf(" Sonda alimentada solo al medir (GPIO %d)\n", SUELO_ALIM_GPIO);
#else
  Serial.println(F(" Sonda alimentada siempre (VCC fijo a 3.3 V)"));
#endif

  cargarSeq();
  iniciarBuffer();
  iniciarRed();
  iniciarHora();

  Serial.printf(" Próximo seq: %lu\n", (unsigned long)siguienteSeq);
  Serial.println(F(" Comandos: CAL (calibrar suelo) · LEER (medir ahora) · ESTADO"));
  Serial.println();
}

void loop() {
  alimentarWatchdog();
  actualizarLed();
  actualizarRed();
  if (wifiConectado()) wifiAlgunaVez = true;
  atenderSerial();
  fecharLecturasEnEspera();
  enviarPendientes();  // el buffer se vacía también durante la calibración

  if (enModoCal()) {
    actualizarModoCal();
    return;  // en calibración se pausan las lecturas normales
  }

  uint32_t ahora = millis();
  bool toca = primeraHecha ? (ahora - ultimaLectura >= INTERVALO_EFECTIVO_MS)
                           : (ahora >= ESPERA_PRIMERA_LECTURA_MS);
  if (toca) {
    ultimaLectura = ahora;
    ultimoRefresco = ahora;
    primeraHecha = true;
    tomarLectura();
    actualizarIndicadores();
  } else if (primeraHecha && ahora - ultimoRefresco >= REFRESCO_EFECTIVO_MS) {
    ultimoRefresco = ahora;
    refrescarPantalla();
  }
}

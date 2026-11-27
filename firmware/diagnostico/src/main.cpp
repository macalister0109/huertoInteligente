/*
 * Huerto Inteligente — sketch de DIAGNÓSTICO del nodo (ESP32).
 *
 * Sirve para saber qué hardware tienes antes de cargar el firmware final:
 *   1. Escanea el bus I2C e identifica cada dirección.
 *   2. Distingue BME280 de BMP280 (el BMP280 NO mide humedad) leyendo su chip ID.
 *   3. Si no hay sensor de aire por I2C, prueba un DHT22 y un DHT11 en GPIO 4.
 *   4. Muestra los valores crudos del ADS1115 para calibrar las sondas de suelo,
 *      con un asistente que entrega las líneas listas para config.h.
 *   5. Prueba el LED RGB.
 *
 * Uso: pio run -t upload  y luego  pio device monitor  (115200 baudios).
 * Escribe una letra en el monitor y presiona Enter:
 *   h ayuda · s escanear I2C · r leer todo · m lectura continua
 *   a sonda al AIRE (seco) · w sonda en AGUA (mojado) · p imprimir calibración
 *   l probar LED
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_BME280.h>
#include <Adafruit_BMP280.h>
#include <BH1750.h>
#include <DHT.h>
#include <esp_system.h>

#include "config_diagnostico.h"

#if NUM_SONDAS < 1 || NUM_SONDAS > 4
#error "NUM_SONDAS debe estar entre 1 y 4"
#endif

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------

enum class SensorAire { NINGUNO, BME280, BMP280, BME680, DHT22, DHT11 };

struct Hallazgos {
  uint8_t dirAds = 0;       // 0 = no encontrado
  uint8_t dirAire = 0;
  uint8_t idChipAire = 0;
  uint8_t dirLuz = 0;
  SensorAire aire = SensorAire::NINGUNO;
  bool hayAht = false;
  bool haySht = false;
  bool hayRtcOled = false;
} hallazgos;

Adafruit_ADS1115 ads;
Adafruit_BME280 bme;
Adafruit_BMP280 bmp(&Wire);
BH1750 medidorLuz;
DHT *dht = nullptr;

bool adsListo = false, bmeListo = false, bmpListo = false, luzLista = false;

int32_t calibSeco[4] = {-1, -1, -1, -1};
int32_t calibMojado[4] = {-1, -1, -1, -1};

bool lecturaContinua = false;
unsigned long ultimaLectura = 0;
const unsigned long INTERVALO_CONTINUO_MS = 1000;

// Prueba del LED como máquina de estados (sin delay largos)
int pasoLed = -1;
unsigned long inicioPasoLed = 0;
const unsigned long DURACION_PASO_LED_MS = 800;

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

const char *motivoReinicio() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:   return "encendido (POWERON)";
    case ESP_RST_SW:        return "reinicio por software (SW)";
    case ESP_RST_PANIC:     return "error del programa (PANIC)";
    case ESP_RST_INT_WDT:   return "watchdog de interrupciones (INT_WDT)";
    case ESP_RST_TASK_WDT:  return "watchdog de tareas (TASK_WDT)";
    case ESP_RST_WDT:       return "watchdog (WDT)";
    case ESP_RST_BROWNOUT:  return "caída de voltaje (BROWNOUT): revisa la fuente";
    case ESP_RST_EXT:       return "pin de reset (EXT)";
    case ESP_RST_DEEPSLEEP: return "salida de sueño profundo";
    default:                return "desconocido";
  }
}

bool existeDispositivo(uint8_t direccion) {
  Wire.beginTransmission(direccion);
  return Wire.endTransmission() == 0;
}

// Devuelve 0xFF si no se pudo leer
uint8_t leerRegistro(uint8_t direccion, uint8_t registro) {
  Wire.beginTransmission(direccion);
  Wire.write(registro);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  if (Wire.requestFrom(direccion, (uint8_t)1) != 1) return 0xFF;
  return Wire.read();
}

const char *nombreDireccion(uint8_t d) {
  switch (d) {
    case 0x23: case 0x5C: return "BH1750 (luz)";
    case 0x48: case 0x49: case 0x4A: case 0x4B: return "ADS1115 (conversor para las sondas de suelo)";
    case 0x76: case 0x77: return "BME280 / BMP280 / BME680 (aire) — ver chip ID abajo";
    case 0x38: return "AHT10 / AHT20 (temperatura y humedad del aire)";
    case 0x44: case 0x45: return "SHT30 / SHT31 (temperatura y humedad del aire)";
    case 0x40: return "HTU21D / SHT21 / INA219";
    case 0x3C: case 0x3D: return "Pantalla OLED SSD1306";
    case 0x68: return "Reloj DS3231 / DS1307 (o MPU6050)";
    case 0x57: return "Memoria EEPROM (viene en módulos de reloj)";
    default:   return "desconocido";
  }
}

const char *nombreSensorAire(SensorAire s) {
  switch (s) {
    case SensorAire::BME280: return "BME280";
    case SensorAire::BMP280: return "BMP280";
    case SensorAire::BME680: return "BME680";
    case SensorAire::DHT22:  return "DHT22 / AM2302";
    case SensorAire::DHT11:  return "DHT11";
    default:                 return "ninguno";
  }
}

void linea() { Serial.println(F("------------------------------------------------------------")); }

// ---------------------------------------------------------------------------
// LED RGB
// ---------------------------------------------------------------------------

void escribirLed(bool r, bool g, bool b) {
  const bool inv = LED_ANODO_COMUN;   // ánodo común: se enciende con LOW
  digitalWrite(PIN_LED_R, (r != inv) ? HIGH : LOW);
  digitalWrite(PIN_LED_G, (g != inv) ? HIGH : LOW);
  digitalWrite(PIN_LED_B, (b != inv) ? HIGH : LOW);
}

struct PasoLed { bool r, g, b; const char *texto; };
const PasoLed PASOS_LED[] = {
  {true, false, false, "ROJO"},
  {false, true, false, "VERDE"},
  {false, false, true, "AZUL"},
  {true, true, false, "AMARILLO (rojo + verde)"},
  {true, true, true, "BLANCO (los tres)"},
  {false, false, false, "APAGADO"},
};
const int NUM_PASOS_LED = sizeof(PASOS_LED) / sizeof(PASOS_LED[0]);

void iniciarPruebaLed() {
  linea();
  Serial.printf("Prueba del LED RGB (R=GPIO %d, G=GPIO %d, B=GPIO %d, %s).\n",
                PIN_LED_R, PIN_LED_G, PIN_LED_B,
                LED_ANODO_COMUN ? "ánodo común" : "cátodo común");
  Serial.println(F("Mira el LED: debe mostrar cada color que se indica."));
  pasoLed = 0;
  inicioPasoLed = 0;   // se aplica en el próximo ciclo
}

void avanzarPruebaLed() {
  if (pasoLed < 0) return;
  if (inicioPasoLed != 0 && millis() - inicioPasoLed < DURACION_PASO_LED_MS) return;
  if (pasoLed >= NUM_PASOS_LED) {
    Serial.println(F("Fin de la prueba del LED."));
    Serial.println(F("  - Si los colores están cambiados, intercambia PIN_LED_R/G/B en config."));
    Serial.println(F("  - Si se encendía cuando decía APAGADO, cambia LED_ANODO_COMUN."));
    pasoLed = -1;
    return;
  }
  const PasoLed &p = PASOS_LED[pasoLed];
  escribirLed(p.r, p.g, p.b);
  Serial.printf("  LED: %s\n", p.texto);
  inicioPasoLed = millis();
  pasoLed++;
}

// ---------------------------------------------------------------------------
// 1 y 2. Escaneo I2C e identificación
// ---------------------------------------------------------------------------

void escanearI2C() {
  hallazgos = Hallazgos();
  linea();
  Serial.printf("Escaneando el bus I2C (SDA=GPIO %d, SCL=GPIO %d)...\n", PIN_SDA, PIN_SCL);
  int encontrados = 0;
  for (uint8_t d = 1; d < 127; d++) {
    if (!existeDispositivo(d)) continue;
    encontrados++;
    Serial.printf("  0x%02X  %s\n", d, nombreDireccion(d));

    if (d >= 0x48 && d <= 0x4B && hallazgos.dirAds == 0) hallazgos.dirAds = d;
    if ((d == 0x23 || d == 0x5C) && hallazgos.dirLuz == 0) hallazgos.dirLuz = d;
    if (d == 0x38) hallazgos.hayAht = true;
    if (d == 0x44 || d == 0x45) hallazgos.haySht = true;
    if (d == 0x3C || d == 0x3D || d == 0x68) hallazgos.hayRtcOled = true;

    if ((d == 0x76 || d == 0x77) && hallazgos.dirAire == 0) {
      uint8_t id = leerRegistro(d, 0xD0);   // registro "chip ID" de Bosch
      hallazgos.dirAire = d;
      hallazgos.idChipAire = id;
      if (id == 0x60) hallazgos.aire = SensorAire::BME280;
      else if (id == 0x58 || id == 0x56 || id == 0x57) hallazgos.aire = SensorAire::BMP280;
      else if (id == 0x61) hallazgos.aire = SensorAire::BME680;
      Serial.printf("        chip ID 0x%02X -> %s\n", id,
                    hallazgos.aire == SensorAire::NINGUNO ? "no reconocido" : nombreSensorAire(hallazgos.aire));
    }
  }
  Serial.printf("Dispositivos encontrados: %d\n", encontrados);

  if (encontrados == 0) {
    Serial.println(F("!! No respondió ningún dispositivo I2C. Revisa:"));
    Serial.println(F("   - SDA al GPIO 21 y SCL al GPIO 22 (no invertidos)"));
    Serial.println(F("   - VCC a 3.3 V y GND común"));
    Serial.println(F("   - Que los módulos tengan resistencias pull-up (casi todos las traen)"));
  }
  if (hallazgos.aire == SensorAire::BMP280) {
    Serial.println(F("!! ATENCIÓN: el sensor es un BMP280. Mide temperatura y presión,"));
    Serial.println(F("   pero NO humedad del aire. Se parece mucho al BME280 (revisa el"));
    Serial.println(F("   chip: el BME280 es cuadrado y el BMP280 rectangular). Con un"));
    Serial.println(F("   BMP280 el campo hum_aire irá siempre vacío (null)."));
  }
  if (hallazgos.aire == SensorAire::BME680) {
    Serial.println(F("!! El sensor es un BME680 (mide además gases). El firmware final"));
    Serial.println(F("   espera un BME280: avísame para agregar su soporte."));
  }
  if (hallazgos.hayAht || hallazgos.haySht) {
    Serial.println(F("!! Hay un sensor AHT o SHT. El firmware final espera BME280 o DHT:"));
    Serial.println(F("   avísame para agregar su soporte."));
  }
  if (hallazgos.dirAds == 0) Serial.println(F("!! Falta el ADS1115: sin él no se pueden leer las sondas de suelo."));
  if (hallazgos.dirLuz == 0) Serial.println(F("!! Falta el BH1750: no habrá medición de luz."));
}

// ---------------------------------------------------------------------------
// 3. Respaldo DHT en GPIO 4
// ---------------------------------------------------------------------------

// Un DHT11 leído como DHT22 (o al revés) da valores absurdos: se descartan
bool lecturaDhtCreible(float t, float h) {
  return !isnan(t) && !isnan(h) && t > -40 && t < 80 && h > 0 && h <= 100;
}

bool probarDht(uint8_t tipo) {
  if (dht) { delete dht; dht = nullptr; }
  dht = new DHT(PIN_DHT, tipo);
  dht->begin();
  // El DHT necesita ~2 s entre lecturas: aquí se acepta esperar (solo al inicio)
  delay(2200);
  float t = dht->readTemperature();
  float h = dht->readHumidity();
  Serial.printf("  Probando %s en GPIO %d: ", tipo == DHT22 ? "DHT22" : "DHT11", PIN_DHT);
  if (lecturaDhtCreible(t, h)) {
    Serial.printf("responde (%.1f °C, %.1f %%)\n", t, h);
    return true;
  }
  Serial.println(F("no responde"));
  return false;
}

void buscarDht() {
  if (hallazgos.aire != SensorAire::NINGUNO) return;
  linea();
  Serial.println(F("No hay sensor de aire por I2C. Probando un DHT en el GPIO 4..."));
  if (probarDht(DHT22)) {
    hallazgos.aire = SensorAire::DHT22;
  } else if (probarDht(DHT11)) {
    hallazgos.aire = SensorAire::DHT11;
  } else {
    delete dht; dht = nullptr;
    Serial.println(F("!! Tampoco se encontró un DHT. Revisa: DATA al GPIO 4, VCC a 3.3 V,"));
    Serial.println(F("   GND, y una resistencia de 10 kΩ entre DATA y VCC (si el módulo no la trae)."));
  }
}

// ---------------------------------------------------------------------------
// Inicio de los sensores encontrados
// ---------------------------------------------------------------------------

void iniciarSensores() {
  adsListo = bmeListo = bmpListo = luzLista = false;
  if (hallazgos.dirAds) {
    adsListo = ads.begin(hallazgos.dirAds);
    // ±4,096 V: cubre la salida de las sondas alimentadas a 3,3 V
    if (adsListo) ads.setGain(GAIN_ONE);
  }
  if (hallazgos.aire == SensorAire::BME280) bmeListo = bme.begin(hallazgos.dirAire);
  if (hallazgos.aire == SensorAire::BMP280) bmpListo = bmp.begin(hallazgos.dirAire, hallazgos.idChipAire);
  if (hallazgos.dirLuz) {
    luzLista = medidorLuz.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, hallazgos.dirLuz, &Wire);
  }
}

// ---------------------------------------------------------------------------
// 4. Lecturas y calibración del suelo
// ---------------------------------------------------------------------------

struct LecturaSonda { int32_t promedio; int16_t minimo; int16_t maximo; };

LecturaSonda leerSonda(uint8_t canal, int muestras) {
  LecturaSonda r = {0, INT16_MAX, INT16_MIN};
  int64_t suma = 0;
  for (int i = 0; i < muestras; i++) {
    int16_t v = ads.readADC_SingleEnded(canal);
    suma += v;
    if (v < r.minimo) r.minimo = v;
    if (v > r.maximo) r.maximo = v;
  }
  r.promedio = (int32_t)(suma / muestras);
  return r;
}

void imprimirLecturas() {
  linea();
  Serial.printf("Lecturas (t = %lu s)\n", millis() / 1000);

  if (adsListo) {
    for (uint8_t c = 0; c < NUM_SONDAS; c++) {
      LecturaSonda s = leerSonda(c, MUESTRAS_SUELO);
      Serial.printf("  Sonda %d (A%d): crudo %6ld  (%.3f V)  ruido %d",
                    c + 1, c, (long)s.promedio, ads.computeVolts(s.promedio), s.maximo - s.minimo);
      if (calibSeco[c] >= 0 && calibMojado[c] >= 0 && calibSeco[c] != calibMojado[c]) {
        float pct = 100.0f * (calibSeco[c] - s.promedio) / (float)(calibSeco[c] - calibMojado[c]);
        pct = constrain(pct, 0.0f, 100.0f);
        Serial.printf("  -> %.1f %% de humedad", pct);
      }
      Serial.println();
    }
  } else {
    Serial.println(F("  Suelo: sin ADS1115"));
  }

  switch (hallazgos.aire) {
    case SensorAire::BME280:
      if (bmeListo) Serial.printf("  Aire (BME280): %.1f °C, %.1f %% de humedad, %.0f hPa\n",
                                  bme.readTemperature(), bme.readHumidity(), bme.readPressure() / 100.0f);
      break;
    case SensorAire::BMP280:
      if (bmpListo) Serial.printf("  Aire (BMP280): %.1f °C, humedad NO disponible, %.0f hPa\n",
                                  bmp.readTemperature(), bmp.readPressure() / 100.0f);
      break;
    case SensorAire::DHT22:
    case SensorAire::DHT11: {
      float t = dht->readTemperature(), h = dht->readHumidity();
      if (lecturaDhtCreible(t, h)) Serial.printf("  Aire (%s): %.1f °C, %.1f %% de humedad\n",
                                                 nombreSensorAire(hallazgos.aire), t, h);
      else Serial.println(F("  Aire (DHT): lectura fallida (¿menos de 2 s desde la anterior?)"));
      break;
    }
    default:
      Serial.println(F("  Aire: sin sensor"));
  }

  if (luzLista) Serial.printf("  Luz (BH1750): %.0f lux\n", medidorLuz.readLightLevel());
  else Serial.println(F("  Luz: sin BH1750"));
}

void capturarCalibracion(bool seco) {
  if (!adsListo) { Serial.println(F("No hay ADS1115: no se puede calibrar.")); return; }
  linea();
  Serial.printf("Midiendo con la sonda %s (64 muestras por sonda)...\n",
                seco ? "al AIRE, limpia y seca" : "en un vaso de AGUA hasta la línea marcada");
  for (uint8_t c = 0; c < NUM_SONDAS; c++) {
    LecturaSonda s = leerSonda(c, 64);
    (seco ? calibSeco : calibMojado)[c] = s.promedio;
    Serial.printf("  Sonda %d: %ld (ruido %d)\n", c + 1, (long)s.promedio, s.maximo - s.minimo);
  }
  Serial.println(seco ? F("Listo. Ahora pon las sondas en agua y escribe 'w'.")
                      : F("Listo. Escribe 'p' para ver las líneas para config.h."));
}

void imprimirCalibracion() {
  linea();
  bool completa = true;
  for (uint8_t c = 0; c < NUM_SONDAS; c++) {
    if (calibSeco[c] < 0 || calibMojado[c] < 0) completa = false;
  }
  if (!completa) {
    Serial.println(F("Falta medir: usa 'a' (sonda al aire) y 'w' (sonda en agua)."));
    return;
  }
  Serial.println(F("Copia estas líneas en firmware/include/config.h:"));
  Serial.printf("#define NUM_SONDAS %d\n", NUM_SONDAS);
  Serial.print(F("#define SUELO_SECO_RAW   {"));
  for (uint8_t c = 0; c < NUM_SONDAS; c++) Serial.printf("%s%ld", c ? ", " : "", (long)calibSeco[c]);
  Serial.println(F("}"));
  Serial.print(F("#define SUELO_MOJADO_RAW {"));
  for (uint8_t c = 0; c < NUM_SONDAS; c++) Serial.printf("%s%ld", c ? ", " : "", (long)calibMojado[c]);
  Serial.println(F("}"));

  for (uint8_t c = 0; c < NUM_SONDAS; c++) {
    int32_t dif = calibSeco[c] - calibMojado[c];
    if (dif < 0) {
      Serial.printf("!! Sonda %d: en agua da MÁS que al aire. ¿Se invirtieron los pasos?\n", c + 1);
    } else if (dif < 2000) {
      Serial.printf("!! Sonda %d: poca diferencia entre seco y mojado (%ld). Revisa la sonda.\n",
                    c + 1, (long)dif);
    }
  }
}

// ---------------------------------------------------------------------------
// Resumen y comandos
// ---------------------------------------------------------------------------

void imprimirResumen() {
  linea();
  Serial.println(F("RESUMEN PARA EL FIRMWARE FINAL"));
  Serial.printf("  Sondas de suelo (ADS1115): %s\n",
                hallazgos.dirAds ? "OK" : "NO ENCONTRADO");
  if (hallazgos.dirAds && hallazgos.dirAds != 0x48)
    Serial.printf("    ADS1115 en 0x%02X: usa #define ADS1115_DIRECCION 0x%02X\n", hallazgos.dirAds, hallazgos.dirAds);
  Serial.printf("  Sensor de aire: %s", nombreSensorAire(hallazgos.aire));
  switch (hallazgos.aire) {
    case SensorAire::BME280: Serial.printf(" -> entorno 'nodo_bme280' (dirección 0x%02X)\n", hallazgos.dirAire); break;
    case SensorAire::BMP280: Serial.println(" -> entorno 'nodo_bme280' (detecta el BMP280 y envía hum_aire = null)"); break;
    case SensorAire::DHT22:  Serial.println(" -> entorno 'nodo_dht22'"); break;
    case SensorAire::DHT11:  Serial.println(" -> entorno 'nodo_dht11'"); break;
    default:                 Serial.println(" -> revisar conexiones"); break;
  }
  Serial.printf("  Luz (BH1750): %s\n", hallazgos.dirLuz ? "OK" : "NO ENCONTRADO");
}

void ayuda() {
  linea();
  Serial.println(F("Comandos (escribe la letra y presiona Enter):"));
  Serial.println(F("  r  leer todos los sensores una vez"));
  Serial.println(F("  m  activar/desactivar lectura cada 1 segundo"));
  Serial.println(F("  a  calibrar: sondas AL AIRE (secas)"));
  Serial.println(F("  w  calibrar: sondas EN AGUA"));
  Serial.println(F("  p  imprimir la calibración para config.h"));
  Serial.println(F("  l  probar el LED RGB"));
  Serial.println(F("  s  volver a escanear el bus I2C"));
  Serial.println(F("  h  esta ayuda"));
}

void diagnosticoCompleto() {
  escanearI2C();
  buscarDht();
  iniciarSensores();
  imprimirLecturas();
  imprimirResumen();
}

void atenderComando(char c) {
  switch (c) {
    case 'r': imprimirLecturas(); break;
    case 'm':
      lecturaContinua = !lecturaContinua;
      Serial.println(lecturaContinua ? F("Lectura continua ACTIVADA ('m' para detener).")
                                     : F("Lectura continua detenida."));
      break;
    case 'a': capturarCalibracion(true); break;
    case 'w': capturarCalibracion(false); break;
    case 'p': imprimirCalibracion(); break;
    case 'l': iniciarPruebaLed(); break;
    case 's': diagnosticoCompleto(); break;
    case 'h': case '?': ayuda(); break;
    case '\r': case '\n': case ' ': break;
    default: Serial.printf("Comando '%c' desconocido. Escribe 'h' para ver la ayuda.\n", c);
  }
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(1000);   // da tiempo a abrir el monitor serie
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);
  escribirLed(false, false, false);

  Serial.println();
  linea();
  Serial.println(F("HUERTO INTELIGENTE — DIAGNÓSTICO DEL NODO"));
  Serial.printf("Último reinicio: %s\n", motivoReinicio());
  Serial.printf("Sondas configuradas: %d · Memoria libre: %u bytes\n", NUM_SONDAS, ESP.getFreeHeap());

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(100000);
  diagnosticoCompleto();
  ayuda();
}

void loop() {
  while (Serial.available()) atenderComando((char)tolower(Serial.read()));

  if (lecturaContinua && millis() - ultimaLectura >= INTERVALO_CONTINUO_MS) {
    ultimaLectura = millis();
    imprimirLecturas();
  }
  avanzarPruebaLed();
}

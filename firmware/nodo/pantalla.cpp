#include "pantalla.h"

#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Wire.h>

#include "config.h"
#include "hora.h"

static Adafruit_SSD1306 pantalla(128, 64, &Wire, -1);
static bool hayPantalla = false;

static const uint8_t SIMBOLO_GRADOS = 248;  // en la tabla cp437

bool iniciarPantalla() {
  Wire.begin(PIN_SDA, PIN_SCL);
  hayPantalla = pantalla.begin(SSD1306_SWITCHCAPVCC, DIRECCION_OLED);
  if (!hayPantalla) {
    Serial.println(F("[OLED] No encontrada: revisa SDA->21, SCL->22, VCC y GND (o prueba 0x3D)"));
    return false;
  }
  pantalla.cp437(true);
  pantalla.setTextColor(SSD1306_WHITE);
  pantalla.clearDisplay();
  pantalla.setTextSize(1);
  pantalla.setCursor(0, 0);
  pantalla.println(F("Huerto Inteligente"));
  pantalla.println();
  pantalla.println(F("Nodo " NODO_ID));
  pantalla.println(F("Iniciando..."));
  pantalla.display();
  return true;
}

const char *textoEstadoRed(EstadoRed red) {
  switch (red) {
    case EstadoRed::WIFI_OK:   return "WiFi OK";
    case EstadoRed::SIN_WIFI:  return "Sin WiFi";
    case EstadoRed::ERROR_API: return "Error API";
    default:                   return "Conectando";
  }
}

// Línea de estado arriba, en letra chica
static void barraEstado(EstadoRed red, uint16_t pendientes) {
  char texto[24];
  if (pendientes > 0) snprintf(texto, sizeof(texto), "%s Pend:%u", textoEstadoRed(red), pendientes);
  else snprintf(texto, sizeof(texto), "%s", textoEstadoRed(red));

  pantalla.setTextSize(1);
  pantalla.setCursor(0, 0);
  pantalla.print(texto);
  // La hora (5 caracteres de 6 px) a la derecha, solo si cabe junto al estado
  if (strlen(texto) <= 15) {
    char hora[6];
    formatearHoraLocal(hora, sizeof(hora));
    pantalla.setCursor(128 - 5 * 6, 0);
    pantalla.print(hora);
  }
  pantalla.drawFastHLine(0, 9, 128, SSD1306_WHITE);
}

// Una fila: etiqueta chica a la izquierda y valor grande a la derecha
static void fila(int y, const __FlashStringHelper *etiqueta) {
  pantalla.setTextSize(1);
  pantalla.setCursor(0, y + 4);
  pantalla.print(etiqueta);
  pantalla.setTextSize(2);
  pantalla.setCursor(46, y);
}

void mostrarLectura(const LecturaAire &aire, const LecturaSuelo &suelo, EstadoRed red,
                    uint16_t pendientes) {
  if (!hayPantalla) return;
  pantalla.clearDisplay();
  barraEstado(red, pendientes);

  fila(12, F("Temp."));
  if (aire.tempValida) pantalla.print(aire.temp, 0);
  else pantalla.print(F("--"));
  pantalla.write(SIMBOLO_GRADOS);
  pantalla.print(F("C"));

  fila(30, F("Aire"));
  if (aire.humValida) pantalla.print(aire.hum, 0);
  else pantalla.print(F("--"));
  pantalla.print(F("%"));

  fila(48, F("Suelo"));
  if (suelo.pctValido) pantalla.print(suelo.pct);
  else pantalla.print(F("--"));
  pantalla.print(F("%"));

  // Aviso a la derecha de la humedad del suelo
  const char *aviso = !suelo.mvValido         ? "FALLA"
                      : !suelo.pctValido       ? "CAL"
                      : suelo.pct < SUELO_MIN  ? "SECO"
                      : suelo.pct > SUELO_MAX  ? "AGUA"
                                               : "OK";
  pantalla.setTextSize(1);
  pantalla.setCursor(128 - (int)strlen(aviso) * 6, 52);  // alineado a la derecha
  pantalla.print(aviso);

  pantalla.display();
}

void mostrarCalibracion(int mv, int pct) {
  if (!hayPantalla) return;
  pantalla.clearDisplay();
  pantalla.setTextSize(1);
  pantalla.setCursor(0, 0);
  pantalla.print(F("MODO CALIBRACION"));
  pantalla.drawFastHLine(0, 9, 128, SSD1306_WHITE);
  pantalla.setTextSize(2);
  pantalla.setCursor(0, 18);
  pantalla.print(mv);
  pantalla.print(F(" mV"));
  pantalla.setTextSize(1);
  pantalla.setCursor(0, 42);
  if (pct >= 0) {
    pantalla.print(F("Suelo: "));
    pantalla.print(pct);
    pantalla.print(F(" %"));
  } else {
    pantalla.print(F("Sin calibrar"));
  }
  pantalla.setCursor(0, 54);
  pantalla.print(F("SECO / MOJADO / FIN"));
  pantalla.display();
}

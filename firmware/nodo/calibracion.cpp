#include "calibracion.h"

#include "config.h"
#include "pantalla.h"
#include "sensores.h"

static const uint32_t PERIODO_CAL_MS = 1000;
static const int MUESTRAS_CAPTURA = 50;  // más muestras al guardar SECO / MOJADO
static const size_t LARGO_MAX_COMANDO = 32;

static bool activo = false;
static uint32_t ultimaImpresion = 0;
static int capturaSeco = -1;
static int capturaMojado = -1;
static String bufferEntrada;

bool leerComando(String &comando) {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r' || c == '\n') {
      if (bufferEntrada.length() == 0) continue;
      comando = bufferEntrada;
      bufferEntrada = "";
      comando.trim();
      comando.toUpperCase();
      return comando.length() > 0;
    }
    if (bufferEntrada.length() < LARGO_MAX_COMANDO) bufferEntrada += c;
  }
  return false;
}

bool enModoCal() { return activo; }

void entrarModoCal() {
  activo = true;
  ultimaImpresion = 0;
  Serial.println();
  Serial.println(F("================ MODO CALIBRACIÓN ================"));
  Serial.println(F(" 1. Deja la sonda AL AIRE, limpia y seca. Espera que el"));
  Serial.println(F("    valor se estabilice y escribe  SECO"));
  Serial.println(F(" 2. Mete la sonda EN UN VASO CON AGUA hasta la línea"));
  Serial.println(F("    (sin mojar el módulo LM393) y escribe  MOJADO"));
  Serial.println(F(" 3. Copia las líneas #define que aparecen en config.h"));
  Serial.println(F(" Escribe  FIN  para volver a las lecturas normales."));
  Serial.printf(" Calibración actual: seco=%d mV, mojado=%d mV%s\n",
                SUELO_MV_SECO, SUELO_MV_MOJADO,
                sueloCalibrado() ? "" : " (mojado SIN calibrar)");
  Serial.println(F("=================================================="));
}

void salirModoCal() {
  activo = false;
  Serial.println(F("[CAL] Fin del modo calibración. Vuelven las lecturas normales."));
}

static void imprimirLineasConfig() {
  Serial.println(F("[CAL] Copia estas líneas en firmware/nodo/config.h:"));
  Serial.printf("  #define SUELO_MV_SECO %d\n",
                capturaSeco >= 0 ? capturaSeco : SUELO_MV_SECO);
  Serial.printf("  #define SUELO_MV_MOJADO %d\n",
                capturaMojado >= 0 ? capturaMojado : SUELO_MV_MOJADO);
  int seco = capturaSeco >= 0 ? capturaSeco : SUELO_MV_SECO;
  int mojado = capturaMojado >= 0 ? capturaMojado : SUELO_MV_MOJADO;
  if (mojado >= 0 && seco - mojado < 300) {
    Serial.println(F("[CAL] OJO: seco y mojado están muy cerca (< 300 mV)."));
    Serial.println(F("      Revisa que la sonda esté bien sumergida y el cable AO firme."));
  }
}

bool atenderComandoCal(const String &comando) {
  if (comando == "FIN") {
    salirModoCal();
    return true;
  }
  if (comando == "SECO" || comando == "MOJADO") {
    MedicionSuelo m = medirSuelo(MUESTRAS_CAPTURA);
    if (!m.valida) {
      Serial.printf("[CAL] Lectura no válida (%d mV). Revisa el cable AO y VCC.\n", m.mv);
      return true;
    }
    if (comando == "SECO") {
      capturaSeco = m.mv;
      Serial.printf("[CAL] SECO guardado: %d mV\n", m.mv);
    } else {
      capturaMojado = m.mv;
      Serial.printf("[CAL] MOJADO guardado: %d mV\n", m.mv);
    }
    imprimirLineasConfig();
    return true;
  }
  return false;
}

void actualizarModoCal() {
  if (!activo) return;
  uint32_t ahora = millis();
  if (ultimaImpresion != 0 && ahora - ultimaImpresion < PERIODO_CAL_MS) return;
  ultimaImpresion = ahora;

  MedicionSuelo m = medirSuelo(MUESTRAS_SUELO);
  Serial.printf("[CAL] suelo = %4d mV  (mín %4d · máx %4d en %d muestras)",
                m.mv, m.mvMin, m.mvMax, MUESTRAS_SUELO);
  int pct = sueloPorcentaje(m.mv);
  mostrarCalibracion(m.mv, pct);
  if (!m.valida) {
    Serial.print(F("  -> FALLA: casi 0 mV, revisa AO y VCC"));
  } else if (pct >= 0) {
    Serial.printf("  -> %d %%", pct);
  }
  Serial.println();
}

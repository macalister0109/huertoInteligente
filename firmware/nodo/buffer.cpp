#include "buffer.h"

#include <LittleFS.h>

#include "config.h"

static const char *ARCHIVO = "/lecturas.bin";
static const uint32_t MAGICO = 0x48554552;  // "HUER"
static const uint16_t VERSION_FORMATO = 1;

// Encabezado al inicio del archivo; después van los registros
struct Encabezado {
  uint32_t magico;
  uint16_t version;
  uint16_t capacidad;
  uint16_t cabeza;      // posición del más antiguo
  uint16_t cantidad;
  uint32_t descartadas; // por buffer lleno (histórico)
};

static Encabezado enc;
static bool listo = false;

static size_t posicion(uint16_t indice) {
  return sizeof(Encabezado) + (size_t)indice * sizeof(Registro);
}

static bool escribirEncabezado(File &f) {
  f.seek(0);
  return f.write((const uint8_t *)&enc, sizeof(enc)) == sizeof(enc);
}

static bool crearArchivoVacio() {
  enc = {MAGICO, VERSION_FORMATO, BUFFER_MAX_LECTURAS, 0, 0, 0};
  File f = LittleFS.open(ARCHIVO, "w");
  if (!f) return false;
  bool ok = f.write((const uint8_t *)&enc, sizeof(enc)) == sizeof(enc);
  Registro vacio = {};
  for (uint16_t i = 0; ok && i < BUFFER_MAX_LECTURAS; i++) {
    ok = f.write((const uint8_t *)&vacio, sizeof(vacio)) == sizeof(vacio);
  }
  f.close();
  return ok;
}

bool iniciarBuffer() {
  // true = formatear si la partición está vacía o dañada (solo la primera vez)
  if (!LittleFS.begin(true)) {
    Serial.println(F("[Buffer] ERROR: no se pudo montar la memoria flash (LittleFS)"));
    return false;
  }
  File f = LittleFS.open(ARCHIVO, "r");
  bool valido = false;
  if (f && f.read((uint8_t *)&enc, sizeof(enc)) == sizeof(enc)) {
    valido = enc.magico == MAGICO && enc.version == VERSION_FORMATO &&
             enc.capacidad == BUFFER_MAX_LECTURAS && enc.cantidad <= enc.capacidad &&
             enc.cabeza < enc.capacidad && f.size() == posicion(enc.capacidad);
  }
  if (f) f.close();

  if (!valido) {
    Serial.println(F("[Buffer] Creando buffer nuevo en la memoria flash"));
    if (!crearArchivoVacio()) {
      Serial.println(F("[Buffer] ERROR: no se pudo crear el archivo del buffer"));
      return false;
    }
  }
  listo = true;
  Serial.printf("[Buffer] Listo: %u lecturas pendientes (capacidad %u)\n", enc.cantidad,
                enc.capacidad);
  return true;
}

bool guardarEnBuffer(const Registro &r) {
  if (!listo) return false;
  File f = LittleFS.open(ARCHIVO, "r+");
  if (!f) return false;

  if (enc.cantidad == enc.capacidad) {
    // Lleno: se pierde la más antigua para dejar lugar a la nueva
    enc.cabeza = (enc.cabeza + 1) % enc.capacidad;
    enc.cantidad--;
    enc.descartadas++;
    Serial.println(F("[Buffer] AVISO: buffer lleno, se descartó la lectura más antigua"));
  }
  uint16_t cola = (enc.cabeza + enc.cantidad) % enc.capacidad;
  f.seek(posicion(cola));
  bool ok = f.write((const uint8_t *)&r, sizeof(r)) == sizeof(r);
  if (ok) {
    enc.cantidad++;
    ok = escribirEncabezado(f);
  }
  f.close();
  return ok;
}

bool primeroDelBuffer(Registro &r) {
  if (!listo || enc.cantidad == 0) return false;
  File f = LittleFS.open(ARCHIVO, "r");
  if (!f) return false;
  f.seek(posicion(enc.cabeza));
  bool ok = f.read((uint8_t *)&r, sizeof(r)) == sizeof(r);
  f.close();
  return ok;
}

void sacarPrimeroDelBuffer() {
  if (!listo || enc.cantidad == 0) return;
  enc.cabeza = (enc.cabeza + 1) % enc.capacidad;
  enc.cantidad--;
  File f = LittleFS.open(ARCHIVO, "r+");
  if (!f) return;
  escribirEncabezado(f);
  f.close();
}

uint16_t pendientesEnBuffer() { return listo ? enc.cantidad : 0; }

uint32_t descartadasPorBufferLleno() { return enc.descartadas; }

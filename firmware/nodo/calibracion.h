// Modo calibración de la sonda de suelo (sin recompilar).
//
// En el Monitor Serie (115200, "Nueva línea") escribe:
//   CAL     entra al modo: muestra los mV del suelo cada segundo
//   SECO    guarda el valor actual como "sonda al aire"
//   MOJADO  guarda el valor actual como "sonda en agua"
//   FIN     sale y vuelve a las lecturas normales
// Al capturar SECO y MOJADO imprime las líneas listas para config.h.
#pragma once

#include <Arduino.h>

// Lee el Serial sin bloquear. Devuelve true cuando llegó una línea completa
// (en mayúsculas y sin espacios en los extremos).
bool leerComando(String &comando);

bool enModoCal();
void entrarModoCal();
void salirModoCal();

// Procesa un comando del modo CAL (SECO, MOJADO, FIN). Devuelve true si lo usó.
bool atenderComandoCal(const String &comando);

// Llamar en cada vuelta de loop(): imprime cada segundo mientras está activo.
void actualizarModoCal();

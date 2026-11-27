// LED de estado (LED integrado del ESP32, GPIO 2).
//   APAGADO         -> todo bien
//   FIJO            -> alguna variable fuera de rango
//   PARPADEO_LENTO  -> sin conexión con el equipo central
#pragma once

enum class ModoLed { APAGADO, FIJO, PARPADEO_LENTO };

void iniciarLed();
void ponerModoLed(ModoLed modo);
ModoLed modoLed();
void actualizarLed();  // llamar en cada vuelta de loop()

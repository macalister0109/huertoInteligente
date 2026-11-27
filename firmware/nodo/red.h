// WiFi con reconexión que NO bloquea: la pantalla sigue funcionando
// mientras el nodo intenta volver a conectarse.
#pragma once

#include <Arduino.h>

void iniciarRed();
void actualizarRed();   // llamar en cada vuelta de loop()
bool wifiConectado();
int rssiWifi();         // intensidad de la señal en dBm (0 si no hay WiFi)

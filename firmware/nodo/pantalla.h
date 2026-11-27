// Pantalla OLED SSD1306 128×64 (I2C en GPIO 21/22).
//
//   ┌────────────────────────┐
//   │WiFi OK  Pend:3    15:04│  <- estado de la red (letra chica)
//   │Temp.   23°C            │
//   │Aire    61%             │
//   │Suelo   42%         OK  │  <- SECO / AGUA / OK según SUELO_MIN y SUELO_MAX
//   └────────────────────────┘
//
// Si la pantalla no está conectada, el nodo sigue funcionando igual.
#pragma once

#include <Arduino.h>

#include "sensores.h"

enum class EstadoRed { CONECTANDO, WIFI_OK, SIN_WIFI, ERROR_API };

bool iniciarPantalla();
void mostrarLectura(const LecturaAire &aire, const LecturaSuelo &suelo, EstadoRed red,
                    uint16_t pendientes);
void mostrarCalibracion(int mv, int pct);

// Texto corto del estado ("WiFi OK", "Sin WiFi", ...), también para el log
const char *textoEstadoRed(EstadoRed red);

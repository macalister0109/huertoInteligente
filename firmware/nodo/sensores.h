// Sensores del nodo. Una función por sensor; para sumar otro sensor
// (luz en el prototipo 2) se agrega su función y su campo en Lectura.
#pragma once

#include <Arduino.h>

// Aire: DHT11 (0 a 50 °C, ±2 °C, resolución 1 °C)
struct LecturaAire {
  bool tempValida = false;
  float temp = NAN;       // °C
  bool humValida = false;
  float hum = NAN;        // % humedad del aire
};

// Medición cruda del suelo (promedio de MUESTRAS_SUELO)
struct MedicionSuelo {
  bool valida = false;
  int mv = -1;            // promedio
  int mvMin = -1;
  int mvMax = -1;
};

// Suelo ya interpretado
struct LecturaSuelo {
  bool mvValido = false;
  int mv = -1;
  bool pctValido = false; // false si la sonda falla o aún no está calibrada
  int pct = -1;           // 0 a 100 %
};

struct Lectura {
  LecturaAire aire;
  LecturaSuelo suelo;
  // Luz: no hay sensor en el prototipo 1 (va null). Prototipo 2: HU-04.
  bool luzValida = false;
  float luz = NAN;
};

void iniciarSensores();

LecturaAire leerAire();
MedicionSuelo medirSuelo(int muestras);
LecturaSuelo leerSuelo();
Lectura leerTodo();

// Conversión lineal entre SUELO_MV_SECO y SUELO_MV_MOJADO, acotada a 0–100.
// Devuelve -1 si la sonda no está calibrada.
int sueloPorcentaje(int mv);
bool sueloCalibrado();

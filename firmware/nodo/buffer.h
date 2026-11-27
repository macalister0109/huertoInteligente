// Buffer de lecturas en la memoria flash (LittleFS).
//
// TODA lectura pasa por aquí: primero se guarda y después se envía.
// Así, si se corta la red (o la luz), nada se pierde y se reenvía en
// orden al volver. Es una cola circular de BUFFER_MAX_LECTURAS registros;
// si se llena, se descarta la más antigua (aviso por Serial).
#pragma once

#include <Arduino.h>

// Valor que indica "sin dato" (el JSON lleva null)
static const int16_t SIN_VALOR = INT16_MIN;

struct Registro {
  uint32_t seq;
  uint32_t medidoEn;  // segundos Unix, UTC
  int16_t temp10;     // °C × 10
  int16_t hum10;      // % × 10
  int16_t sueloPct;   // 0 a 100
  int16_t sueloMv;    // mV crudos
};

bool iniciarBuffer();             // false si la memoria no se pudo montar
bool guardarEnBuffer(const Registro &r);
bool primeroDelBuffer(Registro &r);   // el más antiguo, sin sacarlo
void sacarPrimeroDelBuffer();
uint16_t pendientesEnBuffer();
uint32_t descartadasPorBufferLleno();

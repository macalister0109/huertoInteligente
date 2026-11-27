// Hora por NTP. medido_en se envía SIEMPRE en UTC ("2026-11-27T18:00:00Z").
// Mientras no haya hora válida no se inventa ninguna: las lecturas esperan.
#pragma once

#include <Arduino.h>
#include <time.h>

void iniciarHora();          // configura NTP y zona horaria (no bloquea)
bool horaValida();           // true cuando ya se sincronizó con NTP
uint32_t ahoraUtc();         // segundos Unix (0 si aún no hay hora)

// "2026-11-27T18:00:00Z" (destino de al menos 21 bytes)
void formatearIsoUtc(uint32_t segundos, char *destino, size_t largo);
// "15:04" en hora de Chile, o "--:--" sin hora (destino de al menos 6 bytes)
void formatearHoraLocal(char *destino, size_t largo);

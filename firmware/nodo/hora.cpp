#include "hora.h"

#include "config.h"

// Cualquier fecha anterior a esta significa "el reloj no se ha sincronizado"
// (al encender, el ESP32 parte en 1970).
static const time_t HORA_MINIMA_VALIDA = 1767225600;  // 2026-01-01 00:00 UTC

void iniciarHora() {
  // Configura la zona y arranca SNTP en segundo plano: se sincroniza solo
  // cuando hay WiFi y se vuelve a sincronizar cada hora.
  configTzTime(ZONA_HORARIA, NTP_SERVER, "time.google.com");
}

bool horaValida() { return time(nullptr) >= HORA_MINIMA_VALIDA; }

uint32_t ahoraUtc() {
  time_t t = time(nullptr);
  return t >= HORA_MINIMA_VALIDA ? (uint32_t)t : 0;
}

void formatearIsoUtc(uint32_t segundos, char *destino, size_t largo) {
  time_t t = (time_t)segundos;
  struct tm utc;
  gmtime_r(&t, &utc);
  strftime(destino, largo, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

void formatearHoraLocal(char *destino, size_t largo) {
  if (!horaValida()) {
    snprintf(destino, largo, "--:--");
    return;
  }
  time_t t = time(nullptr);
  struct tm local;
  localtime_r(&t, &local);
  strftime(destino, largo, "%H:%M", &local);
}

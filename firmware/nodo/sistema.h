// Utilidades del sistema: watchdog y motivo del último reinicio.
#pragma once

void iniciarWatchdog(int segundos);
void alimentarWatchdog();

// Ej. "POWERON", "TASK_WDT", "BROWNOUT" (se envía en el heartbeat)
const char *motivoReinicio();

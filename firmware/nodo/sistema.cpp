#include "sistema.h"

#include <Arduino.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

void iniciarWatchdog(int segundos) {
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms = (uint32_t)segundos * 1000;
  cfg.idle_core_mask = 0;     // vigila solo la tarea de loop()
  cfg.trigger_panic = true;   // si se cuelga, reinicia
  // El core 3.x normalmente ya inicia el watchdog: se reconfigura; si no, se inicia
  if (esp_task_wdt_reconfigure(&cfg) != ESP_OK) {
    esp_task_wdt_init(&cfg);
  }
  esp_task_wdt_add(NULL);     // tarea actual (loop)
}

void alimentarWatchdog() { esp_task_wdt_reset(); }

const char *motivoReinicio() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:   return "POWERON";
    case ESP_RST_EXT:       return "EXT";
    case ESP_RST_SW:        return "SW";
    case ESP_RST_PANIC:     return "PANIC";
    case ESP_RST_INT_WDT:   return "INT_WDT";
    case ESP_RST_TASK_WDT:  return "TASK_WDT";
    case ESP_RST_WDT:       return "WDT";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:  return "BROWNOUT";
    case ESP_RST_SDIO:      return "SDIO";
    default:                return "UNKNOWN";
  }
}

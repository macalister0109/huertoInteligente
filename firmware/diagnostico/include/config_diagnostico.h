// Pines del sketch de diagnóstico. No contiene credenciales: se versiona.
// Usa los MISMOS valores que pondrás después en firmware/include/config.h.
#pragma once

// Bus I2C (ADS1115, BME280, BH1750)
#define PIN_SDA 21
#define PIN_SCL 22

// Respaldo si el sensor de aire resulta ser un DHT11 / DHT22
#define PIN_DHT 4

// LED RGB
#define PIN_LED_R 25
#define PIN_LED_G 26
#define PIN_LED_B 27
// true si el LED es de ánodo común (la pata larga va a 3.3 V);
// false si es de cátodo común (la pata larga va a GND)
#define LED_ANODO_COMUN false

// Cuántas sondas de suelo hay conectadas al ADS1115 (1 a 4, en A0..A3)
#define NUM_SONDAS 2

// Lecturas promediadas por sonda (reduce el ruido al calibrar)
#define MUESTRAS_SUELO 16

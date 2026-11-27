// Configuración del nodo del Huerto Inteligente.
//
// CÓMO USARLO: copia este archivo como "config.h" en esta misma carpeta
// y cambia los valores. El config.h real NO se sube al repositorio
// (está en .gitignore) porque lleva la clave del WiFi y el token del nodo.
#pragma once

// ---------------------------------------------------------------------------
// WiFi (solo redes de 2,4 GHz y sin portal de inicio de sesión)
// ---------------------------------------------------------------------------
#define WIFI_SSID "nombre_de_tu_wifi"
#define WIFI_PASS "clave_de_tu_wifi"

// ---------------------------------------------------------------------------
// API del equipo central
// ---------------------------------------------------------------------------
// En la casa: la IP de tu PC (mírala con "ipconfig") y el puerto 8080.
// En tu servidor: https://tu-dominio/api/lecturas
#define API_URL "http://192.168.1.50:8080/api/lecturas"

// Token del nodo. Se genera con:  python -m web.nodos crear cama-a
#define API_TOKEN "pega_aqui_el_token"

// Solo para https: certificado raíz (CA) del servidor, en formato PEM.
// Con nullptr la conexión va cifrada pero SIN verificar el servidor
// (sirve para probar, no para dejarlo así). Ver README.
#define API_CA_CERT nullptr

// Identificador de la cama que mide este nodo (igual que en web.nodos)
#define NODO_ID "cama-a"

// ---------------------------------------------------------------------------
// Hora
// ---------------------------------------------------------------------------
#define NTP_SERVER "pool.ntp.org"
// Hora de Chile continental (America/Santiago) en formato POSIX.
// Solo se usa para el reloj de la pantalla: medido_en siempre va en UTC.
#define ZONA_HORARIA "<-04>4<-03>,M9.1.6/24,M4.1.6/24"

// ---------------------------------------------------------------------------
// Lectura
// ---------------------------------------------------------------------------
// Cada cuánto se guarda y envía una lectura (milisegundos). 30000 = 30 s.
#define INTERVALO_MS 30000
// Cada cuánto se refresca la pantalla con datos nuevos (mínimo 2000: DHT11)
#define REFRESCO_PANTALLA_MS 2500

// Rango ideal de humedad del suelo para el aviso de la pantalla y el LED.
// (Las alertas "oficiales" las calcula el equipo central con el rango de la cama.)
#define SUELO_MIN 30
#define SUELO_MAX 70

// ---------------------------------------------------------------------------
// Pines (montaje verificado: NO cambiar sin revisar el cableado)
// ---------------------------------------------------------------------------
#define PIN_DHT 4      // DHT11 (KY-015), pin S
#define PIN_SUELO 34   // YL-69 + LM393, pin AO. Solo entrada, ADC1 (sirve con WiFi)
#define PIN_LED 2      // LED azul integrado del ESP32
#define PIN_SDA 21     // OLED SSD1306
#define PIN_SCL 22
#define DIRECCION_OLED 0x3C   // si la pantalla queda negra, prueba 0x3D

// Alimentación de la sonda de suelo:
//   -1 = VCC fijo a 3.3 V (montaje actual).
//   25 = VCC conectado al pin S del GPIO 25: el nodo la enciende solo
//        durante la lectura para que no se corroa.
#define SUELO_ALIM_GPIO -1
// Espera tras encender la sonda antes de medir (ms)
#define SUELO_ESPERA_ALIM_MS 100

// ---------------------------------------------------------------------------
// Calibración de la sonda de suelo (en milivolts, medir con el modo CAL)
// Más agua = MENOS voltaje.
// ---------------------------------------------------------------------------
#define SUELO_MV_SECO 3160     // sonda al aire (medido)
#define SUELO_MV_MOJADO -1     // sonda en agua. -1 = aún sin calibrar: no se calcula el %

// Muestras que se promedian en cada lectura del suelo
#define MUESTRAS_SUELO 10
// Bajo este voltaje la lectura se considera falla (cable AO suelto o sin VCC)
#define SUELO_MV_MIN_VALIDO 50

// ---------------------------------------------------------------------------
// Sistema
// ---------------------------------------------------------------------------
// Lecturas que caben en la memoria flash si no hay red (720 = 6 h a 30 s)
#define BUFFER_MAX_LECTURAS 720
// Si el programa se cuelga más de este tiempo, el ESP32 se reinicia solo
#define WATCHDOG_S 30

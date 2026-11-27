# Prompt para Claude Code — Huerto Inteligente · Prototipo 1 (montaje real)

Vas a desarrollar el software del PROTOTIPO 1 del proyecto "Huerto Inteligente", a partir de un montaje que YA está armado y probado. La documentación completa del proyecto (problema, historias de usuario HU-01 a HU-05, criterios de calidad CQ y trazabilidad) está en `docs/Documentacion_Proyecto_Huerto_Inteligente.md`: léela antes de empezar.

Antes de escribir código, muéstrame un plan (estructura de carpetas, tópicos MQTT, modelo de datos y etapas) y espera mi aprobación.

## 1. Montaje real (verificado, no lo cambies)

### Placa
- ESP32 con módulo ESP-32D (ESP32-WROOM, 38 pines) y chip USB CP2102, montado sobre una placa base de expansión morada.
- La placa base expone cada GPIO con un trío de pines: S (señal), V (voltaje) y G (tierra). El puente de voltaje está en 3.3V, así que todos los V entregan 3.3 V.
- Programación y energía por el USB-C del módulo ESP32 (no por el USB-C "USB5V" de la placa morada, que solo da energía).
- En mi PC con Windows el puerto es COM5 (driver Silicon Labs CP210x instalado). COM3 y COM4 son Bluetooth: no los uses.

### Sensores conectados
| Sensor | Módulo | Conexión |
| --- | --- | --- |
| Temperatura y humedad del aire | DHT11 en módulo KY-015 (3 pines: S, +, −) | S → GPIO 4 · + → V (3.3 V) · − → G |
| Humedad del suelo | Sonda resistiva YL-69 + módulo comparador LM393 (pines AO, DO, GND, VCC) | AO → GPIO 34 · VCC → V (3.3 V fijo) · GND → G · DO sin conectar |

### Prueba ya realizada (sketch de diagnóstico en Arduino IDE)
- DHT11: responde bien (23 °C, 61 % de humedad del aire).
- Suelo: con la sonda al aire, ~3160 mV medidos con analogReadMilliVolts() (atenuación ADC_11db, promedio de 10 muestras). Más agua = MENOS voltaje.
- Calibración en agua: PENDIENTE (mvMojado). Déjala como parámetro configurable.

### Entorno que funciona
- Arduino IDE 2.3.11, core "esp32 by Espressif Systems" 3.3.12, placa "ESP32 Dev Module", librerías "DHT sensor library" + "Adafruit Unified Sensor" de Adafruit.
- Para compilar y subir desde la terminal, usa arduino-cli con el MISMO core y las MISMAS librerías (instálalo si no está). FQBN: esp32:esp32:esp32, puerto COM5.
- Si el Monitor Serie del IDE está abierto, la subida falla por puerto ocupado: recuérdamelo antes de subir.
- Si la subida se queda en "Connecting...", avísame para mantener apretado el botón Boot.

## 2. Limitaciones del hardware que el software debe considerar
- DHT11: rango de 0 a 50 °C, ±2 °C, resolución 1 °C. NO mide bajo 0 °C. Lee como máximo una vez por segundo (usa 2 s o más). Si marca 0 °C, el aviso debe decir «Temperatura en el límite del sensor (0 °C o menos)».
- Sonda YL-69 resistiva: se corroe si queda alimentada todo el tiempo y su lectura deriva con el uso. Deja una opción de configuración SUELO_ALIM_GPIO (por defecto -1 = VCC fijo). Si después muevo el VCC al pin S del GPIO 25, el firmware debe encenderla solo durante la lectura (~100 ms antes de medir y apagar al terminar).
- GPIO 34 es solo entrada y pertenece al ADC1, que funciona con el WiFi activo. No muevas la señal a pines ADC2.
- El ADC del ESP32 no es lineal: usa siempre analogReadMilliVolts() y promedios.
- No tengo sensor de luz en este prototipo: la variable luz va null (la HU-04 queda para el prototipo 2). Tampoco tengo LED RGB conectado: usa el LED integrado del ESP32 (GPIO 2) como indicador simple: fijo = alguna variable fuera de rango, parpadeo lento = sin conexión con el equipo central, apagado = todo bien.

## 3. Firmware del nodo (firmware/nodo/)
Proyecto compatible con Arduino IDE (sketch .ino + archivos .h/.cpp en la misma carpeta) y compilable con arduino-cli.

- `config.example.h` (el `config.h` real va en .gitignore) con: WIFI_SSID, WIFI_PASS, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, NODO_ID ("cama-a"), INTERVALO_MS (30000), PIN_DHT 4, PIN_SUELO 34, SUELO_ALIM_GPIO -1, SUELO_MV_SECO 3160, SUELO_MV_MOJADO (por calibrar), NTP_SERVER.
- Módulos separados: sensores (una función por sensor, preparada para sumar luz y otros sensores después), red (WiFi + MQTT con reconexión sin bloquear), hora (NTP), buffer y LED de estado.
- Conversión del suelo a %: lineal entre seco y mojado, acotada entre 0 y 100.
- Lectura cada INTERVALO_MS con millis(), sin delay() largos.
- Publicación MQTT (librería PubSubClient o similar) en `huerto/cama/<NODO_ID>/lectura`, QoS 1:
  {"nodo_id":"cama-a","seq":123,"medido_en":"2026-11-27T17:30:00Z","suelo_pct":42,"suelo_mv":2350,"temp":23,"hum_aire":61,"luz":null}
  Un sensor que falla va como null y no bloquea a los demás. `seq` es un contador persistente (Preferences/NVS).
- Hora de medición: NTP. Si aún no hay hora válida, NO publiques con una hora inventada: guarda la lectura hasta sincronizar.
- Buffer en flash (LittleFS) para no perder lecturas si se cae la red (CQ-07: 0 lecturas perdidas en cortes de hasta 1 hora). Al reconectar, reenvía en orden.
- LWT en `huerto/nodo/<NODO_ID>/conexion` (online/offline, retained) y heartbeat cada 60 s con uptime, RSSI y motivo del último reinicio.
- Suscripción a `huerto/cama/<NODO_ID>/estado` (retained) para manejar el LED.
- Modo calibración: si al arrancar se recibe "CAL" por Serial, imprime los mV del suelo cada segundo, para medir seco y mojado sin recompilar.
- Watchdog activado y logs claros por Serial a 115200.

## 4. Equipo central local (central/)
Para el prototipo 1 corre en MI PC con Windows; después se moverá a una Raspberry Pi, así que todo debe ser portable.

- Primero verifica si tengo Docker Desktop. Si lo tengo: docker-compose con mosquitto, mariadb, procesador y web. Si no: Mosquitto para Windows + Python con venv + MariaDB o, como respaldo, SQLite. Pregúntame antes de instalar nada.
- Explícame cómo ver la IP de mi PC para ponerla en MQTT_HOST, y cómo permitir el puerto 1883 en el firewall de Windows.
- Procesador (Python, paho-mqtt):
  - Valida rangos físicos (suelo 0–100, temp 0–50 por ser DHT11, hum_aire 20–95) y marca como inválidas las lecturas imposibles.
  - Deduplica por (nodo, seq).
  - HU-01: la lectura actual es la de mayor `medido_en`, no la última en llegar. Si no hay datos: «Sin lecturas».
  - HU-02: alerta de suelo seco o encharcado según el rango de la cama (por defecto 30–70 %, configurable), en menos de 5 minutos, actualizando la alerta abierta en vez de duplicarla y con 2 puntos de histéresis. Textos: «Cama A seca: 22 % (ideal 30 % a 70 %)» y «Cama A con exceso de agua: 85 %. No riegues hoy».
  - HU-03: helada inmediata bajo el mínimo; calor solo tras más de 30 minutos seguidos sobre el máximo. Resolución con hora de inicio y término.
  - HU-05: estado verde «Todo bien», rojo «Revisar: humedad 22 %», gris si algún sensor lleva más de 2 horas sin datos válidos. La luz NO cuenta para el gris en este prototipo, porque no hay sensor.
  - Publica el estado de cada cama en `huerto/cama/<id>/estado` (retained).
- Tablero web (Flask), en español y con lenguaje simple:
  - Tarjeta por cama con color, mensaje, humedad del suelo, temperatura y hora de la última medición.
  - Actualización en tiempo real (Server-Sent Events).
  - Gráfico de las últimas 24 h (Chart.js servido localmente).
  - Configuración del rango por cama.
- Exportación CSV por cama y fechas.

## 5. Pruebas
- Simulador de nodos por MQTT con estos escenarios:
  - suelo seco y encharcado
  - calor breve (no debe alertar) y calor sostenido
  - sensor que deja de enviar
  - lectura atrasada
  - reenvío de buffer con duplicados
- Tests con pytest de los criterios de aceptación de HU-01, HU-02, HU-03 y HU-05.

## 6. README.md
- Foto-guía en texto del montaje (tabla de conexiones de la sección 1), en lenguaje para alguien que no sabe electrónica.
- Pasos de calibración de la sonda (al aire y en agua) usando el modo CAL.
- Cómo compilar y subir con arduino-cli y con el Arduino IDE.
- Cómo levantar el equipo central en Windows y cómo verificar que llegan mensajes (mosquitto_sub).
- Problemas frecuentes y su solución:
  - el puerto no aparece (driver CP210x / cable solo de carga / USB-C equivocado)
  - "Write timeout" por puerto Bluetooth
  - DHT11 sin respuesta
  - suelo en 0 mV o topado en el máximo

## Reglas de trabajo
- Código, comentarios y nombres de variables en español.
- Etapas, en este orden:
  1. Firmware solo Serial (lectura + calibración), y yo lo pruebo en la placa
  2. WiFi + MQTT + NTP + buffer
  3. Equipo central + simulador + tests
  4. Tablero
  5. Prueba de punta a punta con la placa real
- Al terminar cada etapa, verifícala (compila con arduino-cli, tests en verde) y dame instrucciones claras de qué probar yo en el hardware antes de seguir.
- No subas credenciales al repositorio.
- No cambies pines ni conexiones sin preguntarme: el montaje ya está verificado.

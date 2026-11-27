# Estado del despliegue — Huerto Inteligente, prototipo 1

**Fecha:** 27-11-2026  ·  **Equipo central:** PC con Windows 11 (Docker Desktop 29.9.3)  ·
**Rama:** `main` (cambios **sin commit**)

> Este archivo no contiene claves. Las credenciales están solo en archivos que no se suben al
> repositorio: `central/.env`, `central/mosquitto/config/passwd` y `firmware/nodo/config.h`.

## Resumen

| Parte | Estado |
| --- | --- |
| Base de datos (MariaDB 11.4) | ✅ En marcha, con la migración `001_api_nodos.sql` aplicada |
| API HTTP para el ESP32 | ✅ En marcha y probada con el simulador (7 de 7 pruebas OK) |
| Procesador (alertas y estado) | ✅ En marcha, recibe los avisos de la API |
| Tablero web | ✅ http://localhost:8080 responde |
| Tests automáticos | ✅ 163 de 163 en verde (pytest) |
| Firmware del nodo | ✅ Compila sin advertencias · ⏳ **falta subirlo a la placa** |
| Calibración de la sonda en agua | ⏳ Pendiente (`SUELO_MV_MOJADO = -1`) |
| Red (firewall y perfil privado) | ⏳ Pendiente: lo hace la usuaria como administradora |
| Prueba con la placa real y corte de WiFi | ⏳ Pendiente |
| Servidor en internet (HTTPS) | ⏳ Más adelante (ver README, sección 7) |

## Servicios en Docker (`central/docker-compose.yml`)

| Servicio | Puerto | Para qué |
| --- | --- | --- |
| `web` | `0.0.0.0:8080` | Tablero, configuración y **API** (`POST /api/lecturas`, `GET /api/camas/<nodo>/ultima`) |
| `procesador` | (interno) | Valida lecturas MQTT, calcula alertas y el color de cada cama |
| `mariadb` | `127.0.0.1:3306` | Base de datos (solo accesible desde este PC) |
| `mosquitto` | `0.0.0.0:1883` | Broker MQTT interno (web → procesador) |
| `mariadb_test` | `127.0.0.1:3307` | BD desechable para pytest (perfil `test`, se puede apagar) |

Comandos útiles (desde `central/`):

```bash
docker compose ps                   # ver qué está corriendo
docker compose logs -f web procesador
docker compose down                 # apagar (los datos se conservan)
docker compose up -d                # volver a encender
docker compose --profile test stop mariadb_test   # apagar la BD de tests
```

## Datos registrados

- **Nodo `cama-a`:** creado y activo, con su token guardado como hash SHA-256. El token en texto
  plano está **solo** en `firmware/nodo/config.h` (`API_TOKEN`).
- **Cama A:** creada sin cultivo, así que el tablero muestra «Configura un cultivo para activar las
  alertas». Se configura en http://localhost:8080/configuracion con el `PIN_DOCENTE` del `.env`.
- **Lecturas:** 0. Las del simulador se borraron después de la prueba.

## Red

- **IP del PC:** `192.168.0.139` (adaptador «Ethernet», red «Programacion»).
- **`API_URL` en `config.h`:** `http://192.168.0.139:8080/api/lecturas`.
- ⚠️ La red está marcada como **Pública**. Así Windows bloquea las conexiones que llegan desde el
  ESP32. Falta:
  1. Cambiar la red a **Privada** (Configuración → Red e Internet → Ethernet).
  2. Crear la regla del firewall en PowerShell **como administrador**:

     ```powershell
     New-NetFirewallRule -DisplayName "Huerto API 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
     ```

  3. Comprobarlo desde un celular en la misma red: `http://192.168.0.139:8080`.
- El ESP32 debe conectarse a un WiFi de **2,4 GHz** del mismo router y sin portal de inicio de
  sesión.

## Firmware (`firmware/nodo/`)

- **Entorno:** el arduino-cli 1.6.0 que viene con el Arduino IDE, core esp32 3.3.12, FQBN
  `esp32:esp32:esp32`, puerto COM5.
- **Librerías:** DHT sensor library 1.4.7, Adafruit Unified Sensor 1.1.15, Adafruit SSD1306 2.5.17,
  Adafruit GFX 2.0.0 y ArduinoJson 7.4.3 (instalada hoy).
- **Tamaño:** usa el 86 % de la memoria de programa y el 17 % de la RAM.
- **Variantes compiladas:**
  - la normal (http, VCC fijo, sin calibrar);
  - una con https + CA, sonda en GPIO 25 y calibrada.
- **En `config.h` ya están** `API_URL` y `API_TOKEN`. **Faltan** `WIFI_SSID`, `WIFI_PASS` y
  `SUELO_MV_MOJADO`.

## Próximos pasos (en orden)

1. Completar `WIFI_SSID` y `WIFI_PASS` en `firmware/nodo/config.h`.
2. Cambiar la red a Privada y crear la regla del firewall (sección Red).
3. Cerrar el Monitor Serie y subir el firmware por COM5 (README, sección 4).
4. Calibrar con `CAL` → `SECO` → `MOJADO`, copiar los valores en `config.h` y volver a subir
   (README, sección 5).
5. Verificar que lleguen lecturas: Monitor Serie con `HTTP 201`, la consulta SQL o
   `/api/camas/cama-a/ultima` (README, sección 6).
6. Prueba de corte de WiFi de 5 minutos y la consulta de seq sin huecos (README, sección 6).
7. Configurar el cultivo o el rango de la Cama A en el tablero.
8. Hacer commit de los cambios.
9. Más adelante: servidor con HTTPS y `API_CA_CERT` (README, sección 7).

## Observaciones

- El log de `web` muestra `Control server error: Permission denied: '/home/huerto'` (gunicorn). El
  tablero y la API funcionan igual; queda por revisar.
- La carpeta `firmware/diagnostico/` (PlatformIO) es del hardware anterior: ADS1115, BME280 y LED
  RGB. No se usa en este montaje.
- El nodo envía solo por HTTP. MQTT queda como canal interno entre la web y el procesador, y para
  el simulador antiguo (`tools/simular_nodos.py`).

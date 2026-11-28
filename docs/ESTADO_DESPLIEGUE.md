# Estado del despliegue — Huerto Inteligente, prototipo 1

**Actualizado:** 27-11-2026, 23:40  ·  **Equipo central en uso:** servidor `huerto.mjvirtual.cl`
(VPS Debian)  ·  **Desarrollo:** PC con Windows 11 (Docker Desktop 29.9.3)  ·  **Versión:** `main`,
commit `c7559f1`

> Este archivo no contiene claves. Las credenciales están solo en archivos que no se suben al
> repositorio: `central/.env`, `central/mosquitto/config/passwd` y `firmware/nodo/config.h`.

## Resumen

| Parte | Estado |
| --- | --- |
| Servidor mjvirtual (`huerto.mjvirtual.cl`) | ✅ En marcha con HTTPS, actualizado el 27-11-2026 a `c7559f1` (ver la sección del servidor) |
| Base de datos (MariaDB 11.4) | ✅ En el servidor, con las migraciones 001 a 007 aplicadas |
| API HTTP para el ESP32 | ✅ En marcha; la Cama A recibe lecturas en el servidor |
| Procesador (alertas, estado, agregados, tendencia, clima) | ✅ En marcha en el servidor |
| Página principal, camas y configuración | ✅ Inicio (presentación del proyecto) en https://huerto.mjvirtual.cl · camas en `/tablero` · kiosco en `/tablero?kiosco=1` |
| Clima exterior de referencia (Open-Meteo) | ✅ Responde con `estado: ok` desde el servidor |
| Tendencias y predicción (RF-15) | ✅ Se calculan; alerta preventiva **desactivada** (por defecto) |
| Tests automáticos | ✅ 393 de 393 en verde (pytest, en el PC) |
| Firmware del nodo | ✅ La placa envía lecturas al servidor (la Cama A en https://huerto.mjvirtual.cl, 27-11-2026; seq 896, llegan en unos 3 s) |
| Calibración de la sonda | ⚠️ Calibrada (seco 3160 mV, mojado 2042 mV), pero en la cama marca 1568 mV: menos que el «mojado», así que queda en el tope de 100 %. Recalibrar el «mojado» con la sonda en la tierra de la cama saturada (`CAL` → `MOJADO`) |
| Red (firewall y perfil privado del PC) | ➖ Ya no hace falta con el servidor: el ESP32 solo necesita salir a internet |
| Prueba con la placa real y corte de WiFi | ⏳ Pendiente |
| Evaluación del modelo (CQ-10 a CQ-13) | ⏳ Faltan semanas de lecturas reales: `tools/evaluar_tendencia.py` |
| Rangos por zona | ⏳ Valores de ejemplo: confirmar con fichas INIA/INDAP |

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

## Próximos pasos del equipo de desarrollo (PC, en orden)

> Esta lista es del montaje inicial en el PC. Hoy el equipo central en uso es el servidor; los
> pasos del firmware y la calibración siguen vigentes.

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

## Servidor mjvirtual: en marcha

**Actualización del 27-11-2026 (commit `c7559f1`)**, con el orden de la guía (sección 3 de
[DESPLIEGUE_MJVIRTUAL.md](DESPLIEGUE_MJVIRTUAL.md)):

1. `git pull` y `docker compose build web procesador`.
2. Respaldo antes de migrar: `~/respaldos/huerto-antes-de-migrar-2026-11-27-2333.sql.gz` (18 KB).
   Un primer intento quedó vacío (20 bytes) por correr `docker compose` fuera de `central/`; se
   borró y se repitió.
3. `docker compose up -d web` y `python -m comun.migrar`: se aplicaron 002, 003, 004, 005, 006 y 007.
4. `docker compose up -d procesador`: los 4 servicios quedaron «Up».

**Verificado desde fuera (HTTPS):**
- `/`, `/proyecto`, el logo y `/api/tendencias` respondían 200 (antes de pasar la presentación a `/`);
- `/api/clima/actual` entrega datos de Open-Meteo para La Pintana con `estado: ok`;
- la Cama A tiene tendencia calculada. El 27-11 a las 23:40 decía «Subiendo», +1,1 puntos por hora
  en 6 h: revisar si hubo riego o si es la sonda sin calibrar.

**Por revisar:**
- en los registros del procesador, que aparezcan «Agregados recalculados» y «Clima de referencia
  guardado», y ningún `ERROR`;
- variables opcionales del `.env` del servidor: `PILOTO_CORREO` (formulario de `/proyecto`) y
  `EXPORT_TOKEN` (exportación desde scripts).

### Preparación del servidor (27-11-2026)

- **Ya está en el repo:**
  - el `.env` del servidor se genera con `python3 despliegue/crear_env.py --servidor`;
  - todos los puertos quedan solo en `127.0.0.1` (web 18020, MariaDB 13306, MQTT 11883);
  - la web confía en el `X-Forwarded-For` de nginx (`PROXY_SALTOS=1`) y la cookie de sesión es
    segura;
  - la configuración de nginx con soporte para SSE está en `central/despliegue/`;
  - `firmware/nodo/ca_letsencrypt.h` trae ISRG Root X1 y X2.
- **Verificado:**
  - con la configuración del servidor, el compose publica solo en `127.0.0.1`;
  - el firmware con `https://huerto.mjvirtual.cl` + `CA_LETS_ENCRYPT` compila;
  - la cadena TLS de `asistente.mjvirtual.cl` valida con solo esos dos certificados raíz;
  - pasan 166 tests.
- **Hecho después:** el registro DNS, el HTTPS con certbot y la instalación en el VPS (la Cama A ya
  envía lecturas al servidor).

## Observaciones

- El log de `web` muestra `Control server error: Permission denied: '/home/huerto'` (gunicorn). El
  tablero y la API funcionan igual; queda por revisar.
- La carpeta `firmware/diagnostico/` (PlatformIO) es del hardware anterior: ADS1115, BME280 y LED
  RGB. No se usa en este montaje.
- El nodo envía solo por HTTP. MQTT queda como canal interno entre la web y el procesador, y para
  el simulador antiguo (`tools/simular_nodos.py`).

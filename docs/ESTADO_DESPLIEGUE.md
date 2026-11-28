# Estado del despliegue — Huerto Inteligente, prototipo 1

**Actualizado:** 28-11-2026, 11:20  ·  **Equipo central en uso:** servidor `huerto.mjvirtual.cl`
(VPS Debian)  ·  **Desarrollo:** PC con Windows 11 (Docker Desktop 29.9.3)  ·  **Versión:** `main`,
commit `625d4df` (desplegado en el servidor el 28-11-2026, con la migración 008)

> **Para continuar el lunes 30-11-2026:** ver [NOTA_LUNES_30-11.md](NOTA_LUNES_30-11.md).

> Este archivo no contiene claves. Las credenciales están solo en archivos que no se suben al
> repositorio: `central/.env`, `central/mosquitto/config/passwd` y `firmware/nodo/config.h`.

## Resumen

| Parte | Estado |
| --- | --- |
| Servidor mjvirtual (`huerto.mjvirtual.cl`) | ✅ En marcha con HTTPS, actualizado el 28-11-2026 a `625d4df` (rediseño + calibración en el servidor) |
| Base de datos (MariaDB 11.4) | ✅ En el servidor, con las migraciones 001 a 008 aplicadas (la 008, el 28-11-2026) |
| API HTTP para el ESP32 | ✅ En marcha; la Cama A recibe lecturas en el servidor (28-11-2026 11:16, seq 2272) |
| Procesador (alertas, estado, agregados, tendencia, clima) | ✅ En marcha en el servidor |
| Página principal, camas y configuración | ✅ Inicio (presentación del proyecto) en https://huerto.mjvirtual.cl · camas en `/tablero` · kiosco en `/tablero?kiosco=1` |
| Clima exterior de referencia (Open-Meteo) | ✅ Responde con `estado: ok` desde el servidor |
| Tendencias y predicción (RF-15) | ✅ Se calcula de nuevo desde la calibración en el servidor: la Cama A muestra «Subiendo, +0,4 pts/h, sin tendencia clara (no se está secando)», R² 0,6. Alerta preventiva **desactivada** (por defecto) |
| Tests automáticos | ✅ 448 de 448 en verde (pytest, en el PC, 28-11-2026) |
| Firmware del nodo | ✅ La placa envía lecturas al servidor (la Cama A en https://huerto.mjvirtual.cl; del 27-11 23:40 al 28-11 10:43 pasó de seq 896 a 2206, unas 1310 de 1326 esperadas a 30 s; llegan en unos 3 s) |
| Calibración de la sonda | ⚠️ **Provisional, en el servidor:** seco 3160 mV, mojado 980 mV (el mínimo registrado, 27-11 17:42), con el historial recalculado. 1422 mV → 79,7 %. **Lunes 30-11-2026:** con la tierra saturada, «Usar la lectura actual como mojado» en `/configuracion`. La placa (OLED y LED) sigue con `config.h` (mojado 2042 mV) y muestra 100 % |
| Red (firewall y perfil privado del PC) | ➖ Ya no hace falta con el servidor: el ESP32 solo necesita salir a internet |
| Formulario de contacto de la portada | ⏳ Antes solo abría el programa de correo del visitante (con Gmail en el navegador no pasaba nada). Desde el 28-11-2026 el **servidor envía el correo** a `macarena@mjamett.cl` por SMTP (no guarda los datos). Falta: crear la cuenta SMTP en el hosting, poner `SMTP_*` en el `.env` del servidor y desplegar (`git pull` + `docker compose up -d --build web`, sin migraciones) |
| Prueba con la placa real y corte de WiFi | ⏳ Pendiente |
| Evaluación del modelo (CQ-10 a CQ-13) | ⏳ Faltan semanas de lecturas reales: `tools/evaluar_tendencia.py` |
| Rangos por zona | ⏳ Valores de ejemplo: confirmar con fichas INIA/INDAP |

## Servidor mjvirtual: en marcha

**Actualización del 28-11-2026 (commit `625d4df`): calibración de la sonda en el servidor.**
Desplegada con el orden de la guía (migración 008 antes del procesador). En `/configuracion` se
guardó la calibración provisional de la Cama A (seco 3160, mojado 980 mV) y se recalculó el
historial.

**Verificado desde fuera (11:16):**
- `/api/camas/cama-a/ultima`: seq 2272, 1422 mV → `suelo_pct` 79,7 % (antes, 100 %);
- en el CSV de la Cama A solo queda 1 lectura en 100 % (la de 978 mV) y 38 en 0 % (la sonda al
  aire antes de enterrarla, 27-11 de 17:18 a 17:40);
- `/api/tendencias`: «Subiendo», +0,4 pts/h;
- la ficha `/cama/1` muestra la curva entre 67 % y 80 %.

**Observado en la ficha:**
- la instalación del 27-11 en la tarde (de 0 % a 100 %) aparece como «Riego detectado», pero no
  fue un riego;
- la humedad sube lento durante la noche y la mañana (de 1700 a 1422 mV). En esta sonda,
  **menos mV = más húmedo**: ¿rocío, agua que se reparte en la tierra o deriva de la sonda?

**Revisión del 28-11-2026, 10:45 (antes de desplegar la calibración):**
- `/`, `/tablero`, `/tablero?kiosco=1`, `/api/clima/actual`, `/api/tendencias` y
  `/api/camas/cama-a/ultima` responden 200; `/proyecto` responde 301 hacia `/`. El rediseño
  (`07eee89`) ya está en el servidor.
- Última lectura de la Cama A: 10:43 (hora de Chile), seq 2206, suelo 1458 mV → 100 %, aire
  24,4 °C y 61 %.
- Clima: Open-Meteo con `estado: ok` (24,7 °C, ET0 de hoy 0,74 mm).
- Tendencia de la Cama A: «Sin datos suficientes», porque la humedad está fija en 100 %. Se
  resuelve con la recalibración del lunes.
- Falta `PILOTO_CORREO` en el `.env` del servidor (correo elegido: `macarena@mjamett.cl`). Después
  de agregarlo: `docker compose up -d web` (desde `central/`).
- No se revisaron los registros del procesador (requiere entrar al VPS).


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

## Servicios en el servidor (`central/docker-compose.yml`)

Todos los puertos quedan solo en `127.0.0.1` del VPS; desde fuera se entra por nginx con HTTPS
(detalle en [DESPLIEGUE_MJVIRTUAL.md](DESPLIEGUE_MJVIRTUAL.md)).

| Servicio | Puerto en el VPS | Para qué |
| --- | --- | --- |
| `web` | `127.0.0.1:18020` (nginx → https://huerto.mjvirtual.cl) | Sitio, tablero, configuración y **API** (`POST /api/lecturas`, `GET /api/camas/<nodo>/ultima`) |
| `procesador` | (interno) | Valida lecturas MQTT, calcula alertas, estado, agregados, tendencia y clima |
| `mariadb` | `127.0.0.1:13306` | Base de datos |
| `mosquitto` | `127.0.0.1:11883` | Broker MQTT interno (web → procesador) |

Comandos útiles (en el VPS, desde `~/huertoInteligente/central`):

```bash
docker compose ps                   # ver qué está corriendo
docker compose logs -f web procesador
git pull && docker compose up -d --build web   # actualizar (si hay migraciones: ver la guía, sección 3)
```

## Datos registrados

- **Nodo `cama-a`:** creado y activo, con su token guardado como hash SHA-256. El token en texto
  plano está **solo** en `firmware/nodo/config.h` (`API_TOKEN`).
- **Cama A:** creada sin cultivo, así que el tablero muestra «Configura un cultivo para activar las
  alertas». Se configura en https://huerto.mjvirtual.cl/configuracion/ con el `PIN_DOCENTE` del `.env` del
  servidor.
- **Lecturas:** las del simulador se borraron después de la prueba en el PC. En el servidor, la
  Cama A envía lecturas reales desde el 27-11-2026 (seq 2206 el 28-11 a las 10:43).

## Observaciones

- El log de `web` muestra `Control server error: Permission denied: '/home/huerto'` (gunicorn). El
  tablero y la API funcionan igual; queda por revisar.
- La carpeta `firmware/diagnostico/` (PlatformIO) es del hardware anterior: ADS1115, BME280 y LED
  RGB. No se usa en este montaje.
- El nodo envía solo por HTTP. MQTT queda como canal interno entre la web y el procesador, y para
  el simulador antiguo (`tools/simular_nodos.py`).

## Historial: montaje inicial en el PC (noviembre 2026)

> Estas secciones describen el primer montaje en el PC con Docker Desktop, antes del servidor. Se
> dejan como referencia; ya **no** reflejan el estado actual. Hoy el ESP32 envía por HTTPS a
> `huerto.mjvirtual.cl`, ya tiene WiFi configurado y la sonda está calibrada (falta corregir el
> «mojado», ver el resumen).

### Servicios en Docker en el PC (`central/docker-compose.yml`)

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

### Red

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

### Firmware (`firmware/nodo/`)

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

### Próximos pasos del equipo de desarrollo (PC, en orden)

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

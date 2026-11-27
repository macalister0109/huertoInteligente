# Huerto Inteligente

Un ESP32 mide la temperatura y la humedad del aire y la humedad del suelo de una
cama del huerto. Muestra los datos en una pantallita OLED y los envía a un equipo
central, que los guarda, avisa si algo anda mal y los muestra en un tablero web.

```
ESP32 ──WiFi──> HTTP POST con JSON ──> API Flask (web) ──> base de datos MariaDB
                                            │
                                            └─ aviso ─> procesador (alertas y color de cada cama)
```

- El ESP32 **nunca** se conecta directo a la base de datos.
- La pantalla OLED funciona siempre, haya o no red.
- Si se corta el WiFi, las lecturas quedan guardadas en la memoria del ESP32 y se envían en
  orden cuando vuelve la conexión.

| Carpeta | Qué hay |
| --- | --- |
| `firmware/nodo/` | Programa del ESP32 (Arduino IDE o arduino-cli) |
| `central/` | Equipo central: base de datos, API, procesador y tablero (Docker) |
| `tools/` | Simuladores para probar sin la placa |
| `docs/` | Instrucciones del proyecto |

---

## 1. El montaje (no cambiar los cables)

La placa ESP32 va montada sobre una placa base morada. Cada pin de la placa base tiene tres
patitas en fila: **S** (señal), **V** (3,3 V) y **G** (tierra). El puente de voltaje está en 3.3V.

| Qué mide | Módulo | Cable del módulo | Va a la placa base |
| --- | --- | --- | --- |
| Temperatura y humedad del aire | DHT11 (KY-015, 3 patitas) | S | S del **GPIO 4** |
| | | + | V del GPIO 4 |
| | | − | G del GPIO 4 |
| Humedad del suelo | Sonda YL-69 + módulo LM393 (4 patitas) | AO | S del **GPIO 34** |
| | | VCC | V (3,3 V) |
| | | GND | G |
| | | DO | sin conectar |
| Pantalla | OLED SSD1306 128×64 | SDA | **GPIO 21** |
| | | SCL | **GPIO 22** |
| | | VCC / GND | V / G |

- **USB:** usa el USB-C **del módulo ESP32** para programar. El USB-C «USB5V» de la placa morada
  solo da energía.
- **Puerto:** en este PC la placa aparece como **COM5**. COM3 y COM4 son Bluetooth: no los uses.
- **LED azul integrado (GPIO 2):**
  - parpadeo lento = sin conexión con el equipo central;
  - fijo = suelo fuera del rango ideal;
  - apagado = todo bien.

Límites de los sensores:

- **DHT11:** mide de 0 a 50 °C (±2 °C) y no mide bajo cero. Si marca 0 °C, puede estar
  más frío.
- **Sonda YL-69:** es resistiva y se corroe con el uso. Si después mueves su VCC al pin S del
  GPIO 25 y pones `SUELO_ALIM_GPIO 25` en `config.h`, el ESP32 la enciende solo mientras mide.

---

## 2. Equipo central en Windows

Necesitas **Docker Desktop** abierto (la ballena en la barra de tareas). En una terminal de Git Bash:

```bash
cd central
cp .env.example .env              # y cambia TODOS los "cambia_esto"
./mosquitto/usuarios.sh servicios # usuarios internos de MQTT
docker compose up -d --build
docker compose exec web python -m comun.migrar          # pone la base al día
docker compose exec web python -m web.nodos crear cama-a
```

El último comando muestra **una sola vez** una línea como esta:

```
#define API_TOKEN "xY3...."
```

Cópiala en `firmware/nodo/config.h`. El token no se guarda en ningún lado. Si lo pierdes, genera
uno nuevo con `python -m web.nodos crear cama-a --regenerar`.

- **Tablero:** http://localhost:8080
- **Configuración de las camas:** http://localhost:8080/configuracion (pide el `PIN_DOCENTE` del `.env`)

---

## 3. La red, paso a paso

### 3.1 La IP de tu PC

1. Abre **PowerShell** y escribe `ipconfig`.
2. Busca el adaptador con el que tu PC está conectado a la red de la casa («Ethernet» si va por
   cable, «Wi-Fi» si va inalámbrico). Ignora los que dicen «vEthernet», «VirtualBox» o «WSL».
3. Copia su «Dirección IPv4», por ejemplo `192.168.0.139`.
4. En `firmware/nodo/config.h`:

   ```c
   #define API_URL "http://192.168.0.139:8080/api/lecturas"
   ```

Si la IP del PC cambia (pasa al reiniciar el router), hay que cambiarla aquí y volver a subir el
programa. Para evitarlo, en el router puedes «reservar» la IP del PC (DHCP estático).

### 3.2 Abrir el puerto 8080 en el Firewall, solo en la red privada

1. **Marca tu red como privada.** Ve a *Configuración → Red e Internet → Ethernet* (o *Wi-Fi*)
   → tu red, y en «Tipo de perfil de red» elige **Privada**. Una red «Pública» bloquea las
   conexiones que vienen de otros equipos, y así debe quedar en redes de cafés o del colegio.
2. Abre PowerShell **como administrador** (clic derecho → «Ejecutar como administrador») y
   escribe:

   ```powershell
   New-NetFirewallRule -DisplayName "Huerto API 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Private
   ```

3. Para comprobarlo, desde un celular conectado al mismo WiFi abre `http://192.168.0.139:8080`.
   Debe aparecer el tablero.

Para deshacerlo: `Remove-NetFirewallRule -DisplayName "Huerto API 8080"`.

### 3.3 Dos cosas importantes

- **El ESP32 solo se conecta a WiFi de 2,4 GHz.** Muchos routers tienen dos redes, por ejemplo
  «MiCasa» y «MiCasa-5G»: usa la que no dice 5G. El PC y el ESP32 deben estar en la **misma red**.
  El PC puede ir por cable al mismo router.
- **Las redes con portal de inicio de sesión no sirven.** Son las que te muestran una página para
  aceptar condiciones o poner usuario y clave, típicas en colegios, hoteles y cafés. El ESP32 no
  puede completar ese paso. En ese caso usa la zona WiFi (hotspot) de un celular a 2,4 GHz.

---

## 4. Subir el programa al ESP32

1. Copia `firmware/nodo/config.example.h` como `firmware/nodo/config.h` y completa:
   - `WIFI_SSID` y `WIFI_PASS`;
   - `API_URL`;
   - `API_TOKEN`;
   - `SUELO_MV_MOJADO` (si no lo has medido, ve la sección 5).
2. **Cierra el Monitor Serie del Arduino IDE.** Si está abierto, la subida falla porque el puerto
   está ocupado.

**Con el Arduino IDE:** abre `firmware/nodo/nodo.ino`, elige la placa **ESP32 Dev Module** y el
puerto **COM5**, y presiona *Subir*.

**Con la terminal (PowerShell):** usa el arduino-cli que viene dentro del Arduino IDE, con el mismo
core y las mismas librerías:

```powershell
$cli = "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
& $cli compile --fqbn esp32:esp32:esp32 firmware\nodo
& $cli upload  --fqbn esp32:esp32:esp32 -p COM5 firmware\nodo
```

Si se queda en `Connecting.....`, mantén apretado el botón **Boot** del ESP32 hasta que empiece a
escribir.

Librerías (Herramientas → Administrar bibliotecas): «DHT sensor library», «Adafruit Unified Sensor»,
«Adafruit SSD1306», «Adafruit GFX» y «ArduinoJson».

### Lo que debes ver en el Monitor Serie (115200 baudios, «Nueva línea»)

```
[WiFi] Conectado. IP 192.168.0.57, señal -58 dBm
[Lectura] {"nodo_id":"cama-a","seq":12,"medido_en":"2026-11-27T18:00:00Z","temp":23,...}
[API] seq=12 -> HTTP 201 guardada
```

Comandos que puedes escribir en el Monitor Serie:

- `ESTADO`: muestra la red, el buffer y el último código HTTP.
- `LEER`: mide en ese momento.
- `CAL`: entra al modo calibración.

En la línea de arriba de la OLED aparece el estado de la red:

- `WiFi OK`
- `Sin WiFi`
- `Error API`
- `Pend: N`: cantidad de lecturas esperando para enviarse.

---

## 5. Calibrar la sonda de suelo (modo CAL)

La sonda entrega milivolts (mV): **más agua = menos mV**. Hay que medir dos puntos.

1. Abre el Monitor Serie y escribe `CAL` + Enter. Los mV aparecen cada segundo, también en la
   OLED.
2. Con la sonda **al aire**, limpia y seca, espera que el número se estabilice y escribe `SECO`.
3. Mete la sonda en un **vaso con agua** hasta la línea, sin mojar el módulo LM393, y escribe
   `MOJADO`.
4. Copia en `config.h` las dos líneas `#define SUELO_MV_SECO ...` y `#define SUELO_MV_MOJADO ...`
   que aparecen.
5. Escribe `FIN` y vuelve a subir el programa.

Mientras falte `SUELO_MV_MOJADO`, la OLED muestra `CAL` junto al suelo y se envían solo los mV.

---

## 6. Comprobar que las lecturas llegan

### Sin la placa: simulador del ESP32

```bash
python tools/simular_esp32_http.py --token EL_TOKEN_DEL_NODO
```

Prueba una lectura normal, un duplicado, una lectura atrasada, un valor imposible, un token malo y
un JSON roto. Cada prueba debe decir `OK`. **Ojo:** las lecturas de prueba quedan en la base, así
que úsalo antes de dejar el huerto funcionando.

### En la base de datos

```bash
cd central
docker compose exec mariadb sh -c 'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"'
```

Las últimas 10 lecturas de la cama A:

```sql
SELECT l.seq, l.medido_en, l.recibido_en, l.temp, l.hum_aire,
       l.suelo_prom AS suelo_pct, l.suelo_mv, l.valida, l.motivo_invalida
  FROM lecturas l JOIN camas c ON c.id = l.cama_id
 WHERE c.nodo_id = 'cama-a'
 ORDER BY l.medido_en DESC
 LIMIT 10;
```

Las horas están en UTC (en Chile son 3 horas menos en verano y 4 en invierno). `medido_en` es
cuándo midió el ESP32 y `recibido_en` es cuándo llegó.

Con la API, sin entrar a la base: http://localhost:8080/api/camas/cama-a/ultima

### Prueba de corte de WiFi (5 minutos)

1. Con el nodo enviando bien, apaga el WiFi del router (o del celular) durante 5 minutos. La OLED
   debe mostrar `Sin WiFi Pend:1`, `Pend:2`, ... y la pantalla debe seguir actualizándose.
2. Vuelve a encender el WiFi. En el Monitor Serie deben aparecer varias líneas `HTTP 201`
   seguidas, y `Pend` vuelve a desaparecer.
3. En la base, comprueba que no falte ni se repita ningún seq:

```sql
SELECT COUNT(*) AS lecturas, COUNT(DISTINCT seq) AS distintas, MIN(seq), MAX(seq),
       MAX(seq) - MIN(seq) + 1 AS esperadas
  FROM lecturas l JOIN camas c ON c.id = l.cama_id
 WHERE c.nodo_id = 'cama-a' AND l.medido_en >= UTC_TIMESTAMP() - INTERVAL 30 MINUTE;
```

`lecturas`, `distintas` y `esperadas` deben ser iguales.

---

## 7. Llevarlo a un servidor en internet

La API funciona igual en un servidor. Pon el equipo central detrás de un proxy con **HTTPS** (Caddy
o nginx con Let's Encrypt). Por HTTP el token viaja sin cifrar, y eso solo es aceptable dentro de
la red de la casa.

En `config.h`:

```c
#define API_URL "https://tu-dominio/api/lecturas"
#define API_CA_CERT \
  "-----BEGIN CERTIFICATE-----\n" \
  "MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n" \
  "...una línea así por cada línea del certificado...\n" \
  "-----END CERTIFICATE-----\n"
```

`API_CA_CERT` es el certificado **raíz** de quien firmó el certificado de tu servidor. Para Let's
Encrypt es «ISRG Root X1» (https://letsencrypt.org/certs/isrgrootx1.pem). Con `nullptr` la
conexión va cifrada pero el ESP32 no comprueba que el servidor sea el tuyo. Sirve para probar, no
para dejarlo así.

---

## 8. Problemas frecuentes

| Problema | Solución |
| --- | --- |
| **El puerto COM no aparece** | Instala el driver «Silicon Labs CP210x». Prueba otro cable: muchos solo cargan y no transmiten datos. Usa el USB-C del módulo ESP32, no el «USB5V» de la placa morada. |
| **«Write timeout» o «Could not open port»** | Elegiste COM3 o COM4 (Bluetooth): usa COM5. O el Monitor Serie está abierto: ciérralo. |
| **Se queda en «Connecting.....»** | Mantén apretado **Boot** durante la subida. |
| **DHT11 «SIN DATO» / OLED muestra `--`** | Revisa que S esté en el GPIO 4 y que + y − no estén invertidos. Espera 2 s después de encender. |
| **Suelo en 0 mV (OLED: `FALLA`)** | El cable AO está suelto o la sonda no tiene VCC. Revisa los cables entre la sonda y el LM393. |
| **Suelo topado en ~3 100 mV aunque esté mojado** | La sonda está desconectada del LM393 o muy corroída. Límpiala o cámbiala, y vuelve a calibrar. |
| **OLED negra** | Revisa SDA → 21, SCL → 22, VCC y GND. Prueba `DIRECCION_OLED 0x3D`. |
| **`Sin WiFi` todo el rato** | La red es de 5 GHz, la clave está mal escrita o la red tiene portal de inicio de sesión (sección 3.3). |
| **`Error API` con `HTTP 401`** | El `API_TOKEN` no coincide. Genera uno nuevo con `web.nodos crear cama-a --regenerar`. |
| **`Error API` con «connection refused» o «timeout»** | Revisa `API_URL` (IP y puerto 8080), que Docker esté corriendo, que la red esté como **Privada** y la regla del firewall (sección 3.2). |
| **`Pend` crece y nunca baja** | El ESP32 aún no tiene hora (NTP): la red no deja salir a internet. Las lecturas esperan y no se pierden. |

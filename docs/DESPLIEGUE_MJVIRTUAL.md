# Desplegar el Huerto Inteligente en el servidor mjvirtual

Usa el mismo esquema que `asistente.mjvirtual.cl`:

- **Docker** escucha solo en `127.0.0.1`.
- **nginx** del host recibe las visitas y las pasa a Docker.
- **certbot** pone el HTTPS.
- **El código** se clona en `~`, y el `.env` queda fuera de git.

```
ESP32 ──HTTPS──> huerto.mjvirtual.cl (nginx + certbot) ──> 127.0.0.1:18020 (web, Docker)
                                                              ├─ mariadb   127.0.0.1:13306
                                                              ├─ mosquitto 127.0.0.1:11883
                                                              └─ procesador
```

| Dato | Valor |
| --- | --- |
| Dominio | `huerto.mjvirtual.cl` |
| IP del VPS | `216.185.51.164` (la misma de `asistente.mjvirtual.cl`) |
| Carpeta | `~/huertoInteligente` |
| Configuración y secretos | `~/huertoInteligente/central/.env` (fuera de git, permisos 600) |
| nginx | `/etc/nginx/sites-available/huerto.mjvirtual.cl` |
| Puertos en el host | 18020 (web), 13306 (MariaDB), 11883 (MQTT). Todos solo en `127.0.0.1` |

> ⚠️ **El VPS anda justo de memoria:** 3,8 GB, y el 26-11-2026 la swap se llenó. Este proyecto
> suma unos 300 MB: MariaDB, web, procesador y Mosquitto. Antes de empezar, revisa
> `free -h`. Si queda menos de 500 MB disponibles, libera memoria primero.

---

## 0. Antes, desde tu PC

1. **Sube los cambios a GitHub** (commit + push de la rama `main`). El servidor los descarga con
   `git clone` / `git pull`.
2. **Crea el registro DNS** en el panel de tu dominio:

   | Tipo | Nombre | Valor |
   | --- | --- | --- |
   | A | `huerto` | `216.185.51.164` |

3. Espera a que exista. Desde PowerShell:

   ```powershell
   nslookup huerto.mjvirtual.cl 8.8.8.8
   ```

   Debe responder `216.185.51.164`. Sin esto, certbot no puede crear el certificado.

---

## 1. En el servidor (por SSH)

### 1.1 Revisar que los puertos estén libres

```bash
free -h
sudo ss -ltnp | grep -E ':(18020|13306|11883)\b' || echo "Puertos libres"
```

Si alguno está ocupado, después cámbialo en el `.env` (`WEB_PUERTO`, `DB_PUERTO_LOCAL`,
`MQTT_PUERTO_LOCAL`). Si cambias `WEB_PUERTO`, cámbialo también en el archivo de nginx.

### 1.2 Descargar el código y crear el `.env`

```bash
cd ~
git clone https://github.com/macalister0109/huertoInteligente.git
cd huertoInteligente/central
python3 despliegue/crear_env.py --servidor
```

El script genera claves aleatorias y deja los valores del servidor:
- `WEB_ESCUCHA=127.0.0.1`
- `WEB_PUERTO=18020`
- `PROXY_SALTOS=1`
- `COOKIE_SEGURA=true`

Al final muestra el **PIN del docente**: anótalo.

### 1.3 Levantar los servicios

```bash
./mosquitto/usuarios.sh servicios
docker compose up -d --build
docker compose ps                                  # los 4 servicios "Up" (mariadb "healthy")
docker compose exec web python -m comun.migrar     # "La BD ya está al día."
curl -sI http://127.0.0.1:18020/ | head -1         # HTTP/1.1 200 OK
```

### 1.4 nginx y HTTPS

```bash
sudo cp despliegue/nginx-huerto.mjvirtual.cl.conf /etc/nginx/sites-available/huerto.mjvirtual.cl
sudo ln -s /etc/nginx/sites-available/huerto.mjvirtual.cl /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d huerto.mjvirtual.cl        # acepta redirigir HTTP -> HTTPS
```

Abre https://huerto.mjvirtual.cl: debe aparecer el tablero, con candado.

**Opcional: tablero con usuario y clave.** Así solo tú lo ves; la API del ESP32 sigue
funcionando con su token. Está explicado al final de `despliegue/nginx-huerto.mjvirtual.cl.conf`.
Sin esto, cualquiera con el enlace ve los datos del huerto (no puede cambiar nada sin el PIN).

### 1.5 Crear el nodo y su token

```bash
docker compose exec web python -m web.nodos crear cama-a
```

Copia la línea `#define API_TOKEN "..."` que aparece. **Se muestra una sola vez.** Para no dejar el
token en el historial de la terminal: `history -d $(history 1 | awk '{print $1}')`.

> Es un token **distinto** del de tu PC: cada equipo central tiene su propia base de datos.

### 1.6 Probar la API sin la placa

```bash
cd ~/huertoInteligente
python3 tools/simular_esp32_http.py --url https://huerto.mjvirtual.cl --token EL_TOKEN
```

Las 7 pruebas deben decir `OK`. Después borra las lecturas de prueba:

```bash
cd central
docker compose exec mariadb sh -c 'mariadb -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" -e "DELETE FROM lecturas; DELETE FROM incidencias;"'
```

---

## 2. En el ESP32 (`firmware/nodo/config.h` de tu PC)

Cambia estas tres líneas:

```c
#define API_URL "https://huerto.mjvirtual.cl/api/lecturas"
#define API_TOKEN "EL_TOKEN_DEL_SERVIDOR"
#define API_CA_CERT CA_LETS_ENCRYPT
```

- **`CA_LETS_ENCRYPT`** está en `firmware/nodo/ca_letsencrypt.h`. Son los certificados raíz
  ISRG Root X1 y X2: públicos, no secretos. Con ellos el ESP32 comprueba que habla con tu
  servidor antes de mandarle el token. El 27-11-2026 se verificó que la cadena de
  `asistente.mjvirtual.cl` (YE2 → Root YE → ISRG Root X2 → ISRG Root X1) valida con esos dos
  certificados.
- **El WiFi** ahora solo necesita salir a internet. Ya no hace falta que el PC esté en la misma
  red ni abrir el firewall de Windows. Sigue valiendo que sea de 2,4 GHz y sin portal de inicio
  de sesión.

Cierra el Monitor Serie, sube el programa y mira el Monitor Serie. Debe aparecer:

```
[WiFi] Conectado. IP ...
[API] seq=1 -> HTTP 201 guardada
```

Si aparece `HTTP -1` o un error de conexión al principio, espera unos segundos. El ESP32 necesita
la hora de internet (NTP) para validar el certificado, y las lecturas esperan en el buffer
mientras tanto.

Comprueba en https://huerto.mjvirtual.cl/api/camas/cama-a/ultima que llegó la lectura.

---

## 3. Mantenimiento

**Actualizar después de un cambio en GitHub.** Hay que migrar la BD **antes** de que el procesador
arranque con el código nuevo: si el código nuevo usa tablas que aún no existen, el procesador falla
hasta que se migra. Mientras tanto, el ESP32 guarda las lecturas en su buffer y las reenvía
después, así que no se pierden.

```bash
cd ~/huertoInteligente && git pull
cd central
free -h                                              # revisar memoria antes de compilar
docker compose build web procesador
docker compose exec mariadb sh -c 'mariadb-dump -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
  | gzip > ~/respaldos/huerto-antes-de-migrar-$(date +%F-%H%M).sql.gz   # respaldo antes de migrar
docker compose up -d web                             # la web trae las migraciones (db/migraciones)
docker compose exec web python -m comun.migrar       # aplica las que falten
docker compose up -d procesador                      # recién ahora el procesador nuevo
docker compose ps
docker compose logs --tail 30 procesador             # sin errores; «Procesador listo.»
```

Si una migración da problemas, se revierte con
`docker compose exec web python -m comun.migrar --revertir NNN_nombre.sql`. Revertir **nunca**
toca las lecturas.

**Variables opcionales del `.env`** (sin ellas, todo funciona con los valores por defecto):

| Variable | Para qué |
| --- | --- |
| `PILOTO_CORREO` | Correo que recibe el formulario «Sumarse al piloto» de `/proyecto`. Sin ella, la página avisa que falta. |
| `EXPORT_TOKEN` | Token (16 caracteres o más) para exportar datos desde scripts o notebooks. Sin él, solo se exporta con el PIN. |
| `CLIMA_LAT`, `CLIMA_LON` | Ubicación del clima de referencia (por defecto, La Pintana). También se cambia en `/configuracion`. |
| `DMC_USER_EMAIL`, `DMC_API_TOKEN`, `OPENWEATHER_API_KEY` | Solo si se usa la DMC u OpenWeatherMap en vez de Open-Meteo. |

Después de editar el `.env`: `docker compose up -d` (recrea los servicios con las variables nuevas).

**Página pública del proyecto con el tablero protegido.** Si activas el usuario y la clave de nginx
(bloque opcional de `despliegue/nginx-huerto.mjvirtual.cl.conf`) y quieres que `/proyecto` siga
abierta para la comunidad, exime también esa página y sus archivos:

```nginx
location = /proyecto { auth_basic off; proxy_pass http://127.0.0.1:18020; proxy_set_header Host $host;
                       proxy_set_header X-Forwarded-For $remote_addr; proxy_set_header X-Forwarded-Proto $scheme; }
location /static/    { auth_basic off; proxy_pass http://127.0.0.1:18020; proxy_set_header Host $host; }
```

**Ver qué pasa:**

```bash
cd ~/huertoInteligente/central
docker compose ps
docker compose logs -f --tail 50 web procesador
docker stats --no-stream
```

**Respaldo diario de la base.** Sigue el mismo esquema de `~/respaldos` que asistonto. Con
`crontab -e`, agrega una línea (todo en una línea):

```cron
30 3 * * * cd ~/huertoInteligente/central && docker compose exec -T mariadb sh -c 'mariadb-dump -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' | gzip > ~/respaldos/huerto-$(date +\%F).sql.gz && find ~/respaldos -name 'huerto-*.sql.gz' -mtime +14 -delete
```

**Apagar todo** (los datos se conservan en los volúmenes de Docker):

```bash
cd ~/huertoInteligente/central && docker compose down
```

---

## 4. Problemas frecuentes

| Síntoma | Causa y solución |
| --- | --- |
| certbot: «DNS problem: NXDOMAIN» | Falta el registro A `huerto` o aún no se propaga. Revisa con `nslookup huerto.mjvirtual.cl 8.8.8.8`. |
| `502 Bad Gateway` | La app no está corriendo o el puerto no coincide. Revisa `docker compose ps` y que `WEB_PUERTO` del `.env` sea el mismo del `proxy_pass`. |
| El tablero carga pero no se actualiza solo | nginx está acumulando los eventos en tiempo real. Revisa que exista el bloque `location = /api/eventos` con `proxy_buffering off`. |
| ESP32: `HTTP 401` | El token es el de tu PC, no el del servidor. Crea o regenera el del servidor (paso 1.5). |
| ESP32: falla el TLS («connection refused» / `-1`) siempre | Revisa que `API_CA_CERT` sea `CA_LETS_ENCRYPT` y que el ESP32 tenga hora (`ESTADO` en el Monitor Serie). Si Let's Encrypt deja de enviar la cadena hacia ISRG Root X2, habrá que agregar su raíz nueva («Root YE») a `ca_letsencrypt.h`. |
| No puedo entrar a `/configuracion` después de equivocarme con el PIN | Es el bloqueo por IP: 5 intentos y 5 minutos de espera. Con `PROXY_SALTOS=1` bloquea solo tu IP, no a todos. |
| El VPS se pone lento / 504 en n8n | Falta memoria. Revisa `free -h` y `docker stats --no-stream`. El huerto se puede apagar con `docker compose down` sin perder datos. |

-- =============================================================
-- Huerto Inteligente — Iteración 1 — esquema de la BD local (MariaDB)
--
-- * Todas las fechas se guardan en UTC. El "día" de luz se calcula
--   en hora de Chile (America/Santiago) en el procesador.
-- * Las columnas `sincronizado` quedan listas para la iteración 2
--   (sincronización con la nube). En esta iteración siempre valen 0.
-- * Las fechas con (3) guardan milisegundos: se usan para medir
--   latencias (CQ-02 y CQ-03).
-- =============================================================

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- -------------------------------------------------------------
-- Cultivos: rangos ideales de EJEMPLO por especie
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cultivos (
    id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
    nombre         VARCHAR(60)  NOT NULL,
    humedad_min    DECIMAL(5,2) NULL COMMENT '% humedad del suelo',
    humedad_max    DECIMAL(5,2) NULL,
    temp_min       DECIMAL(5,2) NULL COMMENT '°C',
    temp_max       DECIMAL(5,2) NULL,
    horas_luz_min  DECIMAL(4,2) NULL COMMENT 'horas de luz directa por día',
    tolera_sombra  TINYINT(1)   NOT NULL DEFAULT 0
                   COMMENT '1 = se sugiere cuando una cama recibe poca luz',
    por_confirmar  TINYINT(1)   NOT NULL DEFAULT 1
                   COMMENT '1 = valor de ejemplo, confirmar con INIA/INDAP y la zona',
    notas          VARCHAR(255) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_cultivos_nombre (nombre),
    CONSTRAINT ck_cultivos_humedad CHECK (humedad_min IS NULL OR humedad_max IS NULL OR humedad_min <= humedad_max),
    CONSTRAINT ck_cultivos_temp    CHECK (temp_min    IS NULL OR temp_max    IS NULL OR temp_min    <= temp_max),
    CONSTRAINT ck_cultivos_hum_0_100 CHECK ((humedad_min IS NULL OR humedad_min BETWEEN 0 AND 100)
                                        AND (humedad_max IS NULL OR humedad_max BETWEEN 0 AND 100)),
    CONSTRAINT ck_cultivos_luz     CHECK (horas_luz_min IS NULL OR horas_luz_min BETWEEN 0 AND 24)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Zonas climáticas (migración 007). Ajustan los rangos ideales de cada
-- cultivo: no es lo mismo plantar en el norte que en el sur.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zonas_climaticas (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    codigo      VARCHAR(20)  NOT NULL COMMENT 'norte | centro | sur',
    nombre      VARCHAR(60)  NOT NULL,
    descripcion VARCHAR(255) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_zonas_codigo (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Camas: un nodo ESP32 por cama.
-- RF-09: cada rango personalizado (NULL = usar el del cultivo)
-- reemplaza campo por campo al del cultivo.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camas (
    id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
    nombre         VARCHAR(60)  NOT NULL COMMENT 'nombre visible, ej. Cama A',
    nodo_id        VARCHAR(40)  NOT NULL COMMENT 'identificador del ESP32, ej. cama-a',
    cultivo_id     INT UNSIGNED NULL,
    zona_climatica VARCHAR(60)  NULL COMMENT 'texto libre anterior (se conserva)',
    zona_id        INT UNSIGNED NULL COMMENT 'NULL = usar la zona del huerto',
    humedad_min    DECIMAL(5,2) NULL,
    humedad_max    DECIMAL(5,2) NULL,
    temp_min       DECIMAL(5,2) NULL,
    temp_max       DECIMAL(5,2) NULL,
    horas_luz_min  DECIMAL(4,2) NULL,
    cal_seco_mv    SMALLINT UNSIGNED NULL COMMENT 'mV de la sonda en suelo seco o al aire (0 %)',
    cal_mojado_mv  SMALLINT UNSIGNED NULL COMMENT 'mV de la sonda en suelo saturado (100 %)',
    cal_actualizada_en DATETIME NULL COMMENT 'UTC: último cambio de la calibración',
    activa         TINYINT(1)   NOT NULL DEFAULT 1,
    creada_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_camas_nodo (nodo_id),
    KEY ix_camas_cultivo (cultivo_id),
    CONSTRAINT fk_camas_cultivo FOREIGN KEY (cultivo_id) REFERENCES cultivos (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_camas_zona FOREIGN KEY (zona_id) REFERENCES zonas_climaticas (id)
        ON DELETE SET NULL,
    CONSTRAINT ck_camas_humedad CHECK (humedad_min IS NULL OR humedad_max IS NULL OR humedad_min <= humedad_max),
    CONSTRAINT ck_camas_temp    CHECK (temp_min    IS NULL OR temp_max    IS NULL OR temp_min    <= temp_max),
    CONSTRAINT ck_camas_hum_0_100 CHECK ((humedad_min IS NULL OR humedad_min BETWEEN 0 AND 100)
                                     AND (humedad_max IS NULL OR humedad_max BETWEEN 0 AND 100)),
    CONSTRAINT ck_camas_luz     CHECK (horas_luz_min IS NULL OR horas_luz_min BETWEEN 0 AND 24),
    CONSTRAINT ck_camas_calibracion CHECK (cal_seco_mv IS NULL OR cal_mojado_mv IS NULL OR cal_seco_mv > cal_mojado_mv)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Lecturas. RF-05: se guarda TODO, pero separado:
--   * suelo_prom, temp, hum_aire, lux: SOLO valores válidos (NULL si el
--     sensor falló o el valor se descartó). Así las consultas de estado
--     usan el índice sin leer JSON.
--   * suelo_detalle: valores crudos de cada sonda, tal como llegaron.
--   * campos_invalidos: valores crudos descartados y su motivo, ej.
--     {"temp": {"valor": 150, "tipo": "rango", "detalle": "temp fuera de rango físico"}}
--     tipo = rango | salto | tipo_dato
--   * valida = 0 solo cuando la lectura completa no sirve (hora imposible
--     o ningún dato utilizable).
-- UNIQUE(cama_id, seq): un reenvío desde el buffer no duplica.
-- La lectura "actual" es la de mayor medido_en válida (HU-01).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lecturas (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id          INT UNSIGNED    NOT NULL,
    seq              INT UNSIGNED    NOT NULL,
    medido_en        DATETIME        NOT NULL,
    recibido_en      DATETIME(3)     NOT NULL,
    suelo_prom       DOUBLE          NULL COMMENT '% promedio de las sondas válidas',
    suelo_detalle    JSON            NULL COMMENT 'valor crudo de cada sonda, ej. [28.1, 30.4]',
    temp             DOUBLE          NULL COMMENT '°C',
    hum_aire         DOUBLE          NULL COMMENT '%',
    lux              DOUBLE          NULL,
    suelo_mv         INT             NULL COMMENT 'mV crudos de la sonda de suelo (calibración y deriva)',
    valida           TINYINT(1)      NOT NULL DEFAULT 1,
    campos_invalidos JSON            NULL,
    motivo_invalida  VARCHAR(500)    NULL,
    sincronizado     TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_lecturas_cama_seq (cama_id, seq),
    KEY ix_lecturas_cama_medido (cama_id, medido_en),
    KEY ix_lecturas_sincronizado (sincronizado),
    CONSTRAINT fk_lecturas_cama FOREIGN KEY (cama_id) REFERENCES camas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Nodos que envían lecturas por HTTP (POST /api/lecturas).
-- El token NUNCA se guarda: solo su hash SHA-256 (el token es aleatorio
-- de 256 bits, así que un hash rápido es suficiente). Se crea con:
--   python -m web.nodos crear cama-a
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodos (
    nodo_id        VARCHAR(40)  NOT NULL,
    cama_id        INT UNSIGNED NOT NULL,
    token_hash     CHAR(64)     NOT NULL COMMENT 'SHA-256 en hexadecimal',
    activo         TINYINT(1)   NOT NULL DEFAULT 1,
    creado_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_uso_en  DATETIME     NULL,
    PRIMARY KEY (nodo_id),
    UNIQUE KEY uq_nodos_token (token_hash),
    KEY ix_nodos_cama (cama_id),
    CONSTRAINT fk_nodos_cama FOREIGN KEY (cama_id) REFERENCES camas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Luz diaria (HU-04). Se escribe al cerrar cada día (hora de Chile).
--   horas_luz NULL = no hubo datos de luz ("Sin datos de luz hoy", nunca "0 h").
--   minutos_con_datos_sol: cobertura en el horario de sol; si es menor
--   al 75 %, el día no cuenta como "poca luz" y corta la racha.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS luz_diaria (
    id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id               INT UNSIGNED    NOT NULL,
    fecha                 DATE            NOT NULL COMMENT 'día en hora de Chile',
    horas_luz             DECIMAL(5,2)    NULL,
    minutos_con_datos     INT UNSIGNED    NOT NULL DEFAULT 0,
    minutos_con_datos_sol INT UNSIGNED    NOT NULL DEFAULT 0,
    sincronizado          TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_luz_cama_fecha (cama_id, fecha),
    CONSTRAINT fk_luz_cama FOREIGN KEY (cama_id) REFERENCES camas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Alertas. Deduplicación garantizada por la BD:
-- clave_abierta = 1 si está abierta, NULL si está resuelta. Como un
-- UNIQUE admite varios NULL, puede haber UNA sola alerta abierta por
-- (cama, tipo, variable) y todas las resueltas que se quiera.
-- `variable` indica qué sensor la originó (para sensor_sin_datos).
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alertas (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id        INT UNSIGNED    NOT NULL,
    tipo           ENUM('suelo_seco','suelo_encharcado','helada','calor',
                        'poca_luz','sensor_sin_datos','tendencia_secado') NOT NULL
                   COMMENT 'tendencia_secado = preventiva (RF-15), no pone la cama en rojo',
    variable       ENUM('suelo','temperatura','luz') NOT NULL,
    estado         ENUM('abierta','resuelta') NOT NULL DEFAULT 'abierta',
    mensaje        VARCHAR(255)    NOT NULL COMMENT 'texto que se muestra en pantalla',
    valor_inicial  DOUBLE          NULL,
    valor_actual   DOUBLE          NULL,
    iniciada_en    DATETIME        NOT NULL,
    actualizada_en DATETIME        NOT NULL,
    resuelta_en    DATETIME        NULL,
    sincronizado   TINYINT(1)      NOT NULL DEFAULT 0,
    clave_abierta  TINYINT AS (IF(estado = 'abierta', 1, NULL)) PERSISTENT,
    PRIMARY KEY (id),
    UNIQUE KEY uq_alertas_una_abierta (cama_id, tipo, variable, clave_abierta),
    KEY ix_alertas_estado (estado, iniciada_en),
    KEY ix_alertas_sincronizado (sincronizado),
    CONSTRAINT fk_alertas_cama FOREIGN KEY (cama_id) REFERENCES camas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- CQ-02: tiempo desde la medición hasta que el aviso se ve en pantalla.
--   visible_en lo confirma el navegador del kiosco al dibujar el aviso.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_alerta (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    alerta_id        BIGINT UNSIGNED NOT NULL,
    evento           ENUM('apertura','resolucion') NOT NULL DEFAULT 'apertura',
    lectura_medida_en DATETIME       NOT NULL COMMENT 'medido_en de la lectura que la gatilló',
    procesado_en     DATETIME(3)     NOT NULL,
    visible_en       DATETIME(3)     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_eventos_alerta (alerta_id, evento),
    CONSTRAINT fk_eventos_alerta FOREIGN KEY (alerta_id) REFERENCES alertas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- CQ-03: latencia desde la medición hasta la pantalla.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS latencias_pantalla (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id     INT UNSIGNED    NOT NULL,
    seq         INT UNSIGNED    NOT NULL,
    medido_en   DATETIME        NOT NULL,
    mostrado_en DATETIME(3)     NOT NULL,
    latencia_ms INT             NOT NULL,
    PRIMARY KEY (id),
    KEY ix_latencias_cama (cama_id, mostrado_en),
    CONSTRAINT fk_latencias_cama FOREIGN KEY (cama_id) REFERENCES camas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- CQ-08: heartbeat de cada nodo (reinicios, señal WiFi, buffer).
-- Se usa nodo_id (no cama_id) porque el heartbeat puede llegar antes
-- que la primera lectura.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS heartbeats (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    nodo_id          VARCHAR(40)     NOT NULL,
    recibido_en      DATETIME(3)     NOT NULL,
    uptime_s         INT UNSIGNED    NULL,
    rssi             SMALLINT        NULL,
    motivo_reinicio  VARCHAR(30)     NULL COMMENT 'esp_reset_reason, ej. POWERON, TASK_WDT',
    buffer_pendiente INT UNSIGNED    NULL,
    heap_libre       INT UNSIGNED    NULL,
    PRIMARY KEY (id),
    KEY ix_heartbeats_nodo (nodo_id, recibido_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Conexión y desconexión de nodos (LWT online/offline)
CREATE TABLE IF NOT EXISTS conexiones_nodo (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    nodo_id     VARCHAR(40)     NOT NULL,
    estado      ENUM('online','offline') NOT NULL,
    ocurrido_en DATETIME(3)     NOT NULL,
    PRIMARY KEY (id),
    KEY ix_conexiones_nodo (nodo_id, ocurrido_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- CQ-06 e historial: cada cambio de estado de una cama (HU-05).
--   ultima_valida_en: última lectura válida del sensor que provocó el gris.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cambios_estado (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id          INT UNSIGNED    NOT NULL,
    estado_anterior  ENUM('verde','rojo','gris','sin_configurar') NULL,
    estado_nuevo     ENUM('verde','rojo','gris','sin_configurar') NOT NULL,
    mensaje          VARCHAR(255)    NOT NULL,
    ocurrido_en      DATETIME(3)     NOT NULL,
    ultima_valida_en DATETIME        NULL,
    PRIMARY KEY (id),
    KEY ix_cambios_cama (cama_id, ocurrido_en),
    CONSTRAINT fk_cambios_cama FOREIGN KEY (cama_id) REFERENCES camas (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Incidencias técnicas para el docente, ej. "contador seq reiniciado"
-- (mismo seq con distinto medido_en) o JSON mal formado.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidencias (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    nodo_id     VARCHAR(40)     NOT NULL,
    tipo        ENUM('seq_reiniciado','mensaje_invalido','otro') NOT NULL,
    detalle     VARCHAR(500)    NOT NULL,
    ocurrido_en DATETIME(3)     NOT NULL,
    revisada    TINYINT(1)      NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY ix_incidencias_pendientes (revisada, ocurrido_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Configuración del huerto editable desde /configuracion (migración 002).
-- Clave/valor; si una clave no está, rige el valor del .env.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS configuracion_huerto (
    clave          VARCHAR(60)  NOT NULL,
    valor          VARCHAR(255) NOT NULL,
    actualizado_en DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (clave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Clima externo de REFERENCIA, una instantánea por hora (migración 003).
-- No es un pronóstico. hum_suelo_vwc_pct es % volumétrico MODELADO para una
-- celda de varios km: no se compara directo con el % calibrado de la sonda.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clima_referencia (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    fuente            VARCHAR(30)     NOT NULL COMMENT 'open-meteo | dmc | openweather',
    observado_en      DATETIME        NOT NULL COMMENT 'UTC, hora del dato según el proveedor',
    obtenido_en       DATETIME(3)     NOT NULL COMMENT 'UTC, cuándo se consultó',
    lat               DECIMAL(8,5)    NOT NULL,
    lon               DECIMAL(8,5)    NOT NULL,
    temp_aire_c       DOUBLE          NULL COMMENT '°C a 2 m',
    hum_rel_pct       DOUBLE          NULL COMMENT '% humedad relativa a 2 m',
    precipitacion_mm  DOUBLE          NULL COMMENT 'mm',
    radiacion_wm2     DOUBLE          NULL COMMENT 'W/m² radiación de onda corta',
    temp_suelo_c      DOUBLE          NULL COMMENT '°C superficie del suelo (modelo)',
    hum_suelo_vwc_pct DOUBLE          NULL COMMENT '% vol. 0-1 cm (modelo)',
    et0_mm            DOUBLE          NULL COMMENT 'mm ET0 FAO de la hora',
    et0_hoy_mm        DOUBLE          NULL COMMENT 'mm ET0 acumulada hoy (hora de Chile)',
    PRIMARY KEY (id),
    UNIQUE KEY uq_clima_fuente_hora (fuente, observado_en, lat, lon),
    KEY ix_clima_observado (observado_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Capa de datos para análisis (migración 004). Todo se calcula desde
-- `lecturas` (que no se toca) y se puede recalcular:
--   python -m comun.analitica.recalcular --desde AAAA-MM-DD --hasta AAAA-MM-DD
-- Detalle de cada columna en docs/diccionario_de_datos.md
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS calidad_lecturas (
    lectura_id   BIGINT UNSIGNED NOT NULL,
    cama_id      INT UNSIGNED    NOT NULL,
    medido_en    DATETIME        NOT NULL COMMENT 'UTC, copiado de la lectura (para filtrar sin JOIN)',
    variable     ENUM('suelo','temp','hum_aire','lectura') NOT NULL,
    marca        ENUM('rango','salto','pegado','hueco') NOT NULL,
    detalle      VARCHAR(255)    NULL,
    calculado_en DATETIME        NOT NULL,
    PRIMARY KEY (lectura_id, variable, marca),
    KEY ix_calidad_cama_medido (cama_id, medido_en),
    CONSTRAINT fk_calidad_lectura FOREIGN KEY (lectura_id) REFERENCES lecturas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agregados_hora (
    cama_id      INT UNSIGNED    NOT NULL,
    hora_inicio  DATETIME        NOT NULL COMMENT 'UTC, inicio de la hora',
    variable     ENUM('suelo','temp','hum_aire') NOT NULL,
    media        DOUBLE          NULL,
    minimo       DOUBLE          NULL,
    maximo       DOUBLE          NULL,
    desviacion   DOUBLE          NULL COMMENT 'desviación estándar muestral (NULL con menos de 2 valores)',
    n_lecturas   INT UNSIGNED    NOT NULL COMMENT 'valores válidos usados',
    n_excluidas  INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT 'valores descartados (rango, salto, pegado)',
    n_esperadas  INT UNSIGNED    NOT NULL,
    cobertura    DOUBLE          NOT NULL COMMENT '0 a 1',
    calculado_en DATETIME        NOT NULL,
    PRIMARY KEY (cama_id, hora_inicio, variable),
    CONSTRAINT fk_agr_hora_cama FOREIGN KEY (cama_id) REFERENCES camas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS agregados_dia (
    cama_id           INT UNSIGNED    NOT NULL,
    fecha             DATE            NOT NULL COMMENT 'día en hora de Chile',
    variable          ENUM('suelo','temp','hum_aire') NOT NULL,
    media             DOUBLE          NULL,
    minimo            DOUBLE          NULL,
    maximo            DOUBLE          NULL,
    desviacion        DOUBLE          NULL,
    amplitud          DOUBLE          NULL COMMENT 'máximo - mínimo del día (amplitud térmica en temp)',
    horas_fuera_rango DOUBLE          NULL COMMENT 'horas fuera del rango ideal de la cama (NULL sin rango)',
    n_lecturas        INT UNSIGNED    NOT NULL,
    n_excluidas       INT UNSIGNED    NOT NULL DEFAULT 0,
    n_esperadas       INT UNSIGNED    NOT NULL,
    cobertura         DOUBLE          NOT NULL,
    calculado_en      DATETIME        NOT NULL,
    PRIMARY KEY (cama_id, fecha, variable),
    CONSTRAINT fk_agr_dia_cama FOREIGN KEY (cama_id) REFERENCES camas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE OR REPLACE VIEW v_clima_hora AS
SELECT fuente,
       TIMESTAMP(DATE(observado_en), MAKETIME(HOUR(observado_en), 0, 0)) AS hora_inicio,
       AVG(lat) AS lat, AVG(lon) AS lon,
       AVG(temp_aire_c) AS temp_aire_c, AVG(hum_rel_pct) AS hum_rel_pct,
       SUM(precipitacion_mm) AS precipitacion_mm, AVG(radiacion_wm2) AS radiacion_wm2,
       AVG(temp_suelo_c) AS temp_suelo_c, AVG(hum_suelo_vwc_pct) AS hum_suelo_vwc_pct,
       MAX(et0_mm) AS et0_mm, COUNT(*) AS n_instantaneas
  FROM clima_referencia
 GROUP BY fuente, TIMESTAMP(DATE(observado_en), MAKETIME(HOUR(observado_en), 0, 0));

-- -------------------------------------------------------------
-- Eventos de riego y tramos de secado (migración 005). Los 'detectado'
-- se recalculan desde las lecturas; los 'manual' (futuro) no se borran.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_riego (
    id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id          INT UNSIGNED    NOT NULL,
    origen           ENUM('detectado','manual') NOT NULL DEFAULT 'detectado',
    inicio           DATETIME        NOT NULL COMMENT 'UTC',
    fin              DATETIME        NULL     COMMENT 'UTC, punto más alto de la subida',
    humedad_antes    DOUBLE          NULL     COMMENT '% suelo (escala calibrada de la sonda)',
    humedad_despues  DOUBLE          NULL,
    lectura_antes_id BIGINT UNSIGNED NULL,
    lectura_despues_id BIGINT UNSIGNED NULL,
    notas            VARCHAR(255)    NULL     COMMENT 'para el registro manual (futuro)',
    calculado_en     DATETIME        NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_riego_cama_inicio (cama_id, inicio, origen),
    KEY ix_riego_cama_fin (cama_id, fin),
    CONSTRAINT fk_riego_cama FOREIGN KEY (cama_id) REFERENCES camas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE OR REPLACE VIEW v_tramos_secado AS
SELECT id AS evento_id,
       cama_id,
       origen,
       COALESCE(fin, inicio) AS inicio_tramo,
       LEAD(inicio) OVER (PARTITION BY cama_id ORDER BY inicio, id) AS fin_tramo,
       humedad_despues AS humedad_inicial
  FROM eventos_riego;

-- -------------------------------------------------------------
-- CQ-13: tiempo de cálculo de cada predicción de tendencia (migración 006)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tiempos_tendencia (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    cama_id      INT UNSIGNED    NOT NULL,
    calculado_en DATETIME(3)     NOT NULL,
    duracion_ms  DOUBLE          NOT NULL,
    n_puntos     INT UNSIGNED    NOT NULL,
    estado       VARCHAR(30)     NOT NULL COMMENT 'estimacion | fuera_horizonte | bajo_minimo | sin_tendencia | sin_rango',
    horas        DOUBLE          NULL     COMMENT 'horas estimadas hasta el mínimo',
    pendiente    DOUBLE          NULL     COMMENT 'puntos % por hora',
    r2           DOUBLE          NULL,
    PRIMARY KEY (id),
    KEY ix_tiempos_cama (cama_id, calculado_en),
    CONSTRAINT fk_tiempos_cama FOREIGN KEY (cama_id) REFERENCES camas (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- Rangos del cultivo por zona (migración 007). Orden para cada campo:
-- rango de la cama > cultivo + zona > cultivo genérico.
-- Los valores de ejemplo se cargan en semillas.sql.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rangos_cultivo_zona (
    cultivo_id    INT UNSIGNED NOT NULL,
    zona_id       INT UNSIGNED NOT NULL,
    humedad_min   DECIMAL(5,2) NULL,
    humedad_max   DECIMAL(5,2) NULL,
    temp_min      DECIMAL(5,2) NULL,
    temp_max      DECIMAL(5,2) NULL,
    horas_luz_min DECIMAL(4,2) NULL,
    por_confirmar TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1 = valor de ejemplo, confirmar con INIA/INDAP',
    notas         VARCHAR(255) NULL,
    PRIMARY KEY (cultivo_id, zona_id),
    CONSTRAINT fk_rcz_cultivo FOREIGN KEY (cultivo_id) REFERENCES cultivos (id) ON DELETE CASCADE,
    CONSTRAINT fk_rcz_zona FOREIGN KEY (zona_id) REFERENCES zonas_climaticas (id) ON DELETE CASCADE,
    CONSTRAINT ck_rcz_humedad CHECK (humedad_min IS NULL OR humedad_max IS NULL OR humedad_min <= humedad_max),
    CONSTRAINT ck_rcz_temp    CHECK (temp_min    IS NULL OR temp_max    IS NULL OR temp_min    <= temp_max),
    CONSTRAINT ck_rcz_hum_0_100 CHECK ((humedad_min IS NULL OR humedad_min BETWEEN 0 AND 100)
                                   AND (humedad_max IS NULL OR humedad_max BETWEEN 0 AND 100)),
    CONSTRAINT ck_rcz_luz     CHECK (horas_luz_min IS NULL OR horas_luz_min BETWEEN 0 AND 24)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Zona efectiva y rango del cultivo en esa zona, por cama
CREATE OR REPLACE VIEW v_camas_zona AS
SELECT c.id AS cama_id,
       z.id AS zona_efectiva_id,
       z.codigo AS zona_codigo,
       z.nombre AS zona_nombre,
       (c.zona_id IS NULL) AS zona_heredada,
       rz.humedad_min AS zona_humedad_min, rz.humedad_max AS zona_humedad_max,
       rz.temp_min AS zona_temp_min, rz.temp_max AS zona_temp_max,
       rz.horas_luz_min AS zona_horas_luz_min, rz.por_confirmar AS zona_por_confirmar
  FROM camas c
  LEFT JOIN zonas_climaticas z
         ON z.id = COALESCE(c.zona_id,
                   (SELECT z2.id FROM zonas_climaticas z2
                     WHERE z2.codigo = COALESCE((SELECT h.valor FROM configuracion_huerto h
                                                  WHERE h.clave = 'zona_huerto'), 'centro')))
  LEFT JOIN rangos_cultivo_zona rz ON rz.cultivo_id = c.cultivo_id AND rz.zona_id = z.id;

-- -------------------------------------------------------------
-- Migraciones aplicadas (python -m comun.migrar). Una BD creada con
-- este archivo ya incluye todas las migraciones de db/migraciones/.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migraciones (
    nombre       VARCHAR(100) NOT NULL,
    aplicada_en  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO migraciones (nombre) VALUES
    ('001_api_nodos.sql'), ('002_configuracion_huerto.sql'), ('003_clima_referencia.sql'),
    ('004_calidad_agregados.sql'), ('005_eventos_riego.sql'),
    ('006_tendencias.sql'), ('007_zonas.sql'), ('008_calibracion_suelo.sql');

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
-- Camas: un nodo ESP32 por cama.
-- RF-09: cada rango personalizado (NULL = usar el del cultivo)
-- reemplaza campo por campo al del cultivo.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS camas (
    id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
    nombre         VARCHAR(60)  NOT NULL COMMENT 'nombre visible, ej. Cama A',
    nodo_id        VARCHAR(40)  NOT NULL COMMENT 'identificador del ESP32, ej. cama-a',
    cultivo_id     INT UNSIGNED NULL,
    zona_climatica VARCHAR(60)  NULL,
    humedad_min    DECIMAL(5,2) NULL,
    humedad_max    DECIMAL(5,2) NULL,
    temp_min       DECIMAL(5,2) NULL,
    temp_max       DECIMAL(5,2) NULL,
    horas_luz_min  DECIMAL(4,2) NULL,
    activa         TINYINT(1)   NOT NULL DEFAULT 1,
    creada_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_camas_nodo (nodo_id),
    KEY ix_camas_cultivo (cultivo_id),
    CONSTRAINT fk_camas_cultivo FOREIGN KEY (cultivo_id) REFERENCES cultivos (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT ck_camas_humedad CHECK (humedad_min IS NULL OR humedad_max IS NULL OR humedad_min <= humedad_max),
    CONSTRAINT ck_camas_temp    CHECK (temp_min    IS NULL OR temp_max    IS NULL OR temp_min    <= temp_max),
    CONSTRAINT ck_camas_hum_0_100 CHECK ((humedad_min IS NULL OR humedad_min BETWEEN 0 AND 100)
                                     AND (humedad_max IS NULL OR humedad_max BETWEEN 0 AND 100)),
    CONSTRAINT ck_camas_luz     CHECK (horas_luz_min IS NULL OR horas_luz_min BETWEEN 0 AND 24)
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
                        'poca_luz','sensor_sin_datos') NOT NULL,
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
-- Migraciones aplicadas (python -m comun.migrar). Una BD creada con
-- este archivo ya incluye todas las migraciones de db/migraciones/.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migraciones (
    nombre       VARCHAR(100) NOT NULL,
    aplicada_en  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO migraciones (nombre) VALUES ('001_api_nodos.sql');

-- =============================================================
-- 003 — Clima externo de referencia (una instantánea por hora)
--
-- La guarda el procesador cada hora. Sirve para comparar la lectura de
-- cada cama con el clima de la zona a la MISMA hora y para graficar las
-- diferencias en el tiempo. No es un pronóstico.
--   hum_suelo_vwc_pct: contenido volumétrico de agua (% vol.) MODELADO para
--   una celda de varios km. NO es comparable con el % calibrado de la sonda.
-- Revertir con:  python -m comun.migrar --revertir 003_clima_referencia.sql
-- =============================================================

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

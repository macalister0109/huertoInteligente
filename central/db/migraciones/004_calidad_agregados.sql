-- =============================================================
-- 004 — Capa de datos para análisis: crudo -> limpio -> agregado
--
-- Las lecturas crudas (tabla `lecturas`) NO se tocan: son la fuente de
-- verdad. Todo lo de aquí se calcula a partir de ellas y se puede borrar y
-- recalcular en cualquier momento:
--     python -m comun.analitica.recalcular --desde 2026-11-01 --hasta 2026-11-30
--
-- * calidad_lecturas: marcas de calidad por lectura y variable.
--     rango  = fuera de rango físico (o no numérico): viene de campos_invalidos
--     salto  = salto imposible respecto de la lectura anterior: de campos_invalidos
--     pegado = el mismo valor exacto por más de N horas (sensor pegado)
--     hueco  = antes de esta lectura faltaron más de 2 lecturas seguidas
--              (variable = 'lectura': no es de un sensor en particular)
-- * agregados_hora / agregados_dia: estadísticas por cama y variable. Usan
--   solo valores válidos y excluyen los marcados como «pegado».
--   cobertura = n_lecturas / n_esperadas (máximo 1).
-- * v_clima_hora: clima de referencia a la misma granularidad horaria.
--
-- Revertir con:  python -m comun.migrar --revertir 004_calidad_agregados.sql
-- =============================================================

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

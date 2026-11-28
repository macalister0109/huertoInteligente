-- =============================================================
-- 007 — Rangos ideales por zona climática (comentario del profesor:
-- «los rangos deben adaptarse a la zona»)
--
-- Orden para resolver el rango de cada campo de una cama:
--   1. el personalizado de la cama (camas.humedad_min, …)
--   2. el del cultivo en la zona de la cama (rangos_cultivo_zona)
--   3. el del cultivo genérico (cultivos)
-- La zona de una cama es camas.zona_id o, si está vacía, la zona del huerto
-- (configuracion_huerto.zona_huerto; si no está, «centro»).
--
-- Los valores de ejemplo están marcados por_confirmar = 1: deben
-- confirmarse con las fichas de INIA / INDAP.
-- camas.zona_climatica (texto libre anterior) se conserva sin cambios.
-- Revertir con:  python -m comun.migrar --revertir 007_zonas.sql
-- =============================================================

CREATE TABLE IF NOT EXISTS zonas_climaticas (
    id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
    codigo      VARCHAR(20)  NOT NULL COMMENT 'norte | centro | sur',
    nombre      VARCHAR(60)  NOT NULL,
    descripcion VARCHAR(255) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_zonas_codigo (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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

ALTER TABLE camas
    ADD COLUMN IF NOT EXISTS zona_id INT UNSIGNED NULL
        COMMENT 'NULL = usar la zona del huerto' AFTER zona_climatica;

ALTER TABLE camas
    ADD CONSTRAINT fk_camas_zona FOREIGN KEY IF NOT EXISTS (zona_id) REFERENCES zonas_climaticas (id)
        ON DELETE SET NULL;

INSERT IGNORE INTO zonas_climaticas (codigo, nombre, descripcion) VALUES
    ('norte',  'Norte',  'Más cálido y seco, mucha radiación (ej. Coquimbo). Ejemplo por confirmar.'),
    ('centro', 'Centro', 'Clima mediterráneo: veranos secos y calurosos, heladas en invierno (ej. Región Metropolitana).'),
    ('sur',    'Sur',    'Más fresco y lluvioso, menos horas de sol (ej. Los Lagos). Ejemplo por confirmar.');

-- Valores de EJEMPLO (por confirmar con fichas INIA/INDAP)
INSERT IGNORE INTO rangos_cultivo_zona
    (cultivo_id, zona_id, humedad_min, humedad_max, temp_min, temp_max, horas_luz_min, por_confirmar, notas)
SELECT cu.id, z.id, v.hmin, v.hmax, v.tmin, v.tmax, v.luz, 1, 'Ejemplo. Por confirmar con fichas INIA/INDAP.'
  FROM (SELECT 'tomate' AS cultivo, 'norte' AS zona, 35 AS hmin, 70 AS hmax, 16 AS tmin, 32 AS tmax, 6 AS luz
        UNION ALL SELECT 'tomate',  'centro', 30, 70, 15, 30, 6
        UNION ALL SELECT 'tomate',  'sur',    30, 65, 13, 28, 5
        UNION ALL SELECT 'lechuga', 'norte',  45, 80,  8, 26, 3
        UNION ALL SELECT 'lechuga', 'centro', 40, 80,  7, 24, 3
        UNION ALL SELECT 'lechuga', 'sur',    40, 75,  5, 22, 3) v
  JOIN cultivos cu ON cu.nombre = v.cultivo
  JOIN zonas_climaticas z ON z.codigo = v.zona;

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

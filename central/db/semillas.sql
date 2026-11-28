-- =============================================================
-- Valores semilla de EJEMPLO.
-- ¡POR CONFIRMAR con INIA / INDAP y según la zona antes de usarlos!
-- Por eso quedan con por_confirmar = 1. El docente puede ajustarlos
-- o personalizar los rangos de cada cama desde la configuración.
-- =============================================================

SET NAMES utf8mb4;

INSERT INTO cultivos
    (nombre, humedad_min, humedad_max, temp_min, temp_max, horas_luz_min,
     tolera_sombra, por_confirmar, notas)
VALUES
    ('tomate',  30, 70, 15, 30, 6, 0, 1,
     'Ejemplo. Por confirmar con INIA/INDAP y la zona.'),
    ('lechuga', 40, 80,  7, 24, 3, 1, 1,
     'Cultivo de sombra. Ejemplo. Por confirmar con INIA/INDAP y la zona.')
ON DUPLICATE KEY UPDATE nombre = nombre;

-- Zonas climáticas y rangos por zona (también de EJEMPLO, por confirmar)
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

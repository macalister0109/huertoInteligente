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

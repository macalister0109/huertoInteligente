-- =============================================================
-- 002 — Configuración del huerto editable desde /configuracion
--
-- Tabla clave/valor. Si una clave no está, se usa el valor del .env.
-- Ejemplos: clima_proveedor, clima_lat, clima_lon.
-- Revertir con:  python -m comun.migrar --revertir 002_configuracion_huerto.sql
-- =============================================================

CREATE TABLE IF NOT EXISTS configuracion_huerto (
    clave          VARCHAR(60)  NOT NULL,
    valor          VARCHAR(255) NOT NULL,
    actualizado_en DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (clave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

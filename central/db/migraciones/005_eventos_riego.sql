-- =============================================================
-- 005 — Eventos de riego y tramos de secado
--
-- * eventos_riego: un riego es una subida brusca de la humedad del suelo
--   (por defecto +10 puntos en 30 min o menos; RIEGO_UMBRAL_PTS y
--   RIEGO_VENTANA_MIN). origen = 'detectado' los calcula el sistema y se
--   recalculan sin duplicar (UNIQUE). origen = 'manual' queda listo para un
--   registro hecho por personas (sin pantalla de registro por ahora): el
--   recálculo nunca los borra.
--     inicio = última lectura antes de la subida (humedad_antes)
--     fin    = punto más alto de la subida (humedad_despues)
-- * v_tramos_secado: cada riego parte un «tramo de secado», desde el fin del
--   riego hasta el inicio del siguiente (fin_tramo NULL = tramo en curso).
--
-- Revertir con:  python -m comun.migrar --revertir 005_eventos_riego.sql
-- =============================================================

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

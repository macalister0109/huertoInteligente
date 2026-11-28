-- =============================================================
-- 006 — Predicción de tendencia (RF-15)
--
-- * alertas.tipo: agrega 'tendencia_secado' (alerta PREVENTIVA: «al ritmo
--   actual llegaría al mínimo en unas X h»). Desactivada por defecto
--   (TENDENCIA_ACTIVA / configuración). Se abre y actualiza sin duplicar,
--   igual que las demás. No pone la cama en rojo: no está fuera de rango.
-- * tiempos_tendencia: CQ-13, cuánto tarda cada predicción en el equipo
--   central (meta: 1 s o menos por cama).
--
-- Revertir con:  python -m comun.migrar --revertir 006_tendencias.sql
-- =============================================================

ALTER TABLE alertas
    MODIFY COLUMN tipo ENUM('suelo_seco','suelo_encharcado','helada','calor',
                            'poca_luz','sensor_sin_datos','tendencia_secado') NOT NULL;

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

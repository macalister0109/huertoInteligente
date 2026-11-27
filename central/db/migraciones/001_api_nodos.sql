-- =============================================================
-- 001 — Lecturas por HTTP desde el ESP32 (POST /api/lecturas)
--
-- * lecturas.suelo_mv: mV crudos de la sonda de suelo.
-- * nodos: token de cada nodo, guardado como hash SHA-256.
--
-- Es idempotente (IF NOT EXISTS): se puede ejecutar más de una vez.
-- Aplicar con:  python -m comun.migrar
-- =============================================================

ALTER TABLE lecturas
    ADD COLUMN IF NOT EXISTS suelo_mv INT NULL
        COMMENT 'mV crudos de la sonda de suelo (calibración y deriva)'
        AFTER lux;

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

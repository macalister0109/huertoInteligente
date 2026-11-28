-- =============================================================
-- 008 — Calibración de la sonda de suelo por cama, en el servidor
--
-- El nodo envía los mV crudos de la sonda (lecturas.suelo_mv). Si la cama
-- tiene los dos puntos de calibración, el % de humedad (suelo_prom) lo
-- calcula el equipo central desde los mV, en vez de usar el % del nodo:
--     % = (seco - mV) * 100 / (seco - mojado), acotado a 0–100
-- Así se puede recalibrar desde /configuracion sin tocar la placa, y
-- volver a calcular el historial con la calibración nueva.
-- NULL en cualquiera de los dos = se usa el % que envía el nodo (como antes).
-- suelo_detalle sigue guardando el % del nodo tal como llegó.
-- Revertir con:  python -m comun.migrar --revertir 008_calibracion_suelo.sql
-- =============================================================

ALTER TABLE camas
    ADD COLUMN IF NOT EXISTS cal_seco_mv SMALLINT UNSIGNED NULL
        COMMENT 'mV de la sonda en suelo seco o al aire (0 %)' AFTER horas_luz_min;

ALTER TABLE camas
    ADD COLUMN IF NOT EXISTS cal_mojado_mv SMALLINT UNSIGNED NULL
        COMMENT 'mV de la sonda en suelo saturado (100 %)' AFTER cal_seco_mv;

ALTER TABLE camas
    ADD COLUMN IF NOT EXISTS cal_actualizada_en DATETIME NULL
        COMMENT 'UTC: último cambio de la calibración' AFTER cal_mojado_mv;

ALTER TABLE camas
    ADD CONSTRAINT IF NOT EXISTS ck_camas_calibracion
        CHECK (cal_seco_mv IS NULL OR cal_mojado_mv IS NULL OR cal_seco_mv > cal_mojado_mv);

-- Revierte 008: el % de humedad vuelve a ser el que envía el nodo.
-- Las lecturas ya recalculadas conservan su suelo_prom (no se tocan).
ALTER TABLE camas DROP CONSTRAINT IF EXISTS ck_camas_calibracion;
ALTER TABLE camas DROP COLUMN IF EXISTS cal_actualizada_en;
ALTER TABLE camas DROP COLUMN IF EXISTS cal_mojado_mv;
ALTER TABLE camas DROP COLUMN IF EXISTS cal_seco_mv;

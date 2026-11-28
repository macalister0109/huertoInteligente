-- Revierte 005. OJO: también borra los riegos de origen 'manual' (si los hubiera).
-- No toca las lecturas.
DROP VIEW IF EXISTS v_tramos_secado;
DROP TABLE IF EXISTS eventos_riego;

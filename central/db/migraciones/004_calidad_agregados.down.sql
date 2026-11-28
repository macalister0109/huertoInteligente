-- Revierte 004: borra solo datos CALCULADOS (se pueden recalcular). No toca las lecturas.
DROP VIEW IF EXISTS v_clima_hora;
DROP TABLE IF EXISTS agregados_dia;
DROP TABLE IF EXISTS agregados_hora;
DROP TABLE IF EXISTS calidad_lecturas;

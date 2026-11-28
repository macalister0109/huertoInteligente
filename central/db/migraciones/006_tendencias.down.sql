-- Revierte 006. Borra las alertas preventivas 'tendencia_secado' (si no, el
-- ENUM no se puede achicar) y las mediciones de CQ-13. No toca las lecturas.
DELETE FROM alertas WHERE tipo = 'tendencia_secado';
ALTER TABLE alertas
    MODIFY COLUMN tipo ENUM('suelo_seco','suelo_encharcado','helada','calor',
                            'poca_luz','sensor_sin_datos') NOT NULL;
DROP TABLE IF EXISTS tiempos_tendencia;

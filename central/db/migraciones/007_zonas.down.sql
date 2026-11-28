-- Revierte 007: las camas vuelven a usar solo su rango propio y el del cultivo genérico.
-- Se pierden la zona elegida por cama y los rangos por zona. No toca las lecturas.
DROP VIEW IF EXISTS v_camas_zona;
ALTER TABLE camas DROP FOREIGN KEY IF EXISTS fk_camas_zona;
ALTER TABLE camas DROP COLUMN IF EXISTS zona_id;
DROP TABLE IF EXISTS rangos_cultivo_zona;
DROP TABLE IF EXISTS zonas_climaticas;
DELETE FROM configuracion_huerto WHERE clave = 'zona_huerto';

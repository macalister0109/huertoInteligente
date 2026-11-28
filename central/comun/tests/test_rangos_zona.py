"""Rangos por zona climática: cama > cultivo + zona > cultivo genérico."""

from datetime import timedelta

import pytest

from comun import ajustes, migrar
from comun.rangos import CAMA, CULTIVO, ZONA, SELECT_CAMA, rango_efectivo
from pruebas.bd import CFG, INICIO

CULTIVO_TOMATE = {"cultivo_nombre": "tomate", "cultivo_humedad_min": 30, "cultivo_humedad_max": 70,
                  "cultivo_temp_min": 15, "cultivo_temp_max": 30, "cultivo_horas_luz_min": 6}


# ------------------------------------------------------------------ puras

def test_orden_cama_luego_zona_luego_cultivo():
    cama = {**CULTIVO_TOMATE, "zona_nombre": "Norte",
            "zona_humedad_min": 35, "zona_temp_max": 32,           # el norte cambia dos campos
            "humedad_min": 50}                                     # la cama personaliza uno
    r = rango_efectivo(cama)
    assert (r.humedad_min, r.humedad_max, r.temp_min, r.temp_max, r.horas_luz_min) == (50, 70, 15, 32, 6)
    assert r.origenes == {"humedad_min": CAMA, "humedad_max": CULTIVO, "temp_min": CULTIVO,
                          "temp_max": ZONA, "horas_luz_min": CULTIVO}
    assert (r.cultivo, r.zona) == ("tomate", "Norte")


def test_sin_rangos_de_zona_usa_el_cultivo():
    r = rango_efectivo({**CULTIVO_TOMATE, "zona_nombre": "Sur"})
    assert (r.humedad_min, r.temp_min) == (30, 15) and set(r.origenes.values()) == {CULTIVO}


def test_sin_cultivo_ni_rangos_no_esta_configurada():
    assert not rango_efectivo({"zona_nombre": "Centro"}).configurado


# --------------------------------------------------------------- con la BD

def ejecutar(bd, sql, args=()):
    with bd.cursor() as cur:
        cur.execute(sql, args)
        filas = cur.fetchall()
        ultimo = cur.lastrowid
    bd.commit()
    return filas, ultimo


def crear_cama(bd, zona=None, **propios):
    columnas = ", ".join(["nombre", "nodo_id", "cultivo_id", "zona_id", *propios])
    marcas = ", ".join(["%s"] * (4 + len(propios)))
    zona_id = None
    if zona:
        zona_id = ejecutar(bd, "SELECT id FROM zonas_climaticas WHERE codigo = %s", (zona,))[0][0]["id"]
    tomate = ejecutar(bd, "SELECT id FROM cultivos WHERE nombre = 'tomate'")[0][0]["id"]
    return ejecutar(bd, f"INSERT INTO camas ({columnas}) VALUES ({marcas})",
                    ("Cama A", f"cama-{zona or 'h'}", tomate, zona_id, *propios.values()))[1]


def rango_de(bd, cama_id):
    fila = ejecutar(bd, SELECT_CAMA + " WHERE c.id = %s", (cama_id,))[0][0]
    return rango_efectivo(fila), fila


@pytest.mark.bd
def test_zonas_y_valores_de_ejemplo_cargados(bd):
    zonas = [f["codigo"] for f in ejecutar(bd, "SELECT codigo FROM zonas_climaticas ORDER BY id")[0]]
    assert zonas == ["norte", "centro", "sur"]
    filas = ejecutar(bd, "SELECT por_confirmar FROM rangos_cultivo_zona")[0]
    assert len(filas) == 6 and all(f["por_confirmar"] == 1 for f in filas)


@pytest.mark.bd
def test_cama_sin_zona_usa_la_del_huerto(bd):
    cama = crear_cama(bd)
    r, fila = rango_de(bd, cama)
    assert (fila["zona_codigo"], fila["zona_heredada"]) == ("centro", 1)     # por defecto: centro
    assert (r.humedad_min, r.temp_max) == (30, 30)
    ajustes.guardar(bd, {"zona_huerto": "norte"})
    bd.commit()
    r, fila = rango_de(bd, cama)
    assert fila["zona_codigo"] == "norte" and (r.humedad_min, r.temp_max) == (35, 32)
    assert r.origenes["humedad_min"] == ZONA


@pytest.mark.bd
def test_zona_propia_de_la_cama_y_rango_personalizado(bd):
    cama = crear_cama(bd, zona="sur", humedad_min=45)
    r, fila = rango_de(bd, cama)
    assert (fila["zona_codigo"], fila["zona_heredada"]) == ("sur", 0)
    assert r.humedad_min == 45 and r.origenes["humedad_min"] == CAMA      # la cama manda
    assert (r.temp_min, r.humedad_max) == (13, 65)                        # del tomate en el sur


@pytest.mark.bd
def test_la_zona_cambia_cuando_se_alerta(bd):
    """Tomate con 33 %: en el centro (mín. 30) está bien; en el norte (mín. 35) está seco."""
    from procesador.publicador import PublicadorMemoria
    from procesador.servicio import Procesador
    from pruebas.bd import Reloj
    cama = crear_cama(bd)
    ejecutar(bd, """INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom, temp, hum_aire)
                    VALUES (%s, 1, %s, %s, 33, 20, 50)""", (cama, INICIO, INICIO))
    proc = Procesador(bd, CFG, PublicadorMemoria(), Reloj(INICIO + timedelta(minutes=1)))
    proc.reevaluar_cama(cama)
    assert ejecutar(bd, "SELECT COUNT(*) AS n FROM alertas")[0][0]["n"] == 0
    ajustes.guardar(bd, {"zona_huerto": "norte"})
    bd.commit()
    proc.reevaluar_cama(cama)
    alertas = ejecutar(bd, "SELECT tipo, mensaje FROM alertas WHERE estado = 'abierta'")[0]
    assert [a["tipo"] for a in alertas] == ["suelo_seco"] and "35" in alertas[0]["mensaje"]


@pytest.mark.bd
def test_migracion_007_se_revierte_sin_tocar_las_lecturas(bd):
    cama = crear_cama(bd, zona="norte")
    ejecutar(bd, """INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom)
                    VALUES (%s, 1, %s, %s, 40)""", (cama, INICIO, INICIO))
    migrar.revertir(bd, "007_zonas.sql")
    assert ejecutar(bd, "SELECT COUNT(*) AS n FROM lecturas")[0][0]["n"] == 1
    assert "007_zonas.sql" in migrar.migrar(bd)
    r, fila = rango_de(bd, cama)
    assert fila["zona_codigo"] == "centro"            # la zona propia se perdió al revertir

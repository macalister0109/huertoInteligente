"""Calibración de la sonda de suelo desde /configuracion, sin tocar la placa."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pruebas.bd import INICIO
from web import nodos

from .conftest import ingresar

pytestmark = pytest.mark.bd

MIN = timedelta(minutes=1)


@pytest.fixture
def cama(datos):
    return datos.cama("cama-a", "Cama A")


@pytest.fixture
def enviar(cliente, cama, bd, reloj):
    token = nodos.crear_nodo(bd, "cama-a")

    def _enviar(seq: int, mv: int, pct=100, medido_en=None):
        medido_en = medido_en or INICIO + seq * MIN
        reloj.t = medido_en + timedelta(seconds=2)
        r = cliente.post("/api/lecturas", headers={"Authorization": f"Bearer {token}"},
                         json={"nodo_id": "cama-a", "seq": seq,
                               "medido_en": medido_en.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "temp": 23, "hum_aire": 61, "suelo_pct": pct, "suelo_mv": mv})
        assert r.status_code == 201, r.get_json()
        return r
    return _enviar


def suelo(datos) -> list:
    return [float(f["suelo_prom"]) for f in
            datos.consulta("SELECT suelo_prom FROM lecturas ORDER BY seq")]


def calibrar(cliente, cama, **form):
    csrf = ingresar(cliente)
    return cliente.post(f"/configuracion/camas/{cama}/calibracion",
                        data={"csrf": csrf, "recalcular": "1", **form})


def test_sin_calibracion_se_usa_el_porcentaje_de_la_placa(enviar, datos):
    enviar(1, mv=1437, pct=100)
    assert suelo(datos) == [100.0]


def test_con_calibracion_la_api_guarda_el_porcentaje_desde_los_mv(enviar, datos, cliente, cama):
    calibrar(cliente, cama, cal_seco_mv="3160", cal_mojado_mv="980")
    enviar(1, mv=1437, pct=100)
    assert suelo(datos) == [79.0]
    fila, = datos.consulta("SELECT suelo_detalle FROM lecturas")
    assert json.loads(fila["suelo_detalle"]) == [100]          # lo que mandó la placa
    ultima = cliente.get("/api/camas/cama-a/ultima").get_json()["lectura"]
    assert ultima["suelo_pct"] == 79.0 and ultima["suelo_mv"] == 1437


def test_guardar_con_recalcular_corrige_el_historial(enviar, datos, cliente, cama, difusor):
    for seq, mv in ((1, 1700), (2, 1600), (3, 1437)):
        enviar(seq, mv=mv)
    assert suelo(datos) == [100.0, 100.0, 100.0]

    r = calibrar(cliente, cama, cal_seco_mv="3160", cal_mojado_mv="980")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"#calibracion-{cama}")
    assert suelo(datos) == [67.0, 71.6, 79.0]
    assert cama in difusor.avisos_configuracion
    # Los agregados por hora también salen del % nuevo
    hora, = datos.consulta("SELECT media FROM agregados_hora WHERE cama_id = %s AND variable = 'suelo'",
                           (cama,))
    assert hora["media"] == pytest.approx((67.0 + 71.6 + 79.0) / 3, abs=0.1)
    pagina = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Calibración de Cama A guardada: seco 3160 mV = 0 %, mojado 980 mV = 100 %." in pagina
    assert "3 lecturas cambiaron" in pagina


def test_sin_recalcular_el_historial_queda_igual(enviar, datos, cliente, cama):
    enviar(1, mv=1700, pct=70)
    csrf = ingresar(cliente)
    cliente.post(f"/configuracion/camas/{cama}/calibracion",
                 data={"csrf": csrf, "cal_seco_mv": "3160", "cal_mojado_mv": "980"})
    enviar(2, mv=1700)
    assert suelo(datos) == [70.0, 67.0]


def test_usar_la_lectura_actual_como_mojado(enviar, datos, cliente, cama):
    # El lunes: sonda en la tierra saturada, unos minutos de lecturas
    for seq, mv in ((1, 1700), (2, 1010), (3, 1000), (4, 990)):
        enviar(seq, mv=mv)
    calibrar(cliente, cama, accion="mojado_actual", cal_seco_mv="3160", cal_mojado_mv="2042")
    fila, = datos.consulta("SELECT cal_seco_mv, cal_mojado_mv FROM camas")
    assert (fila["cal_seco_mv"], fila["cal_mojado_mv"]) == (3160, 1175)   # promedio de 10 min
    pagina = cliente.get("/configuracion/").get_data(as_text=True)
    assert "se usó la lectura actual, 1175 mV (promedio de 4 lecturas)" in pagina


def test_lectura_actual_solo_promedia_los_ultimos_minutos(enviar, datos, cliente, cama):
    enviar(1, mv=1700, medido_en=INICIO)
    enviar(2, mv=1000, medido_en=INICIO + 30 * MIN)
    enviar(3, mv=980, medido_en=INICIO + 31 * MIN)
    calibrar(cliente, cama, accion="mojado_actual", cal_seco_mv="3160")
    fila, = datos.consulta("SELECT cal_mojado_mv FROM camas")
    assert fila["cal_mojado_mv"] == 990


def test_usar_la_lectura_actual_sin_lecturas(cliente, cama, datos):
    calibrar(cliente, cama, accion="mojado_actual", cal_seco_mv="3160")
    pagina = cliente.get("/configuracion/").get_data(as_text=True)
    assert "todavía no hay lecturas con mV" in pagina
    fila, = datos.consulta("SELECT cal_mojado_mv FROM camas")
    assert fila["cal_mojado_mv"] is None


def test_quitar_vuelve_al_porcentaje_de_la_placa(enviar, datos, cliente, cama):
    calibrar(cliente, cama, cal_seco_mv="3160", cal_mojado_mv="980")
    enviar(1, mv=1437, pct=100)
    enviar(2, mv=1437, pct=None)        # la placa sin calibrar: no hay % que restaurar
    calibrar(cliente, cama, accion="quitar")
    fila = datos.consulta("SELECT cal_seco_mv, cal_mojado_mv FROM camas")[0]
    assert fila["cal_seco_mv"] is None and fila["cal_mojado_mv"] is None
    assert suelo(datos) == [100.0, 79.0]
    enviar(3, mv=1437, pct=100)
    assert suelo(datos)[-1] == 100.0


def test_calibracion_invalida_no_se_guarda(cliente, cama, datos):
    calibrar(cliente, cama, cal_seco_mv="980", cal_mojado_mv="3160")
    pagina = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Calibración de Cama A" in pagina and "más agua = menos mV" in pagina
    fila, = datos.consulta("SELECT cal_seco_mv FROM camas")
    assert fila["cal_seco_mv"] is None


def test_la_pagina_muestra_los_mv_actuales_y_el_porcentaje(enviar, cliente, cama):
    enviar(1, mv=1437)
    calibrar(cliente, cama, cal_seco_mv="3160", cal_mojado_mv="980")
    pagina = cliente.get("/configuracion/").get_data(as_text=True)
    assert 'id="calibracion-' in pagina
    assert "Ahora la sonda marca <strong>1437 mV</strong>" in pagina
    assert "<strong>79.0 %</strong>" in pagina


def test_sin_pin_no_se_puede_calibrar(cliente, cama, datos):
    r = cliente.post(f"/configuracion/camas/{cama}/calibracion",
                     data={"cal_seco_mv": "3160", "cal_mojado_mv": "980"})
    assert r.status_code in (302, 403)
    fila, = datos.consulta("SELECT cal_seco_mv FROM camas")
    assert fila["cal_seco_mv"] is None


def test_cama_inexistente_responde_404(cliente):
    csrf = ingresar(cliente)
    r = cliente.post("/configuracion/camas/999/calibracion", data={"csrf": csrf})
    assert r.status_code == 404

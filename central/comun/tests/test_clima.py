"""Clima externo: normalización de Open-Meteo y caché. Ningún test llama a internet."""

import copy
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from comun.clima import (DESACTUALIZADO, NO_CONFIGURADO, NO_DISPONIBLE, OK, CacheClima,
                         ClimaReferencia, ErrorClima, ProveedorClima, ProveedorOpenMeteo,
                         validar_coordenadas)
from comun.clima import open_meteo

FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_actual.json"
LAT, LON = -33.54, -70.64


@pytest.fixture
def respuesta():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class Reloj:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def avanzar(self, **kw):
        self.t += timedelta(**kw)


# ----------------------------------------------------------- normalización

def test_normaliza_respuesta_real_guardada(respuesta):
    c = open_meteo.normalizar(respuesta, LAT, LON)
    assert c.fuente == "open-meteo"
    assert c.temp_aire_c == 23.0
    assert c.hum_rel_pct == 67
    assert c.precipitacion_mm == 0.0
    assert c.radiacion_wm2 == 0.0
    # 22:00 hora de Chile (UTC-3) = 01:00 UTC del día siguiente
    assert c.observado_en == datetime(2026, 11, 28, 1, 0)
    # Valores de la hora 22 (índice 22), no del primer elemento del arreglo
    assert c.temp_suelo_c == 23.1
    assert c.hum_suelo_vwc_pct == 16.8           # 0.168 m³/m³ -> 16,8 % vol.
    assert c.et0_mm == 0.0
    assert c.et0_hoy_mm == pytest.approx(sum(respuesta["hourly"]["et0_fao_evapotranspiration"][:23]),
                                         abs=0.01)
    assert (c.lat, c.lon) == (LAT, LON)


def test_toma_la_hora_de_current_time_y_no_la_primera(respuesta):
    datos = copy.deepcopy(respuesta)
    datos["current"]["time"] = "2026-11-27T14:45"     # pasos de 15 min: corresponde la hora 14
    c = open_meteo.normalizar(datos, LAT, LON)
    h = datos["hourly"]
    assert c.temp_suelo_c == h["soil_temperature_0cm"][14] != h["soil_temperature_0cm"][0]
    assert c.hum_suelo_vwc_pct == round(h["soil_moisture_0_to_1cm"][14] * 100, 1)
    assert c.et0_mm == h["et0_fao_evapotranspiration"][14]
    assert c.observado_en == datetime(2026, 11, 27, 17, 45)


def test_hora_sin_datos_horarios_deja_none(respuesta):
    datos = copy.deepcopy(respuesta)
    datos["current"]["time"] = "2026-11-29T10:00"     # fuera del arreglo horario
    c = open_meteo.normalizar(datos, LAT, LON)
    assert c.temp_aire_c == 23.0
    assert c.temp_suelo_c is None and c.hum_suelo_vwc_pct is None and c.et0_mm is None


def test_campos_faltantes_son_none(respuesta):
    datos = copy.deepcopy(respuesta)
    del datos["current"]["shortwave_radiation"]
    del datos["hourly"]
    c = open_meteo.normalizar(datos, LAT, LON)
    assert c.radiacion_wm2 is None and c.temp_suelo_c is None


def test_respuesta_de_error_de_la_api():
    with pytest.raises(ErrorClima, match="Latitude"):
        open_meteo.normalizar({"error": True, "reason": "Latitude must be in range"}, 99, 0)


def test_parametros_usan_el_endpoint_de_la_api_y_las_variables_pedidas():
    pedidos = []

    def falso(url, params, timeout):
        pedidos.append((url, params, timeout))
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    ProveedorOpenMeteo(obtener_json=falso).obtener(LAT, LON, timeout=5)
    url, params, timeout = pedidos[0]
    assert url == "https://api.open-meteo.com/v1/forecast"
    assert params["current"] == "temperature_2m,relative_humidity_2m,precipitation,shortwave_radiation"
    assert params["hourly"] == "soil_temperature_0cm,soil_moisture_0_to_1cm,et0_fao_evapotranspiration"
    assert params["timezone"] == "America/Santiago"
    assert timeout == 5


def test_validar_coordenadas():
    assert validar_coordenadas(-33.54, -70.64) == []
    assert len(validar_coordenadas(-91, 181)) == 2
    assert validar_coordenadas("abc", 0) == ["La latitud debe ser un número."]


# ------------------------------------------------------------------ caché

def clima(t=datetime(2026, 11, 27, 15, 0), temp=20.0):
    return ClimaReferencia(temp, 50, 0, 800, None, None, None, t, "falso", LAT, LON)


class ProveedorFalso(ProveedorClima):
    nombre = "falso"

    def __init__(self):
        self.llamadas = 0
        self.falla = False

    def obtener(self, lat, lon, timeout=5):
        self.llamadas += 1
        if self.falla:
            raise ErrorClima("sin conexión (timed out)")
        return clima(temp=20.0 + self.llamadas)


def test_no_repite_la_peticion_dentro_del_ttl():
    reloj = Reloj(datetime(2026, 11, 27, 15, 0))
    p, cache = ProveedorFalso(), CacheClima(ttl_s=1200, reloj=reloj)
    assert cache.consultar(p, LAT, LON).estado == OK
    reloj.avanzar(minutes=19)
    r = cache.consultar(p, LAT, LON)
    assert (r.estado, p.llamadas) == (OK, 1)
    reloj.avanzar(minutes=2)
    cache.consultar(p, LAT, LON)
    assert p.llamadas == 2


def test_ante_error_usa_el_valor_desactualizado_con_su_hora():
    reloj = Reloj(datetime(2026, 11, 27, 15, 0))
    p, cache = ProveedorFalso(), CacheClima(ttl_s=1200, reloj=reloj)
    primero = cache.consultar(p, LAT, LON)
    p.falla = True
    reloj.avanzar(hours=2)
    r = cache.consultar(p, LAT, LON)
    assert r.estado == DESACTUALIZADO
    assert r.clima == primero.clima
    assert r.obtenido_en == datetime(2026, 11, 27, 15, 0)
    assert "sin conexión" in r.error


def test_sin_valor_previo_queda_no_disponible():
    p = ProveedorFalso()
    p.falla = True
    r = CacheClima(reloj=Reloj(datetime(2026, 11, 27, 15, 0))).consultar(p, LAT, LON)
    assert (r.estado, r.clima) == (NO_DISPONIBLE, None)


def test_sin_valor_en_memoria_usa_el_respaldo_de_la_bd():
    p = ProveedorFalso()
    p.falla = True
    guardado = clima(temp=11.0)
    cache = CacheClima(reloj=Reloj(datetime(2026, 11, 27, 15, 0)),
                       respaldo=lambda fuente, lat, lon: guardado)
    r = cache.consultar(p, LAT, LON)
    assert (r.estado, r.clima) == (DESACTUALIZADO, guardado)


def test_tras_un_error_no_reintenta_en_cada_visita():
    reloj = Reloj(datetime(2026, 11, 27, 15, 0))
    p = ProveedorFalso()
    p.falla = True
    cache = CacheClima(espera_tras_error_s=120, reloj=reloj)
    for _ in range(5):
        cache.consultar(p, LAT, LON)
    assert p.llamadas == 1
    reloj.avanzar(minutes=3)
    cache.consultar(p, LAT, LON)
    assert p.llamadas == 2


def test_forzar_ignora_ttl_y_espera():
    reloj = Reloj(datetime(2026, 11, 27, 15, 0))
    p, cache = ProveedorFalso(), CacheClima(reloj=reloj)
    cache.consultar(p, LAT, LON)
    cache.consultar(p, LAT, LON, forzar=True)
    assert p.llamadas == 2


def test_un_solo_aviso_en_el_log_por_falla(caplog):
    reloj = Reloj(datetime(2026, 11, 27, 15, 0))
    p = ProveedorFalso()
    cache = CacheClima(espera_tras_error_s=0, reloj=reloj)
    p.falla = True
    with caplog.at_level(logging.WARNING, logger="comun.clima.cache"):
        for _ in range(4):
            cache.consultar(p, LAT, LON)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    # Se recupera y vuelve a fallar: un aviso nuevo
    p.falla = False
    cache.consultar(p, LAT, LON, forzar=True)
    p.falla = True
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="comun.clima.cache"):
        cache.consultar(p, LAT, LON, forzar=True)
        cache.consultar(p, LAT, LON, forzar=True)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_proveedor_no_configurado_no_llama_ni_falla():
    class SinClave(ProveedorFalso):
        def motivo_no_configurado(self):
            return "Falta la API key"

    p = SinClave()
    r = CacheClima().consultar(p, LAT, LON)
    assert (r.estado, r.error, p.llamadas) == (NO_CONFIGURADO, "Falta la API key", 0)


def test_un_error_inesperado_del_proveedor_no_se_propaga():
    class Roto(ProveedorFalso):
        def obtener(self, lat, lon, timeout=5):
            raise KeyError("x")

    r = CacheClima().consultar(Roto(), LAT, LON)
    assert r.estado == NO_DISPONIBLE


def test_edad_del_dato():
    c = clima(t=datetime(2026, 11, 27, 15, 0))
    from comun.clima import ResultadoClima
    r = ResultadoClima(OK, c, datetime(2026, 11, 27, 15, 5))
    assert r.edad_s(datetime(2026, 11, 27, 15, 12)) == 12 * 60

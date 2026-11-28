"""Proveedores opcionales (DMC y OpenWeatherMap) y selección. Sin internet.

Las respuestas de ejemplo siguen el formato de la documentación oficial
de cada proveedor (no son respuestas reales: no hay credenciales).
"""

from datetime import datetime

import pytest

from comun.clima import NO_CONFIGURADO, CacheClima, ErrorClima
from comun.clima import dmc, openweather
from comun.clima.dmc import ProveedorDMC, numero_con_unidad
from comun.clima.openweather import ProveedorOpenWeather
from comun.clima.proveedores import crear_proveedor, nombres

LAT, LON = -33.54, -70.64


def respuesta_dmc(datos):
    """Estructura del ejemplo de getDatosRecientesEma (getDocumento/2 de la DMC)."""
    return {"organismo": "DMC", "timezone": "UTC", "producto": "Datos recientes",
            "registros": len(datos), "status": "Estación con datos disponibles recientemente",
            "datosEstaciones": {
                "estacion": {"codigoNacional": "330020", "latitud": "-33.44500",
                             "longitud": "-70.68278", "altura": 527},
                "datos": datos}}


def fila(momento, temp="21.4 °C", hum="45 %", rad="812.500 Watt/m2", lluvia="0.0 mm"):
    return {"momento": momento, "temperatura": temp, "humedadRelativa": hum,
            "radiacionGlobalInst": rad, "aguaCaidaDelMinuto": lluvia, "temperatura02Mts": None}


# --------------------------------------------------------------- selección

def test_proveedores_registrados():
    assert nombres() == ("open-meteo", "dmc", "openweather")


def test_dmc_y_openweather_sin_credenciales_aparecen_no_configurados():
    d = crear_proveedor("dmc", entorno={})
    o = crear_proveedor("openweather", entorno={})
    assert not d.configurado() and "DMC_USER_EMAIL y DMC_API_TOKEN" in d.motivo_no_configurado()
    assert not o.configurado() and "OPENWEATHER_API_KEY" in o.motivo_no_configurado()
    # Seleccionados igual: «no configurado», sin errores ni llamadas a la red
    for p in (d, o):
        r = CacheClima().consultar(p, LAT, LON)
        assert r.estado == NO_CONFIGURADO and r.clima is None


def test_dmc_con_credenciales_pero_sin_estacion():
    p = crear_proveedor("dmc", entorno={"DMC_USER_EMAIL": "a@b.cl", "DMC_API_TOKEN": "x"})
    assert "estación" in p.motivo_no_configurado()
    p.aplicar_ajustes({"dmc_estacion": "330020"})
    assert p.configurado()


def test_nombre_desconocido_usa_open_meteo():
    assert crear_proveedor("otro", entorno={}).nombre == "open-meteo"


# -------------------------------------------------------------------- DMC

def test_numero_con_unidad():
    assert numero_con_unidad("8.0 °C") == 8.0
    assert numero_con_unidad("79 %") == 79.0
    assert numero_con_unidad("158.900 Watt/m2") == 158.9
    assert numero_con_unidad("-1,5 °C") == -1.5
    assert numero_con_unidad(None) is None and numero_con_unidad("") is None


def test_dmc_normaliza_y_usa_el_momento_mas_reciente_sin_importar_el_orden():
    datos = respuesta_dmc([fila("2026-11-27 18:02:00", temp="22.0 °C", lluvia="0.2 mm"),
                           fila("2026-11-27 16:30:00", temp="19.0 °C", lluvia="5.0 mm"),
                           fila("2026-11-27 17:30:00", temp="21.0 °C", lluvia="0.3 mm")])
    c = dmc.normalizar(datos, LAT, LON)
    assert c.fuente == "dmc"
    assert c.observado_en == datetime(2026, 11, 27, 18, 2)       # UTC según la DMC
    assert (c.temp_aire_c, c.hum_rel_pct, c.radiacion_wm2) == (22.0, 45.0, 812.5)
    # Lluvia de la última hora: 0,2 + 0,3 (la de las 16:30 queda fuera)
    assert c.precipitacion_mm == 0.5
    # Coordenadas de la estación, sin datos de suelo ni ET0
    assert (c.lat, c.lon) == (-33.445, -70.68278)
    assert c.temp_suelo_c is None and c.hum_suelo_vwc_pct is None and c.et0_mm is None


def test_dmc_sin_datos_es_un_error_controlado():
    with pytest.raises(ErrorClima):
        dmc.normalizar(respuesta_dmc([]), LAT, LON)
    with pytest.raises(ErrorClima):
        dmc.normalizar({"mensaje": "token inválido"}, LAT, LON)


def test_dmc_pide_la_url_documentada_de_la_estacion():
    pedidos = []

    def falso(url, params, timeout):
        pedidos.append((url, params))
        return respuesta_dmc([fila("2026-11-27 18:00:00")])

    p = ProveedorDMC("a@b.cl", "secreto", "330020", obtener_json=falso)
    p.obtener(LAT, LON)
    assert pedidos == [(
        "https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesEma/330020",
        {"usuario": "a@b.cl", "token": "secreto"})]


# ---------------------------------------------------------- OpenWeatherMap

OWM = {"coord": {"lon": -70.64, "lat": -33.54}, "main": {"temp": 24.3, "humidity": 38},
       "dt": 1795791600, "timezone": -10800, "name": "La Pintana", "cod": 200}


def test_openweather_normaliza_current_weather():
    c = openweather.normalizar(OWM, LAT, LON)
    assert (c.fuente, c.temp_aire_c, c.hum_rel_pct) == ("openweather", 24.3, 38.0)
    assert c.observado_en == datetime(2026, 11, 27, 15, 0)        # dt es unix UTC
    # Sin lluvia en la respuesta: no se inventa un 0. Sin radiación ni suelo.
    assert c.precipitacion_mm is None and c.radiacion_wm2 is None and c.hum_suelo_vwc_pct is None


def test_openweather_con_lluvia():
    c = openweather.normalizar({**OWM, "rain": {"1h": 1.4}}, LAT, LON)
    assert c.precipitacion_mm == 1.4


def test_openweather_pide_unidades_metricas():
    pedidos = []

    def falso(url, params, timeout):
        pedidos.append((url, params))
        return OWM

    ProveedorOpenWeather("clave", obtener_json=falso).obtener(LAT, LON)
    url, params = pedidos[0]
    assert url == "https://api.openweathermap.org/data/2.5/weather"
    assert params == {"lat": LAT, "lon": LON, "appid": "clave", "units": "metric"}


def test_openweather_clave_rechazada_sin_mostrar_la_clave():
    def rechazo(url, params, timeout):
        raise ErrorClima("HTTP 401")

    with pytest.raises(ErrorClima) as e:
        ProveedorOpenWeather("mi-clave-secreta", obtener_json=rechazo).obtener(LAT, LON)
    assert "401" in str(e.value) and "mi-clave-secreta" not in str(e.value)

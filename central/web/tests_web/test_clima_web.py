"""Clima exterior en el tablero. Nunca se llama a internet (proveedor falso)."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from comun.clima import ClimaReferencia
from comun.clima import repositorio as repo_clima
from pruebas.bd import INICIO

pytestmark = pytest.mark.bd


def instantanea(bd, t, temp=25.0, hum=40.0):
    repo_clima.guardar_instantanea(
        bd, ClimaReferencia(temp, hum, 0, 800, 30, 16.8, 0.5, t, "open-meteo", -33.54, -70.64, 4.2), t)
    bd.commit()


# ------------------------------------------------------------ /api/clima/actual

def test_clima_actual_ok(cliente):
    d = cliente.get("/api/clima/actual").get_json()
    assert d["estado"] == "ok"
    assert d["texto_estado"] == "Open-Meteo · hace 12 min"
    assert d["clima"]["temp_aire_c"] == 25.0
    assert d["edad_s"] == 12 * 60
    assert d["et0"] == "La zona perdió 4,2 mm de agua hoy por evaporación"


def test_clima_actual_usa_la_cache(cliente, clima_falso):
    cliente.get("/api/clima/actual")
    cliente.get("/api/clima/actual")
    assert clima_falso.llamadas == 1


def test_sin_internet_y_sin_datos_queda_no_disponible(cliente, clima_falso):
    clima_falso.falla = True
    d = cliente.get("/api/clima/actual").get_json()
    assert (d["estado"], d["texto_estado"], d["clima"]) == (
        "no_disponible", "Clima exterior no disponible", None)


def test_sin_internet_usa_el_ultimo_dato_guardado(cliente, clima_falso, bd):
    instantanea(bd, INICIO - timedelta(hours=2))
    clima_falso.falla = True
    d = cliente.get("/api/clima/actual").get_json()
    assert d["estado"] == "desactualizado"
    assert d["texto_estado"].startswith("Dato de hace 2 h")


def test_la_respuesta_no_expone_credenciales(cliente):
    texto = cliente.get("/api/clima/actual").get_data(as_text=True).lower()
    assert "token" not in texto and "api_key" not in texto and "appid" not in texto


# ------------------------------------------------- la página no depende del clima

def test_timeout_de_la_api_no_afecta_la_vista_de_camas(cliente, datos, clima_falso):
    cama = datos.cama("cama-a", "Cama A")
    datos.lectura(cama, INICIO, 1)
    clima_falso.demora_s = 3
    inicio = time.monotonic()
    r = cliente.get("/api/tablero")
    assert r.status_code == 200 and r.get_json()["camas"][0]["nombre"] == "Cama A"
    assert cliente.get("/").status_code == 200
    assert cliente.get(f"/cama/{cama}").status_code == 200
    assert cliente.get("/api/alertas").status_code == 200
    assert time.monotonic() - inicio < 1.5
    # Ninguna de esas vistas consultó el clima: se pide aparte
    assert clima_falso.llamadas == 0
    # El bloque de clima responde «no disponible» sin romper nada
    assert cliente.get("/api/clima/actual").get_json()["estado"] == "no_disponible"


def test_tablero_carga_el_clima_aparte(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert 'id="clima-exterior"' in html and "js/clima.js" in html


# ------------------------------------------------------------- comparación

def test_comparacion_de_cada_cama_con_la_misma_hora(cliente, datos, bd):
    cama = datos.cama("cama-a", "Cama A")
    datos.lectura(cama, INICIO, 1, temp=28.0)                 # hum_aire = 60
    instantanea(bd, INICIO - timedelta(minutes=20), temp=25.0, hum=40.0)
    d = cliente.get("/api/clima/camas").get_json()
    c = d["camas"][0]["comparacion"]
    assert c["temperatura"]["texto"] == "+3 °C más que afuera"
    assert c["humedad_aire"]["texto"] == "+20 puntos más húmedo que afuera"
    assert c["fuente_nombre"] == "Open-Meteo"


def test_sin_referencia_cercana_no_hay_delta(cliente, datos, bd):
    cama = datos.cama("cama-a", "Cama A")
    datos.lectura(cama, INICIO - timedelta(hours=3), 1)
    instantanea(bd, INICIO)                                   # 3 h después: muy lejos
    assert cliente.get("/api/clima/camas").get_json()["camas"][0]["comparacion"] is None


def test_detalle_compara_y_entrega_la_serie_horaria(cliente, datos, bd):
    cama = datos.cama("cama-a", "Cama A")
    datos.lectura(cama, INICIO, 1, temp=25.0, suelo=55.0)
    for h in range(3):
        instantanea(bd, INICIO - timedelta(hours=h), temp=24.0 + h)
    d = cliente.get(f"/api/camas/{cama}/clima?horas=24").get_json()
    assert d["comparacion"]["temperatura"]["texto"] == "similar al exterior"
    # Suelo: solo referencia del modelo, sin diferencia
    assert d["comparacion"]["suelo_zona"] == "Suelo de la zona (modelo): 17 % vol."
    assert "suelo" not in d["comparacion"]
    assert [p["temp"] for p in d["serie"]] == [26.0, 25.0, 24.0]
    assert d["lectura"]["suelo_prom"] == 55.0


def test_detalle_de_cama_inexistente(cliente):
    assert cliente.get("/api/camas/9999/clima").status_code == 404


# ------------------------------------------------------------- configuración

from .conftest import ingresar  # noqa: E402


def test_configuracion_muestra_el_clima_y_el_estado_de_los_proveedores(cliente):
    ingresar(cliente)
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert 'id="clima"' in html and "Probar conexión" in html
    assert 'value="-33.54"' in html and 'value="-70.64"' in html
    assert "Configurado" in html


def test_guardar_coordenadas_del_clima(cliente, clima_falso):
    csrf = ingresar(cliente)
    cliente.get("/api/clima/actual")
    r = cliente.post("/configuracion/clima", data={
        "csrf": csrf, "clima_proveedor": "open-meteo", "clima_lat": "-36,82", "clima_lon": "-73.05"})
    assert r.status_code == 302
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Ajustes del clima exterior guardados." in html and 'value="-36.82"' in html
    # La caché se vació: el tablero consulta con las coordenadas nuevas
    d = cliente.get("/api/clima/actual").get_json()
    assert (d["clima"]["lat"], d["clima"]["lon"]) == (-36.82, -73.05)
    assert clima_falso.llamadas == 2


def test_coordenadas_invalidas_no_se_guardan(cliente):
    csrf = ingresar(cliente)
    cliente.post("/configuracion/clima", data={
        "csrf": csrf, "clima_proveedor": "open-meteo", "clima_lat": "-95", "clima_lon": "200"})
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "La latitud debe estar entre -90 y 90." in html
    assert "La longitud debe estar entre -180 y 180." in html
    assert 'value="-33.54"' in html


def test_proveedor_desconocido_no_se_guarda(cliente):
    csrf = ingresar(cliente)
    cliente.post("/configuracion/clima", data={
        "csrf": csrf, "clima_proveedor": "inventado", "clima_lat": "-33", "clima_lon": "-70"})
    assert "Proveedor de clima desconocido." in cliente.get("/configuracion/").get_data(as_text=True)


def test_probar_conexion_ok_con_las_coordenadas_escritas(cliente, clima_falso):
    csrf = ingresar(cliente)
    cliente.post("/configuracion/clima/probar", data={
        "csrf": csrf, "clima_proveedor": "open-meteo", "clima_lat": "-20.2", "clima_lon": "-70.1"})
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Conexión correcta con Open-Meteo: 25 °C, 40 % de humedad" in html
    # Probar no guarda: siguen las coordenadas anteriores
    assert 'value="-33.54"' in html


def test_probar_conexion_ignora_la_cache_y_avisa_la_falla(cliente, clima_falso):
    csrf = ingresar(cliente)
    cliente.get("/api/clima/actual")
    clima_falso.falla = True
    cliente.post("/configuracion/clima/probar", data={"csrf": csrf, "clima_proveedor": "open-meteo"})
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "No se pudo conectar con Open-Meteo: sin conexión." in html
    assert clima_falso.llamadas == 2


def test_clima_en_configuracion_requiere_pin_y_csrf(cliente):
    assert cliente.post("/configuracion/clima", data={"clima_lat": "0"}).status_code == 403
    assert cliente.post("/configuracion/clima/probar").status_code == 403
    ingresar(cliente)
    assert cliente.post("/configuracion/clima", data={"csrf": "malo"}).status_code == 400


def test_configuracion_muestra_proveedores_no_configurados(bd, difusor, reloj):
    """Con los proveedores reales y sin credenciales en el entorno."""
    from comun.clima.proveedores import crear_proveedor
    from comun.db import conectar
    from pruebas.bd import CFG
    from web import crear_app
    from web.config import ConfigWeb

    from .conftest import PIN

    app = crear_app(ConfigWeb(bd=CFG, pin_docente=PIN, clave_sesion="x"), difusor=difusor,
                    conectar_bd=lambda: conectar(CFG), reloj=reloj,
                    crear_proveedor_clima=lambda n: crear_proveedor(n, entorno={}))
    cliente = app.test_client()
    csrf = ingresar(cliente)
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "No configurado</span>: falta DMC_USER_EMAIL y DMC_API_TOKEN" in html
    assert "No configurado</span>: falta OPENWEATHER_API_KEY" in html
    # Elegir un proveedor sin claves no da error: «no configurado»
    cliente.post("/configuracion/clima", data={"csrf": csrf, "clima_proveedor": "openweather",
                                               "clima_lat": "-33.54", "clima_lon": "-70.64"})
    d = cliente.get("/api/clima/actual").get_json()
    assert (d["estado"], d["texto_estado"]) == ("no_configurado", "Clima exterior no disponible")
    cliente.post("/configuracion/clima/probar", data={"csrf": csrf, "clima_proveedor": "dmc",
                                                      "dmc_estacion": "330020"})
    assert "DMC no está configurado: falta DMC_USER_EMAIL" in cliente.get("/configuracion/").get_data(as_text=True)


def test_estacion_dmc_invalida(cliente):
    csrf = ingresar(cliente)
    cliente.post("/configuracion/clima", data={"csrf": csrf, "clima_proveedor": "open-meteo",
                                               "clima_lat": "-33", "clima_lon": "-70",
                                               "dmc_estacion": "abc"})
    assert "solo números" in cliente.get("/configuracion/").get_data(as_text=True)

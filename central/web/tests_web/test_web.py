"""Tablero web: API, tiempo real, mediciones de calidad y configuración con PIN."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pruebas.bd import INICIO
from web.formularios import validar_cama, validar_cultivo

from .conftest import PIN, ingresar

pytestmark = pytest.mark.bd
MIN = timedelta(minutes=1)


# =========================================================================
# Páginas
# =========================================================================

def test_paginas_y_archivos_locales(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    r = cliente.get("/")
    assert r.status_code == 200 and "Huerto Inteligente" in r.get_data(as_text=True)
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    # Chart.js se sirve desde la Pi (sin internet)
    assert cliente.get("/static/vendor/chart-4.6.2.umd.min.js").status_code == 200
    assert cliente.get(f"/cama/{cama}").status_code == 200
    assert cliente.get("/cama/9999").status_code == 404


def test_modo_kiosco(cliente):
    assert 'data-kiosco="1"' in cliente.get("/?kiosco=1").get_data(as_text=True)
    assert 'data-kiosco="0"' in cliente.get("/").get_data(as_text=True)


# =========================================================================
# API del tablero
# =========================================================================

def test_tablero_usa_la_tarjeta_del_procesador(cliente, datos, difusor):
    cama = datos.cama("cama-a", "Cama A")
    tarjeta = {"cama_id": cama, "nodo_id": "cama-a", "nombre": "Nombre viejo", "color": "rojo",
               "mensaje": "Revisar: humedad 22 %", "lectura": {"seq": 1, "medido_en": "2026-11-26T15:00:00Z",
               "suelo_prom": 22}, "horas_luz_hoy": 3.5, "texto_luz": "3,5 h de luz"}
    difusor.recibir("huerto/tablero/cama/cama-a", json.dumps(tarjeta).encode())
    difusor.recibir("huerto/nodo/cama-a/conexion", b"online")

    [t] = cliente.get("/api/tablero").get_json()["camas"]
    assert (t["color"], t["mensaje"], t["horas_luz_hoy"]) == ("rojo", "Revisar: humedad 22 %", 3.5)
    assert t["nombre"] == "Cama A"            # el nombre siempre viene fresco de la BD
    assert t["cultivo"] == "tomate" and t["conexion"] == "online"


def test_tablero_sin_tarjeta_usa_la_bd(cliente, datos):
    a = datos.cama("cama-a", "Cama A")
    datos.cama("cama-b", "Cama B")
    datos.lectura(a, INICIO, seq=1, suelo=45)
    datos.estado(a, "verde", "Todo bien", INICIO)

    camas = {t["nodo_id"]: t for t in cliente.get("/api/tablero").get_json()["camas"]}
    assert camas["cama-a"]["color"] == "verde" and camas["cama-a"]["lectura"]["suelo_prom"] == 45
    assert camas["cama-b"]["mensaje"] == "Sin lecturas" and camas["cama-b"]["lectura"] is None


def test_camas_desactivadas_no_aparecen(cliente, datos):
    datos.cama("cama-a", "Cama A")
    datos.cama("cama-z", "Cama Z", activa=0)
    assert [t["nodo_id"] for t in cliente.get("/api/tablero").get_json()["camas"]] == ["cama-a"]


def test_avisos_abiertos_y_resueltos_de_hoy(cliente, datos):
    cama = datos.cama("cama-b", "Cama B")
    datos.alerta(cama, "suelo_seco", "Cama B seca: 22 % (ideal 30 % a 70 %)", INICIO - 30 * MIN)
    datos.alerta(cama, "helada", "Riesgo de helada en cama B: 4 °C. Cubre la planta",
                 INICIO - 5 * timedelta(hours=1), INICIO - 4 * timedelta(hours=1), variable="temperatura")
    datos.alerta(cama, "calor", "ayer", INICIO - timedelta(days=1),
                 INICIO - timedelta(days=1) + 40 * MIN, variable="temperatura")

    r = cliente.get("/api/alertas").get_json()
    assert [a["mensaje"] for a in r["abiertas"]] == ["Cama B seca: 22 % (ideal 30 % a 70 %)"]
    [resuelta] = r["resueltas_hoy"]                  # la de ayer no aparece
    assert resuelta["tipo"] == "helada"
    assert resuelta["iniciada_en"] == "2026-11-26T10:00:00Z"
    assert resuelta["resuelta_en"] == "2026-11-26T11:00:00Z"


def test_serie_para_graficos_con_rango_y_huecos(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    for i in range(0, 60, 2):
        datos.lectura(cama, INICIO - 3 * timedelta(hours=1) + i * MIN, seq=i, suelo=40 + i / 10)
    for i in range(0, 30, 2):                       # 1 h 30 min sin datos y luego vuelve
        datos.lectura(cama, INICIO - 30 * MIN + i * MIN, seq=100 + i, suelo=35)

    r = cliente.get(f"/api/camas/{cama}/serie?horas=24").get_json()
    assert r["rango"]["humedad_min"] == 30 and r["rango"]["humedad_max"] == 70
    assert r["umbral_luz"] == 25000
    puntos = r["puntos"]
    assert any(p["suelo"] is None for p in puntos)    # el hueco corta la línea
    assert puntos[-1]["suelo"] == 35
    assert cliente.get("/api/camas/9999/serie").status_code == 404


# =========================================================================
# Tiempo real (SSE)
# =========================================================================

def test_eventos_en_tiempo_real(cliente, difusor):
    respuesta = cliente.get("/api/eventos")
    assert respuesta.mimetype == "text/event-stream"
    flujo = iter(respuesta.response)
    assert next(flujo).decode().startswith("retry:")
    assert difusor.clientes == 1
    difusor.recibir("huerto/tablero/cama/cama-a",
                    json.dumps({"nodo_id": "cama-a", "mensaje": "Todo bien"}).encode())
    evento = next(flujo).decode()
    assert evento.startswith("event: tarjeta\n")
    assert json.loads(evento.split("data: ", 1)[1])["mensaje"] == "Todo bien"
    respuesta.close()
    assert difusor.clientes == 0                   # el navegador se fue: se libera


# =========================================================================
# CQ-02 y CQ-03: mediciones desde la pantalla del kiosco
# =========================================================================

def test_registra_latencia_de_pantalla(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    r = cliente.post("/api/latencia", json={"nodo_id": "cama-a", "seq": 7,
                                            "medido_en": "2026-11-26T15:00:00Z",
                                            "mostrado_en": "2026-11-26T15:00:03.250Z"})
    assert r.status_code == 201 and r.get_json()["latencia_ms"] == 3250
    [fila] = datos.consulta("SELECT * FROM latencias_pantalla")
    assert fila["cama_id"] == cama and fila["latencia_ms"] == 3250


@pytest.mark.parametrize("cuerpo, codigo", [
    ({"nodo_id": "cama-a", "seq": 7, "medido_en": "x", "mostrado_en": "2026-11-26T15:00:03Z"}, 400),
    ({"nodo_id": "cama-a", "seq": "7", "medido_en": "2026-11-26T15:00:00Z", "mostrado_en": "2026-11-26T15:00:03Z"}, 400),
    ({"nodo_id": "cama-a", "seq": 7, "medido_en": "2026-11-26T15:00:00Z", "mostrado_en": "2026-11-20T15:00:03Z"}, 422),
    ({"nodo_id": "no-existe", "seq": 7, "medido_en": "2026-11-26T15:00:00Z", "mostrado_en": "2026-11-26T15:00:03Z"}, 404),
])
def test_latencia_rechaza_datos_malos(cliente, datos, cuerpo, codigo):
    datos.cama("cama-a", "Cama A")
    assert cliente.post("/api/latencia", json=cuerpo).status_code == codigo


def test_latencia_exige_json(cliente):
    assert cliente.post("/api/latencia", data="nodo_id=x").status_code == 415


def test_marca_avisos_visibles_una_sola_vez(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    alerta = datos.alerta(cama, "suelo_seco", "Cama A seca", INICIO)
    datos.evento_apertura(alerta, INICIO)
    r = cliente.post("/api/alertas/visibles", json={"ids": [alerta], "visible_en": "2026-11-26T15:00:04Z"})
    assert r.get_json()["marcadas"] == 1
    cliente.post("/api/alertas/visibles", json={"ids": [alerta], "visible_en": "2026-11-26T15:09:00Z"})
    [ev] = datos.consulta("SELECT visible_en FROM eventos_alerta")
    assert ev["visible_en"].strftime("%H:%M:%S") == "15:00:04"     # se conserva la primera


# =========================================================================
# Configuración con PIN
# =========================================================================

def test_configuracion_pide_pin(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    assert 'name="pin"' in cliente.get("/configuracion/").get_data(as_text=True)
    assert cliente.post(f"/configuracion/camas/{cama}", data={"nombre": "X"}).status_code == 403


def test_pin_incorrecto_y_bloqueo_tras_5_intentos(cliente):
    for _ in range(4):
        assert cliente.post("/configuracion/ingresar", data={"pin": "0000"}).status_code == 401
    assert cliente.post("/configuracion/ingresar", data={"pin": "0000"}).status_code == 401
    # Bloqueado: ni el PIN correcto entra
    assert cliente.post("/configuracion/ingresar", data={"pin": PIN}).status_code == 429


def test_sin_pin_definido_la_configuracion_queda_desactivada(app, cliente):
    app.extensions["huerto"].cfg = type(app.extensions["huerto"].cfg)(pin_docente="cambia_esto")
    assert cliente.post("/configuracion/ingresar", data={"pin": "cambia_esto"}).status_code == 503


def test_guardar_cama_y_avisar_al_procesador(cliente, datos, difusor):
    cama = datos.cama("cama-a", "Cama A", cultivo=None)
    csrf = ingresar(cliente)
    pagina = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Cama A" in pagina and "tomate" in pagina

    r = cliente.post(f"/configuracion/camas/{cama}", data={
        "csrf": csrf, "nombre": "Cama del norte", "cultivo_id": str(datos.cultivo_id("tomate")),
        "zona_climatica": "Coquimbo", "humedad_min": "35,5", "humedad_max": "", "activa": "1"})
    assert r.status_code == 302
    [fila] = datos.consulta("SELECT * FROM camas")
    assert (fila["nombre"], fila["zona_climatica"], float(fila["humedad_min"])) == \
        ("Cama del norte", "Coquimbo", 35.5)
    assert fila["humedad_max"] is None                 # vacío = usar el del cultivo
    assert difusor.avisos_configuracion == [cama]


def test_guardar_sin_token_csrf_se_rechaza(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    ingresar(cliente)
    assert cliente.post(f"/configuracion/camas/{cama}", data={"nombre": "X"}).status_code == 400


def test_rango_invalido_no_se_guarda(cliente, datos, difusor):
    cama = datos.cama("cama-a", "Cama A")
    csrf = ingresar(cliente)
    r = cliente.post(f"/configuracion/camas/{cama}", data={
        "csrf": csrf, "nombre": "Cama A", "cultivo_id": str(datos.cultivo_id("tomate")),
        "humedad_min": "80", "activa": "1"}, follow_redirects=True)
    assert "es mayor que el máximo" in r.get_data(as_text=True)    # 80 > 70 del tomate
    assert datos.consulta("SELECT humedad_min FROM camas")[0]["humedad_min"] is None
    assert difusor.avisos_configuracion == []


def test_editar_cultivo_avisa_a_sus_camas(cliente, datos, difusor):
    a = datos.cama("cama-a", "Cama A")
    datos.cama("cama-b", "Cama B", cultivo="lechuga")
    csrf = ingresar(cliente)
    tomate = datos.cultivo_id("tomate")
    cliente.post(f"/configuracion/cultivos/{tomate}", data={
        "csrf": csrf, "nombre": "tomate", "humedad_min": "35", "humedad_max": "65",
        "temp_min": "15", "temp_max": "30", "horas_luz_min": "6"})
    assert float(datos.consulta("SELECT humedad_min FROM cultivos WHERE id=%s", (tomate,))[0]["humedad_min"]) == 35
    assert datos.consulta("SELECT por_confirmar FROM cultivos WHERE id=%s", (tomate,))[0]["por_confirmar"] == 0
    assert difusor.avisos_configuracion == [a]


def test_agregar_cultivo_y_nombre_repetido(cliente, datos):
    csrf = ingresar(cliente)
    cliente.post("/configuracion/cultivos", data={"csrf": csrf, "nombre": "Acelga", "humedad_min": "35",
                                                  "tolera_sombra": "1", "por_confirmar": "1"})
    r = cliente.post("/configuracion/cultivos", data={"csrf": csrf, "nombre": "acelga"},
                     follow_redirects=True)
    assert "Ya existe un cultivo llamado «acelga»" in r.get_data(as_text=True)
    assert len(datos.consulta("SELECT * FROM cultivos WHERE nombre='acelga'")) == 1


def test_marcar_incidencia_revisada(cliente, datos):
    datos._ejecutar("""INSERT INTO incidencias (nodo_id, tipo, detalle, ocurrido_en)
                       VALUES ('cama-a', 'seq_reiniciado', 'contador en cero', %s)""", (INICIO,))
    csrf = ingresar(cliente)
    assert "contador en cero" in cliente.get("/configuracion/").get_data(as_text=True)
    [inc] = datos.consulta("SELECT id FROM incidencias")
    cliente.post(f"/configuracion/incidencias/{inc['id']}/revisada", data={"csrf": csrf})
    assert datos.consulta("SELECT revisada FROM incidencias")[0]["revisada"] == 1


def test_salir_cierra_la_sesion(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    csrf = ingresar(cliente)
    cliente.post("/configuracion/salir")
    assert cliente.post(f"/configuracion/camas/{cama}", data={"csrf": csrf, "nombre": "X"}).status_code == 403


# =========================================================================
# Validación de formularios (puros)
# =========================================================================

def test_formulario_acepta_coma_decimal_y_rechaza_fuera_de_rango():
    valores, errores = validar_cama({"nombre": "A", "humedad_min": "30,5", "temp_max": "95"}, {})
    assert valores["humedad_min"] == 30.5
    assert errores == ["Temperatura máxima: debe estar entre -40 y 80 °C."]


def test_formulario_texto_no_numerico():
    _, errores = validar_cultivo({"nombre": "x", "horas_luz_min": "mucha"}, set())
    assert errores == ["Horas de luz mínimas: «mucha» no es un número."]

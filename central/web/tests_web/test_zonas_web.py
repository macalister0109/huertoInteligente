"""Configuración de zonas climáticas en /configuracion."""

from __future__ import annotations

import pytest

from comun import ajustes
from pruebas.bd import CFG

from .conftest import ingresar

pytestmark = pytest.mark.bd


def zona_id(datos, codigo):
    return datos.consulta("SELECT id FROM zonas_climaticas WHERE codigo = %s", (codigo,))[0]["id"]


def test_pagina_muestra_zonas_y_rangos_por_zona(cliente, datos):
    datos.cama("cama-a", "Cama A")
    ingresar(cliente)
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert 'id="zonas"' in html and 'name="zona_huerto"' in html
    assert "La del huerto (Centro)" in html                       # opción por defecto de la cama
    assert "tomate por zona" in html and "lechuga por zona" in html
    assert 'placeholder="Zona Centro: 30"' in html                # valor heredado de la zona
    assert "INIA / INDAP" in html


def test_guardar_zona_del_huerto(cliente, datos, difusor, bd):
    cama = datos.cama("cama-a", "Cama A")
    csrf = ingresar(cliente)
    cliente.post("/configuracion/zona", data={"csrf": csrf, "zona_huerto": "sur"})
    bd.commit()
    assert ajustes.leer(bd, CFG)["zona_huerto"] == "sur"
    assert cama in difusor.avisos_configuracion                  # el procesador reevalúa las camas
    assert "Zona del huerto: Sur" in cliente.get("/configuracion/").get_data(as_text=True)
    cliente.post("/configuracion/zona", data={"csrf": csrf, "zona_huerto": "luna"})
    assert "la zona elegida no existe" in cliente.get("/configuracion/").get_data(as_text=True)


def test_elegir_zona_de_una_cama(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    csrf = ingresar(cliente)
    norte = zona_id(datos, "norte")
    cliente.post(f"/configuracion/camas/{cama}", data={
        "csrf": csrf, "nombre": "Cama A", "cultivo_id": datos.cultivo_id("tomate"), "zona_id": norte,
        "activa": "1"})
    fila = datos.consulta("SELECT zona_id FROM camas WHERE id = %s", (cama,))[0]
    assert fila["zona_id"] == norte
    assert "Zona: Norte" in cliente.get(f"/cama/{cama}").get_data(as_text=True)
    # Volver a «la del huerto»
    cliente.post(f"/configuracion/camas/{cama}", data={
        "csrf": csrf, "nombre": "Cama A", "cultivo_id": datos.cultivo_id("tomate"), "zona_id": "",
        "activa": "1"})
    assert datos.consulta("SELECT zona_id FROM camas WHERE id = %s", (cama,))[0]["zona_id"] is None
    html = cliente.get(f"/cama/{cama}").get_data(as_text=True)
    assert "Zona: Centro (la del huerto)" in html and "por confirmar" in html


def test_editar_rangos_de_un_cultivo_por_zona(cliente, datos, difusor):
    datos.cama("cama-a", "Cama A")
    csrf = ingresar(cliente)
    tomate, norte, sur = datos.cultivo_id("tomate"), zona_id(datos, "norte"), zona_id(datos, "sur")
    formulario = {"csrf": csrf, f"z{norte}_humedad_min": "38", f"z{norte}_humedad_max": "72",
                  f"z{norte}_temp_max": "33,5"}                    # sur y centro quedan vacíos
    cliente.post(f"/configuracion/cultivos/{tomate}/zonas", data=formulario)
    filas = {f["zona_id"]: f for f in datos.consulta(
        "SELECT * FROM rangos_cultivo_zona WHERE cultivo_id = %s", (tomate,))}
    assert set(filas) == {norte}                                  # las filas vacías se borran
    assert (float(filas[norte]["humedad_min"]), float(filas[norte]["temp_max"])) == (38, 33.5)
    assert filas[norte]["por_confirmar"] == 0                     # casilla sin marcar
    assert difusor.avisos_configuracion
    assert sur not in filas


def test_rangos_por_zona_invalidos_no_se_guardan(cliente, datos):
    csrf = ingresar(cliente)
    tomate, norte = datos.cultivo_id("tomate"), zona_id(datos, "norte")
    cliente.post(f"/configuracion/cultivos/{tomate}/zonas", data={
        "csrf": csrf, f"z{norte}_humedad_min": "80", f"z{norte}_humedad_max": "20", "por_confirmar": "1"})
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Norte: El mínimo de la humedad (80) es mayor que el máximo (20)." in html
    fila = datos.consulta("SELECT humedad_min FROM rangos_cultivo_zona WHERE cultivo_id = %s AND zona_id = %s",
                          (tomate, norte))[0]
    assert float(fila["humedad_min"]) == 35                       # quedó el valor de ejemplo

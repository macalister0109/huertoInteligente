"""Endpoint de exportación: acceso con PIN o token."""

from __future__ import annotations

import pytest

from comun.db import conectar
from pruebas.bd import CFG, INICIO
from web import crear_app
from web.config import ConfigWeb

from .conftest import ingresar

pytestmark = pytest.mark.bd
TOKEN = "token-de-exportacion-123456"


def test_sin_pin_ni_token_no_se_exporta(cliente):
    r = cliente.get("/api/exportar/lecturas.csv")
    assert r.status_code == 401 and "PIN" in r.get_json()["error"]


def test_con_sesion_docente(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    datos.lectura(cama, INICIO, 1, suelo=48.5)
    ingresar(cliente)
    r = cliente.get("/api/exportar/lecturas.csv?desde=2026-11-26&hasta=2026-11-26")
    texto = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert texto.splitlines()[0].startswith("origen,lectura_id,cama_id")
    assert ",48.5," in texto and "2026-11-26T15:00:00Z" in texto
    assert 'filename="lecturas_2026-11-26_2026-11-26.csv"' in r.headers["Content-Disposition"]
    assert cliente.get("/api/exportar/otra.csv").status_code == 404
    assert cliente.get("/api/exportar/lecturas.csv?desde=2026-11-27&hasta=2026-11-26").status_code == 400


def test_formulario_redirige_al_archivo(cliente):
    ingresar(cliente)
    r = cliente.get("/api/exportar?conjunto=clima&cama=&desde=2026-11-01&hasta=")
    assert r.status_code == 302 and r.headers["Location"].endswith("/api/exportar/clima.csv?desde=2026-11-01")
    assert "Datos para análisis" in cliente.get("/configuracion/").get_data(as_text=True)


def test_con_token(bd, difusor, reloj):
    cfg = ConfigWeb(bd=CFG, pin_docente="2468", clave_sesion="x", export_token=TOKEN)
    cliente = crear_app(cfg, difusor=difusor, conectar_bd=lambda: conectar(CFG), reloj=reloj).test_client()
    assert cliente.get("/api/exportar/clima.csv", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert cliente.get("/api/exportar/clima.csv", headers={"Authorization": "Bearer otro"}).status_code == 401


def test_token_corto_no_se_acepta():
    assert ConfigWeb.desde_entorno({"EXPORT_TOKEN": "corto"}).export_token == ""

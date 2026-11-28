"""Página del proyecto (landing) y menú principal."""

from __future__ import annotations

import re

import pytest

from comun.db import conectar
from pruebas.bd import CFG
from web import crear_app
from web.config import ConfigWeb

pytestmark = pytest.mark.bd


def test_la_pagina_principal_es_la_del_proyecto(cliente):
    r = cliente.get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Deja de regar «a ojo» en La Pintana" in html
    assert "Quiero sumarme al piloto del colegio" in html
    assert 'id="sumate"' in html and 'href="#sumate"' in html
    for seccion in ("El valor educativo de un huerto muere", "pedagogía de la sencillez",
                    "dos iteraciones", "Metas de calidad", "Unirme al proyecto piloto smartYusChaMau"):
        assert seccion in html
    # El dato del 33 % / 32 % va con su fuente y su alcance
    assert "Trees.com (2022)" in html and "evidencia indirecta" in html
    assert 'href="/tablero"' in html and "Ver las camas en vivo" in html


def test_la_direccion_anterior_redirige_al_inicio(cliente):
    r = cliente.get("/proyecto")
    assert r.status_code == 301 and r.headers["Location"].endswith("/")


def test_pagina_sin_recursos_externos(cliente):
    """Carga rápida, funciona sin internet y respeta la CSP (script-src 'self')."""
    html = cliente.get("/").get_data(as_text=True)
    assert not re.search(r'(src|href)="https?://', html)
    assert "<style" not in html and "onclick" not in html and "<script>" not in html
    for ruta in ("/static/css/landing.css", "/static/js/landing.js", "/static/img/logo-smartyuschamau-96.webp"):
        assert cliente.get(ruta).status_code == 200


def test_menu_con_las_opciones_actuales(cliente):
    for pagina in ("/", "/tablero"):
        html = cliente.get(pagina).get_data(as_text=True)
        for texto, enlace in (("Inicio", "/"), ("Camas en vivo", "/tablero"),
                              ("Pantalla del huerto", "/tablero?kiosco=1"), ("Configuración", "/configuracion/")):
            assert f'href="{enlace}"' in html and texto in html
    assert 'href="/tablero" aria-current="page">Camas en vivo' in cliente.get("/tablero").get_data(as_text=True)
    assert 'href="/" aria-current="page">Inicio' in cliente.get("/").get_data(as_text=True)


def test_formulario_sin_smtp_configurado_lo_avisa(cliente):
    html = cliente.get("/").get_data(as_text=True)
    assert "Falta configurar el envío automático" in html and "SMTP_HOST" in html
    assert 'action="/api/piloto"' in html and 'name="sitio_web"' in html


def test_formulario_con_correo_configurado(bd, difusor, reloj):
    cfg = ConfigWeb(bd=CFG, pin_docente="2468", clave_sesion="x", piloto_correo="huerto@colegio.cl",
                    smtp_host="mail.colegio.cl", smtp_usuario="no-responder@colegio.cl", smtp_clave="x")
    app = crear_app(cfg, difusor=difusor, conectar_bd=lambda: conectar(CFG), reloj=reloj)
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'data-correo="huerto@colegio.cl"' in html and "Falta configurar el envío" not in html


def test_sin_piloto_correo_en_el_env_se_usa_el_del_equipo():
    from web.config import PILOTO_CORREO_POR_DEFECTO, ConfigWeb as _Cfg
    assert PILOTO_CORREO_POR_DEFECTO == "macarena@mjamett.cl"
    assert _Cfg.desde_entorno({}).piloto_correo == "macarena@mjamett.cl"
    assert _Cfg.desde_entorno({"PILOTO_CORREO": "  "}).piloto_correo == "macarena@mjamett.cl"
    assert _Cfg.desde_entorno({"PILOTO_CORREO": "otro@colegio.cl"}).piloto_correo == "otro@colegio.cl"

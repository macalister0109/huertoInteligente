"""Tablero web del Huerto Inteligente (Flask).

    gunicorn --workers 1 --threads 32 --bind 0.0.0.0:8080 "web:crear_app()"

Un solo proceso (workers=1) porque el difusor MQTT -> SSE vive en memoria;
los hilos atienden a varias pantallas y celulares a la vez.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from flask import Flask, current_app, g
from werkzeug.middleware.proxy_fix import ProxyFix

from comun.config import cargar_env
from comun.db import ahora_utc, conectar

from .config import ConfigWeb
from .contexto import Contexto
from .difusor import Difusor, DifusorMqtt


def crear_app(cfg: Optional[ConfigWeb] = None, difusor: Optional[Difusor] = None,
              conectar_bd: Optional[Callable] = None, reloj: Optional[Callable] = None) -> Flask:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if cfg is None:
        cargar_env()
        cfg = ConfigWeb.desde_entorno()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.clave_sesion,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=cfg.cookie_segura,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    app.json.ensure_ascii = False
    if cfg.proxy_saltos > 0:
        # nginx en el servidor: la IP y el esquema (https) reales vienen en X-Forwarded-*
        n = cfg.proxy_saltos
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    if difusor is None:
        difusor = DifusorMqtt(cfg.bd.mqtt_host, cfg.bd.mqtt_puerto,
                              cfg.mqtt_usuario, cfg.mqtt_clave).iniciar()
    app.extensions["huerto"] = Contexto(
        cfg=cfg, difusor=difusor,
        conectar_bd=conectar_bd or (lambda: conectar(cfg.bd)),
        reloj=reloj or ahora_utc,
        zona=ZoneInfo(cfg.zona_horaria),
    )

    from .rutas_api import bp as bp_api
    from .rutas_config import bp as bp_config
    from .rutas_historial import bp as bp_historial
    from .rutas_tablero import bp as bp_tablero
    app.register_blueprint(bp_tablero)
    app.register_blueprint(bp_config)
    app.register_blueprint(bp_api)
    app.register_blueprint(bp_historial)

    @app.teardown_appcontext
    def cerrar_bd(_error=None):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.after_request
    def cabeceras_seguridad(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        # Todo se sirve desde la Pi: ni CDN ni scripts en línea
        respuesta.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'")
        return respuesta

    @app.context_processor
    def variables_plantillas():
        return {"zona_horaria": cfg.zona_horaria}

    return app


def contexto() -> Contexto:
    return current_app.extensions["huerto"]


def bd():
    """Conexión a la BD de esta petición (se cierra al terminar)."""
    if "conn" not in g:
        g.conn = contexto().conectar_bd()
    return g.conn

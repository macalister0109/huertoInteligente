"""Configuración para el docente, protegida con un PIN simple (sin cuentas).

* El PIN se define en central/.env (PIN_DOCENTE).
* Tras 5 intentos fallidos desde un mismo equipo, se bloquea 5 minutos.
* Los formularios llevan un token CSRF de la sesión.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, flash, redirect, render_template, request, session,
                   url_for)

from comun.fechas import iso

from . import bd, consultas, contexto
from .formularios import validar_cama, validar_cultivo

bp = Blueprint("config", __name__, url_prefix="/configuracion")

_intentos: dict[str, list] = {}       # ip -> [fallos, bloqueado_hasta]
_lock_intentos = threading.Lock()


def es_docente() -> bool:
    return session.get("docente") is True


def token_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.app_context_processor
def _variables():
    return {"csrf_token": token_csrf, "es_docente": es_docente()}


def requiere_docente(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not es_docente():
            if request.method == "GET":
                return redirect(url_for("config.inicio"))
            abort(403)
        if request.method == "POST":
            enviado = request.form.get("csrf", "")
            if not hmac.compare_digest(enviado, session.get("csrf", "")):
                abort(400)
        return vista(*args, **kwargs)
    return envoltura


# ---------------------------------------------------------------------------
# Ingreso con PIN
# ---------------------------------------------------------------------------

def _bloqueado_hasta(ip: str, ahora: datetime):
    with _lock_intentos:
        fallos, hasta = _intentos.get(ip, [0, None])
        return hasta if hasta and hasta > ahora else None


def _registrar_fallo(ip: str, ahora: datetime) -> None:
    cfg = contexto().cfg
    with _lock_intentos:
        fallos, hasta = _intentos.get(ip, [0, None])
        fallos += 1
        if fallos >= cfg.max_intentos_pin:
            _intentos[ip] = [0, ahora + timedelta(minutes=cfg.minutos_bloqueo_pin)]
        else:
            _intentos[ip] = [fallos, hasta]


@bp.get("/")
def inicio():
    if not es_docente():
        return render_template("ingresar.html", pin_configurado=contexto().cfg.pin_configurado)
    conn = bd()
    return render_template(
        "configuracion.html",
        camas=consultas.camas(conn, solo_activas=False),
        cultivos=consultas.cultivos(conn),
        incidencias=consultas.incidencias_pendientes(conn),
        iso=iso,
    )


@bp.post("/ingresar")
def ingresar():
    ctx = contexto()
    ahora = datetime.now()
    ip = request.remote_addr or "?"
    if not ctx.cfg.pin_configurado:
        flash("Falta definir PIN_DOCENTE en central/.env (al menos 4 números).", "error")
        return render_template("ingresar.html", pin_configurado=False), 503
    if _bloqueado_hasta(ip, ahora):
        flash(f"Demasiados intentos. Espera {ctx.cfg.minutos_bloqueo_pin} minutos.", "error")
        return render_template("ingresar.html", pin_configurado=True), 429

    pin = request.form.get("pin", "").strip()
    if hmac.compare_digest(pin.encode(), ctx.cfg.pin_docente.encode()):
        with _lock_intentos:
            _intentos.pop(ip, None)
        session.clear()
        session["docente"] = True
        session.permanent = True
        token_csrf()
        return redirect(url_for("config.inicio"))

    _registrar_fallo(ip, ahora)
    flash("PIN incorrecto.", "error")
    return render_template("ingresar.html", pin_configurado=True), 401


@bp.post("/salir")
def salir():
    session.clear()
    return redirect(url_for("tablero.tablero"))


# ---------------------------------------------------------------------------
# Cambios
# ---------------------------------------------------------------------------

def _mostrar_errores(errores: list[str], prefijo: str) -> None:
    for error in errores:
        flash(f"{prefijo}: {error}", "error")


@bp.post("/camas/<int:cama_id>")
@requiere_docente
def guardar_cama(cama_id: int):
    conn = bd()
    cama = consultas.cama(conn, cama_id)
    if cama is None:
        abort(404)
    cultivos = {c["id"]: c for c in consultas.cultivos(conn)}
    valores, errores = validar_cama(request.form, cultivos)
    if errores:
        _mostrar_errores(errores, cama["nombre"])
    else:
        consultas.actualizar_cama(conn, cama_id, valores)
        contexto().difusor.avisar_configuracion(cama_id)
        flash(f"Cambios guardados en {valores['nombre']}.", "ok")
    return redirect(url_for("config.inicio") + f"#cama-{cama_id}")


@bp.post("/cultivos")
@bp.post("/cultivos/<int:cultivo_id>")
@requiere_docente
def guardar_cultivo(cultivo_id: int | None = None):
    conn = bd()
    existentes = consultas.cultivos(conn)
    if cultivo_id is not None and not any(c["id"] == cultivo_id for c in existentes):
        abort(404)
    otros = {c["nombre"] for c in existentes if c["id"] != cultivo_id}
    valores, errores = validar_cultivo(request.form, otros)
    if errores:
        _mostrar_errores(errores, valores["nombre"] or "Cultivo")
        return redirect(url_for("config.inicio") + "#cultivos")
    cultivo_id = consultas.guardar_cultivo(conn, cultivo_id, valores)
    for cama_id in consultas.camas_con_cultivo(conn, cultivo_id):
        contexto().difusor.avisar_configuracion(cama_id)
    flash(f"Cultivo «{valores['nombre']}» guardado.", "ok")
    return redirect(url_for("config.inicio") + "#cultivos")


@bp.post("/incidencias/<int:incidencia_id>/revisada")
@requiere_docente
def revisar_incidencia(incidencia_id: int):
    consultas.marcar_incidencia_revisada(bd(), incidencia_id)
    return redirect(url_for("config.inicio") + "#incidencias")

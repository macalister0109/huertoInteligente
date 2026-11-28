"""Configuración para el docente, protegida con un PIN simple (sin cuentas).

* El PIN se define en central/.env (PIN_DOCENTE).
* Tras 5 intentos fallidos desde un mismo equipo, se bloquea 5 minutos.
* Los formularios llevan un token CSRF de la sesión.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (Blueprint, abort, flash, redirect, render_template, request, session,
                   url_for)

from comun import ajustes
from comun.analitica.proceso import recalcular
from comun.clima import DESACTUALIZADO, NO_CONFIGURADO, OK
from comun.clima.proveedores import nombres as nombres_proveedores
from comun.fechas import iso

from . import bd, consultas, contexto
from .formularios import validar_cama, validar_cultivo, validar_rangos_zona

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
    conn, ctx = bd(), contexto()
    vigentes = ajustes.leer(conn, ctx.cfg.bd)
    conn.commit()
    return render_template(
        "configuracion.html",
        camas=consultas.camas(conn, solo_activas=False),
        cultivos=consultas.cultivos(conn),
        incidencias=consultas.incidencias_pendientes(conn),
        iso=iso,
        clima=vigentes,
        proveedores=_estado_proveedores(vigentes),
        zonas=consultas.zonas(conn),
        rangos_zona=consultas.rangos_por_zona(conn),
    )


def _estado_proveedores(vigentes: dict) -> list[dict]:
    """Nombre y estado (configurado / no configurado) de cada proveedor.
    Nunca incluye las claves: solo si están o no."""
    estados = []
    for nombre in nombres_proveedores():
        p = contexto().clima.crear(nombre)
        p.aplicar_ajustes(vigentes)
        estados.append({"nombre": p.nombre, "titulo": p.titulo or p.nombre,
                        "motivo": p.motivo_no_configurado()})
    return estados


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
    zonas = {z["id"]: z for z in consultas.zonas(conn)}
    valores, errores = validar_cama(request.form, cultivos, zonas)
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


@bp.post("/clima")
@requiere_docente
def guardar_clima():
    conn, ctx = bd(), contexto()
    cambios = {clave: request.form.get(clave, "")
               for clave in ("clima_proveedor", "clima_lat", "clima_lon", "dmc_estacion")}
    errores = ajustes.guardar(conn, cambios)
    if errores:
        _mostrar_errores(errores, "Clima exterior")
        conn.rollback()
    else:
        conn.commit()
        ctx.clima.cache.invalidar()         # el tablero usa los datos nuevos de inmediato
        flash("Ajustes del clima exterior guardados.", "ok")
    return redirect(url_for("config.inicio") + "#clima")


def _reevaluar_todas() -> None:
    """Las camas cambian de rango: el procesador las vuelve a evaluar al instante."""
    for cama_id in consultas.camas_ids(bd()):
        contexto().difusor.avisar_configuracion(cama_id)


@bp.post("/zona")
@requiere_docente
def guardar_zona_huerto():
    conn, ctx = bd(), contexto()
    codigo = request.form.get("zona_huerto", "")
    zonas = {z["codigo"]: z for z in consultas.zonas(conn)}
    if codigo not in zonas:
        flash("Zona climática: la zona elegida no existe.", "error")
        return redirect(url_for("config.inicio") + "#zonas")
    ajustes.guardar(conn, {"zona_huerto": codigo})
    conn.commit()
    _reevaluar_todas()
    flash(f"Zona del huerto: {zonas[codigo]['nombre']}. Las camas sin zona propia usan sus rangos.", "ok")
    return redirect(url_for("config.inicio") + "#zonas")


@bp.post("/cultivos/<int:cultivo_id>/zonas")
@requiere_docente
def guardar_rangos_zona(cultivo_id: int):
    conn = bd()
    cultivo = consultas.cultivo(conn, cultivo_id)
    if cultivo is None:
        abort(404)
    zonas = consultas.zonas(conn)
    todos, errores = {}, []
    for zona in zonas:
        valores, errs = validar_rangos_zona(request.form, f"z{zona['id']}_")
        todos[zona["id"]] = valores
        errores += [f"{zona['nombre']}: {e}" for e in errs]
    if errores:
        _mostrar_errores(errores, cultivo["nombre"])
        return redirect(url_for("config.inicio") + f"#zonas-{cultivo_id}")
    por_confirmar = bool(request.form.get("por_confirmar"))
    for zona_id, valores in todos.items():
        consultas.guardar_rangos_zona(conn, cultivo_id, zona_id, valores, por_confirmar)
    conn.commit()
    _reevaluar_todas()
    flash(f"Rangos por zona de «{cultivo['nombre']}» guardados.", "ok")
    return redirect(url_for("config.inicio") + f"#zonas-{cultivo_id}")


@bp.post("/tendencia")
@requiere_docente
def guardar_tendencia():
    """Ventana de la regresión, R² mínimo, umbral de riego y alerta preventiva."""
    conn, ctx = bd(), contexto()
    antes = ajustes.leer(conn, ctx.cfg.bd)
    cambios = {clave: request.form.get(clave, "")
               for clave in ("tendencia_ventana_h", "tendencia_r2_min", "riego_umbral_pts")}
    # Una casilla sin marcar no se envía: el formulario manda un «0» oculto antes
    cambios["tendencia_activa"] = request.form.getlist("tendencia_activa")[-1:] or ["0"]
    cambios["tendencia_activa"] = cambios["tendencia_activa"][0]
    errores = ajustes.guardar(conn, cambios)
    if errores:
        conn.rollback()
        _mostrar_errores(errores, "Tendencia")
        return redirect(url_for("config.inicio") + "#tendencia")
    conn.commit()
    flash("Ajustes de la tendencia guardados.", "ok")
    nuevos = ajustes.leer(conn, ctx.cfg.bd)
    if nuevos["riego_umbral_pts"] != antes["riego_umbral_pts"]:
        # Los riegos de la última semana se vuelven a detectar con el umbral nuevo
        hoy = ctx.reloj().replace(tzinfo=timezone.utc).astimezone(ctx.zona).date()
        r = recalcular(conn, ajustes.config_vigente(conn, ctx.cfg.bd), hoy - timedelta(days=6), hoy,
                       ctx.reloj())
        flash(f"Riegos de los últimos 7 días recalculados con el umbral nuevo: {r.riegos} encontrados. "
              "Para fechas anteriores usa el comando «recalcular».", "ok")
    return redirect(url_for("config.inicio") + "#tendencia")


@bp.post("/clima/probar")
@requiere_docente
def probar_clima():
    """Consulta al proveedor elegido ahora mismo (ignora la caché)."""
    conn, ctx = bd(), contexto()
    nombre = request.form.get("clima_proveedor") or None
    if nombre is not None and nombre not in nombres_proveedores():
        abort(400)
    # Se prueban las coordenadas escritas en el formulario (aunque no se hayan guardado)
    escritas = {c: request.form[c] for c in ("clima_lat", "clima_lon", "dmc_estacion")
                if c in request.form}
    valores, errores = ajustes.validar(escritas)
    if errores:
        _mostrar_errores(errores, "Clima exterior")
        return redirect(url_for("config.inicio") + "#clima")
    proveedor, r = ctx.clima.consultar(conn, forzar=True, proveedor_nombre=nombre,
                                       lat=valores.get("clima_lat"), lon=valores.get("clima_lon"),
                                       extra=valores)
    titulo = ctx.clima.nombre_visible(proveedor)
    if r.estado == OK and r.clima is not None:
        c = r.clima
        hora = (c.observado_en.replace(tzinfo=timezone.utc).astimezone(ctx.zona)
                .strftime("%H:%M"))
        partes = []
        if c.temp_aire_c is not None:
            partes.append(f"{c.temp_aire_c:g} °C")
        if c.hum_rel_pct is not None:
            partes.append(f"{c.hum_rel_pct:g} % de humedad")
        flash(f"Conexión correcta con {titulo}: {', '.join(partes) or 'sin valores'} "
              f"(dato de las {hora}).", "ok")
    elif r.estado == NO_CONFIGURADO:
        flash(f"{titulo} no está configurado: {r.error}", "error")
    else:
        extra = " Se sigue mostrando el último dato guardado." if r.estado == DESACTUALIZADO else ""
        flash(f"No se pudo conectar con {titulo}: {r.error}.{extra}", "error")
    return redirect(url_for("config.inicio") + "#clima")


@bp.post("/incidencias/<int:incidencia_id>/revisada")
@requiere_docente
def revisar_incidencia(incidencia_id: int):
    consultas.marcar_incidencia_revisada(bd(), incidencia_id)
    return redirect(url_for("config.inicio") + "#incidencias")

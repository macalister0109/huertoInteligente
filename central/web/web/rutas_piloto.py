"""Formulario «Sumarse al piloto» de la portada: el servidor envía el correo.

    POST /api/piloto   JSON {nombre, estamento, correo, comentario, sitio_web}

La solicitud se envía por SMTP a PILOTO_CORREO, con «Responder a» = el correo
del visitante, y NO se guarda en la BD ni en los registros (solo se registra
que hubo un envío).

Protección contra spam:
* `sitio_web` es un campo trampa oculto: si viene lleno, se responde «enviado»
  pero no se envía nada;
* hasta 3 envíos por IP cada 15 minutos y 30 por hora en total;
* si el navegador manda Origin, debe ser este mismo sitio.

Respuestas: 200 enviado · 400 datos inválidos · 403 otro sitio · 429 demasiados
envíos · 503 correo no configurado o el servidor SMTP falló (el visitante ve el
correo para escribir directo).
"""

from __future__ import annotations

import logging
import re
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request

from . import contexto
from .config import ConfigWeb

log = logging.getLogger(__name__)

bp = Blueprint("piloto", __name__)

ESTAMENTOS = ("Docente", "Directivo", "Estudiante", "Apoderado")
CORREO_VALIDO = re.compile(r"^[^\s@<>,;\"]+@[^\s@<>,;\"]+\.[^\s@<>,;\"]{2,}$")
LIMITES = {"nombre": 80, "correo": 120, "comentario": 600}
MAX_POR_IP, VENTANA_IP = 3, timedelta(minutes=15)
MAX_GLOBAL, VENTANA_GLOBAL = 30, timedelta(hours=1)

_envios_ip: dict[str, deque] = {}
_envios_global: deque = deque()
_lock = threading.Lock()


def _texto(valor: Any, limite: int) -> str:
    """Texto de una línea sin caracteres de control (evita inyectar cabeceras)."""
    texto = re.sub(r"[\x00-\x1f\x7f]+", " ", str(valor or "")).strip()
    return texto[:limite]


def validar(datos: dict) -> tuple[dict, list[str]]:
    problemas = []
    nombre = _texto(datos.get("nombre"), LIMITES["nombre"])
    estamento = _texto(datos.get("estamento"), 20)
    correo = _texto(datos.get("correo"), LIMITES["correo"])
    # El comentario sí puede tener varias líneas
    comentario = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]+", " ", str(datos.get("comentario") or ""))
    comentario = comentario.strip()[:LIMITES["comentario"]]
    if len(nombre) < 3:
        problemas.append("Escribe tu nombre completo.")
    if estamento not in ESTAMENTOS:
        problemas.append("Elige tu estamento.")
    if not CORREO_VALIDO.match(correo):
        problemas.append("Revisa tu correo electrónico.")
    return {"nombre": nombre, "estamento": estamento, "correo": correo,
            "comentario": comentario}, problemas


def armar_mensaje(cfg: ConfigWeb, s: dict, ahora_local: datetime) -> EmailMessage:
    remitente = cfg.smtp_remitente or cfg.smtp_usuario
    m = EmailMessage()
    m["Subject"] = f"Quiero sumarme al piloto smartYusChaMau ({s['estamento']})"
    m["From"] = formataddr(("smartYusChaMau · Huerto Inteligente", remitente))
    m["To"] = cfg.piloto_correo
    m["Reply-To"] = formataddr((s["nombre"], s["correo"]))
    m["Message-ID"] = make_msgid(domain=remitente.rpartition("@")[2] or None)
    m.set_content("\n".join([
        "Nueva solicitud desde el formulario de https://huerto.mjvirtual.cl",
        "",
        f"Nombre: {s['nombre']}",
        f"Estamento: {s['estamento']}",
        f"Correo: {s['correo']}",
        "",
        "Comentario o propuesta de cultivo:",
        s["comentario"] or "(sin comentario)",
        "",
        f"Enviado el {ahora_local:%d-%m-%Y a las %H:%M}. Para contestar, usa «Responder».",
    ]))
    return m


def _limite_superado(ip: str, ahora: datetime) -> bool:
    """Registra el envío si está dentro de los límites; True si no lo está."""
    with _lock:
        while _envios_global and ahora - _envios_global[0] > VENTANA_GLOBAL:
            _envios_global.popleft()
        cola = _envios_ip.setdefault(ip, deque())
        while cola and ahora - cola[0] > VENTANA_IP:
            cola.popleft()
        if len(cola) >= MAX_POR_IP or len(_envios_global) >= MAX_GLOBAL:
            return True
        cola.append(ahora)
        _envios_global.append(ahora)
        return False


def reiniciar_limites() -> None:
    """Para los tests."""
    with _lock:
        _envios_ip.clear()
        _envios_global.clear()


def _origen_ajeno() -> bool:
    origen = request.headers.get("Origin")
    if not origen:
        return False
    return urlsplit(origen).netloc != request.host


@bp.post("/api/piloto")
def solicitud_piloto():
    ctx = contexto()
    cfg = ctx.cfg
    if _origen_ajeno():
        return jsonify(error="El formulario debe enviarse desde este sitio."), 403
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify(error="Solicitud mal formada."), 400
    if str(datos.get("sitio_web") or "").strip():
        log.info("Formulario del piloto: se ignoró un envío con el campo trampa lleno")
        return jsonify(estado="enviado")
    solicitud, problemas = validar(datos)
    if problemas:
        return jsonify(error=" ".join(problemas), problemas=problemas), 400
    if not cfg.smtp_configurado:
        log.error("Formulario del piloto: falta configurar SMTP_HOST, SMTP_USUARIO y SMTP_CLAVE")
        return jsonify(error="El envío automático no está configurado.", correo=cfg.piloto_correo), 503
    ahora = ctx.reloj()
    if _limite_superado(request.remote_addr or "?", ahora):
        return jsonify(error="Se enviaron varias solicitudes seguidas. Espera unos minutos e "
                             "inténtalo de nuevo."), 429
    ahora_local = ahora.replace(tzinfo=timezone.utc).astimezone(ctx.zona)
    try:
        ctx.enviar_correo(cfg, armar_mensaje(cfg, solicitud, ahora_local))
    except Exception as e:   # SMTP, red, TLS, clave con tildes…: el visitante siempre recibe JSON
        log.error("Formulario del piloto: el servidor SMTP falló (%s: %s)", type(e).__name__, e)
        return jsonify(error="No se pudo enviar en este momento.", correo=cfg.piloto_correo), 503
    log.info("Formulario del piloto: solicitud enviada a %s", cfg.piloto_correo)
    return jsonify(estado="enviado")

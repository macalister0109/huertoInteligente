"""Configuración del tablero web (central/.env)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Mapping, Optional

from comun.config import Config

PINES_DE_EJEMPLO = {"", "cambia_esto"}


# Correo del equipo del piloto que recibe el formulario «Sumarse al piloto» si
# el .env no define PILOTO_CORREO (ya se muestra en la página pública).
PILOTO_CORREO_POR_DEFECTO = "macarena@mjamett.cl"


@dataclass(frozen=True)
class ConfigWeb:
    bd: Config = field(default_factory=Config)
    mqtt_usuario: str = "web"
    mqtt_clave: str = ""
    pin_docente: str = ""
    clave_sesion: str = ""
    zona_horaria: str = "America/Santiago"
    umbral_luz_lux: float = 25000.0
    max_intentos_pin: int = 5
    minutos_bloqueo_pin: int = 5
    # Detrás de nginx en el servidor: cuántos proxys hay delante (0 = ninguno).
    # Con 1 se confía en X-Forwarded-For/Proto que pone nginx (la IP real del
    # visitante sirve para bloquear intentos de PIN). En la casa va en 0.
    proxy_saltos: int = 0
    # true cuando el tablero se sirve por HTTPS: la cookie de sesión no viaja por HTTP
    cookie_segura: bool = False
    # Correo que recibe las solicitudes del formulario de la página del proyecto.
    # El servidor las envía por SMTP y NO las guarda en la BD.
    piloto_correo: str = ""     # desde_entorno usa PILOTO_CORREO_POR_DEFECTO si falta
    # Cuenta SMTP que envía esas solicitudes (la del hosting de mjamett.cl).
    # Puerto 465 = SSL directo; cualquier otro (ej. 587) = STARTTLS.
    smtp_host: str = ""
    smtp_puerto: int = 465
    smtp_usuario: str = ""
    smtp_clave: str = ""
    smtp_remitente: str = ""    # vacío = el mismo smtp_usuario
    # Token para exportar datos desde scripts o notebooks (Authorization: Bearer …).
    # Vacío = solo con la sesión docente. Mínimo 16 caracteres.
    export_token: str = ""

    @property
    def smtp_configurado(self) -> bool:
        return bool(self.smtp_host and self.smtp_usuario and self.smtp_clave and self.piloto_correo)

    @property
    def pin_configurado(self) -> bool:
        return self.pin_docente not in PINES_DE_EJEMPLO and len(self.pin_docente) >= 4

    @classmethod
    def desde_entorno(cls, entorno: Optional[Mapping[str, str]] = None) -> "ConfigWeb":
        entorno = os.environ if entorno is None else entorno
        bd = Config.desde_entorno(entorno)
        return cls(
            bd=bd,
            mqtt_usuario=entorno.get("MQTT_USER_WEB", "web"),
            mqtt_clave=entorno.get("MQTT_PASS_WEB", ""),
            pin_docente=entorno.get("PIN_DOCENTE", "").strip(),
            # Si no se define, se genera al arrancar (las sesiones se pierden al reiniciar)
            clave_sesion=entorno.get("CLAVE_SESION_WEB") or secrets.token_hex(32),
            zona_horaria=bd.zona_horaria,
            umbral_luz_lux=bd.umbral_luz_lux,
            proxy_saltos=int(entorno.get("PROXY_SALTOS") or 0),
            cookie_segura=(entorno.get("COOKIE_SEGURA", "").strip().lower()
                           in ("1", "true", "si", "sí", "yes", "on")),
            piloto_correo=entorno.get("PILOTO_CORREO", "").strip() or PILOTO_CORREO_POR_DEFECTO,
            # Se aceptan también los nombres en inglés (SMTP_PORT, SMTP_USER, …)
            smtp_host=entorno.get("SMTP_HOST", "").strip(),
            smtp_puerto=int((entorno.get("SMTP_PUERTO") or entorno.get("SMTP_PORT") or "465").strip()),
            smtp_usuario=(entorno.get("SMTP_USUARIO") or entorno.get("SMTP_USER") or "").strip(),
            smtp_clave=entorno.get("SMTP_CLAVE") or entorno.get("SMTP_PASSWORD") or "",
            smtp_remitente=(entorno.get("SMTP_REMITENTE") or entorno.get("SMTP_FROM") or "").strip(),
            export_token=(lambda t: t if len(t) >= 16 else "")(entorno.get("EXPORT_TOKEN", "").strip()),
        )

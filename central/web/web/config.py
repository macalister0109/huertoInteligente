"""Configuración del tablero web (central/.env)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Mapping, Optional

from comun.config import Config

PINES_DE_EJEMPLO = {"", "cambia_esto"}


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
        )

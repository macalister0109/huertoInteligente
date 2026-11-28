from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

from .config import ConfigWeb
from .difusor import Difusor

if TYPE_CHECKING:
    from .clima import ServicioClima


@dataclass
class Contexto:
    cfg: ConfigWeb
    difusor: Difusor
    conectar_bd: Callable
    reloj: Callable[[], datetime]
    zona: ZoneInfo
    clima: "ServicioClima"
    # (cfg, EmailMessage) -> None. Por defecto, SMTP; los tests usan uno falso.
    enviar_correo: Callable = None  # type: ignore[assignment]

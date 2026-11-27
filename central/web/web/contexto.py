from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from .config import ConfigWeb
from .difusor import Difusor


@dataclass
class Contexto:
    cfg: ConfigWeb
    difusor: Difusor
    conectar_bd: Callable
    reloj: Callable[[], datetime]
    zona: ZoneInfo

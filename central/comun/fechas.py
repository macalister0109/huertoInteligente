"""Conversión de fechas. Convención: datetime ingenuos en UTC dentro del código."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def iso(t: Optional[datetime]) -> Optional[str]:
    """datetime UTC ingenuo -> '2026-11-26T12:00:00Z' (con ms si los tiene)."""
    if t is None:
        return None
    if t.microsecond:
        return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parsear_iso_utc(texto: object) -> Optional[datetime]:
    """'2026-11-26T12:00:00.123Z' -> datetime UTC ingenuo. None si no es válido."""
    if not isinstance(texto, str) or not texto:
        return None
    try:
        t = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return t.astimezone(timezone.utc).replace(tzinfo=None)


def inicio_del_dia_utc(ahora_utc: datetime, zona: ZoneInfo) -> datetime:
    """Medianoche de hoy (hora local) expresada en UTC ingenuo."""
    hoy: date = ahora_utc.replace(tzinfo=timezone.utc).astimezone(zona).date()
    local = datetime.combine(hoy, time(0), tzinfo=zona)
    return local.astimezone(timezone.utc).replace(tzinfo=None)

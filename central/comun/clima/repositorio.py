"""Acceso a la tabla clima_referencia (instantáneas horarias). Sin commit."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .base import ClimaReferencia

CAMPOS = ("temp_aire_c", "hum_rel_pct", "precipitacion_mm", "radiacion_wm2", "temp_suelo_c",
          "hum_suelo_vwc_pct", "et0_mm", "et0_hoy_mm")


def _num(v):
    return None if v is None else float(v)


def desde_fila(fila: dict) -> ClimaReferencia:
    return ClimaReferencia(**{c: _num(fila[c]) for c in CAMPOS},
                           observado_en=fila["observado_en"], fuente=fila["fuente"],
                           lat=float(fila["lat"]), lon=float(fila["lon"]))


def guardar_instantanea(conn, clima: ClimaReferencia, obtenido_en: datetime) -> None:
    """Idempotente: la misma hora del mismo proveedor y lugar se reemplaza."""
    columnas = ("fuente", "observado_en", "obtenido_en", "lat", "lon") + CAMPOS
    valores = (clima.fuente, clima.observado_en, obtenido_en, clima.lat, clima.lon) + tuple(
        getattr(clima, c) for c in CAMPOS)
    actualizar = ", ".join(f"{c} = VALUES({c})" for c in ("obtenido_en",) + CAMPOS)
    with conn.cursor() as cur:
        cur.execute(f"""INSERT INTO clima_referencia ({", ".join(columnas)})
                        VALUES ({", ".join(["%s"] * len(columnas))})
                        ON DUPLICATE KEY UPDATE {actualizar}""", valores)


def ultima(conn, fuente: Optional[str] = None, lat: Optional[float] = None,
           lon: Optional[float] = None) -> Optional[ClimaReferencia]:
    condiciones, parametros = [], []
    if fuente:
        condiciones.append("fuente = %s")
        parametros.append(fuente)
    if lat is not None and lon is not None:
        condiciones.append("lat = %s AND lon = %s")
        parametros += [round(lat, 5), round(lon, 5)]
    donde = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM clima_referencia {donde} ORDER BY observado_en DESC LIMIT 1",
                    parametros)
        fila = cur.fetchone()
    return desde_fila(fila) if fila else None


def entre(conn, desde: datetime, hasta: datetime) -> list[ClimaReferencia]:
    """Instantáneas en [desde, hasta], ordenadas por hora (para series y comparaciones)."""
    with conn.cursor() as cur:
        cur.execute("""SELECT * FROM clima_referencia WHERE observado_en BETWEEN %s AND %s
                       ORDER BY observado_en""", (desde, hasta))
        return [desde_fila(f) for f in cur.fetchall()]


def cercanas_a(conn, momento: datetime, margen_min: float = 60) -> list[ClimaReferencia]:
    """Candidatas para comparar con una lectura medida en `momento`."""
    margen = timedelta(minutes=margen_min)
    return entre(conn, momento - margen, momento + margen)

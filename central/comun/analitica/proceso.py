"""Recalcula la capa de análisis de una cama por días completos (hora de Chile).

Idempotente: para cada día se borran y se vuelven a escribir sus marcas de
calidad y sus agregados. Ejecutarlo dos veces deja exactamente lo mismo.
Nunca modifica la tabla `lecturas`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from ..config import Config
from ..rangos import rango_efectivo
from . import repositorio as repo
from .agregados import agregar_dia, agregar_horas, limites_dia_local
from .calidad import calcular_marcas
from .riego import detectar_riegos, puntos_suelo

log = logging.getLogger(__name__)


@dataclass
class Resumen:
    dias: int = 0
    marcas: int = 0
    filas_hora: int = 0
    filas_dia: int = 0
    riegos: int = 0
    camas: set = field(default_factory=set)

    def sumar(self, otro: "Resumen") -> None:
        self.dias += otro.dias
        self.marcas += otro.marcas
        self.filas_hora += otro.filas_hora
        self.filas_dia += otro.filas_dia
        self.riegos += otro.riegos
        self.camas |= otro.camas


def contexto(cfg: Config) -> timedelta:
    """Margen de lecturas antes y después del día, para que una racha de
    «sensor pegado» o un hueco que cruza la medianoche se detecte igual."""
    return timedelta(hours=max(max(cfg.pegado_horas(v) for v in ("suelo", "temp", "hum_aire")),
                               cfg.riego_ventana_min / 60) + 1)


def recalcular_dia(conn, cfg: Config, cama: dict, fecha: date, ahora: datetime,
                   zona: Optional[ZoneInfo] = None) -> Resumen:
    zona = zona or ZoneInfo(cfg.zona_horaria)
    inicio, fin = limites_dia_local(fecha, zona)
    margen = contexto(cfg)
    lecturas = repo.lecturas_entre(conn, cama["id"], inicio - margen, fin + margen)
    marcas = calcular_marcas(lecturas, cfg)
    del_dia = [l for l in lecturas if inicio <= l.medido_en < fin]

    r = Resumen(dias=1, camas={cama["id"]})
    r.marcas = repo.reemplazar_marcas(conn, cama["id"], inicio, fin, marcas, ahora)
    r.filas_hora = repo.reemplazar_agregados_hora(
        conn, cama["id"], inicio, fin,
        agregar_horas(cama["id"], del_dia, marcas, cfg.intervalo_lectura_s, ahora), ahora)
    # Riegos: con el margen, una subida que empieza antes de la medianoche se ve entera
    riegos = detectar_riegos(puntos_suelo(lecturas, marcas), cfg.riego_umbral_pts,
                             cfg.riego_ventana_min)
    r.riegos = repo.reemplazar_riegos_detectados(conn, cama["id"], inicio, fin, riegos, ahora)
    r.filas_dia = repo.reemplazar_agregados_dia(
        conn, cama["id"], [fecha],
        agregar_dia(cama["id"], fecha, del_dia, marcas, cfg.intervalo_lectura_s, ahora, zona,
                    rango_efectivo(cama)), ahora)
    return r


def recalcular_fechas(conn, cfg: Config, cama: dict, fechas: Iterable[date],
                      ahora: datetime) -> Resumen:
    zona = ZoneInfo(cfg.zona_horaria)
    total = Resumen()
    for fecha in sorted(set(fechas)):
        total.sumar(recalcular_dia(conn, cfg, cama, fecha, ahora, zona))
    conn.commit()
    return total


def recalcular(conn, cfg: Config, desde: date, hasta: date, ahora: datetime,
               cama_id: Optional[int] = None) -> Resumen:
    """Recalcula [desde, hasta] (fechas en hora de Chile, ambas incluidas)."""
    if hasta < desde:
        raise ValueError("«hasta» debe ser igual o posterior a «desde»")
    fechas = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
    total = Resumen()
    for cama in repo.camas(conn, cama_id):
        total.sumar(recalcular_fechas(conn, cfg, cama, fechas, ahora))
    return total

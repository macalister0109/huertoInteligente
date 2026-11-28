"""Agregados por hora y por día. Funciones puras (sin BD).

* Solo se usan valores válidos: los descartados por la validación (rango,
  salto) ya vienen en NULL y además se excluyen los marcados «pegado».
* n_esperadas = duración / INTERVALO_LECTURA_S. En la hora o el día en curso
  se cuenta solo hasta «ahora».
* cobertura = n_lecturas / n_esperadas, con un máximo de 1.
* horas_fuera_rango (día): cada valor válido fuera del rango ideal de la cama
  cuenta como un intervalo de lectura. Usa el rango vigente de la cama al
  momento de calcular (el historial de rangos no se guarda).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from ..rangos import Rango
from .calidad import VARIABLES, LecturaCruda, Marca, excluidas


@dataclass(frozen=True)
class Estadisticas:
    media: Optional[float]
    minimo: Optional[float]
    maximo: Optional[float]
    desviacion: Optional[float]
    n: int


@dataclass(frozen=True)
class Agregado:
    cama_id: int
    periodo: object              # datetime (hora_inicio, UTC) o date (día local)
    variable: str
    estadisticas: Estadisticas
    n_excluidas: int
    n_esperadas: int
    cobertura: float
    amplitud: Optional[float] = None
    horas_fuera_rango: Optional[float] = None


def estadisticas(valores: list[float]) -> Estadisticas:
    if not valores:
        return Estadisticas(None, None, None, None, 0)
    desviacion = round(statistics.stdev(valores), 3) if len(valores) >= 2 else None
    return Estadisticas(round(statistics.fmean(valores), 3), min(valores), max(valores),
                        desviacion, len(valores))


def esperadas(desde: datetime, hasta: datetime, intervalo_s: float) -> int:
    return max(0, round((hasta - desde).total_seconds() / intervalo_s))


def cobertura(n: int, n_esperadas: int) -> float:
    return 0.0 if n_esperadas <= 0 else round(min(1.0, n / n_esperadas), 4)


def inicio_hora(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def limites_dia_local(fecha: date, zona: ZoneInfo) -> tuple[datetime, datetime]:
    """[inicio, fin) del día local, en UTC ingenuo (el día puede durar 23 o 25 h)."""
    def a_utc(d: date) -> datetime:
        return datetime.combine(d, time(0), tzinfo=zona).astimezone(timezone.utc).replace(tzinfo=None)
    return a_utc(fecha), a_utc(fecha + timedelta(days=1))


def fecha_local(t: datetime, zona: ZoneInfo) -> date:
    return t.replace(tzinfo=timezone.utc).astimezone(zona).date()


def _valores(lecturas: list[LecturaCruda], variable: str, fuera: set) -> tuple[list[float], int]:
    usados, n_excluidas = [], 0
    for l in lecturas:
        v = l.valor(variable)
        if (l.id, variable) in fuera:
            n_excluidas += 1
        elif v is not None:
            usados.append(v)
    return usados, n_excluidas


def _limites_rango(rango: Optional[Rango], variable: str) -> tuple[Optional[float], Optional[float]]:
    if rango is None:
        return None, None
    if variable == "suelo":
        return rango.humedad_min, rango.humedad_max
    if variable == "temp":
        return rango.temp_min, rango.temp_max
    return None, None


def agregar_horas(cama_id: int, lecturas: Iterable[LecturaCruda], marcas: Iterable[Marca],
                  intervalo_s: float, ahora: datetime) -> list[Agregado]:
    """Una fila por hora (con al menos una lectura) y variable."""
    fuera = excluidas(marcas)
    por_hora: dict[datetime, list[LecturaCruda]] = {}
    for l in lecturas:
        por_hora.setdefault(inicio_hora(l.medido_en), []).append(l)
    filas = []
    for hora, grupo in sorted(por_hora.items()):
        n_esp = esperadas(hora, min(hora + timedelta(hours=1), max(ahora, hora)), intervalo_s)
        for variable in VARIABLES:
            valores, n_excl = _valores(grupo, variable, fuera)
            filas.append(Agregado(cama_id, hora, variable, estadisticas(valores), n_excl, n_esp,
                                  cobertura(len(valores), n_esp)))
    return filas


def agregar_dia(cama_id: int, fecha: date, lecturas: Iterable[LecturaCruda],
                marcas: Iterable[Marca], intervalo_s: float, ahora: datetime, zona: ZoneInfo,
                rango: Optional[Rango]) -> list[Agregado]:
    """Una fila por variable para el día local `fecha` (vacío si no hubo lecturas)."""
    inicio, fin = limites_dia_local(fecha, zona)
    del_dia = [l for l in lecturas if inicio <= l.medido_en < fin]
    if not del_dia:
        return []
    fuera = excluidas(marcas)
    n_esp = esperadas(inicio, min(fin, max(ahora, inicio)), intervalo_s)
    filas = []
    for variable in VARIABLES:
        valores, n_excl = _valores(del_dia, variable, fuera)
        e = estadisticas(valores)
        minimo, maximo = _limites_rango(rango, variable)
        horas_fuera = None
        if minimo is not None or maximo is not None:
            n_fuera = sum(1 for v in valores
                          if (minimo is not None and v < minimo) or (maximo is not None and v > maximo))
            horas_fuera = round(n_fuera * intervalo_s / 3600, 2)
        amplitud = None if e.n == 0 else round(e.maximo - e.minimo, 2)
        filas.append(Agregado(cama_id, fecha, variable, e, n_excl, n_esp,
                              cobertura(e.n, n_esp), amplitud, horas_fuera))
    return filas

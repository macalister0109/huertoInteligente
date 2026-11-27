"""HU-04: horas de luz directa por día y aviso de poca luz.

Horas de luz: cada lectura válida de luz "cubre" el tiempo hasta la
siguiente lectura válida, con un tope de `max_hueco_min` (si el nodo se
cae, el hueco no cuenta). El tiempo cubierto con lux sobre el umbral son
las horas de luz directa. Sin lecturas de luz -> None ("Sin datos de luz
hoy"), nunca 0 h.

Poca luz: se avisa cuando hay N días completos seguidos (por defecto 3) con
menos horas que el mínimo. Un día con menos del 75 % del horario de sol con
datos no cuenta como "poca luz" y corta la racha (evita falsas alarmas).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from comun import mensajes
from comun.rangos import Rango

from . import ABRIR, ACTUALIZAR, RESOLVER, Decision

POCA_LUZ = "poca_luz"

@dataclass(frozen=True)
class ResumenLuz:
    horas_luz: Optional[float]
    minutos_con_datos: float
    minutos_con_datos_sol: float

@dataclass(frozen=True)
class DiaLuz:
    fecha: date
    horas_luz: Optional[float]
    minutos_con_datos_sol: float

# ---------------------------------------------------------------------------
# Límites del día en hora de Chile, expresados en UTC ingenuo
# ---------------------------------------------------------------------------

def a_utc(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)

def fecha_local(t_utc: datetime, zona: ZoneInfo) -> date:
    return t_utc.replace(tzinfo=timezone.utc).astimezone(zona).date()

def limites_dia(fecha: date, zona: ZoneInfo) -> tuple[datetime, datetime]:
    """[inicio, fin) del día local en UTC. Respeta los cambios de horario."""
    inicio = datetime.combine(fecha, time(0), tzinfo=zona)
    fin = datetime.combine(fecha + timedelta(days=1), time(0), tzinfo=zona)
    return a_utc(inicio), a_utc(fin)

def limites_sol(fecha: date, zona: ZoneInfo, hora_inicio: int, hora_fin: int) -> tuple[datetime, datetime]:
    inicio = datetime.combine(fecha, time(hora_inicio), tzinfo=zona)
    fin = datetime.combine(fecha, time(hora_fin), tzinfo=zona)
    return a_utc(inicio), a_utc(fin)

# ---------------------------------------------------------------------------
# Cálculo de horas de luz
# ---------------------------------------------------------------------------

def calcular_luz(lecturas: Sequence[tuple[datetime, float]], inicio: datetime, fin: datetime,
                 sol_inicio: datetime, sol_fin: datetime, umbral_lux: float,
                 max_hueco_min: float) -> ResumenLuz:
    """`lecturas`: (medido_en, lux) válidas, en orden ascendente."""
    lecturas = [(t, lux) for t, lux in lecturas if inicio <= t < fin]
    if not lecturas:
        return ResumenLuz(None, 0.0, 0.0)

    tope = timedelta(minutes=max_hueco_min)
    minutos = minutos_sol = minutos_luz = 0.0
    for i, (t, lux) in enumerate(lecturas):
        siguiente = lecturas[i + 1][0] if i + 1 < len(lecturas) else fin
        hasta = min(siguiente, t + tope, fin)
        if hasta <= t:
            continue
        duracion = (hasta - t).total_seconds() / 60
        minutos += duracion
        solapado = (min(hasta, sol_fin) - max(t, sol_inicio)).total_seconds() / 60
        minutos_sol += max(0.0, solapado)
        if lux > umbral_lux:
            minutos_luz += duracion
    return ResumenLuz(round(minutos_luz / 60, 2), round(minutos, 1), round(minutos_sol, 1))

# ---------------------------------------------------------------------------
# Aviso de poca luz
# ---------------------------------------------------------------------------

def dia_completo(dia: DiaLuz, minutos_sol_dia: float, cobertura_minima: float) -> bool:
    return (dia.horas_luz is not None
            and dia.minutos_con_datos_sol >= cobertura_minima * minutos_sol_dia)

def racha_poca_luz(dias_desc: Sequence[DiaLuz], minimo: float, minutos_sol_dia: float,
                   cobertura_minima: float) -> int:
    """Días seguidos (desde el más reciente hacia atrás, sin saltarse
    fechas) completos y bajo el mínimo."""
    racha, esperada = 0, None
    for dia in dias_desc:
        if esperada is not None and dia.fecha != esperada:
            break                                   # falta un día: se corta
        if not dia_completo(dia, minutos_sol_dia, cobertura_minima) or dia.horas_luz >= minimo:
            break
        racha += 1
        esperada = dia.fecha - timedelta(days=1)
    return racha

def evaluar_poca_luz(nombre: str, rango: Rango, dias_desc: Sequence[DiaLuz],
                     abiertas: set[str], dias_necesarios: int, minutos_sol_dia: float,
                     cobertura_minima: float, cultivos_sombra: Sequence[str]) -> list[Decision]:
    """`dias_desc`: días cerrados, del más reciente al más antiguo."""

    if rango.horas_luz_min is None:
        return [Decision(RESOLVER, POCA_LUZ, "luz")] if POCA_LUZ in abiertas else []
    if not dias_desc:
        return []

    ultimo = dias_desc[0]
    racha = racha_poca_luz(dias_desc, rango.horas_luz_min, minutos_sol_dia, cobertura_minima)
    if racha >= dias_necesarios:
        sombra = [c for c in cultivos_sombra if c != rango.cultivo]
        texto = mensajes.poca_luz(nombre, rango.cultivo, sombra)
        accion = ACTUALIZAR if POCA_LUZ in abiertas else ABRIR
        return [Decision(accion, POCA_LUZ, "luz", ultimo.horas_luz, texto)]
    if (POCA_LUZ in abiertas and dia_completo(ultimo, minutos_sol_dia, cobertura_minima)
            and ultimo.horas_luz >= rango.horas_luz_min):
        return [Decision(RESOLVER, POCA_LUZ, "luz", ultimo.horas_luz)]
    return []

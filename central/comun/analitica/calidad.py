"""Marcas de calidad por lectura. Funciones puras (sin BD).

* rango  : fuera de rango físico o no numérico. Lo detecta la validación al
           recibir la lectura (campos_invalidos, tipo «rango» o «tipo_dato»).
* salto  : salto imposible respecto de la lectura anterior. También de la
           validación (campos_invalidos, tipo «salto»); los umbrales son los
           del .env (SALTO_MAX_BAJADA_SUELO, SALTO_MAX_TEMP, SALTO_MAX_HUM_AIRE).
* pegado : el mismo valor EXACTO durante más de N horas (sensor pegado).
           N por variable: PEGADO_HORAS_SUELO / _TEMP / _HUM_AIRE.
* hueco  : antes de esta lectura faltaron más de HUECO_LECTURAS_FALTANTES
           lecturas seguidas (con INTERVALO_LECTURA_S entre lecturas).

Las marcas no cambian las lecturas: se guardan aparte (calidad_lecturas).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Optional

from ..config import Config

VARIABLES = ("suelo", "temp", "hum_aire")
RANGO, SALTO, PEGADO, HUECO = "rango", "salto", "pegado", "hueco"
LECTURA = "lectura"          # variable de la marca «hueco» (no es de un sensor)

# Dos valores iguales separados por más que esto no cuentan como la misma
# racha de «sensor pegado»: no se observó qué pasó entremedio.
CORTE_RACHA_PEGADO = timedelta(hours=1)


@dataclass(frozen=True)
class LecturaCruda:
    id: int
    medido_en: datetime
    suelo: Optional[float]
    temp: Optional[float]
    hum_aire: Optional[float]
    campos_invalidos: dict = field(default_factory=dict)

    def valor(self, variable: str) -> Optional[float]:
        return getattr(self, variable)


@dataclass(frozen=True)
class Marca:
    lectura_id: int
    medido_en: datetime
    variable: str
    marca: str
    detalle: str


def variable_de_campo(clave: str) -> Optional[str]:
    """Clave de campos_invalidos -> variable. «suelo_sonda_2» -> «suelo»."""
    if clave == "suelo_mv":
        return None
    if clave == "suelo" or clave.startswith("suelo_sonda_"):
        return "suelo"
    return clave if clave in ("temp", "hum_aire") else None


def marcas_de_validacion(lectura: LecturaCruda) -> list[Marca]:
    """rango y salto, tal como los registró la validación al recibir la lectura."""
    marcas: dict[tuple[str, str], Marca] = {}
    for clave, info in (lectura.campos_invalidos or {}).items():
        variable = variable_de_campo(clave)
        if variable is None or not isinstance(info, dict):
            continue
        tipo = info.get("tipo")
        marca = SALTO if tipo == "salto" else RANGO if tipo in ("rango", "tipo_dato") else None
        if marca and (variable, marca) not in marcas:
            marcas[(variable, marca)] = Marca(lectura.id, lectura.medido_en, variable, marca,
                                              str(info.get("detalle") or "")[:255])
    return list(marcas.values())


def marcas_hueco(lecturas: list[LecturaCruda], intervalo_s: float,
                 faltantes_max: int) -> list[Marca]:
    """Marca la lectura que llega DESPUÉS de un hueco. `lecturas` en orden de medido_en."""
    marcas = []
    for anterior, actual in zip(lecturas, lecturas[1:]):
        segundos = (actual.medido_en - anterior.medido_en).total_seconds()
        faltaron = round(segundos / intervalo_s) - 1
        if faltaron > faltantes_max:
            minutos = segundos / 60
            texto = f"{minutos:.0f} min" if minutos < 120 else f"{minutos / 60:.1f} h"
            marcas.append(Marca(actual.id, actual.medido_en, LECTURA, HUECO,
                                f"faltaron unas {faltaron} lecturas ({texto} sin datos)"))
    return marcas


def marcas_pegado(lecturas: list[LecturaCruda], variable: str, horas: float) -> list[Marca]:
    """Rachas del MISMO valor exacto que duran más de `horas`. Se marcan todas
    las lecturas de la racha. Las lecturas sin valor válido no cortan la racha;
    un hueco de más de CORTE_RACHA_PEGADO sí."""
    limite = timedelta(hours=horas)
    con_valor = [l for l in lecturas if l.valor(variable) is not None]
    marcas: list[Marca] = []

    def cerrar(racha: list[LecturaCruda]) -> None:
        if len(racha) > 1 and racha[-1].medido_en - racha[0].medido_en > limite:
            duracion = (racha[-1].medido_en - racha[0].medido_en).total_seconds() / 3600
            detalle = f"{variable} quedó en {racha[0].valor(variable):g} durante {duracion:.1f} h"
            marcas.extend(Marca(l.id, l.medido_en, variable, PEGADO, detalle) for l in racha)

    racha: list[LecturaCruda] = []
    for l in con_valor:
        if racha and (l.valor(variable) != racha[-1].valor(variable)
                      or l.medido_en - racha[-1].medido_en > CORTE_RACHA_PEGADO):
            cerrar(racha)
            racha = []
        racha.append(l)
    cerrar(racha)
    return marcas


def calcular_marcas(lecturas: Iterable[LecturaCruda], cfg: Config) -> list[Marca]:
    """Todas las marcas de un conjunto de lecturas de UNA cama."""
    ordenadas = sorted(lecturas, key=lambda l: (l.medido_en, l.id))
    marcas: list[Marca] = []
    for l in ordenadas:
        marcas.extend(marcas_de_validacion(l))
    marcas.extend(marcas_hueco(ordenadas, cfg.intervalo_lectura_s, cfg.hueco_lecturas_faltantes))
    for variable in VARIABLES:
        marcas.extend(marcas_pegado(ordenadas, variable, cfg.pegado_horas(variable)))
    return marcas


def excluidas(marcas: Iterable[Marca]) -> set[tuple[int, str]]:
    """(lectura_id, variable) que NO se usan en los agregados ni las tendencias."""
    return {(m.lectura_id, m.variable) for m in marcas if m.marca in (RANGO, SALTO, PEGADO)}

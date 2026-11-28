"""HU-05: estado (color y mensaje) de cada cama.

Prioridad: gris > rojo > sin_configurar > verde.
* Gris: no hay lecturas, o ALGUNO de los sensores requeridos (por defecto
  suelo y temperatura; la luz solo si hay sensor) lleva más de N minutos sin
  datos válidos. «Sensor de temperatura sin
  conexión».
* Rojo: alguna alerta abierta. «Revisar: humedad 22 %».
* Sin configurar: la cama no tiene cultivo ni rangos. «Configura un cultivo…».
* Verde: «Todo bien».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Optional, Sequence

from comun import mensajes
from comun.rangos import Rango

VERDE, ROJO, GRIS, SIN_CONFIGURAR = "verde", "rojo", "gris", "sin_configurar"
SENSORES = ("suelo", "temperatura", "luz")


@dataclass(frozen=True)
class Estado:
    color: str
    mensaje: str
    sensores_sin_datos: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertaResumen:
    tipo: str
    variable: str
    valor_actual: Optional[float]


def sensores_sin_datos(ultimas_validas: Mapping[str, Optional[datetime]],
                       primera_lectura: Optional[datetime], ahora: datetime,
                       minutos: float, requeridos: Sequence[str] = SENSORES) -> list[str]:
    """Sensores sin datos válidos en los últimos `minutos`.

    Un sensor que nunca envió datos válidos se mide desde la primera
    lectura de la cama (así una cama recién instalada no parte en gris).
    """
    if primera_lectura is None:
        return []
    limite = ahora - timedelta(minutes=minutos)
    resultado = []
    for sensor in SENSORES:              # en este orden, para el mensaje
        if sensor not in requeridos:
            continue
        referencia = ultimas_validas.get(sensor) or primera_lectura
        if referencia < limite:
            resultado.append(sensor)
    return resultado


def _items_revisar(alertas: Sequence[AlertaResumen], rango: Optional[Rango] = None) -> list[str]:
    items: list[str] = []
    for variable in SENSORES:
        de_variable = [a for a in alertas if a.variable == variable]
        if not de_variable:
            continue
        alerta = de_variable[0]
        # Límite cruzado, para no mostrar "30 %" cuando el mínimo es 30
        minimo = maximo = None
        if rango is not None:
            minimo = {"suelo_seco": rango.humedad_min, "helada": rango.temp_min}.get(alerta.tipo)
            maximo = {"suelo_encharcado": rango.humedad_max, "calor": rango.temp_max}.get(alerta.tipo)
        if variable == "suelo" and alerta.valor_actual is not None:
            items.append(mensajes.item_suelo(alerta.valor_actual, minimo, maximo))
        elif variable == "temperatura" and alerta.valor_actual is not None:
            items.append(mensajes.item_temperatura(alerta.valor_actual, minimo, maximo))
        elif variable == "luz":
            items.append(mensajes.ITEM_POCA_LUZ)
    return items


def calcular_estado(configurada: bool, hay_lecturas: bool, sin_datos: Sequence[str],
                    alertas_abiertas: Sequence[AlertaResumen],
                    rango: Optional[Rango] = None) -> Estado:
    if not hay_lecturas:
        return Estado(GRIS, mensajes.SIN_LECTURAS)
    if sin_datos:
        return Estado(GRIS, mensajes.sensores_sin_conexion(sin_datos), tuple(sin_datos))
    # La alerta preventiva de tendencia no pone la cama en rojo: no está fuera de rango
    de_rango = [a for a in alertas_abiertas if a.tipo not in ("sensor_sin_datos", "tendencia_secado")]
    if de_rango:
        items = _items_revisar(de_rango, rango)
        return Estado(ROJO, mensajes.revisar(items) if items else "Revisar")
    if not configurada:
        return Estado(SIN_CONFIGURAR, mensajes.CONFIGURA_CULTIVO)
    return Estado(VERDE, mensajes.TODO_BIEN)

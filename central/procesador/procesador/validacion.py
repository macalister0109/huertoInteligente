"""RF-05: interpretación, validación y limpieza de las lecturas.

Lógica pura (sin BD ni MQTT) para poder testearla aislada.

Reglas:
* Rango físico: suelo 0–100 %, temperatura y humedad del aire según el
  sensor (Config; por defecto DHT11: 0 a 50 °C y 0–100 %), luz 0 a
  120 000 lux y mV crudos del suelo 0 a 3 600. Un valor fuera de rango
  se descarta (la lectura se guarda igual, marcando el campo inválido).
* Saltos imposibles respecto de la lectura ANTERIOR EN EL TIEMPO (válida
  o no, para que un cambio real solo invalide una lectura y la cama no
  quede "pegada"):
    - suelo: solo las BAJADAS bruscas (un riego sí sube de golpe),
    - temperatura y humedad del aire: en ambos sentidos,
    - luz: sin control (una nube la cambia en segundos).
* Cada variable se valida por separado: un sensor malo no bloquea a los demás.
* La lectura completa es inválida solo si su hora es imposible (en el futuro)
  o si no trae ningún dato utilizable.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from comun.calibracion import Calibracion, porcentaje
from comun.config import Config

# Rangos fijos (no dependen del sensor de aire instalado)
RANGOS_FISICOS = {
    "suelo": (0.0, 100.0),
    "lux": (0.0, 120000.0),
    "suelo_mv": (0.0, 3600.0),   # el ADC del ESP32 a 3,3 V no pasa de ~3 300 mV
}


def rangos_fisicos(cfg: Config) -> dict[str, tuple[float, float]]:
    return {
        **RANGOS_FISICOS,
        "temp": (cfg.temp_min_fisico, cfg.temp_max_fisico),
        "hum_aire": (cfg.hum_aire_min_fisico, cfg.hum_aire_max_fisico),
    }

# Más allá de este tiempo entre lecturas no tiene sentido comparar saltos
MAX_MINUTOS_COMPARACION = 30.0
SEQ_MAXIMO = 2**32 - 1


class MensajeInvalido(ValueError):
    """El mensaje no se puede guardar (JSON roto, sin seq o sin hora)."""


@dataclass
class DatosLectura:
    """Contenido del mensaje MQTT ya interpretado (aún sin validar valores)."""
    nodo_id: str
    seq: int
    medido_en: datetime            # UTC ingenuo
    suelo: Optional[list]          # valores crudos por sonda
    temp: Any
    hum_aire: Any
    lux: Any
    nodo_id_mensaje: Optional[str] = None
    suelo_mv: Any = None           # mV crudos de la sonda (para calibrar y ver deriva)


@dataclass
class ValoresAnteriores:
    """Valores de la lectura anterior en el tiempo, para detectar saltos."""
    medido_en: datetime
    suelo_prom: Optional[float] = None
    temp: Optional[float] = None
    hum_aire: Optional[float] = None


@dataclass
class LecturaValidada:
    nodo_id: str
    seq: int
    medido_en: datetime
    suelo_detalle: Optional[list]
    suelo_prom: Optional[float]
    temp: Optional[float]
    hum_aire: Optional[float]
    lux: Optional[float]
    suelo_mv: Optional[int] = None
    valida: bool = True
    invalidos: dict = field(default_factory=dict)
    motivo: Optional[str] = None

    @property
    def tiene_datos(self) -> bool:
        return any(v is not None for v in (self.suelo_prom, self.temp, self.hum_aire, self.lux))


# ---------------------------------------------------------------------------
# Interpretación del mensaje
# ---------------------------------------------------------------------------

def parsear_hora(texto: Any) -> datetime:
    """ISO 8601 en UTC ('2026-11-26T12:00:00Z') -> datetime UTC ingenuo."""
    if not isinstance(texto, str) or not texto:
        raise MensajeInvalido("falta medido_en")
    try:
        t = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        raise MensajeInvalido(f"medido_en no es ISO 8601: {texto!r}")
    if t.tzinfo is None:
        raise MensajeInvalido("medido_en debe indicar la zona (UTC, terminado en Z)")
    return t.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def interpretar(nodo_id: str, payload: bytes | str) -> DatosLectura:
    try:
        datos = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise MensajeInvalido("el mensaje no es JSON")
    if not isinstance(datos, dict):
        raise MensajeInvalido("el mensaje no es un objeto JSON")

    seq = datos.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or not 0 <= seq <= SEQ_MAXIMO:
        raise MensajeInvalido(f"seq inválido: {seq!r}")

    suelo = datos.get("suelo")
    # Nodo con una sola sonda: "suelo_pct" (prototipo 1) o "suelo_prom"
    for clave in ("suelo_pct", "suelo_prom"):
        if suelo is None and datos.get(clave) is not None:
            suelo = [datos.get(clave)]
    if suelo is not None and not isinstance(suelo, list):
        suelo = [suelo]

    return DatosLectura(
        nodo_id=nodo_id,
        seq=seq,
        medido_en=parsear_hora(datos.get("medido_en")),
        suelo=suelo,
        temp=datos.get("temp"),
        hum_aire=datos.get("hum_aire"),
        lux=datos.get("lux", datos.get("luz")),
        nodo_id_mensaje=datos.get("nodo_id"),
        suelo_mv=datos.get("suelo_mv"),
    )


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def _es_numero(valor: Any) -> bool:
    return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
            and math.isfinite(valor))


def _redondear(valor: float, decimales: int = 1) -> float:
    """Redondeo con 0,5 hacia arriba (igual que el nodo): 29.25 -> 29.3."""
    cuantizador = Decimal(1).scaleb(-decimales)
    return float(Decimal(str(valor)).quantize(cuantizador, rounding=ROUND_HALF_UP))


def _fmt(valor: Any) -> str:
    return f"{valor:g}" if _es_numero(valor) else repr(valor)


def validar(datos: DatosLectura, anterior: Optional[ValoresAnteriores],
            recibido_en: datetime, cfg: Config,
            calibracion: Optional[Calibracion] = None) -> LecturaValidada:
    """`calibracion`: la de la cama (comun/calibracion.py). Si viene y la
    lectura trae mV válidos, el % de suelo se calcula desde los mV y no se usa
    el % del nodo (que queda igual en suelo_detalle)."""
    invalidos: dict[str, dict] = {}
    detalles: list[str] = []

    def descartar(campo: str, valor: Any, tipo: str, detalle: str) -> None:
        invalidos[campo] = {"valor": valor, "tipo": tipo, "detalle": detalle}
        detalles.append(detalle)

    rangos = rangos_fisicos(cfg)

    def en_rango(campo: str, valor: Any, etiqueta: str) -> Optional[float]:
        if valor is None:
            return None
        if not _es_numero(valor):
            descartar(etiqueta, valor, "tipo_dato", f"{etiqueta} no es un número ({_fmt(valor)})")
            return None
        minimo, maximo = rangos[campo]
        if not minimo <= valor <= maximo:
            descartar(etiqueta, valor, "rango", f"{etiqueta} fuera de rango físico ({_fmt(valor)})")
            return None
        return float(valor)

    # --- Suelo: cada sonda por separado; el promedio se recalcula aquí ---
    sondas_validas = []
    for i, valor in enumerate(datos.suelo or [], start=1):
        v = en_rango("suelo", valor, f"suelo_sonda_{i}")
        if v is not None:
            sondas_validas.append(v)
    suelo_prom = _redondear(sum(sondas_validas) / len(sondas_validas)) if sondas_validas else None

    temp = en_rango("temp", datos.temp, "temp")
    hum_aire = en_rango("hum_aire", datos.hum_aire, "hum_aire")
    lux = en_rango("lux", datos.lux, "lux")
    suelo_mv = en_rango("suelo_mv", datos.suelo_mv, "suelo_mv")

    # --- Calibración de la cama en el servidor (una sola sonda con mV) ---
    if calibracion is not None and suelo_mv is not None and len(datos.suelo or []) <= 1:
        if "suelo_sonda_1" in invalidos:
            # el % del nodo venía malo, pero los mV sirven: se usan los mV
            invalidos.pop("suelo_sonda_1")
            detalles[:] = [d for d in detalles if not d.startswith("suelo_sonda_1")]
        suelo_prom = porcentaje(suelo_mv, calibracion)

    # --- Saltos imposibles respecto de la lectura anterior en el tiempo ---
    if anterior is not None:
        minutos = (datos.medido_en - anterior.medido_en).total_seconds() / 60
        if 0 < minutos <= MAX_MINUTOS_COMPARACION:
            if suelo_prom is not None and anterior.suelo_prom is not None:
                bajada = (anterior.suelo_prom - suelo_prom) / minutos
                if bajada > cfg.salto_max_bajada_suelo:
                    descartar("suelo", suelo_prom, "salto",
                              f"suelo bajó {_fmt(round(anterior.suelo_prom - suelo_prom, 1))} "
                              f"puntos en {_fmt(round(minutos, 1))} min")
                    suelo_prom = None
            if temp is not None and anterior.temp is not None:
                if abs(temp - anterior.temp) / minutos > cfg.salto_max_temp:
                    descartar("temp", temp, "salto",
                              f"temp cambió {_fmt(round(temp - anterior.temp, 1))} °C "
                              f"en {_fmt(round(minutos, 1))} min")
                    temp = None
            if hum_aire is not None and anterior.hum_aire is not None:
                if abs(hum_aire - anterior.hum_aire) / minutos > cfg.salto_max_hum_aire:
                    descartar("hum_aire", hum_aire, "salto",
                              f"hum_aire cambió {_fmt(round(hum_aire - anterior.hum_aire, 1))} "
                              f"puntos en {_fmt(round(minutos, 1))} min")
                    hum_aire = None

    lectura = LecturaValidada(
        nodo_id=datos.nodo_id, seq=datos.seq, medido_en=datos.medido_en,
        suelo_detalle=datos.suelo, suelo_prom=suelo_prom,
        temp=temp, hum_aire=hum_aire, lux=lux, invalidos=invalidos,
        suelo_mv=None if suelo_mv is None else int(round(suelo_mv)),
    )

    # --- Validez de la lectura completa ---
    if datos.medido_en > recibido_en + timedelta(minutes=cfg.max_adelanto_reloj_min):
        lectura.valida = False
        detalles.insert(0, "hora de medición en el futuro (reloj del nodo mal sincronizado)")
    elif not lectura.tiene_datos:
        lectura.valida = False
        detalles.insert(0, "sin datos válidos")

    lectura.motivo = "; ".join(detalles)[:500] if detalles else None
    return lectura


def valores_anteriores_desde_fila(fila: dict) -> ValoresAnteriores:
    """Arma los valores anteriores desde una fila de `lecturas`.

    Si un valor se descartó por SALTO, se usa igual su valor crudo para la
    siguiente comparación (así un cambio real no deja la cama "pegada").
    Los descartados por rango físico no se usan: no son mediciones reales.
    """
    invalidos = fila.get("campos_invalidos") or {}
    if isinstance(invalidos, str):
        invalidos = json.loads(invalidos)

    def valor(columna: str, clave: str) -> Optional[float]:
        if fila.get(columna) is not None:
            return float(fila[columna])
        entrada = invalidos.get(clave)
        if entrada and entrada.get("tipo") == "salto" and _es_numero(entrada.get("valor")):
            return float(entrada["valor"])
        return None

    return ValoresAnteriores(
        medido_en=fila["medido_en"],
        suelo_prom=valor("suelo_prom", "suelo"),
        temp=valor("temp", "temp"),
        hum_aire=valor("hum_aire", "hum_aire"),
    )

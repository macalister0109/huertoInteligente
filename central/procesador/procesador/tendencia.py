"""Tarea del procesador: predicción de secado y alerta preventiva (RF-15).

Cada `cada_min` minutos, para cada cama activa:
* calcula la predicción y guarda cuánto tardó (CQ-13, tabla tiempos_tendencia);
* si la alerta está ACTIVADA en la configuración (por defecto no):
    - abre o actualiza `tendencia_secado` cuando llegaría al mínimo dentro
      del horizonte (sin duplicar, como las demás alertas);
    - la resuelve si ya no se está secando, si no llegaría en las próximas
      6 h, o si ya se abrió la alerta real de suelo seco;
    - si la tendencia no es clara (pocos datos o mal ajuste) no cambia nada:
      así un dato ruidoso no abre y cierra la alerta a cada rato.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from comun import ajustes
from comun.analitica.prediccion import (BAJO_MINIMO, ESTIMACION, FUERA_HORIZONTE, SIN_RANGO,
                                        Prediccion)
from comun.analitica.servicio_tendencia import parametros, predecir_cama
from comun.config import Config
from comun.rangos import rango_efectivo

from . import repositorio as repo
from .reglas import RESOLVER, Decision, abrir_o_actualizar

log = logging.getLogger(__name__)

TIPO = "tendencia_secado"


def mensaje(nombre: str, pred: Prediccion) -> str:
    return f"{pred.texto(nombre)}. Planifica el riego."


def decidir(pred: Prediccion, activa: bool, configurada: bool, abiertas: set[str],
            nombre: str) -> list[Decision]:
    """Regla pura de la alerta preventiva."""
    tiene = TIPO in abiertas
    if not activa or not configurada or "suelo_seco" in abiertas:
        return [Decision(RESOLVER, TIPO, "suelo")] if tiene else []
    if pred.estado == ESTIMACION:
        return [abrir_o_actualizar(TIPO, "suelo", pred.horas, mensaje(nombre, pred), abiertas)]
    no_se_seca = pred.ajuste is not None and pred.ajuste.pendiente >= 0
    if tiene and (pred.estado in (FUERA_HORIZONTE, BAJO_MINIMO, SIN_RANGO) or no_se_seca):
        return [Decision(RESOLVER, TIPO, "suelo")]
    return []


class TareaTendencia:
    def __init__(self, cfg: Config, cada_min: float = 5):
        self.cfg = cfg
        self.cada = timedelta(minutes=cada_min)
        self._ultima: Optional[datetime] = None

    def pendiente(self, ahora: datetime) -> bool:
        return self._ultima is None or ahora - self._ultima >= self.cada

    def ejecutar(self, procesador, ahora: datetime) -> int:
        """Devuelve cuántas alertas cambiaron."""
        if not self.pendiente(ahora):
            return 0
        self._ultima = ahora
        conn = procesador.conn
        vigentes = ajustes.leer(conn, self.cfg)
        p = parametros(self.cfg, vigentes)
        cambios = 0
        for cama in repo.camas_activas(conn):
            pred, ms = predecir_cama(conn, cama, ahora, p, registrar=True)
            if ms > 1000:
                log.warning("[%s] la predicción tardó %.0f ms (meta CQ-13: 1 s)", cama["nodo_id"], ms)
            abiertas = {a["tipo"] for a in repo.alertas_abiertas(conn, cama["id"])}
            decisiones = decidir(pred, bool(vigentes["tendencia_activa"]),
                                 rango_efectivo(cama).configurado, abiertas, cama["nombre"])
            conn.commit()
            if decisiones:
                procesador.aplicar_y_publicar(cama, decisiones, ahora)
                cambios += len(decisiones)
        conn.commit()
        return cambios

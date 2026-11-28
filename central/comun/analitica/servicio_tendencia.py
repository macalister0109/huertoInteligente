"""Predicción de una cama con los datos de la BD y medición de su tiempo (CQ-13)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from ..config import Config
from ..fechas import iso as _iso
from ..rangos import rango_efectivo
from . import repositorio as repo
from .prediccion import FUERA_HORIZONTE, ParametrosPrediccion, Prediccion, predecir
from .riego import puntos_suelo


def parametros(cfg: Config, vigentes: Optional[Mapping[str, Any]] = None) -> ParametrosPrediccion:
    """Los de /configuracion (ventana y R²) y, si faltan, los del .env."""
    v = vigentes or {}
    return ParametrosPrediccion(
        ventana_h=float(v.get("tendencia_ventana_h", cfg.tendencia_ventana_h)),
        min_puntos=int(v.get("tendencia_min_puntos", cfg.tendencia_min_puntos)),
        r2_min=float(v.get("tendencia_r2_min", cfg.tendencia_r2_min)),
        horizonte_h=cfg.tendencia_horizonte_h,
        riego_umbral_pts=float(v.get("riego_umbral_pts", cfg.riego_umbral_pts)),
        riego_ventana_min=cfg.riego_ventana_min,
    )


def predecir_cama(conn, cama: Mapping[str, Any], ahora: datetime, p: ParametrosPrediccion,
                  registrar: bool = False) -> tuple[Prediccion, float]:
    """Devuelve (predicción, milisegundos). Mide TODO: lectura de la BD y cálculo.
    `registrar=True` guarda la medición en tiempos_tendencia (CQ-13)."""
    inicio = time.perf_counter()
    desde = ahora - timedelta(hours=p.ventana_h) - timedelta(minutes=p.riego_ventana_min * 2)
    hasta = ahora + timedelta(seconds=1)
    lecturas = repo.lecturas_entre(conn, cama["id"], desde, hasta)
    marcas = repo.marcas_entre(conn, cama["id"], desde, hasta)
    conocidos = repo.riegos(conn, cama["id"], desde=desde, hasta=ahora)
    pred = predecir(puntos_suelo(lecturas, marcas), ahora, rango_efectivo(cama).humedad_min, p,
                    conocidos)
    ms = (time.perf_counter() - inicio) * 1000
    if registrar:
        a = pred.ajuste
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tiempos_tendencia
                               (cama_id, calculado_en, duracion_ms, n_puntos, estado, horas, pendiente, r2)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (cama["id"], ahora, round(ms, 3), pred.n_puntos, pred.estado, pred.horas,
                         None if a is None else a.pendiente, None if a is None else a.r2))
    return pred, ms


def prediccion_json(pred: Prediccion, nombre_cama: str, ms: Optional[float] = None,
                    horizonte_h: float = 6.0) -> dict:
    a = pred.ajuste
    recta = None
    if a is not None and pred.desde is not None:
        # Dos puntos de la recta del tramo actual (para dibujarla en el gráfico): hasta el
        # cruce estimado o, si no llega en el horizonte, proyectada `horizonte_h` horas
        if pred.horas:
            fin = a.t0 + timedelta(hours=pred.horas)
        elif pred.estado == FUERA_HORIZONTE:
            fin = a.t0 + timedelta(hours=horizonte_h)
        else:
            fin = a.t0
        recta = [{"t": _iso(pred.desde), "valor": round(a.valor_en(pred.desde), 2)},
                 {"t": _iso(fin), "valor": round(a.valor_en(fin), 2)}]
    return {
        "estado": pred.estado,
        "texto": pred.texto(nombre_cama),
        "horas": pred.horas,
        "minimo": pred.minimo,
        "motivo": pred.motivo,
        "pendiente_pts_h": None if a is None else round(a.pendiente, 3),
        "r2": None if a is None or a.r2 is None else round(a.r2, 3),
        "n_puntos": pred.n_puntos,
        "desde": _iso(pred.desde),
        "inicio_tramo": _iso(pred.inicio_tramo),
        "recta": recta,
        "duracion_ms": None if ms is None else round(ms, 1),
    }


"""Ajustes del huerto editables desde /configuracion (tabla configuracion_huerto).

Cada ajuste tiene un valor por defecto que viene del .env (Config). Lo que
guarda el docente en la BD tiene prioridad. Si un valor guardado no es
válido (ej. alguien lo editó a mano), se ignora y rige el del .env.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from .clima.base import validar_coordenadas
from .clima.proveedores import nombres as nombres_proveedores
from .config import Config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Definicion:
    clave: str
    etiqueta: str
    convertir: Callable[[str], Any]           # texto -> valor; lanza ValueError si no sirve
    por_defecto: Callable[[Config], Any]


def _float(texto: str) -> float:
    return float(str(texto).strip().replace(",", "."))


def _latitud(texto: str) -> float:
    v = _float(texto)
    errores = validar_coordenadas(v, 0)
    if errores:
        raise ValueError(errores[0])
    return v


def _longitud(texto: str) -> float:
    v = _float(texto)
    errores = validar_coordenadas(0, v)
    if errores:
        raise ValueError(errores[0])
    return v


def _estacion(texto: str) -> str:
    v = str(texto).strip()
    if v and not (v.isdigit() and len(v) <= 10):
        raise ValueError("El código de estación de la DMC debe tener solo números (ej. 330020).")
    return v


def _booleano(texto: str) -> bool:
    v = str(texto).strip().lower()
    if v in ("1", "true", "si", "sí", "on", "yes"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return False
    raise ValueError("Valor no válido: usa sí o no.")


def _entre(minimo: float, maximo: float, etiqueta: str, entero: bool = False):
    def convertir(texto: str):
        v = _float(texto)
        if not minimo <= v <= maximo:
            raise ValueError(f"{etiqueta} debe estar entre {minimo:g} y {maximo:g}.")
        return int(v) if entero else v
    return convertir


def _zona(texto: str) -> str:
    v = str(texto).strip().lower()
    if not v.isalpha() or len(v) > 20:
        raise ValueError("Zona climática no válida.")
    return v


def _proveedor(texto: str) -> str:
    v = str(texto).strip()
    if v not in nombres_proveedores():
        raise ValueError("Proveedor de clima desconocido.")
    return v


DEFINICIONES: dict[str, Definicion] = {d.clave: d for d in (
    Definicion("clima_proveedor", "Proveedor de clima", _proveedor, lambda c: c.clima_proveedor),
    Definicion("clima_lat", "Latitud", _latitud, lambda c: c.clima_lat),
    Definicion("clima_lon", "Longitud", _longitud, lambda c: c.clima_lon),
    Definicion("dmc_estacion", "Estación DMC", _estacion, lambda c: c.dmc_estacion),
    # Tendencia (RF-15)
    Definicion("tendencia_activa", "Alerta preventiva", _booleano, lambda c: c.tendencia_activa),
    Definicion("tendencia_ventana_h", "Ventana de la regresión",
               _entre(1, 24, "La ventana de la regresión (horas)"), lambda c: c.tendencia_ventana_h),
    Definicion("tendencia_r2_min", "R² mínimo", _entre(0, 1, "El R² mínimo"),
               lambda c: c.tendencia_r2_min),
    # Zona climática del huerto (las camas sin zona propia usan esta). La lee también
    # la vista v_camas_zona de la BD; si no está guardada, «centro».
    Definicion("zona_huerto", "Zona del huerto", _zona, lambda c: "centro"),
    Definicion("riego_umbral_pts", "Subida que cuenta como riego",
               _entre(3, 50, "La subida que cuenta como riego (puntos)"), lambda c: c.riego_umbral_pts),
)}

# Ajustes que también cambian la configuración de los cálculos (Config)
_EN_CONFIG = ("tendencia_activa", "tendencia_ventana_h", "tendencia_r2_min", "riego_umbral_pts")


def leer(conn, cfg: Config) -> dict[str, Any]:
    """Valores vigentes: los guardados en la BD y, si faltan, los del .env."""
    valores = {clave: d.por_defecto(cfg) for clave, d in DEFINICIONES.items()}
    with conn.cursor() as cur:
        cur.execute("SELECT clave, valor FROM configuracion_huerto")
        filas = cur.fetchall()
    for fila in filas:
        d = DEFINICIONES.get(fila["clave"])
        if d is None:
            continue
        try:
            valores[d.clave] = d.convertir(fila["valor"])
        except ValueError:
            log.warning("Ajuste %s guardado no válido (%r): se usa el del .env",
                        d.clave, fila["valor"])
    return valores


def config_vigente(conn, cfg: Config) -> Config:
    """Config con los ajustes guardados en la BD (los que afectan los cálculos)."""
    vigentes = leer(conn, cfg)
    return replace(cfg, **{c: vigentes[c] for c in _EN_CONFIG})


def validar(cambios: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Devuelve (valores convertidos, errores en lenguaje simple)."""
    valores, errores = {}, []
    for clave, texto in cambios.items():
        d = DEFINICIONES.get(clave)
        if d is None:
            errores.append(f"Ajuste desconocido: {clave}.")
            continue
        try:
            valores[clave] = d.convertir(texto)
        except ValueError as e:
            mensaje = str(e)
            errores.append(mensaje if mensaje and not mensaje.startswith("could not")
                           else f"{d.etiqueta}: valor no válido.")
    return valores, errores


def guardar(conn, cambios: Mapping[str, Any]) -> list[str]:
    """Valida y guarda. Si hay algún error no guarda nada. No hace commit."""
    valores, errores = validar(cambios)
    if errores:
        return errores
    with conn.cursor() as cur:
        for clave, valor in valores.items():
            cur.execute("""INSERT INTO configuracion_huerto (clave, valor) VALUES (%s, %s)
                           ON DUPLICATE KEY UPDATE valor = VALUES(valor)""", (clave, str(valor)))
    return []

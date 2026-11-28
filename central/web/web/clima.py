"""Clima de referencia en el tablero: caché del servidor y textos para la pantalla.

El navegador NUNCA llama a la API externa: pide /api/clima/... a este
servidor, que usa la caché (TTL configurable) y, si la API falla, el último
dato guardado. Las claves de los proveedores nunca salen del servidor.

La página de camas no depende de esto: el bloque de clima se carga aparte.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from comun import ajustes
from comun.clima import (DESACTUALIZADO, OK, CacheClima, ClimaReferencia, ProveedorClima,
                         ResultadoClima)
from comun.clima import comparacion
from comun.clima import repositorio as repo_clima
from comun.clima.proveedores import crear_proveedor
from comun.clima.proveedores import nombres as nombres_proveedores
from comun.config import Config
from comun.fechas import iso

CrearProveedor = Callable[[str], ProveedorClima]

TEXTO_NO_DISPONIBLE = "Clima exterior no disponible"
EPOCA = datetime(1970, 1, 1)


def texto_edad(segundos: Optional[int]) -> Optional[str]:
    """«hace 12 min», «hace 2 h», «hace 3 días» (lenguaje simple)."""
    if segundos is None:
        return None
    minutos = segundos // 60
    if minutos < 1:
        return "recién"
    if minutos < 60:
        return f"hace {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"hace {horas} h"
    dias = horas // 24
    return f"hace {dias} día" if dias == 1 else f"hace {dias} días"


def clima_a_json(c: Optional[ClimaReferencia]) -> Optional[dict]:
    if c is None:
        return None
    d = c.como_dict()
    d["observado_en"] = iso(c.observado_en)
    return d


class ServicioClima:
    def __init__(self, cfg: Config, reloj: Callable[[], datetime],
                 crear: Optional[CrearProveedor] = None):
        self.cfg = cfg
        self.reloj = reloj
        self.crear = crear or (lambda nombre: crear_proveedor(nombre, zona_horaria=cfg.zona_horaria))
        self.cache = CacheClima(ttl_s=cfg.clima_ttl_min * 60, reloj=reloj)

    @staticmethod
    def nombre_visible(proveedor: ProveedorClima) -> str:
        return proveedor.nombre_corto or proveedor.titulo or proveedor.nombre

    # ---------------------------------------------------------------- actual

    def _ajustes(self, conn) -> dict:
        valores = ajustes.leer(conn, self.cfg)
        conn.commit()
        return valores

    def consultar(self, conn, forzar: bool = False, proveedor_nombre: Optional[str] = None,
                  lat: Optional[float] = None,
                  lon: Optional[float] = None,
                  extra: Optional[dict] = None) -> tuple[ProveedorClima, ResultadoClima]:
        """Sin argumentos usa el proveedor y las coordenadas de la configuración.
        `extra` reemplaza ajustes solo para esta consulta (botón «Probar conexión»)."""
        valores = {**self._ajustes(conn), **(extra or {})}
        proveedor = self.crear(proveedor_nombre or valores["clima_proveedor"])
        proveedor.aplicar_ajustes(valores)
        lat = valores["clima_lat"] if lat is None else lat
        lon = valores["clima_lon"] if lon is None else lon

        def respaldo(fuente, lat_, lon_):
            # Una estación fija (DMC) guarda sus propias coordenadas: se busca solo por fuente
            if not proveedor.usa_coordenadas:
                lat_ = lon_ = None
            guardado = repo_clima.ultima(conn, fuente, lat_, lon_)
            conn.commit()
            return guardado

        return proveedor, self.cache.consultar(proveedor, lat, lon, forzar=forzar,
                                               respaldo=respaldo)

    def actual(self, conn) -> dict:
        """Respuesta de GET /api/clima/actual."""
        proveedor, r = self.consultar(conn)
        ahora = self.reloj()
        edad = r.edad_s(ahora)
        nombre = self.nombre_visible(proveedor)
        if r.estado == OK:
            texto = f"{nombre} · {texto_edad(edad)}"
        elif r.estado == DESACTUALIZADO:
            texto = f"Dato de {texto_edad(edad)} ({nombre}, sin conexión)"
        else:
            texto = TEXTO_NO_DISPONIBLE
        return {
            "estado": r.estado,
            "fuente": proveedor.nombre,
            "fuente_nombre": nombre,
            "clima": clima_a_json(r.clima),
            "observado_en": iso(r.clima.observado_en) if r.clima else None,
            "obtenido_en": iso(r.obtenido_en),
            "edad_s": edad,
            "texto_edad": texto_edad(edad),
            "texto_estado": texto,
            "et0": comparacion.texto_et0(r.clima),
        }

    # ----------------------------------------------------------- comparación

    def _candidatas(self, conn, medido_en: datetime) -> list[ClimaReferencia]:
        """Instantáneas horarias guardadas + el dato en memoria (sin consultar la red)."""
        candidatas = repo_clima.cercanas_a(conn, medido_en, comparacion.MARGEN_MAX_MIN)
        conn.commit()
        en_memoria = self.cache.en_memoria()
        return candidatas + [c for c in en_memoria if c not in candidatas]

    def comparar(self, conn, lectura: Optional[dict]) -> Optional[dict]:
        if not lectura or lectura.get("medido_en") is None:
            return None
        datos = {"medido_en": lectura["medido_en"],
                 "temp": None if lectura.get("temp") is None else float(lectura["temp"]),
                 "hum_aire": None if lectura.get("hum_aire") is None else float(lectura["hum_aire"])}
        c = comparacion.comparar(datos, self._candidatas(conn, lectura["medido_en"]))
        if c is None:
            return None
        c["referencia_observada_en"] = iso(c["referencia_observada_en"])
        c["fuente_nombre"] = (self.nombre_visible(self.crear(c["fuente"]))
                              if c["fuente"] in nombres_proveedores() else c["fuente"])
        c["lectura_medida_en"] = iso(lectura["medido_en"])
        return c

    def serie(self, conn, desde: datetime, hasta: datetime) -> list[dict]:
        """Clima exterior guardado (una instantánea por hora) para los gráficos."""
        filas = repo_clima.entre(conn, desde, hasta)
        conn.commit()
        return [{"t": int((c.observado_en - EPOCA).total_seconds() * 1000),
                 "temp": c.temp_aire_c, "hum_aire": c.hum_rel_pct,
                 "suelo_vwc": c.hum_suelo_vwc_pct, "fuente": c.fuente} for c in filas]


"""Configuración leída desde variables de entorno (central/.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Optional


def _a_bool(valor: str) -> bool:
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


# Nombre de cada campo -> variable de entorno
_VARIABLES = {
    "db_host": "DB_HOST",
    "db_puerto": "DB_PORT",
    "db_usuario": "MARIADB_USER",
    "db_clave": "MARIADB_PASSWORD",
    "db_nombre": "MARIADB_DATABASE",
    "mqtt_host": "MQTT_HOST",
    "mqtt_puerto": "MQTT_PORT",
    "mqtt_usuario": "MQTT_USER_PROCESADOR",
    "mqtt_clave": "MQTT_PASS_PROCESADOR",
    "zona_horaria": "ZONA_HORARIA",
    "histeresis_suelo": "HISTERESIS_SUELO",
    "histeresis_temp": "HISTERESIS_TEMP",
    "calor_minutos_sostenido": "CALOR_MINUTOS_SOSTENIDO",
    "max_hueco_racha_min": "MAX_HUECO_RACHA_MIN",
    "umbral_luz_lux": "UMBRAL_LUZ_LUX",
    "dias_poca_luz": "DIAS_POCA_LUZ",
    "hora_inicio_sol": "HORA_INICIO_SOL",
    "hora_fin_sol": "HORA_FIN_SOL",
    "cobertura_minima_luz": "COBERTURA_MINIMA_LUZ",
    "max_hueco_luz_min": "MAX_HUECO_LUZ_MIN",
    "gracia_cierre_dia_min": "GRACIA_CIERRE_DIA_MIN",
    "minutos_sin_datos_gris": "MINUTOS_SIN_DATOS_GRIS",
    "salto_max_bajada_suelo": "SALTO_MAX_BAJADA_SUELO",
    "salto_max_temp": "SALTO_MAX_TEMP",
    "salto_max_hum_aire": "SALTO_MAX_HUM_AIRE",
    "max_adelanto_reloj_min": "MAX_ADELANTO_RELOJ_MIN",
    "temp_min_fisico": "TEMP_MIN_FISICO",
    "temp_max_fisico": "TEMP_MAX_FISICO",
    "hum_aire_min_fisico": "HUM_AIRE_MIN_FISICO",
    "hum_aire_max_fisico": "HUM_AIRE_MAX_FISICO",
    "tendencia_activa": "TENDENCIA_ACTIVA",
    "sensores_requeridos": "SENSORES_REQUERIDOS",
    "clima_proveedor": "CLIMA_PROVEEDOR",
    "clima_lat": "CLIMA_LAT",
    "clima_lon": "CLIMA_LON",
    "clima_ttl_min": "CLIMA_TTL_MIN",
    "dmc_estacion": "DMC_ESTACION",
    "intervalo_lectura_s": "INTERVALO_LECTURA_S",
    "hueco_lecturas_faltantes": "HUECO_LECTURAS_FALTANTES",
    "pegado_horas_suelo": "PEGADO_HORAS_SUELO",
    "pegado_horas_temp": "PEGADO_HORAS_TEMP",
    "pegado_horas_hum_aire": "PEGADO_HORAS_HUM_AIRE",
    "riego_umbral_pts": "RIEGO_UMBRAL_PTS",
    "riego_ventana_min": "RIEGO_VENTANA_MIN",
    "tendencia_pts_rapido": "TENDENCIA_PTS_RAPIDO",
    "tendencia_pts_estable": "TENDENCIA_PTS_ESTABLE",
    "tendencia_ventana_h": "TENDENCIA_VENTANA_H",
    "tendencia_r2_min": "TENDENCIA_R2_MIN",
    "tendencia_min_puntos": "TENDENCIA_MIN_PUNTOS",
    "tendencia_horizonte_h": "TENDENCIA_HORIZONTE_H",
}


@dataclass(frozen=True)
class Config:
    # Base de datos
    db_host: str = "localhost"
    db_puerto: int = 3306
    db_usuario: str = "huerto"
    db_clave: str = ""
    db_nombre: str = "huerto"
    # MQTT
    mqtt_host: str = "localhost"
    mqtt_puerto: int = 1883
    mqtt_usuario: str = "procesador"
    mqtt_clave: str = ""
    # Reglas
    zona_horaria: str = "America/Santiago"
    histeresis_suelo: float = 2.0
    histeresis_temp: float = 1.0
    calor_minutos_sostenido: float = 30.0
    max_hueco_racha_min: float = 10.0       # un hueco mayor corta la racha de calor
    umbral_luz_lux: float = 25000.0
    dias_poca_luz: int = 3
    hora_inicio_sol: int = 6
    hora_fin_sol: int = 21
    cobertura_minima_luz: float = 0.75
    max_hueco_luz_min: float = 10.0         # una lectura de luz "cubre" como máximo 10 min
    gracia_cierre_dia_min: int = 120        # espera lecturas atrasadas antes de cerrar el día
    minutos_sin_datos_gris: float = 120.0
    salto_max_bajada_suelo: float = 10.0    # puntos por minuto
    salto_max_temp: float = 3.0             # °C por minuto
    salto_max_hum_aire: float = 15.0        # puntos por minuto
    max_adelanto_reloj_min: float = 5.0     # medido_en más adelantado que esto = hora imposible
    # Rango físico del sensor de aire. Por defecto el DHT11 del prototipo 1:
    # 0 a 50 °C (no mide bajo cero) y humedad 0 a 100 %.
    temp_min_fisico: float = 0.0
    temp_max_fisico: float = 50.0
    hum_aire_min_fisico: float = 0.0
    hum_aire_max_fisico: float = 100.0
    tendencia_activa: bool = False
    # Sensores que, si pasan MINUTOS_SIN_DATOS_GRIS sin datos válidos, ponen la
    # cama en gris (HU-05). El prototipo 1 no tiene sensor de luz: no cuenta.
    # Cuando se agregue (prototipo 2): SENSORES_REQUERIDOS=suelo,temperatura,luz
    sensores_requeridos: str = "suelo,temperatura"
    # Clima externo de referencia. Proveedor, latitud y longitud son solo los
    # valores POR DEFECTO: el docente los cambia en /configuracion (tabla
    # configuracion_huerto). Por defecto: zona sur de Santiago (San Ramón / La Pintana).
    clima_proveedor: str = "open-meteo"
    clima_lat: float = -33.54
    clima_lon: float = -70.64
    clima_ttl_min: float = 20.0
    dmc_estacion: str = ""          # código nacional de la EMA (solo proveedor DMC)
    # Capa de datos para análisis (marcas de calidad y agregados)
    intervalo_lectura_s: float = 30.0       # cada cuánto mide el nodo (INTERVALO_MS del firmware)
    hueco_lecturas_faltantes: int = 2       # «hueco» = faltan MÁS de estas lecturas seguidas
    # «Sensor pegado»: el mismo valor exacto por más de estas horas. El DHT11
    # entrega enteros, así que temperatura y humedad del aire repiten más.
    pegado_horas_suelo: float = 3.0
    pegado_horas_temp: float = 6.0
    pegado_horas_hum_aire: float = 6.0
    # Riego detectado: la humedad del suelo sube al menos esto en la ventana
    riego_umbral_pts: float = 10.0
    riego_ventana_min: float = 30.0
    # Etiquetas de la pendiente del suelo (puntos por hora, valores de ejemplo):
    # bajo −RAPIDO «Secándose rápido»; hasta −ESTABLE «Secándose lento»;
    # entre ±ESTABLE «Estable»; sobre +ESTABLE «Subiendo»
    tendencia_pts_rapido: float = 1.0
    tendencia_pts_estable: float = 0.2
    # Predicción del tiempo hasta el mínimo (RF-15). Ventana, R² y alerta
    # (TENDENCIA_ACTIVA) también se editan en /configuracion.
    tendencia_ventana_h: float = 6.0
    tendencia_r2_min: float = 0.6
    tendencia_min_puntos: int = 12
    tendencia_horizonte_h: float = 6.0

    def pegado_horas(self, variable: str) -> float:
        return {"suelo": self.pegado_horas_suelo, "temp": self.pegado_horas_temp,
                "hum_aire": self.pegado_horas_hum_aire}[variable]

    @property
    def lista_sensores_requeridos(self) -> tuple[str, ...]:
        return tuple(s.strip().lower() for s in self.sensores_requeridos.split(",") if s.strip())

    @classmethod
    def desde_entorno(cls, entorno: Optional[Mapping[str, str]] = None) -> "Config":
        entorno = os.environ if entorno is None else entorno
        valores = {}
        for campo in fields(cls):
            texto = entorno.get(_VARIABLES[campo.name])
            if texto is None or texto == "":
                continue
            if campo.type in ("bool", bool):
                valores[campo.name] = _a_bool(texto)
            elif campo.type in ("int", int):
                valores[campo.name] = int(texto)
            elif campo.type in ("float", float):
                valores[campo.name] = float(texto.replace(",", "."))
            else:
                valores[campo.name] = texto
        return cls(**valores)


def cargar_env(ruta: Optional[Path] = None) -> None:
    """Carga central/.env si existe (útil al correr fuera de Docker)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    ruta = ruta or Path(__file__).resolve().parent.parent / ".env"
    if ruta.is_file():
        load_dotenv(ruta, override=False)

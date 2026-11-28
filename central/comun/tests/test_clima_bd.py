"""Clima con la BD de test: ajustes, instantáneas horarias y migraciones reversibles."""

import time
from datetime import datetime, timedelta

import pytest

from comun import ajustes, migrar
from comun.clima import ClimaReferencia, ErrorClima, ProveedorClima
from comun.clima import repositorio as repo_clima
from comun.config import Config
from procesador.clima import TareaClima
from procesador.publicador import PublicadorMemoria
from procesador.servicio import Procesador
from pruebas.bd import CFG, INICIO, Reloj

pytestmark = pytest.mark.bd


def clima(t, temp=20.0):
    return ClimaReferencia(temp, 50, 0, 800, 22, 16.8, 0.4, t, "falso", -33.54, -70.64, 3.1)


class Falso(ProveedorClima):
    nombre = "falso"

    def __init__(self, falla=False, demora_s=0.0, configurado=True):
        self.falla, self.demora_s, self._configurado = falla, demora_s, configurado
        self.llamadas = []

    def motivo_no_configurado(self):
        return None if self._configurado else "Falta la clave"

    def obtener(self, lat, lon, timeout=5):
        self.llamadas.append((lat, lon))
        if self.demora_s:
            time.sleep(self.demora_s)
        if self.falla:
            raise ErrorClima("sin conexión")
        return clima(INICIO)


# ---------------------------------------------------------------- ajustes

def test_ajustes_por_defecto_vienen_del_env(bd):
    v = ajustes.leer(bd, Config(clima_lat=-30.0))
    assert {k: v[k] for k in ("clima_proveedor", "clima_lat", "clima_lon", "dmc_estacion")} == {
        "clima_proveedor": "open-meteo", "clima_lat": -30.0, "clima_lon": -70.64, "dmc_estacion": ""}
    assert v["tendencia_activa"] is False                       # alerta preventiva apagada por defecto


def test_ajustes_guardados_tienen_prioridad(bd):
    assert ajustes.guardar(bd, {"clima_lat": "-36,8", "clima_lon": "-73.05"}) == []
    bd.commit()
    v = ajustes.leer(bd, CFG)
    assert (v["clima_lat"], v["clima_lon"]) == (-36.8, -73.05)


def test_ajustes_invalidos_no_se_guardan(bd):
    errores = ajustes.guardar(bd, {"clima_lat": "-95", "clima_lon": "abc",
                                   "clima_proveedor": "otro"})
    assert errores == ["La latitud debe estar entre -90 y 90.", "Longitud: valor no válido.",
                       "Proveedor de clima desconocido."]
    bd.commit()
    assert ajustes.leer(bd, CFG)["clima_lat"] == CFG.clima_lat


def test_valor_guardado_corrupto_usa_el_del_env(bd):
    with bd.cursor() as cur:
        cur.execute("INSERT INTO configuracion_huerto (clave, valor) VALUES ('clima_lat', 'xx')")
    bd.commit()
    assert ajustes.leer(bd, CFG)["clima_lat"] == CFG.clima_lat


# ------------------------------------------------------ instantánea horaria

def test_guardar_instantanea_es_idempotente(bd):
    repo_clima.guardar_instantanea(bd, clima(INICIO, 20), INICIO)
    repo_clima.guardar_instantanea(bd, clima(INICIO, 21), INICIO + timedelta(minutes=5))
    bd.commit()
    with bd.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, MAX(temp_aire_c) AS t FROM clima_referencia")
        fila = cur.fetchone()
    assert (fila["n"], fila["t"]) == (1, 21)
    assert repo_clima.ultima(bd, "falso", -33.54, -70.64).et0_hoy_mm == 3.1


def test_tarea_guarda_una_vez_por_hora(bd):
    p = Falso()
    tarea = TareaClima(CFG, crear=lambda nombre: p)
    t = INICIO.replace(minute=5)
    assert tarea.ejecutar(bd, t)
    assert not tarea.ejecutar(bd, t + timedelta(minutes=30))
    assert len(p.llamadas) == 1
    assert tarea.ejecutar(bd, t + timedelta(minutes=56))     # hora siguiente
    assert len(p.llamadas) == 2


def test_tarea_usa_las_coordenadas_de_la_configuracion(bd):
    ajustes.guardar(bd, {"clima_lat": "-36.8", "clima_lon": "-73.05"})
    bd.commit()
    p = Falso()
    TareaClima(CFG, crear=lambda nombre: p).ejecutar(bd, INICIO)
    assert p.llamadas == [(-36.8, -73.05)]


def test_tarea_tras_falla_reintenta_cada_10_minutos(bd):
    p = Falso(falla=True)
    tarea = TareaClima(CFG, crear=lambda nombre: p, reintento_min=10)
    assert not tarea.ejecutar(bd, INICIO)
    assert not tarea.ejecutar(bd, INICIO + timedelta(minutes=5))
    assert len(p.llamadas) == 1
    p.falla = False
    assert tarea.ejecutar(bd, INICIO + timedelta(minutes=11))


def test_proveedor_no_configurado_no_se_consulta(bd):
    p = Falso(configurado=False)
    assert not TareaClima(CFG, crear=lambda nombre: p).ejecutar(bd, INICIO)
    assert p.llamadas == []


def test_api_lenta_no_detiene_el_ciclo_del_procesador(bd):
    """Timeout de la API externa: el ciclo de las camas termina igual y rápido."""
    p = Falso(demora_s=3)
    tarea = TareaClima(CFG, crear=lambda nombre: p, espera_max_s=0.3)
    proc = Procesador(bd, CFG, PublicadorMemoria(), Reloj(INICIO), tarea_clima=tarea)
    inicio = time.monotonic()
    proc.tick()
    assert time.monotonic() - inicio < 2
    tarea.cerrar()


def test_procesador_sin_tarea_de_clima_no_consulta(bd):
    Procesador(bd, CFG, PublicadorMemoria(), Reloj(INICIO)).tick()   # no debe fallar


# ------------------------------------------------------- migraciones

@pytest.mark.parametrize("nombre,tabla", [("003_clima_referencia.sql", "clima_referencia"),
                                          ("002_configuracion_huerto.sql", "configuracion_huerto")])
def test_migracion_se_revierte_y_se_vuelve_a_aplicar(bd, nombre, tabla):
    def existe():
        with bd.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name = %s", (tabla,))
            return cur.fetchone()["n"] == 1

    with bd.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM lecturas")
        lecturas_antes = cur.fetchone()["n"]
    migrar.revertir(bd, nombre)
    assert not existe()
    assert nombre in [a.name for a in migrar.pendientes(bd)]
    assert nombre in migrar.migrar(bd)
    assert existe()
    with bd.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM lecturas")
        assert cur.fetchone()["n"] == lecturas_antes


def test_los_archivos_down_no_son_migraciones_pendientes(bd):
    assert all(not a.name.endswith(".down.sql") for a in migrar.pendientes(bd))


def test_no_se_revierte_una_migracion_sin_down(bd):
    with pytest.raises(ValueError, match="reversión"):
        migrar.revertir(bd, "001_api_nodos.sql")

"""Tendencias descriptivas (funciones puras)."""

import random
from datetime import datetime, timedelta

import pytest

from comun.analitica.tendencia import (ESTABLE, SECANDOSE_LENTO, SECANDOSE_RAPIDO, SIN_DATOS,
                                       SUBIENDO, ComparacionAmplitud, etiqueta_suelo, media_movil,
                                       pendiente_ventana, regresion_lineal, serie_media_movil)

AHORA = datetime(2026, 11, 27, 18, 0)


def linea(pendiente_h, horas=6, paso_min=1, base=50.0, ruido=0.0, semilla=1):
    rnd = random.Random(semilla)
    n = int(horas * 60 / paso_min)
    return [(AHORA - timedelta(minutes=(n - 1 - i) * paso_min),
             base + pendiente_h * (i * paso_min / 60) + rnd.uniform(-ruido, ruido)) for i in range(n)]


# --------------------------------------------------------------- regresión

def test_pendiente_correcta_sobre_datos_conocidos():
    a = regresion_lineal(linea(-0.8))
    assert a.pendiente == pytest.approx(-0.8, abs=1e-9)
    assert a.r2 == pytest.approx(1.0)
    assert a.n == 360


def test_pendiente_con_ruido_y_r2_menor():
    a = regresion_lineal(linea(-1.5, ruido=1.0))
    assert a.pendiente == pytest.approx(-1.5, abs=0.1)
    assert 0.5 < a.r2 < 1.0


def test_valor_en_un_instante():
    puntos = [(AHORA, 40.0), (AHORA + timedelta(hours=2), 36.0)]
    a = regresion_lineal(puntos, t0=AHORA)
    assert a.pendiente == pytest.approx(-2.0) and a.valor_en(AHORA + timedelta(hours=5)) == pytest.approx(30.0)


def test_casos_sin_regresion():
    assert regresion_lineal([(AHORA, 1.0)]) is None
    assert regresion_lineal([(AHORA, 1.0), (AHORA, 2.0)]) is None       # misma hora
    plana = regresion_lineal([(AHORA, 5.0), (AHORA + timedelta(hours=1), 5.0)])
    assert plana.pendiente == 0 and plana.r2 is None


# ---------------------------------------------------------------- etiquetas

@pytest.mark.parametrize("pendiente,etiqueta", [
    (-2.0, SECANDOSE_RAPIDO), (-1.0, SECANDOSE_LENTO), (-0.5, SECANDOSE_LENTO),
    (-0.2, ESTABLE), (0.0, ESTABLE), (0.2, ESTABLE), (0.21, SUBIENDO), (5.0, SUBIENDO), (None, SIN_DATOS)])
def test_etiquetas(pendiente, etiqueta):
    assert etiqueta_suelo(pendiente) == etiqueta


def test_umbrales_de_etiqueta_configurables():
    assert etiqueta_suelo(-0.5, rapido=0.4, estable=0.1) == SECANDOSE_RAPIDO


def test_pendiente_de_las_ultimas_6_horas_con_texto():
    p = pendiente_ventana(linea(-1.5, horas=24), AHORA, 6)
    assert p.etiqueta == SECANDOSE_RAPIDO
    assert p.ajuste.n == 361                                           # solo las de la ventana
    assert p.texto == "Secándose rápido (−1,5 puntos por hora en las últimas 6 h)"


def test_sin_datos_suficientes():
    assert pendiente_ventana(linea(-1, horas=0.05), AHORA, 6).etiqueta == SIN_DATOS     # 3 puntos
    # 60 puntos, pero todos en la última media hora de una ventana de 6 h
    p = pendiente_ventana(linea(-1, horas=0.5, paso_min=0.5), AHORA, 6)
    assert p.etiqueta == SIN_DATOS and "Sin datos suficientes" in p.texto


# --------------------------------------------------------------- media móvil

def test_media_movil_ponderada_por_lecturas():
    horas = [(AHORA - timedelta(hours=2), 20.0, 100), (AHORA - timedelta(hours=1), 30.0, 300),
             (AHORA - timedelta(hours=30), 99.0, 100)]                 # fuera de la ventana
    assert media_movil(horas, AHORA) == 27.5
    assert media_movil([], AHORA) is None


def test_serie_de_media_movil():
    horas = [(AHORA - timedelta(hours=h), float(h), 120) for h in range(1, 49)]
    serie = serie_media_movil(horas, AHORA - timedelta(hours=3), AHORA)
    assert [t for t, _ in serie] == [AHORA - timedelta(hours=2), AHORA - timedelta(hours=1), AHORA]
    assert serie[-1][1] == pytest.approx(12.5)                         # media de 1..24


# ---------------------------------------------------------- amplitud térmica

def test_amplitud_cama_vs_exterior():
    c = ComparacionAmplitud(8, 26, 10, 22)
    assert (c.cama, c.exterior, c.diferencia) == (18, 12, 6)
    assert c.texto("ayer") == ("Ayer la temperatura de la cama varió 18 °C (de 8 a 26 °C); "
                               "afuera, 12 °C: 6 °C más que la zona.")
    assert "parecido a la zona" in ComparacionAmplitud(10, 22, 10, 23).texto()
    assert ComparacionAmplitud(8, 26, None, None).texto("hoy").endswith("26 °C).")

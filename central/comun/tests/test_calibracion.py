"""Calibración de la sonda de suelo en el servidor (comun/calibracion.py)."""

import pytest

from comun.calibracion import Calibracion, de_cama, porcentaje, validar

CAMA_A = Calibracion(seco_mv=3160, mojado_mv=980)


@pytest.mark.parametrize("mv, esperado", [
    (3160, 0.0), (980, 100.0),
    (1700, 67.0),      # (3160-1700)*100/2180 = 66,97
    (1437, 79.0),      # lectura de la Cama A el 28-11 a las 10:48
    (3300, 0.0),       # más seco que «seco»: tope 0 %
    (900, 100.0),      # más mojado que «mojado»: tope 100 %
])
def test_porcentaje(mv, esperado):
    assert porcentaje(mv, CAMA_A) == esperado


def test_porcentaje_redondea_a_un_decimal_hacia_arriba():
    assert porcentaje(2070, Calibracion(3160, 980)) == 50.0      # 50,0
    assert porcentaje(2069, Calibracion(3160, 980)) == 50.0      # 50,046 -> 50,0
    assert porcentaje(1, Calibracion(201, 1)) == 100.0
    assert porcentaje(150, Calibracion(201, 1)) == 25.5          # 25,5


def test_de_cama():
    assert de_cama({"cal_seco_mv": 3160, "cal_mojado_mv": 980}) == CAMA_A
    assert de_cama({"cal_seco_mv": 3160, "cal_mojado_mv": None}) is None
    assert de_cama({"cal_seco_mv": None, "cal_mojado_mv": None}) is None
    assert de_cama({"cal_seco_mv": 900, "cal_mojado_mv": 980}) is None   # al revés: no se usa
    assert de_cama({}) is None and de_cama(None) is None


def test_validar_dos_valores():
    assert validar("3160", " 980 ") == (CAMA_A, [])


def test_validar_ambos_vacios_es_sin_calibracion():
    assert validar("", "") == (None, [])


@pytest.mark.parametrize("seco, mojado, texto", [
    ("3160", "", "los dos valores"),
    ("", "980", "los dos valores"),
    ("tres mil", "980", "número entero"),
    ("3160", "-5", "número entero"),
    ("5000", "980", "entre 0 y 3600"),
    ("980", "3160", "más agua = menos mV"),
    ("1000", "950", "al menos 100 mV"),
])
def test_validar_errores(seco, mojado, texto):
    cal, errores = validar(seco, mojado)
    assert cal is None and len(errores) == 1 and texto in errores[0]

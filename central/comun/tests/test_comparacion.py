"""Comparación sensor vs. clima de la zona (funciones puras)."""

from datetime import datetime, timedelta

from comun.clima import ClimaReferencia
from comun.clima.comparacion import (comparar, diferencia_humedad_aire, diferencia_temperatura,
                                     referencia_mas_cercana, sugerencias, texto_et0,
                                     texto_suelo_zona)

T = datetime(2026, 11, 27, 18, 0)


def ref(t=T, temp=25.0, hum=40.0, rad=800.0, vwc=16.8, et0=0.5, et0_hoy=4.2, lluvia=0.0):
    return ClimaReferencia(temp, hum, lluvia, rad, 30.0, vwc, et0, t, "open-meteo", -33.54, -70.64,
                           et0_hoy)


# ------------------------------------------------------------- temperatura

def test_delta_temperatura_positivo():
    d = diferencia_temperatura(28.4, 25.0)
    assert (d.delta, d.similar, d.texto) == (3.4, False, "+3 °C más que afuera")


def test_delta_temperatura_negativo():
    d = diferencia_temperatura(20.0, 25.0)
    assert d.texto == "5 °C menos que afuera"


def test_temperatura_bajo_2_grados_es_similar():
    assert diferencia_temperatura(26.9, 25.0).texto == "similar al exterior"
    assert diferencia_temperatura(23.1, 25.0).similar
    # justo 2 °C ya no es similar (fuera del error del DHT11)
    assert not diferencia_temperatura(27.0, 25.0).similar


def test_sin_dato_no_hay_delta():
    assert diferencia_temperatura(None, 25.0) is None
    assert diferencia_temperatura(25.0, None) is None


# ---------------------------------------------------------------- humedad

def test_humedad_bajo_5_puntos_es_similar():
    assert diferencia_humedad_aire(44.9, 40.0).texto == "similar al exterior"
    assert not diferencia_humedad_aire(45.0, 40.0).similar
    assert diferencia_humedad_aire(52.0, 40.0).texto == "+12 puntos más húmedo que afuera"
    assert diferencia_humedad_aire(30.0, 40.0).texto == "10 puntos más seco que afuera"


# ------------------------------------------------------------------ suelo

def test_suelo_solo_como_referencia_sin_delta():
    assert texto_suelo_zona(ref(vwc=16.8)) == "Suelo de la zona (modelo): 17 % vol."
    c = comparar({"medido_en": T, "temp": 25.0, "hum_aire": 40.0, "suelo_prom": 55.0}, [ref()])
    assert "suelo" not in c and c["suelo_zona_vwc_pct"] == 16.8
    # Ninguna clave de la comparación tiene un delta de suelo
    assert not any("delta" in str(k) for k in c if "suelo" in k)


def test_et0_informativa():
    assert texto_et0(ref(et0_hoy=4.25)) == "La zona perdió 4,2 mm de agua hoy por evaporación"
    assert texto_et0(ref(et0_hoy=None, et0=0.3)).startswith("La zona pierde 0,3 mm")
    assert texto_et0(ref(et0_hoy=None, et0=None)) is None


# -------------------------------------------------------------- misma hora

def test_elige_la_instantanea_mas_cercana_a_la_medicion():
    a, b, c = ref(t=T - timedelta(minutes=50)), ref(t=T + timedelta(minutes=10)), ref(t=T + timedelta(minutes=40))
    assert referencia_mas_cercana(T, [a, b, c]) is b


def test_sin_instantanea_dentro_de_60_minutos_no_hay_delta():
    lejos = ref(t=T - timedelta(minutes=61))
    assert referencia_mas_cercana(T, [lejos]) is None
    assert comparar({"medido_en": T, "temp": 30.0, "hum_aire": 40.0}, [lejos]) is None
    assert referencia_mas_cercana(T, [ref(t=T - timedelta(minutes=60))]) is not None


# ------------------------------------------------------------ sugerencias

def test_sugiere_revisar_sombra_con_calor_y_sol_fuerte():
    textos = sugerencias(diferencia_temperatura(31.0, 25.0), ref(rad=800))
    assert textos == ["Posible acumulación de calor: revisa sombra y ventilación."]


def test_sin_sol_fuerte_no_sugiere_sombra():
    assert sugerencias(diferencia_temperatura(31.0, 25.0), ref(rad=200)) == []
    assert sugerencias(diferencia_temperatura(29.0, 25.0), ref(rad=900)) == []


def test_lluvia_en_la_zona():
    assert any("lloviendo" in s for s in sugerencias(None, ref(lluvia=1.2)))


def test_comparar_completo():
    c = comparar({"medido_en": T, "temp": 28.4, "hum_aire": 41.0}, [ref()])
    assert c["temperatura"]["texto"] == "+3 °C más que afuera"
    assert c["humedad_aire"]["texto"] == "similar al exterior"
    assert c["fuente"] == "open-meteo" and c["referencia_observada_en"] == T

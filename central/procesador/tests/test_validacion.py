"""RF-05: validación y limpieza de lecturas (lógica pura)."""

import json
from datetime import datetime, timedelta

import pytest

from comun.config import Config
from procesador.validacion import (MensajeInvalido, ValoresAnteriores, interpretar, validar,
                                   valores_anteriores_desde_fila)

CFG = Config()
T0 = datetime(2026, 11, 26, 12, 0, 0)


def mensaje(**cambios) -> bytes:
    datos = {"nodo_id": "cama-a", "medido_en": "2026-11-26T12:00:00Z", "seq": 1234,
             "suelo": [28.1, 30.4], "suelo_prom": 29.3, "temp": 21.4, "hum_aire": 58.2,
             "lux": 18350}
    datos.update(cambios)
    return json.dumps(datos).encode()


def validada(anterior=None, **cambios):
    return validar(interpretar("cama-a", mensaje(**cambios)), anterior, T0, CFG)


def test_mensaje_de_la_especificacion_es_valido():
    lv = validada()
    assert lv.valida and not lv.invalidos
    assert lv.medido_en == T0
    assert lv.suelo_prom == 29.3          # promedio recalculado de las sondas: (28.1+30.4)/2
    assert (lv.temp, lv.hum_aire, lv.lux) == (21.4, 58.2, 18350)


@pytest.mark.parametrize("payload, motivo", [
    (b"no es json", "JSON"),
    (b"[1, 2]", "objeto"),
    (json.dumps({"medido_en": "2026-11-26T12:00:00Z"}).encode(), "seq"),
    (json.dumps({"seq": 1}).encode(), "medido_en"),
    (json.dumps({"seq": 1, "medido_en": "ayer"}).encode(), "ISO"),
    (json.dumps({"seq": 1, "medido_en": "2026-11-26T12:00:00"}).encode(), "zona"),
    (json.dumps({"seq": -1, "medido_en": "2026-11-26T12:00:00Z"}).encode(), "seq"),
])
def test_mensajes_que_no_se_pueden_guardar(payload, motivo):
    with pytest.raises(MensajeInvalido, match=motivo):
        interpretar("cama-a", payload)


@pytest.mark.parametrize("campo, valor", [
    ("temp", 150), ("temp", -41), ("hum_aire", 101), ("lux", 120001), ("lux", -1),
    ("temp", "hola"),
])
def test_fuera_de_rango_fisico_se_descarta_solo_ese_campo(campo, valor):
    lv = validada(**{campo: valor})
    assert getattr(lv, campo) is None
    assert lv.invalidos[campo]["valor"] == valor
    assert lv.valida                     # los otros sensores siguen sirviendo
    assert lv.suelo_prom is not None


def test_sonda_de_suelo_mala_no_arrastra_a_las_otras():
    lv = validada(suelo=[-5, 30.0, 40.0])
    assert lv.suelo_prom == 35.0
    assert "suelo_sonda_1" in lv.invalidos
    assert lv.suelo_detalle == [-5, 30.0, 40.0]     # se guarda todo lo crudo


def test_sensor_caido_null_no_es_invalido():
    lv = validada(temp=None, hum_aire=None)
    assert lv.valida and lv.temp is None and not lv.invalidos


def test_sin_ningun_dato_la_lectura_es_invalida():
    lv = validada(suelo=None, suelo_prom=None, temp=None, hum_aire=None, lux=None)
    assert not lv.valida
    assert lv.motivo == "sin datos válidos"


def test_hora_en_el_futuro_invalida_la_lectura():
    lv = validar(interpretar("cama-a", mensaje(medido_en="2026-11-26T12:10:00Z")), None, T0, CFG)
    assert not lv.valida
    assert "futuro" in lv.motivo


def anterior(**valores):
    return ValoresAnteriores(medido_en=T0 - timedelta(minutes=1), **valores)


def test_bajada_brusca_del_suelo_es_salto_imposible():
    lv = validada(anterior(suelo_prom=60.0), suelo=[29.0])
    assert lv.suelo_prom is None
    assert lv.invalidos["suelo"]["tipo"] == "salto"


def test_subida_brusca_del_suelo_es_un_riego_y_se_acepta():
    lv = validada(anterior(suelo_prom=20.0), suelo=[60.0])
    assert lv.suelo_prom == 60.0


def test_bajada_normal_del_suelo_se_acepta():
    lv = validada(anterior(suelo_prom=35.0), suelo=[30.0])     # 5 puntos/min < 10
    assert lv.suelo_prom == 30.0


def test_salto_de_temperatura_en_ambos_sentidos():
    assert validada(anterior(temp=10.0), temp=21.4).temp is None
    assert validada(anterior(temp=30.0), temp=21.4).temp is None
    assert validada(anterior(temp=20.0), temp=21.4).temp == 21.4


def test_salto_de_humedad_del_aire():
    assert validada(anterior(hum_aire=20.0), hum_aire=58.2).hum_aire is None


def test_saltos_no_se_comparan_contra_lecturas_muy_viejas():
    viejo = ValoresAnteriores(medido_en=T0 - timedelta(hours=2), suelo_prom=90.0, temp=5.0)
    lv = validada(viejo)
    assert lv.suelo_prom is not None and lv.temp is not None


def test_valor_descartado_por_salto_se_usa_en_la_comparacion_siguiente():
    """Un cambio real solo invalida una lectura: la cama no queda pegada."""
    fila = {"medido_en": T0, "suelo_prom": None, "temp": None, "hum_aire": 60.0,
            "campos_invalidos": json.dumps({
                "temp": {"valor": 35.0, "tipo": "salto", "detalle": "x"},
                "suelo": {"valor": -5, "tipo": "rango", "detalle": "x"}})}
    ant = valores_anteriores_desde_fila(fila)
    assert ant.temp == 35.0           # salto: se usa
    assert ant.suelo_prom is None     # rango físico: no es una medición real


# ---------------------------------------------------------------------------
# Prototipo 1: JSON del ESP32 con una sonda (suelo_pct + suelo_mv) y DHT11
# ---------------------------------------------------------------------------

def mensaje_esp32(**cambios) -> bytes:
    datos = {"nodo_id": "cama-a", "seq": 15, "medido_en": "2026-11-26T12:00:00Z",
             "temp": 23, "hum_aire": 61, "suelo_pct": 42, "suelo_mv": 2350}
    datos.update(cambios)
    return json.dumps(datos).encode()


def validada_esp32(**cambios):
    return validar(interpretar("cama-a", mensaje_esp32(**cambios)), None, T0, CFG)


def test_json_del_esp32_es_valido():
    lv = validada_esp32()
    assert lv.valida and not lv.invalidos
    assert lv.suelo_prom == 42.0 and lv.suelo_detalle == [42]
    assert lv.suelo_mv == 2350
    assert lv.temp == 23.0 and lv.hum_aire == 61.0 and lv.lux is None


def test_luz_null_del_prototipo_1_no_invalida_nada():
    lv = validada_esp32(luz=None)
    assert lv.valida and lv.lux is None


@pytest.mark.parametrize("temp", [-1, 51, 85])
def test_dht11_temperatura_fuera_de_0_a_50_se_descarta(temp):
    lv = validada_esp32(temp=temp)
    assert lv.valida and lv.temp is None
    assert lv.invalidos["temp"]["tipo"] == "rango"


@pytest.mark.parametrize("temp", [0, 50])
def test_dht11_limites_0_y_50_son_validos(temp):
    assert validada_esp32(temp=temp).temp == float(temp)


def test_rango_fisico_configurable_para_otro_sensor():
    cfg = Config(temp_min_fisico=-40, temp_max_fisico=80)
    lv = validar(interpretar("cama-a", mensaje_esp32(temp=-5)), None, T0, cfg)
    assert lv.temp == -5.0


@pytest.mark.parametrize("mv", [-1, 9000, "alto"])
def test_suelo_mv_imposible_se_descarta_sin_afectar_el_porcentaje(mv):
    lv = validada_esp32(suelo_mv=mv)
    assert lv.suelo_mv is None and "suelo_mv" in lv.invalidos
    assert lv.suelo_prom == 42.0 and lv.valida


def test_solo_mv_sin_porcentaje_no_es_lectura_util():
    """Sonda sin calibrar y DHT11 caído: no hay nada que mostrar."""
    lv = validada_esp32(suelo_pct=None, temp=None, hum_aire=None)
    assert not lv.valida
    assert lv.suelo_mv == 2350      # pero los mV quedan guardados para calibrar

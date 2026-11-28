"""Marcas de calidad y agregados (funciones puras)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from comun.analitica.agregados import (agregar_dia, agregar_horas, estadisticas,
                                       limites_dia_local)
from comun.analitica.calidad import (HUECO, PEGADO, RANGO, SALTO, LecturaCruda, calcular_marcas,
                                     marcas_de_validacion, marcas_hueco, marcas_pegado)
from comun.config import Config
from comun.rangos import Rango

T0 = datetime(2026, 11, 27, 12, 0)
CFG = Config()                        # intervalo 30 s, hueco > 2 faltantes, pegado suelo 3 h
ZONA = ZoneInfo("America/Santiago")


def serie(n, paso_s=30, suelo=lambda i: 50.0 - i * 0.01, temp=lambda i: 20.0 + (i % 7),
          hum=lambda i: 50.0 + (i % 5), inicio=T0, id0=1):
    return [LecturaCruda(id0 + i, inicio + timedelta(seconds=i * paso_s), suelo(i), temp(i), hum(i))
            for i in range(n)]


def tipos(marcas):
    return {(m.lectura_id, m.variable, m.marca) for m in marcas}


# ------------------------------------------------------------ rango y salto

def test_rango_y_salto_vienen_de_la_validacion():
    l = LecturaCruda(7, T0, None, None, 40.0, {
        "suelo_sonda_1": {"valor": 150, "tipo": "rango", "detalle": "suelo_sonda_1 fuera de rango físico (150)"},
        "suelo_sonda_2": {"valor": -3, "tipo": "rango", "detalle": "x"},
        "temp": {"valor": 31, "tipo": "salto", "detalle": "temp cambió 11 °C en 1 min"},
        "hum_aire": {"valor": "abc", "tipo": "tipo_dato", "detalle": "no es un número"},
        "suelo_mv": {"valor": 9000, "tipo": "rango", "detalle": "mV"},
    })
    assert tipos(marcas_de_validacion(l)) == {(7, "suelo", RANGO), (7, "temp", SALTO),
                                              (7, "hum_aire", RANGO)}


# ------------------------------------------------------------- sensor pegado

def test_suelo_con_el_mismo_valor_mas_de_3_horas_queda_pegado():
    lecturas = serie(int(3.5 * 120), suelo=lambda i: 42.0)
    marcas = marcas_pegado(lecturas, "suelo", 3)
    assert len(marcas) == len(lecturas) and all(m.marca == PEGADO for m in marcas)
    assert "42" in marcas[0].detalle


def test_menos_de_3_horas_no_es_pegado():
    assert marcas_pegado(serie(int(2.5 * 120), suelo=lambda i: 42.0), "suelo", 3) == []


def test_un_cambio_de_valor_corta_la_racha():
    lecturas = serie(4 * 120, suelo=lambda i: 42.0 if i != 240 else 42.1)   # cambia a las 2 h
    assert marcas_pegado(lecturas, "suelo", 3) == []


def test_lecturas_sin_valor_no_cortan_la_racha_pero_un_hueco_largo_si():
    con_nulos = serie(int(3.5 * 120), suelo=lambda i: None if i % 10 == 0 else 42.0)
    assert marcas_pegado(con_nulos, "suelo", 3)
    # 2 h de datos, 2 h sin nada, 2 h de datos: no se observó lo de entremedio
    antes = serie(240, suelo=lambda i: 42.0)
    despues = serie(240, suelo=lambda i: 42.0, inicio=T0 + timedelta(hours=4), id0=1000)
    assert marcas_pegado(antes + despues, "suelo", 3) == []


# ---------------------------------------------------------------------- hueco

def test_hueco_cuando_faltan_mas_de_2_lecturas():
    def con_salto(segundos):
        return [LecturaCruda(1, T0, 50, 20, 50), LecturaCruda(2, T0 + timedelta(seconds=segundos), 50, 20, 50)]
    assert marcas_hueco(con_salto(30), 30, 2) == []          # normal
    assert marcas_hueco(con_salto(90), 30, 2) == []          # faltan 2: todavía no
    m = marcas_hueco(con_salto(120), 30, 2)                   # faltan 3: hueco
    assert tipos(m) == {(2, "lectura", HUECO)} and "3 lecturas" in m[0].detalle
    assert "2.0 h" in marcas_hueco(con_salto(7200), 30, 2)[0].detalle


def test_calcular_marcas_combina_todo_y_ordena_por_hora():
    lecturas = list(reversed(serie(10))) + [LecturaCruda(99, T0 + timedelta(minutes=30), 49, 21, 51)]
    assert tipos(calcular_marcas(lecturas, CFG)) == {(99, "lectura", HUECO)}


# ------------------------------------------------------------------ agregados

def test_estadisticas():
    e = estadisticas([20.0, 22.0, 24.0])
    assert (e.media, e.minimo, e.maximo, e.desviacion, e.n) == (22.0, 20.0, 24.0, 2.0, 3)
    assert estadisticas([5.0]).desviacion is None
    assert estadisticas([]).media is None


def test_agregado_por_hora_con_cobertura_y_excluidas():
    lecturas = serie(60)                                       # media hora de datos
    # un valor de temperatura descartado en la validación (ya viene en NULL)
    lecturas[5] = LecturaCruda(6, lecturas[5].medido_en, 50.0, None, 50.0,
                               {"temp": {"tipo": "rango", "valor": 80, "detalle": "x"}})
    marcas = calcular_marcas(lecturas, CFG)
    filas = {a.variable: a for a in agregar_horas(1, lecturas, marcas, 30, T0 + timedelta(hours=2))}
    assert set(filas) == {"suelo", "temp", "hum_aire"}
    assert (filas["suelo"].estadisticas.n, filas["suelo"].n_esperadas, filas["suelo"].cobertura) == (60, 120, 0.5)
    assert (filas["temp"].estadisticas.n, filas["temp"].n_excluidas) == (59, 1)


def test_hora_en_curso_cuenta_las_esperadas_solo_hasta_ahora():
    lecturas = serie(20)                                       # 10 minutos, hasta ahora
    filas = agregar_horas(1, lecturas, [], 30, T0 + timedelta(minutes=10))
    assert filas[0].n_esperadas == 20 and filas[0].cobertura == 1.0


def test_pegado_se_excluye_de_los_agregados():
    lecturas = serie(int(3.5 * 120), suelo=lambda i: 42.0)
    marcas = calcular_marcas(lecturas, CFG)
    suelo = [a for a in agregar_horas(1, lecturas, marcas, 30, T0 + timedelta(hours=4))
             if a.variable == "suelo"]
    assert all(a.estadisticas.n == 0 and a.n_excluidas > 0 for a in suelo)


def test_dia_con_amplitud_y_horas_fuera_de_rango():
    fecha = date(2026, 11, 27)
    inicio, fin = limites_dia_local(fecha, ZONA)
    assert (inicio, fin) == (datetime(2026, 11, 27, 3, 0), datetime(2026, 11, 28, 3, 0))  # UTC-3
    # 1 h de datos: los primeros 30 min a 10 °C (bajo 15) y los otros 30 a 20 °C
    lecturas = serie(120, inicio=inicio + timedelta(hours=8),
                     temp=lambda i: 10.0 if i < 60 else 20.0, suelo=lambda i: 25.0 + i * 0.01)
    filas = {a.variable: a for a in agregar_dia(1, fecha, lecturas, [], 30, fin, ZONA,
                                                Rango(30, 70, 15, 30))}
    assert filas["temp"].amplitud == 10.0
    assert filas["temp"].horas_fuera_rango == 0.5
    assert filas["suelo"].horas_fuera_rango == 1.0            # todo bajo 30 %
    assert filas["hum_aire"].horas_fuera_rango is None         # sin rango ideal
    assert filas["temp"].n_esperadas == 2880 and filas["temp"].cobertura == round(120 / 2880, 4)


def test_dia_sin_lecturas_no_genera_filas():
    assert agregar_dia(1, date(2026, 11, 27), [], [], 30, T0, ZONA, None) == []

"""Detección de riegos y separación en tramos de secado (funciones puras)."""

from datetime import datetime, timedelta

from comun.analitica.calidad import PEGADO, LecturaCruda, Marca
from comun.analitica.riego import (MANUAL, EventoRiego, Punto, detectar_riegos, puntos_suelo,
                                   tramo_actual, tramos)

T0 = datetime(2026, 11, 27, 12, 0)


def serie(valores, paso_min=1.0, inicio=T0):
    """Un punto por minuto (por defecto) con los valores dados."""
    return [Punto(i + 1, inicio + timedelta(minutes=i * paso_min), v) for i, v in enumerate(valores)]


def secado(desde, n, tasa=0.05):
    return [round(desde - i * tasa, 2) for i in range(n)]


def test_subida_de_10_puntos_en_30_min_es_un_riego():
    valores = secado(40, 60) + [42, 46, 50, 53, 54, 54.5, 54.4] + secado(54.3, 60)
    eventos = detectar_riegos(serie(valores), 10, 30)
    assert len(eventos) == 1
    e = eventos[0]
    assert e.humedad_antes == valores[59] and e.humedad_despues == 54.5     # sube hasta el pico
    assert e.inicio == T0 + timedelta(minutes=59) and e.fin == T0 + timedelta(minutes=65)
    assert e.subida == round(54.5 - valores[59], 1)


def test_subida_lenta_no_es_riego():
    # +12 puntos repartidos en 2 horas (lluvia suave o deriva): nunca +10 en 30 min
    valores = [30 + i * 0.1 for i in range(120)]
    assert detectar_riegos(serie(valores), 10, 30) == []


def test_subida_de_9_puntos_no_alcanza_el_umbral():
    assert detectar_riegos(serie(secado(40, 30) + [45, 48.5]), 10, 30) == []


def test_umbral_y_ventana_configurables():
    valores = secado(40, 30) + [45, 48.5]
    assert len(detectar_riegos(serie(valores), 8, 30)) == 1
    lenta = [30 + i * 0.25 for i in range(60)]                 # +10 en 40 min
    assert detectar_riegos(serie(lenta), 10, 30) == []
    assert len(detectar_riegos(serie(lenta), 10, 45)) == 1


def test_dos_riegos_separados():
    valores = secado(40, 120) + [52, 55] + secado(55, 300, 0.06) + [48, 60] + secado(60, 60)
    eventos = detectar_riegos(serie(valores), 10, 30)
    assert len(eventos) == 2
    assert eventos[0].fin < eventos[1].inicio


def test_ruido_no_genera_riegos():
    import random
    rnd = random.Random(7)
    valores = [45 + rnd.uniform(-2, 2) for _ in range(600)]
    assert detectar_riegos(serie(valores), 10, 30) == []


def test_lecturas_marcadas_no_cuentan():
    lecturas = [LecturaCruda(i + 1, T0 + timedelta(minutes=i), 40.0 if i != 5 else 90.0, 20, 50)
                for i in range(10)]
    marcas = [Marca(6, lecturas[5].medido_en, "suelo", PEGADO, "")]
    assert detectar_riegos(puntos_suelo(lecturas, marcas), 10, 30) == []
    assert len(detectar_riegos(puntos_suelo(lecturas), 10, 30)) == 1


# --------------------------------------------------------------------- tramos

def ev(minuto, duracion=5, origen="detectado"):
    return EventoRiego(T0 + timedelta(minutes=minuto), T0 + timedelta(minutes=minuto + duracion),
                       30, 50, origen)


def test_cada_riego_parte_un_tramo_de_secado():
    partes = tramos([ev(100), ev(400)], T0)
    assert [(p.inicio, p.fin) for p in partes] == [
        (T0, T0 + timedelta(minutes=100)),                                   # antes del primer riego
        (T0 + timedelta(minutes=105), T0 + timedelta(minutes=400)),
        (T0 + timedelta(minutes=405), None)]                                # en curso
    assert partes[0].evento is None and partes[2].evento.inicio == T0 + timedelta(minutes=400)
    assert partes[1].contiene(T0 + timedelta(minutes=200))
    assert not partes[1].contiene(T0 + timedelta(minutes=402))


def test_tramo_actual_empieza_en_el_ultimo_riego():
    t = tramo_actual([ev(100), ev(400)], T0)
    assert t.inicio == T0 + timedelta(minutes=405) and t.fin is None


def test_sin_riegos_un_solo_tramo():
    assert tramos([], T0) == [tramos([], T0)[0]] and tramo_actual([], T0).inicio == T0


def test_riego_manual_y_detectado_cercanos_cuentan_una_vez():
    partes = tramos([ev(100), ev(110, origen=MANUAL)], T0)
    assert len(partes) == 2


def test_riegos_anteriores_al_inicio_fijan_el_comienzo():
    t = tramo_actual([ev(-300), ev(-50)], T0)
    assert t.inicio == T0 and t.evento.inicio == T0 - timedelta(minutes=50)

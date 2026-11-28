"""Predicción del tiempo hasta el mínimo, alerta preventiva y backtesting."""

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from comun.analitica.evaluacion import (MIN_CASOS, Resultado, evaluar_cama, tasa_ingenua,
                                        tramos_cerrados)
from comun.analitica.prediccion import (BAJO_MINIMO, ESTIMACION, FUERA_HORIZONTE, SIN_RANGO,
                                        SIN_TENDENCIA, ParametrosPrediccion, duracion, predecir)
from comun.analitica.riego import EventoRiego, Punto, detectar_riegos
from procesador.reglas import ABRIR, ACTUALIZAR, RESOLVER
from procesador.tendencia import decidir

AHORA = datetime(2026, 11, 27, 18, 0)
P = ParametrosPrediccion()


def secado(valor_ahora, tasa_h, horas=6, paso_min=1, ruido=0.0, semilla=3, hasta=AHORA, id0=1):
    """Serie que termina en `hasta` con `valor_ahora` y baja `tasa_h` puntos por hora."""
    rnd = random.Random(semilla)
    n = int(horas * 60 / paso_min)
    return [Punto(id0 + i, hasta - timedelta(minutes=(n - 1 - i) * paso_min),
                  valor_ahora + tasa_h * (n - 1 - i) * paso_min / 60 + rnd.uniform(-ruido, ruido))
            for i in range(n)]


# ---------------------------------------------------------------- predicción

def test_estimacion_con_pendiente_correcta_y_texto():
    pred = predecir(secado(34, 1.0), AHORA, 30)
    assert pred.estado == ESTIMACION
    assert pred.ajuste.pendiente == pytest.approx(-1.0)
    assert pred.horas == pytest.approx(4.0, abs=0.01)
    assert pred.texto("Cama A") == "Al ritmo actual, la Cama A llegaría a 30 % en unas 4 h (estimación)"


def test_mas_alla_del_horizonte_de_6_horas():
    pred = predecir(secado(40, 1.0), AHORA, 30)
    assert pred.estado == FUERA_HORIZONTE and pred.horas is None
    assert "no llegaría a 30 % en las próximas 6 h" in pred.texto("Cama A")


def test_ya_bajo_el_minimo():
    assert predecir(secado(28, 1.0), AHORA, 30).estado == BAJO_MINIMO


def test_sin_tendencia_clara_con_pocos_puntos():
    pocos = secado(34, 1.0, horas=10 / 60)                      # 10 puntos (< 12)
    pred = predecir(pocos, AHORA, 30)
    assert pred.estado == SIN_TENDENCIA and pred.texto("Cama A") == "Sin tendencia clara"
    assert "pocos puntos" in pred.motivo
    assert predecir(pocos, AHORA, 30, ParametrosPrediccion(min_puntos=5)).estado == ESTIMACION


def test_sin_tendencia_clara_con_mal_ajuste():
    ruidosa = secado(34, 0.3, ruido=3.0)                        # R² muy bajo
    pred = predecir(ruidosa, AHORA, 30)
    assert pred.estado == SIN_TENDENCIA and "R²" in pred.motivo
    assert predecir(ruidosa, AHORA, 30, ParametrosPrediccion(r2_min=0.0)).estado != SIN_TENDENCIA


def test_sin_tendencia_si_no_se_esta_secando():
    assert predecir(secado(40, -0.5), AHORA, 30).motivo == "no se está secando"


def test_sin_minimo_de_humedad():
    assert predecir(secado(34, 1.0), AHORA, None).estado == SIN_RANGO


def test_la_ventana_se_reinicia_tras_un_riego():
    # Hasta hace 2 h se secaba rápido (3 pts/h); riego de +20; desde entonces, lento (0,5 pts/h)
    riego_fin = AHORA - timedelta(hours=2)
    antes = secado(25, 3.0, horas=4, hasta=riego_fin - timedelta(minutes=2))
    despues = secado(44, 0.5, horas=2, hasta=AHORA, id0=10_000)
    pred = predecir(antes + [Punto(9_999, riego_fin - timedelta(minutes=1), 45.0)] + despues, AHORA, 30)
    assert pred.inicio_tramo is not None and pred.inicio_tramo >= riego_fin - timedelta(minutes=2)
    assert pred.desde == pred.inicio_tramo                       # solo el tramo actual
    assert pred.ajuste.pendiente == pytest.approx(-0.5, abs=0.05)


def test_riego_manual_conocido_tambien_reinicia_la_ventana():
    serie = secado(36, 1.0)
    manual = EventoRiego(AHORA - timedelta(hours=1), AHORA - timedelta(hours=1), None, None, "manual")
    pred = predecir(serie, AHORA, 30, riegos_conocidos=[manual])
    assert pred.desde == AHORA - timedelta(hours=1)
    assert pred.n_puntos == 61


def test_no_usa_datos_posteriores_a_ahora():
    serie = secado(34, 1.0)
    futuro = [Punto(50_000 + i, AHORA + timedelta(minutes=i + 1), 99.0) for i in range(120)]
    assert predecir(serie + futuro, AHORA, 30) == predecir(serie, AHORA, 30)


@pytest.mark.parametrize("horas,texto", [(0.7, "unos 40 min"), (0.05, "unos 10 min"),
                                         (1.0, "una hora"), (1.6, "unas 1,5 h"), (4.6, "unas 5 h")])
def test_duracion_en_lenguaje_simple(horas, texto):
    assert duracion(horas) == texto


# --------------------------------------------------------- alerta preventiva

def pred(estado, pendiente=-1.0, horas=4.0):
    from comun.analitica.prediccion import Prediccion
    from comun.analitica.tendencia import Ajuste
    return Prediccion(estado, horas if estado == ESTIMACION else None, 30,
                      Ajuste(pendiente, 34, 0.9, 100, AHORA), AHORA, None)


def acciones(ds):
    return [(d.accion, d.tipo) for d in ds]


def test_alerta_desactivada_por_defecto_no_abre_nada():
    assert decidir(pred(ESTIMACION), False, True, set(), "Cama A") == []
    # Si estaba abierta y se desactiva, se resuelve
    assert acciones(decidir(pred(ESTIMACION), False, True, {"tendencia_secado"}, "Cama A")) == [
        (RESOLVER, "tendencia_secado")]


def test_alerta_activa_abre_y_luego_actualiza_sin_duplicar():
    d = decidir(pred(ESTIMACION), True, True, set(), "Cama A")
    assert acciones(d) == [(ABRIR, "tendencia_secado")]
    assert d[0].mensaje == ("Al ritmo actual, la Cama A llegaría a 30 % en unas 4 h (estimación). "
                            "Planifica el riego.")
    assert acciones(decidir(pred(ESTIMACION), True, True, {"tendencia_secado"}, "Cama A")) == [
        (ACTUALIZAR, "tendencia_secado")]


def test_alerta_se_resuelve_con_riego_horizonte_o_suelo_seco():
    abierta = {"tendencia_secado"}
    assert acciones(decidir(pred(FUERA_HORIZONTE), True, True, abierta, "A")) == [(RESOLVER, "tendencia_secado")]
    assert acciones(decidir(pred(SIN_TENDENCIA, pendiente=2.0), True, True, abierta, "A")) == [
        (RESOLVER, "tendencia_secado")]                       # regaron: ya no se seca
    assert acciones(decidir(pred(ESTIMACION), True, True, abierta | {"suelo_seco"}, "A")) == [
        (RESOLVER, "tendencia_secado")]                       # ya avisa la alerta real


def test_tendencia_poco_clara_no_abre_ni_cierra():
    assert decidir(pred(SIN_TENDENCIA, pendiente=-0.4), True, True, {"tendencia_secado"}, "A") == []


# ---------------------------------------------------------------- backtesting

def ciclos(n_ciclos, tasas, minimo=30, semilla=11, paso_min=5):
    """Secados lineales con ruido y riegos cuando la humedad pasa el mínimo."""
    rnd = random.Random(semilla)
    t, v, puntos, i = AHORA - timedelta(days=30), 60.0, [], 0
    for c in range(n_ciclos):
        tasa = tasas[c % len(tasas)]
        while v > minimo - 3:
            puntos.append(Punto(i, t, round(v + rnd.uniform(-0.3, 0.3), 2)))
            t += timedelta(minutes=paso_min)
            v -= tasa * paso_min / 60
            i += 1
        for paso in range(4):                             # riego en 20 min
            v += 7.5
            puntos.append(Punto(i, t, round(v, 2)))
            t += timedelta(minutes=paso_min)
            i += 1
    return puntos


def test_backtesting_calcula_mae_y_compara_con_la_referencia():
    puntos = ciclos(8, [1.0, 3.0, 2.0])                    # tasas distintas: la referencia se equivoca
    r = evaluar_cama("Cama A", puntos, 30, paso_min=30)
    assert r.suficiente and len(r.comparables) >= MIN_CASOS
    assert r.mae_modelo is not None and r.mae_modelo < 1.0
    assert r.mae_modelo < r.mae_ingenuo and r.supera_referencia is True
    assert r.cumple_meta is True
    assert max(r.tiempos_ms) < 1000                          # CQ-13


def test_backtesting_con_pocos_datos_no_inventa_metricas():
    r = evaluar_cama("Cama A", ciclos(1, [2.0]), 30)
    assert not r.suficiente
    assert (r.mae_modelo, r.mae_ingenuo, r.supera_referencia, r.cumple_meta) == (None, None, None, None)


class SerieEspia(list):
    """Lista que recuerda el índice más alto que se leyó."""
    maximo = -1

    def __getitem__(self, i):
        if isinstance(i, slice):
            fin = len(self) if i.stop is None else i.stop
            SerieEspia.maximo = max(SerieEspia.maximo, fin - 1)
        else:
            SerieEspia.maximo = max(SerieEspia.maximo, i if i >= 0 else len(self) + i)
        return super().__getitem__(i)


def test_backtesting_nunca_usa_datos_posteriores_a_t():
    """Fuga de datos (CQ-12): cambiar TODO lo posterior a t no cambia ni el
    modelo ni la referencia en t."""
    puntos = ciclos(6, [1.0, 2.5])
    tiempos = [q.t for q in puntos]
    for k in (len(puntos) // 3, len(puntos) // 2, 2 * len(puntos) // 3):
        t = tiempos[k]
        basura = puntos[:k + 1] + [Punto(q.lectura_id, q.t, random.Random(q.lectura_id).uniform(0, 100))
                                   for q in puntos[k + 1:]]
        assert predecir(basura, t, 30) == predecir(puntos, t, 30)
        assert tasa_ingenua(tramos_cerrados(basura, P), t) == tasa_ingenua(tramos_cerrados(puntos, P), t)
        # Y el modelo no LEE nada posterior a t
        SerieEspia.maximo = -1
        espia = SerieEspia(puntos)
        predecir(espia, t, 30, tiempos=tiempos)
        assert SerieEspia.maximo <= k


# ------------------------------------------- detección rápida = detección simple

def detectar_simple(puntos, umbral=10.0, ventana_min=30.0):
    """La versión O(n·w) original, como referencia."""
    ventana = timedelta(minutes=ventana_min)
    eventos, ultimo_fin, inicio, n, j = [], None, 0, len(puntos), 0
    while j < n:
        actual = puntos[j]
        if ultimo_fin is not None and actual.t <= ultimo_fin:
            j += 1
            continue
        while puntos[inicio].t < actual.t - ventana:
            inicio += 1
        bajo = None
        for k in range(inicio, j):
            p = puntos[k]
            if ultimo_fin is not None and p.t < ultimo_fin:
                continue
            if bajo is None or p.valor <= bajo.valor:
                bajo = p
        if bajo is not None and actual.valor - bajo.valor >= umbral:
            alto, m = actual, j + 1
            while m < n and puntos[m].t - alto.t <= ventana:
                if puntos[m].valor > alto.valor:
                    alto = puntos[m]
                m += 1
            eventos.append((bajo.t, alto.t, bajo.valor, alto.valor))
            ultimo_fin = alto.t
        j += 1
    return eventos


@pytest.mark.parametrize("semilla", range(8))
def test_deteccion_optimizada_da_lo_mismo_que_la_simple(semilla):
    rnd = random.Random(semilla)
    v, puntos = 40.0, []
    for i in range(3000):
        v += rnd.choice([-0.05] * 30 + [-1, 1, 3, 6])
        puntos.append(Punto(i, AHORA + timedelta(minutes=i), round(v, 1)))
    rapida = [(e.inicio, e.fin, e.humedad_antes, e.humedad_despues) for e in detectar_riegos(puntos)]
    assert rapida == detectar_simple(puntos)


# ------------------------------------------------------------- reporte (tools)

def test_reporte_con_datos_insuficientes(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    import evaluar_tendencia
    md, archivo_csv = evaluar_tendencia.escribir_reporte(
        evaluar_cama("Cama A", ciclos(1, [2.0]), 30), "prueba", P, ["Cama B"], date(2026, 11, 27), tmp_path)
    texto = md.read_text(encoding="utf-8")
    assert md.name == "2026-11-27_evaluacion_tendencia.md" and archivo_csv.exists()
    assert "Datos insuficientes" in texto and "MAE del tiempo" not in texto
    assert "sin mínimo de humedad (no evaluadas): Cama B" in texto


def test_reporte_con_metricas(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    import evaluar_tendencia
    r = evaluar_cama("Cama A", ciclos(8, [1.0, 3.0, 2.0]), 30)
    md, _ = evaluar_tendencia.escribir_reporte(r, "prueba", P, [], date(2026, 11, 27), tmp_path)
    texto = md.read_text(encoding="utf-8")
    assert "CQ-10 (MAE ≤ 2 h):** cumple" in texto and "CQ-11 (supera a la referencia):** sí" in texto

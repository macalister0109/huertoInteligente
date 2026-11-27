"""Reglas puras de suelo, temperatura, luz y estado."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from comun.rangos import Rango, rango_efectivo
from procesador.reglas import ABRIR, ACTUALIZAR, RESOLVER
from procesador.reglas.estado import (GRIS, ROJO, SIN_CONFIGURAR, VERDE, AlertaResumen,
                                      calcular_estado, sensores_sin_datos)
from procesador.reglas.luz import (DiaLuz, calcular_luz, evaluar_poca_luz, limites_dia,
                                   racha_poca_luz)
from procesador.reglas.suelo import evaluar_suelo
from procesador.reglas.temperatura import evaluar_temperatura, inicio_racha_sobre_maximo

TOMATE = Rango(30, 70, 15, 30, 6, "tomate")
T0 = datetime(2026, 11, 26, 12, 0)


# --------------------------------------------------------------------- rangos

def test_rango_personalizado_reemplaza_campo_por_campo():
    cama = {"humedad_min": 40, "humedad_max": None, "temp_min": None, "temp_max": None,
            "horas_luz_min": None, "cultivo_nombre": "tomate", "cultivo_humedad_min": 30,
            "cultivo_humedad_max": 70, "cultivo_temp_min": 15, "cultivo_temp_max": 30,
            "cultivo_horas_luz_min": 6}
    r = rango_efectivo(cama)
    assert (r.humedad_min, r.humedad_max, r.temp_min) == (40, 70, 15)


def test_cama_sin_cultivo_ni_rangos_no_esta_configurada():
    assert not rango_efectivo({"cultivo_nombre": None}).configurado


# ----------------------------------------------------------------------- suelo

def acciones(decisiones):
    return [(d.accion, d.tipo) for d in decisiones]


def test_suelo_seco_abre_y_luego_actualiza():
    assert acciones(evaluar_suelo("Cama B", 22, TOMATE, set(), 2)) == [(ABRIR, "suelo_seco")]
    assert acciones(evaluar_suelo("Cama B", 20, TOMATE, {"suelo_seco"}, 2)) == \
        [(ACTUALIZAR, "suelo_seco")]


def test_suelo_histeresis():
    abierta = {"suelo_seco"}
    assert evaluar_suelo("B", 30.5, TOMATE, abierta, 2) == []      # en el borde: sigue abierta
    assert evaluar_suelo("B", 31.9, TOMATE, abierta, 2) == []
    assert acciones(evaluar_suelo("B", 32, TOMATE, abierta, 2)) == [(RESOLVER, "suelo_seco")]
    assert evaluar_suelo("B", 31, TOMATE, set(), 2) == []           # sin alerta: nada


def test_suelo_encharcado_con_histeresis():
    assert acciones(evaluar_suelo("B", 85, TOMATE, set(), 2)) == [(ABRIR, "suelo_encharcado")]
    assert evaluar_suelo("B", 69, TOMATE, {"suelo_encharcado"}, 2) == []
    assert acciones(evaluar_suelo("B", 68, TOMATE, {"suelo_encharcado"}, 2)) == \
        [(RESOLVER, "suelo_encharcado")]


def test_valor_en_el_limite_no_alerta():
    assert evaluar_suelo("B", 30, TOMATE, set(), 2) == []
    assert evaluar_suelo("B", 70, TOMATE, set(), 2) == []


# ------------------------------------------------------------------ temperatura

def racha(*pares):
    """pares (minutos_atras, temp) -> lista descendente."""
    return [(T0 - timedelta(minutes=m), t) for m, t in pares]


def test_inicio_de_racha_sobre_maximo():
    lecturas = racha((0, 35), (10, 34), (20, 33), (30, 31), (40, 29))
    assert inicio_racha_sobre_maximo(lecturas, 30, 10) == T0 - timedelta(minutes=30)


def test_hueco_largo_corta_la_racha():
    lecturas = racha((0, 35), (5, 35), (25, 35))
    assert inicio_racha_sobre_maximo(lecturas, 30, 10) == T0 - timedelta(minutes=5)


def test_helada_es_inmediata():
    d = evaluar_temperatura("Cama A", 4, T0, TOMATE, set(), 1, None, 30)
    assert acciones(d) == [(ABRIR, "helada")]
    assert d[0].mensaje == "Riesgo de helada en cama A: 4 °C. Cubre la planta"


def test_calor_breve_no_alerta_y_sostenido_si():
    breve = evaluar_temperatura("Cama A", 36, T0, TOMATE, set(), 1, T0 - timedelta(minutes=29), 30)
    assert breve == []
    largo = evaluar_temperatura("Cama A", 36, T0, TOMATE, set(), 1, T0 - timedelta(minutes=30), 30)
    assert acciones(largo) == [(ABRIR, "calor")]
    assert largo[0].iniciada_en == T0 - timedelta(minutes=30)   # inicio real del calor


def test_calor_se_resuelve_con_histeresis():
    assert evaluar_temperatura("A", 29.5, T0, TOMATE, {"calor"}, 1, None, 30) == []
    assert acciones(evaluar_temperatura("A", 29, T0, TOMATE, {"calor"}, 1, None, 30)) == \
        [(RESOLVER, "calor")]


# ------------------------------------------------------------------------- luz

ZONA = ZoneInfo("America/Santiago")


def test_horas_de_luz_por_intervalo_real():
    inicio, fin = limites_dia(date(2026, 11, 26), ZONA)
    sol = (inicio + timedelta(hours=6), inicio + timedelta(hours=21))
    t = inicio + timedelta(hours=10)
    # 3 lecturas cada 30 min con sol fuerte y luego una a la sombra
    lecturas = [(t, 40000), (t + timedelta(minutes=30), 40000),
                (t + timedelta(minutes=60), 40000), (t + timedelta(minutes=90), 1000)]
    r = calcular_luz(lecturas, inicio, fin, *sol, umbral_lux=25000, max_hueco_min=40)
    assert r.horas_luz == 1.5
    assert r.minutos_con_datos == 130      # 30+30+30 y la última cubre 40 (tope)


def test_hueco_sin_datos_no_cuenta_como_luz():
    inicio, fin = limites_dia(date(2026, 11, 26), ZONA)
    t = inicio + timedelta(hours=12)
    lecturas = [(t, 50000), (t + timedelta(hours=3), 50000)]     # nodo caído 3 h
    r = calcular_luz(lecturas, inicio, fin, inicio, fin, 25000, 10)
    assert r.horas_luz == round(20 / 60, 2)


def test_dia_sin_lecturas_de_luz_es_sin_datos_no_cero():
    inicio, fin = limites_dia(date(2026, 11, 26), ZONA)
    assert calcular_luz([], inicio, fin, inicio, fin, 25000, 10).horas_luz is None


def dia(n, horas, cobertura=900):
    return DiaLuz(date(2026, 11, 26) - timedelta(days=n), horas, cobertura)


def test_tres_dias_seguidos_de_poca_luz_avisa():
    dias = [dia(0, 4), dia(1, 5), dia(2, 3)]
    d = evaluar_poca_luz("Cama B", TOMATE, dias, set(), 3, 900, 0.75, ["lechuga"])
    assert acciones(d) == [(ABRIR, "poca_luz")]
    assert d[0].mensaje == ("Cama B recibe poca luz para tomate. Considera moverla o elegir "
                            "un cultivo de sombra, como lechuga")


def test_dos_dias_de_poca_luz_no_avisan():
    assert evaluar_poca_luz("B", TOMATE, [dia(0, 4), dia(1, 5), dia(2, 8)], set(), 3,
                            900, 0.75, []) == []


def test_dia_incompleto_o_faltante_corta_la_racha():
    assert racha_poca_luz([dia(0, 4), dia(1, 4, cobertura=300), dia(2, 4)], 6, 900, 0.75) == 1
    assert racha_poca_luz([dia(0, 4), dia(2, 4), dia(3, 4)], 6, 900, 0.75) == 1
    assert racha_poca_luz([dia(0, None, 0), dia(1, 4)], 6, 900, 0.75) == 0


def test_poca_luz_se_resuelve_con_un_dia_completo_con_sol():
    d = evaluar_poca_luz("B", TOMATE, [dia(0, 7), dia(1, 4)], {"poca_luz"}, 3, 900, 0.75, [])
    assert acciones(d) == [(RESOLVER, "poca_luz")]


# ---------------------------------------------------------------------- estado

def test_gris_si_algun_sensor_lleva_2_horas_sin_datos():
    ahora = T0
    ultimas = {"suelo": ahora, "temperatura": ahora - timedelta(minutes=121), "luz": ahora}
    assert sensores_sin_datos(ultimas, ahora - timedelta(days=1), ahora, 120) == ["temperatura"]


def test_sensor_que_nunca_envio_se_mide_desde_la_primera_lectura():
    ahora = T0
    ultimas = {"suelo": ahora, "temperatura": None, "luz": ahora}
    assert sensores_sin_datos(ultimas, ahora - timedelta(minutes=30), ahora, 120) == []
    assert sensores_sin_datos(ultimas, ahora - timedelta(hours=3), ahora, 120) == ["temperatura"]


def test_prioridad_gris_rojo_verde():
    seca = [AlertaResumen("suelo_seco", "suelo", 22)]
    assert calcular_estado(True, True, ["temperatura"], seca).color == GRIS
    rojo = calcular_estado(True, True, [], seca)
    assert (rojo.color, rojo.mensaje) == (ROJO, "Revisar: humedad 22 %")
    assert calcular_estado(True, True, [], []).mensaje == "Todo bien"
    assert calcular_estado(True, True, [], []).color == VERDE
    sin_conf = calcular_estado(False, True, [], [])
    assert (sin_conf.color, sin_conf.mensaje) == (SIN_CONFIGURAR,
                                                  "Configura un cultivo para activar las alertas")
    assert calcular_estado(True, False, [], []).mensaje == "Sin lecturas"


def test_rojo_con_varias_variables():
    alertas = [AlertaResumen("calor", "temperatura", 36), AlertaResumen("suelo_seco", "suelo", 22.4),
               AlertaResumen("poca_luz", "luz", 4)]
    assert calcular_estado(True, True, [], alertas).mensaje == \
        "Revisar: humedad 22 %, temperatura 36 °C, poca luz"


def test_sensores_no_requeridos_no_ponen_gris():
    ahora = datetime(2026, 11, 26, 15, 0)
    ultimas = {"suelo": ahora, "temperatura": ahora, "luz": None}
    primera = ahora - timedelta(hours=5)
    assert sensores_sin_datos(ultimas, primera, ahora, 120) == ["luz"]
    assert sensores_sin_datos(ultimas, primera, ahora, 120, ("suelo", "temperatura")) == []


def test_config_sensores_requeridos_por_defecto_sin_luz():
    from comun.config import Config
    assert Config().lista_sensores_requeridos == ("suelo", "temperatura")
    cfg = Config.desde_entorno({"SENSORES_REQUERIDOS": "suelo, temperatura, luz"})
    assert cfg.lista_sensores_requeridos == ("suelo", "temperatura", "luz")

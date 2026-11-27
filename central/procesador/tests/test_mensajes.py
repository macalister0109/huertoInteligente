"""Textos exactos de los avisos (especificación HU-02 a HU-05)."""

from comun import mensajes as m


def test_suelo_seco():
    assert m.suelo_seco("Cama B", 22, 30, 70) == "Cama B seca: 22 % (ideal 30 % a 70 %)"


def test_suelo_encharcado():
    assert m.suelo_encharcado("Cama B", 85) == "Cama B con exceso de agua: 85 %. No riegues hoy"


def test_helada():
    assert m.helada("Cama A", 4) == "Riesgo de helada en cama A: 4 °C. Cubre la planta"


def test_calor():
    assert m.calor("Cama A", 36) == \
        "Calor excesivo en cama A: 36 °C. Dale sombra y revisa la humedad"


def test_poca_luz():
    assert m.poca_luz("Cama B", "tomate", ["lechuga"]) == (
        "Cama B recibe poca luz para tomate. Considera moverla o elegir un "
        "cultivo de sombra, como lechuga")


def test_estados():
    assert m.TODO_BIEN == "Todo bien"
    assert m.revisar([m.item_suelo(22)]) == "Revisar: humedad 22 %"
    assert m.sensores_sin_conexion(["temperatura"]) == "Sensor de temperatura sin conexión"
    assert m.sensores_sin_conexion(["luz", "suelo"]) == \
        "Sensores de humedad del suelo y luz sin conexión"
    assert m.CONFIGURA_CULTIVO == "Configura un cultivo para activar las alertas"
    assert m.SIN_LECTURAS == "Sin lecturas"


def test_luz_sin_datos_nunca_es_cero_horas():
    assert m.horas_luz(None) == "Sin datos de luz hoy"
    assert m.horas_luz(0) == "0,0 h de luz"
    assert m.horas_luz(5.25) == "5,3 h de luz"


def test_valor_cerca_del_limite_se_muestra_con_decimal():
    """29,7 % con mínimo 30 no debe leerse "30 %" (parecería estar bien)."""
    assert m.suelo_seco("Cama A", 29.7, 30, 70) == "Cama A seca: 29,7 % (ideal 30 % a 70 %)"
    assert m.suelo_encharcado("Cama A", 70.4, 70) == \
        "Cama A con exceso de agua: 70,4 %. No riegues hoy"
    assert m.calor("Cama A", 30.2, 30).startswith("Calor excesivo en cama A: 30,2 °C")
    assert m.helada("Cama A", 14.6, 15).startswith("Riesgo de helada en cama A: 14,6 °C")
    assert m.item_suelo(29.7, minimo=30) == "humedad 29,7 %"
    # Lejos del límite se mantiene el entero de la especificación
    assert m.suelo_seco("Cama B", 22.4, 30, 70) == "Cama B seca: 22 % (ideal 30 % a 70 %)"


def test_redondeo_de_valores():
    # Redondeo "escolar" (0,5 sube) y sin "-0"
    assert m.entero(22.5) == "23"
    assert m.entero(21.4) == "21"
    assert m.entero(-0.3) == "0"
    assert m.entero(-2.5) == "-3"

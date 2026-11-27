"""Textos que ve el usuario en la pantalla del huerto.

Están todos aquí para que el lenguaje sea uniforme (simple, sin jerga) y
para que los tests verifiquen los textos exactos de la especificación.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Sequence

TODO_BIEN = "Todo bien"
SIN_LECTURAS = "Sin lecturas"
SIN_DATOS_LUZ_HOY = "Sin datos de luz hoy"
CONFIGURA_CULTIVO = "Configura un cultivo para activar las alertas"

# Nombre de cada sensor para los avisos de "sin conexión"
NOMBRE_SENSOR = {
    "suelo": "humedad del suelo",
    "temperatura": "temperatura",
    "luz": "luz",
}
ORDEN_SENSORES = ("suelo", "temperatura", "luz")


# ---------------------------------------------------------------------------
# Formato de números
# ---------------------------------------------------------------------------

def entero(valor: float) -> str:
    """Redondea al entero más cercano (0,5 sube) y evita mostrar '-0'."""
    n = int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return str(n if n != 0 else 0)


def decimal_coma(valor: float, decimales: int = 1) -> str:
    """5.25 -> '5,3' (coma decimal, como se escribe en Chile)."""
    cuantizador = Decimal(1).scaleb(-decimales)
    texto = str(Decimal(str(valor)).quantize(cuantizador, rounding=ROUND_HALF_UP))
    return texto.replace(".", ",")


def fuera_de_rango(valor: float, minimo: Optional[float] = None,
                   maximo: Optional[float] = None) -> str:
    """Valor de un aviso. Normalmente entero ("22"), pero si al redondear
    quedaría DENTRO del rango ("30" con mínimo 30, que confunde) se muestra
    con un decimal ("29,7")."""
    texto = entero(valor)
    redondeado = float(texto)
    if (minimo is not None and redondeado >= minimo) or (maximo is not None and redondeado <= maximo):
        return decimal_coma(valor)
    return texto


def en_frase(nombre: str) -> str:
    """'Cama A' -> 'cama A' para usarlo en medio de una frase."""
    return nombre[:1].lower() + nombre[1:] if nombre else nombre


def unir(elementos: Sequence[str]) -> str:
    """['a'] -> 'a';  ['a','b'] -> 'a y b';  ['a','b','c'] -> 'a, b y c'."""
    elementos = list(elementos)
    if len(elementos) <= 1:
        return "".join(elementos)
    return ", ".join(elementos[:-1]) + " y " + elementos[-1]


def unir_o(elementos: Sequence[str]) -> str:
    elementos = list(elementos)
    if len(elementos) <= 1:
        return "".join(elementos)
    return ", ".join(elementos[:-1]) + " o " + elementos[-1]


# ---------------------------------------------------------------------------
# Avisos (HU-02, HU-03, HU-04)
# ---------------------------------------------------------------------------

def suelo_seco(nombre: str, valor: float, minimo: float, maximo: Optional[float]) -> str:
    """«Cama B seca: 22 % (ideal 30 % a 70 %)»"""
    if maximo is not None:
        ideal = f"ideal {entero(minimo)} % a {entero(maximo)} %"
    else:
        ideal = f"ideal desde {entero(minimo)} %"
    return f"{nombre} seca: {fuera_de_rango(valor, minimo=minimo)} % ({ideal})"


def suelo_encharcado(nombre: str, valor: float, maximo: Optional[float] = None) -> str:
    """«Cama B con exceso de agua: 85 %. No riegues hoy»"""
    return f"{nombre} con exceso de agua: {fuera_de_rango(valor, maximo=maximo)} %. No riegues hoy"


def helada(nombre: str, valor: float, minimo: Optional[float] = None) -> str:
    """«Riesgo de helada en cama A: 4 °C. Cubre la planta»"""
    return (f"Riesgo de helada en {en_frase(nombre)}: {fuera_de_rango(valor, minimo=minimo)} °C. "
            "Cubre la planta")


def calor(nombre: str, valor: float, maximo: Optional[float] = None) -> str:
    """«Calor excesivo en cama A: 36 °C. Dale sombra y revisa la humedad»"""
    return (f"Calor excesivo en {en_frase(nombre)}: {fuera_de_rango(valor, maximo=maximo)} °C. "
            "Dale sombra y revisa la humedad")


def poca_luz(nombre: str, cultivo: Optional[str], cultivos_sombra: Sequence[str]) -> str:
    """«Cama B recibe poca luz para tomate. Considera moverla o elegir un
    cultivo de sombra, como lechuga»"""
    texto = f"{nombre} recibe poca luz"
    if cultivo:
        texto += f" para {cultivo}"
    if cultivos_sombra:
        texto += f". Considera moverla o elegir un cultivo de sombra, como {unir_o(cultivos_sombra)}"
    else:
        texto += ". Considera moverla a un lugar con más sol"
    return texto


def sensores_sin_conexion(variables: Iterable[str]) -> str:
    """«Sensor de temperatura sin conexión» / «Sensores de luz y temperatura sin conexión»"""
    ordenadas = [v for v in ORDEN_SENSORES if v in set(variables)]
    nombres = [NOMBRE_SENSOR[v] for v in ordenadas]
    if len(nombres) == 1:
        return f"Sensor de {nombres[0]} sin conexión"
    return f"Sensores de {unir(nombres)} sin conexión"


# ---------------------------------------------------------------------------
# Estado de la cama (HU-05): «Revisar: humedad 22 %»
# ---------------------------------------------------------------------------

def item_suelo(valor: float, minimo: Optional[float] = None,
               maximo: Optional[float] = None) -> str:
    return f"humedad {fuera_de_rango(valor, minimo, maximo)} %"


def item_temperatura(valor: float, minimo: Optional[float] = None,
                     maximo: Optional[float] = None) -> str:
    return f"temperatura {fuera_de_rango(valor, minimo, maximo)} °C"


ITEM_POCA_LUZ = "poca luz"


def revisar(items: Sequence[str]) -> str:
    return "Revisar: " + ", ".join(items)


def horas_luz(horas: Optional[float]) -> str:
    """Texto de las horas de luz de hoy. Nunca muestra '0 h' si no hubo datos."""
    if horas is None:
        return SIN_DATOS_LUZ_HOY
    return f"{decimal_coma(horas)} h de luz"

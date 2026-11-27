"""Validación de los formularios de configuración (mensajes para el docente)."""

from __future__ import annotations

from typing import Mapping, Optional

LIMITES = {
    "humedad": (0.0, 100.0, "%"),
    "temp": (-40.0, 80.0, "°C"),
    "horas_luz": (0.0, 24.0, "h"),
}

ETIQUETAS = {
    "humedad_min": "Humedad mínima", "humedad_max": "Humedad máxima",
    "temp_min": "Temperatura mínima", "temp_max": "Temperatura máxima",
    "horas_luz_min": "Horas de luz mínimas",
}


def _numero(form: Mapping[str, str], campo: str, tipo: str, errores: list[str]) -> Optional[float]:
    texto = (form.get(campo) or "").strip().replace(",", ".")
    if texto == "":
        return None
    try:
        valor = float(texto)
    except ValueError:
        errores.append(f"{ETIQUETAS[campo]}: «{form.get(campo)}» no es un número.")
        return None
    minimo, maximo, unidad = LIMITES[tipo]
    if not minimo <= valor <= maximo:
        errores.append(f"{ETIQUETAS[campo]}: debe estar entre {minimo:g} y {maximo:g} {unidad}.")
        return None
    return round(valor, 2)


def _rangos(form: Mapping[str, str], errores: list[str]) -> dict:
    return {
        "humedad_min": _numero(form, "humedad_min", "humedad", errores),
        "humedad_max": _numero(form, "humedad_max", "humedad", errores),
        "temp_min": _numero(form, "temp_min", "temp", errores),
        "temp_max": _numero(form, "temp_max", "temp", errores),
        "horas_luz_min": _numero(form, "horas_luz_min", "horas_luz", errores),
    }


def _min_menor_que_max(efectivos: dict, errores: list[str]) -> None:
    for var, nombre in (("humedad", "la humedad"), ("temp", "la temperatura")):
        minimo, maximo = efectivos.get(f"{var}_min"), efectivos.get(f"{var}_max")
        if minimo is not None and maximo is not None and minimo > maximo:
            errores.append(f"El mínimo de {nombre} ({minimo:g}) es mayor que el máximo ({maximo:g}).")


def validar_cama(form: Mapping[str, str], cultivos: dict[int, dict]) -> tuple[dict, list[str]]:
    errores: list[str] = []
    nombre = (form.get("nombre") or "").strip()
    if not 1 <= len(nombre) <= 60:
        errores.append("El nombre es obligatorio (hasta 60 letras).")
    zona = (form.get("zona_climatica") or "").strip() or None
    if zona and len(zona) > 60:
        errores.append("La zona puede tener hasta 60 letras.")

    cultivo_id: Optional[int] = None
    texto_cultivo = (form.get("cultivo_id") or "").strip()
    if texto_cultivo:
        if not texto_cultivo.isdigit() or int(texto_cultivo) not in cultivos:
            errores.append("El cultivo elegido no existe.")
        else:
            cultivo_id = int(texto_cultivo)

    rangos = _rangos(form, errores)
    # Se valida el rango EFECTIVO: el personalizado o, si está vacío, el del cultivo
    cultivo = cultivos.get(cultivo_id, {}) if cultivo_id else {}
    efectivos = {k: v if v is not None else (None if cultivo.get(k) is None else float(cultivo[k]))
                 for k, v in rangos.items()}
    _min_menor_que_max(efectivos, errores)

    valores = {"nombre": nombre, "zona_climatica": zona, "cultivo_id": cultivo_id,
               "activa": 1 if form.get("activa") else 0, **rangos}
    return valores, errores


def validar_cultivo(form: Mapping[str, str], otros_nombres: set[str]) -> tuple[dict, list[str]]:
    errores: list[str] = []
    nombre = (form.get("nombre") or "").strip().lower()
    if not 1 <= len(nombre) <= 60:
        errores.append("El nombre del cultivo es obligatorio (hasta 60 letras).")
    elif nombre in otros_nombres:
        errores.append(f"Ya existe un cultivo llamado «{nombre}».")
    rangos = _rangos(form, errores)
    _min_menor_que_max(rangos, errores)
    notas = (form.get("notas") or "").strip()[:255] or None
    valores = {"nombre": nombre, **rangos, "notas": notas,
               "tolera_sombra": 1 if form.get("tolera_sombra") else 0,
               "por_confirmar": 1 if form.get("por_confirmar") else 0}
    return valores, errores

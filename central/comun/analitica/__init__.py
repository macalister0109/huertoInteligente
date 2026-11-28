"""Capa de datos para análisis: crudo -> limpio -> agregado.

Las lecturas crudas nunca se modifican. Aquí se calculan, a partir de ellas,
las marcas de calidad, los agregados por hora y día, los eventos de riego y
las tendencias. Todo es recalculable (idempotente).
"""

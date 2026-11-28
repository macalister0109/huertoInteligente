# Diccionario de datos — Huerto Inteligente

Describe las tablas de la base de datos y los archivos que se exportan para analizar. La exportación
se hace de dos maneras:

- con el endpoint `GET /api/exportar/<conjunto>.csv`;
- con el comando `python tools/exportar.py`, que genera CSV y Parquet.

Los datos sintéticos se generan con `python tools/generar_sinteticos.py`.

## Convenciones

- **Fechas:** se guardan en **UTC** (columnas `*_utc`, ISO 8601 con `Z`). El «día» es el día en hora de
  Chile (`America/Santiago`), y por eso un día puede durar 23 o 25 horas.
- **Formato de exportación:** CSV estándar (separador `,`, punto decimal y UTF-8). Una celda vacía
  significa «sin dato». Ojo: la descarga de la ficha de cada cama es distinta, porque está pensada para
  Excel (`;`, coma decimal y hora de Chile).
- **`origen`:** `real` (exportado de la base de datos) o `sintetico` (generado). **Nunca se mezclan:**
  el notebook y `tools/evaluar_tendencia.py` se detienen si un archivo trae los dos.
- **Datos crudos y calculados:** la tabla `lecturas` es la fuente de verdad y **nunca se modifica**.
  Todo lo demás (marcas de calidad, agregados, riegos detectados) se calcula a partir de ella y se puede
  recalcular con `python -m comun.analitica.recalcular --desde … --hasta …`.
- **Sin datos personales:** solo variables ambientales y nombres de camas. No hay cuentas de
  estudiantes. Las `notas` de los riegos manuales no se exportan.

## Limitaciones de los sensores (léelas antes de sacar conclusiones)

| Sensor | Variable | Limitación |
| --- | --- | --- |
| **DHT11** (prototipo 1) | Temperatura del aire | Error de **±2 °C** y resolución de **1 °C** (entrega números enteros). Mide de 0 a 50 °C: **no mide bajo cero**, así que no sirve para registrar la intensidad de una helada fuerte. |
| **DHT11** | Humedad relativa del aire | Error de **±5 puntos** y resolución de 1 %. |
| **Sonda resistiva YL-69** + LM393 | Humedad del suelo | El % es una **escala calibrada**: 0 % es la sonda seca en el aire y 100 % es la sonda en agua. **No es contenido volumétrico de agua** (m³/m³) y no se compara directo con el «% vol.» del clima de la zona. La sonda se corroe con el tiempo (deriva): conviene recalibrarla. |
| Clima de la zona (Open-Meteo) | Todas | Es un **modelo** para una celda de varios km, no una medición en el colegio. La humedad del suelo es el contenido volumétrico modelado entre 0 y 1 cm de profundidad. |

---

## `lecturas` — lecturas crudas con marcas de calidad

Una fila por medición de un nodo (por defecto, cada 30 s). Tabla de la base de datos: `lecturas`,
unida con `calidad_lecturas`.

| Columna | Tipo | Unidad | Origen | Rango válido | Significado |
| --- | --- | --- | --- | --- | --- |
| origen | texto | — | exportación | `real` / `sintetico` | De dónde viene la fila. |
| lectura_id | entero | — | base de datos | — | Identificador único de la lectura. |
| cama_id | entero | — | base de datos | — | Identificador de la cama. |
| cama | texto | — | configuración | — | Nombre visible, por ejemplo «Cama A». |
| nodo_id | texto | — | nodo ESP32 | — | Identificador del equipo, por ejemplo `cama-a`. |
| seq | entero | — | nodo | ≥ 0 | Contador de lecturas del nodo. Si un `seq` se repite con otra hora, el contador se reinició. |
| medido_en_utc | fecha y hora | UTC | reloj del nodo (NTP) | — | Cuándo se midió. |
| recibido_en_utc | fecha y hora | UTC | equipo central | — | Cuándo llegó. Si es mucho más tarde que `medido_en_utc`, venía del buffer del nodo (corte de WiFi). |
| suelo_pct | decimal | % calibrado | sonda YL-69 | 0 a 100 | Promedio de las sondas válidas. Si la cama tiene calibración en el servidor (`camas.cal_seco_mv` y `cal_mojado_mv`), se calcula desde `suelo_mv`. Vacío si se descartó. |
| suelo_mv | entero | mV | ADC del ESP32 | 0 a 3600 | Voltaje crudo de la sonda (sirve para calibrar y para ver la deriva). |
| temp_c | decimal | °C | DHT11 | 0 a 50 | Temperatura del aire. Vacía si se descartó. |
| hum_aire_pct | decimal | % | DHT11 | 0 a 100 | Humedad relativa del aire. |
| luz_lux | decimal | lux | BH1750 (prototipo 2) | ≥ 0 | Iluminancia. Vacía en el prototipo 1, que no tiene sensor de luz. |
| valida | 0/1 | — | validación | — | 0 = la lectura completa no sirve (hora imposible o ningún dato utilizable). |
| motivo_invalida | texto | — | validación | — | Por qué se descartó algún valor. |
| marcas | texto | — | calidad | — | Marcas separadas por `;`, por ejemplo `suelo:pegado;lectura:hueco`. |
| excluir_suelo / excluir_temp / excluir_hum_aire | 0/1 | — | calidad | — | 1 = no usar ese valor para analizar (tiene la marca rango, salto o pegado). |
| hueco_antes | 0/1 | — | calidad | — | 1 = antes de esta lectura faltaron más de 2 lecturas seguidas. |

**Marcas de calidad** (tabla `calidad_lecturas`):

| Marca | Variable | Cuándo |
| --- | --- | --- |
| `rango` | suelo, temp, hum_aire | Valor fuera del rango físico del sensor o no numérico. Lo detecta la validación al llegar la lectura. |
| `salto` | suelo, temp, hum_aire | Cambio imposible respecto de la lectura anterior. El suelo solo se marca si **baja** más de 10 puntos por minuto (las subidas son riegos), la temperatura si cambia más de 3 °C por minuto y la humedad del aire si cambia más de 15 puntos por minuto. |
| `pegado` | suelo, temp, hum_aire | El mismo valor exacto durante más de N horas: suelo 3 h, aire 6 h (`PEGADO_HORAS_*`). Un hueco de más de 1 h corta la racha. |
| `hueco` | lectura | Faltaron más de `HUECO_LECTURAS_FALTANTES` (2) lecturas seguidas antes de esta. |

## `agregados_hora` — resumen por hora

Una fila por cama, hora (UTC) y variable. Solo existen las horas con al menos una lectura.

| Columna | Tipo | Unidad | Origen | Rango válido | Significado |
| --- | --- | --- | --- | --- | --- |
| cama_id, cama | — | — | base de datos | — | Cama. |
| hora_inicio_utc | fecha y hora | UTC | cálculo | — | Inicio de la hora. |
| variable | texto | — | cálculo | `suelo` / `temp` / `hum_aire` | Variable resumida. |
| media, minimo, maximo | decimal | la de la variable | cálculo | — | Solo con valores válidos y sin excluidos. |
| desviacion | decimal | la de la variable | cálculo | ≥ 0 | Desviación estándar muestral. Vacía con menos de 2 valores. |
| n_lecturas | entero | — | cálculo | ≥ 0 | Valores usados. |
| n_excluidas | entero | — | cálculo | ≥ 0 | Valores descartados por las marcas rango, salto o pegado. |
| n_esperadas | entero | — | cálculo | — | 3600 / `INTERVALO_LECTURA_S`. En la hora en curso, solo hasta ese momento. |
| cobertura | decimal | fracción | cálculo | 0 a 1 | `n_lecturas / n_esperadas`. Meta CQ-04: 0,95 o más. |

## `agregados_dia` — resumen por día (hora de Chile)

Tiene las mismas columnas que `agregados_hora`, pero usa `fecha` (el día local) en vez de
`hora_inicio_utc`. Además agrega:

| Columna | Tipo | Unidad | Origen | Rango válido | Significado |
| --- | --- | --- | --- | --- | --- |
| amplitud | decimal | la de la variable | cálculo | ≥ 0 | Máximo menos mínimo del día. En `temp` es la **amplitud térmica**. |
| horas_fuera_rango | decimal | h | cálculo | 0 a 24 | Horas con valores fuera del rango ideal de la cama: cada valor fuera de rango cuenta como un intervalo de lectura. Usa el rango **vigente** de la cama al momento del cálculo. Vacía si la variable no tiene rango (humedad del aire). |

## `eventos_riego` — riegos

| Columna | Tipo | Unidad | Origen | Rango válido | Significado |
| --- | --- | --- | --- | --- | --- |
| evento_id | entero | — | base de datos | — | Identificador. Se mantiene al recalcular. |
| cama_id, cama | — | — | base de datos | — | Cama. |
| tipo_registro | texto | — | cálculo / persona | `detectado` / `manual` | `detectado`: lo encontró el sistema. `manual`: lo registró una persona (todavía no hay pantalla para eso). |
| inicio_utc | fecha y hora | UTC | cálculo | — | Lectura más baja antes de la subida. |
| fin_utc | fecha y hora | UTC | cálculo | — | Punto más alto de la subida. Desde aquí empieza el **tramo de secado**. |
| humedad_antes, humedad_despues | decimal | % calibrado | cálculo | 0 a 100 | Humedad del suelo al inicio y al fin del riego. |
| subida | decimal | puntos | cálculo | ≥ 10 por defecto | `humedad_despues − humedad_antes`. |

**Detección:** la humedad sube al menos `RIEGO_UMBRAL_PTS` (10) puntos respecto del valor más bajo de
los últimos `RIEGO_VENTANA_MIN` (30) minutos. La vista `v_tramos_secado` de la base de datos entrega
cada tramo, desde el fin de un riego hasta el inicio del siguiente.

## `alertas` — avisos

| Columna | Tipo | Unidad | Origen | Rango válido | Significado |
| --- | --- | --- | --- | --- | --- |
| alerta_id | entero | — | base de datos | — | Identificador. |
| cama_id, cama | — | — | base de datos | — | Cama. |
| tipo | texto | — | procesador | `suelo_seco`, `suelo_encharcado`, `helada`, `calor`, `poca_luz`, `sensor_sin_datos`, `tendencia_secado` | Tipo de aviso. `tendencia_secado` es preventivo: avisa que se llegaría al mínimo pronto. |
| variable | texto | — | procesador | `suelo` / `temperatura` / `luz` | Sensor que originó el aviso. |
| estado | texto | — | procesador | `abierta` / `resuelta` | Hay una sola alerta abierta por cama, tipo y variable. |
| mensaje | texto | — | procesador | — | Texto que se muestra en la pantalla. |
| valor_inicial, valor_actual | decimal | la de la variable | procesador | — | Valor al abrir el aviso y el último valor. En `tendencia_secado` son las horas estimadas. |
| iniciada_en_utc, actualizada_en_utc, resuelta_en_utc | fecha y hora | UTC | procesador | — | Historial del aviso (HU-03). |

## `clima` — clima de referencia de la zona

Una instantánea por hora. Tabla `clima_referencia`; la vista `v_clima_hora` la agrupa por hora.

| Columna | Tipo | Unidad | Origen | Rango válido | Significado |
| --- | --- | --- | --- | --- | --- |
| fuente | texto | — | proveedor | `open-meteo` / `dmc` / `openweather` | Proveedor del dato. |
| observado_en_utc | fecha y hora | UTC | proveedor | — | Hora del dato. Open-Meteo entrega pasos de 15 min. |
| lat, lon | decimal | grados | configuración o estación | ±90 / ±180 | Ubicación consultada (en la DMC, la de la estación). |
| temp_aire_c | decimal | °C | proveedor | — | Temperatura del aire a 2 m. |
| hum_rel_pct | decimal | % | proveedor | 0 a 100 | Humedad relativa a 2 m. |
| precipitacion_mm | decimal | mm | proveedor | ≥ 0 | Lluvia (Open-Meteo: la de los 15 min anteriores; DMC: la de la última hora). |
| radiacion_wm2 | decimal | W/m² | proveedor | ≥ 0 | Radiación solar de onda corta. |
| temp_suelo_c | decimal | °C | modelo | — | Temperatura de la superficie del suelo (modelo). |
| hum_suelo_vwc_pct | decimal | % vol. | modelo | 0 a 100 | Contenido **volumétrico** de agua entre 0 y 1 cm (modelo). **No es comparable** con `suelo_pct`. |
| et0_mm | decimal | mm | proveedor | ≥ 0 | Evapotranspiración de referencia FAO de la hora. |
| et0_hoy_mm | decimal | mm | cálculo | ≥ 0 | ET0 acumulada desde la medianoche (hora de Chile). |

## Tablas internas (no se exportan)

| Tabla | Para qué |
| --- | --- |
| `configuracion_huerto` | Ajustes editables desde `/configuracion` (clima, tendencia y zona del huerto). Si falta un ajuste, se usa el del `.env`. |
| `zonas_climaticas` | Zonas `norte`, `centro` y `sur`, con su descripción. |
| `rangos_cultivo_zona` | Rango ideal de cada cultivo en cada zona. Son valores de **ejemplo** (`por_confirmar = 1`) que hay que confirmar con las fichas de INIA / INDAP. Una fila vacía significa que el cultivo usa su rango genérico en esa zona. |
| `v_camas_zona` (vista) | Zona efectiva de cada cama: la suya o, si no tiene, la del huerto (por defecto `centro`). También entrega el rango del cultivo en esa zona. Cada campo del rango de una cama se toma en este orden: **el de la cama, luego el del cultivo en la zona y por último el del cultivo genérico**. |
| `camas.cal_seco_mv`, `camas.cal_mojado_mv` | Calibración de la sonda de suelo en el servidor (migración 008), editable en `/configuracion`. Con los dos puntos, el % se calcula en el equipo central: `(seco − mV) × 100 / (seco − mojado)`, acotado a 0–100. Vacíos = se usa el % que envía la placa. `lecturas.suelo_detalle` siempre guarda el % de la placa tal como llegó. |
| `tiempos_tendencia` | CQ-13: cuánto tardó cada predicción (`duracion_ms`), con su estado, las horas estimadas, la pendiente y el R². |
| `luz_diaria` | Horas de luz por día y cama (HU-04). |
| `eventos_alerta`, `latencias_pantalla` | Mediciones de CQ-02 y CQ-03. |
| `heartbeats`, `conexiones_nodo`, `incidencias`, `cambios_estado` | Funcionamiento de los nodos y del tablero. |

# Documentación del prototipo Huerto Inteligente

**Proyecto smartYusChaMau · Prototipo 1**  
**Fecha de referencia:** 27 de noviembre de 2026 · **Versión del código:** `ba90b3d`

## 1. Propósito y alcance

Huerto Inteligente ayuda a estudiantes y docentes a decidir cuándo revisar o regar una cama de cultivo y a observar cómo cambian sus condiciones. El prototipo mide la humedad del suelo, la temperatura y la humedad del aire. Muestra las últimas mediciones en el huerto y en un tablero web, registra avisos cuando una cama sale del rango de su cultivo y conserva el historial para analizarlo en clase. El riego se realiza manualmente.

El sistema admite varias camas identificadas por nodo. El despliegue registrado corresponde a la cama A, que envía lecturas a un servidor. La portada presenta el piloto para la comunidad del Marcelino Champagnat de La Pintana. La validación en el colegio, con estudiantes, docentes y cultivos, sigue pendiente de documentarse. [Estado del despliegue](ESTADO_DESPLIEGUE.md) · [Portada](../central/web/web/templates/proyecto.html)

## 2. Uso del sitio

| Pantalla | Qué permite hacer |
| --- | --- |
| **Inicio** · `/` | Conocer el proyecto, probar una simulación del estado de una cama, acceder al tablero y contactar al equipo del piloto cuando el correo de contacto está configurado. |
| **Camas en vivo** · `/tablero` | Ver la humedad del suelo, la temperatura, la hora de medición y el estado de cada cama. También muestra avisos abiertos y resueltos durante el día, la tendencia de humedad y datos de clima exterior cuando están disponibles. |
| **Pantalla del huerto** · `/tablero?kiosco=1` | Mostrar el tablero en una pantalla compartida. Este modo registra cuándo una lectura o un aviso se hace visible, para medir los tiempos de respuesta. |
| **Ficha de cama** · `/cama/<id>` | Consultar gráficos de 24 horas, 7 o 30 días, resúmenes diarios, rangos ideales, avisos de los últimos 7 días y tendencia de humedad. Permite descargar lecturas en CSV por rango de fechas. |
| **Configuración** · `/configuracion/` | El docente entra con un PIN para administrar camas, cultivos, zonas y rangos, elegir el proveedor de clima exterior y configurar el cálculo de tendencia. También puede exportar conjuntos de datos para análisis. |

El monitoreo registra variables ambientales y funciona sin cuentas individuales de estudiantes. El formulario de contacto pide nombre, estamento y correo para preparar un mensaje en el cliente de correo de la persona. Esos datos se comparten con el equipo del piloto cuando la persona envía el mensaje. [Formulario del piloto](../central/web/web/static/js/landing.js) · [Rutas del tablero](../central/web/web/rutas_tablero.py) · [Historial](../central/web/web/rutas_historial.py)

## 3. Cómo funciona el prototipo

1. **Medición en la cama.** Un ESP32 lee la sonda resistiva YL-69 con módulo LM393 y el sensor DHT11 de temperatura y humedad del aire. La sonda de suelo entrega milivoltios y el firmware calcula un porcentaje a partir de dos puntos de calibración. El intervalo de envío de ejemplo es de 30 segundos.
2. **Información local.** La OLED SSD1306 del nodo muestra las mediciones disponibles incluso si se pierde la conexión. El LED azul parpadea cuando el nodo pierde comunicación con el equipo central y queda fijo cuando detecta humedad de suelo fuera de los límites configurados en el firmware.
3. **Envío y almacenamiento.** El nodo transmite lecturas JSON por Wi-Fi a `POST /api/lecturas`, con un token por nodo. Cada lectura lleva un número de secuencia y su hora de medición en UTC. El firmware conserva en memoria flash las lecturas con hora válida para reintentar el envío tras un corte de red. La capacidad de ejemplo es de 720 registros, equivalentes a seis horas con el intervalo configurado.
4. **Procesamiento y visualización.** La API Flask valida y guarda las lecturas en MariaDB, reconoce reenvíos duplicados y avisa al procesador por MQTT. El procesador calcula los avisos y el estado de la cama. El navegador recibe cambios en tiempo real mediante eventos del servidor y también consulta el tablero periódicamente. Una lectura atrasada válida queda en el historial y la lectura actual se elige por hora de medición.

El equipo central se ejecuta con Docker Compose y puede alojarse en la red local. En el despliegue registrado, el ESP32 envía por HTTPS directamente al VPS. El reloj del nodo usa NTP y la configuración de ejemplo apunta a servidores públicos. Antes de obtener la hora inicial, las lecturas pendientes quedan en RAM. [Montaje y operación](../README.md) · [Configuración del nodo](../firmware/nodo/config.example.h) · [API de lecturas](../central/web/web/rutas_api.py) · [Guía de despliegue](DESPLIEGUE_MJVIRTUAL.md)

## 4. Interpretación de las lecturas y los avisos

- **Humedad del suelo.** Una cama con cultivo configurado avisa por suelo seco o por exceso de agua. El aviso abierto se actualiza mientras persiste la condición y se resuelve cuando la medición se recupera según los márgenes de la regla. Los rangos personalizados de la cama tienen prioridad sobre los de su zona y los valores generales del cultivo. [Reglas de suelo](../central/procesador/procesador/reglas/suelo.py) · [Rangos efectivos](../central/comun/rangos.py)
- **Temperatura.** Una medición por debajo del mínimo del cultivo puede abrir un aviso de riesgo por frío. El aviso de calor exige superar el máximo durante 30 minutos por defecto, con lecturas suficientemente próximas. El DHT11 del montaje actual cubre de 0 a 50 °C, por lo que las temperaturas bajo cero quedan fuera de su rango de medición. [Reglas de temperatura](../central/procesador/procesador/reglas/temperatura.py) · [Sensor del prototipo](../README.md)
- **Estado de la cama.** El tablero usa verde cuando la cama configurada tiene datos y carece de avisos de rango abiertos, rojo cuando hay una condición por revisar y gris cuando falta información necesaria. Por defecto, el estado gris por falta de datos válidos se evalúa para suelo y temperatura con un umbral de dos horas. Una cama con lecturas pero sin cultivo muestra un mensaje para configurarlo. [Reglas de estado](../central/procesador/procesador/reglas/estado.py) · [Configuración central](../central/comun/config.py)
- **Luz.** El prototipo físico carece de sensor de luz y envía el campo vacío. Cuando un nodo aporta lecturas en lux, el software puede acumular horas sobre un umbral configurado y avisar si el cultivo recibe poca luz durante tres días consecutivos con cobertura suficiente. El tablero presenta las horas de hoy. La ficha grafica lux y el umbral de luz directa. [Envío del nodo](../firmware/nodo/envio.cpp) · [Cálculo de horas](../central/procesador/procesador/reglas/luz.py) · [Gráfico de luz](../central/web/web/static/js/cama.js)

## 5. Historial, tendencia y clima exterior

El sistema conserva las lecturas y los avisos con sus marcas de tiempo. Genera agregados por hora y por día y marca problemas de calidad como saltos bruscos, valores repetidos durante mucho tiempo y huecos. Las subidas bruscas de humedad permiten detectar posibles eventos de riego. Los archivos exportados sirven para comparar camas y estudiar cambios del suelo a lo largo del tiempo. [Diccionario de datos](diccionario_de_datos.md)

La tendencia describe si la humedad sube, se mantiene o baja. Con suficientes datos de un tramo de secado entre riegos, una regresión lineal estima cuánto falta para llegar al umbral mínimo de humedad. La ventana y el horizonte son de seis horas por defecto. La interfaz puede mostrar una tendencia sin estimar un tiempo hasta el umbral, por ejemplo, cuando el ajuste es insuficiente. El aviso preventivo asociado a la estimación está desactivado por defecto. [API de tendencia](../central/web/web/rutas_tendencia.py) · [Predicción](../central/comun/analitica/prediccion.py)

El sitio también compara las mediciones con las condiciones exteriores actuales. Open-Meteo es el proveedor predeterminado. La configuración admite DMC y OpenWeatherMap cuando se dispone de las credenciales correspondientes. El clima exterior es una referencia y la comparación depende de la disponibilidad del proveedor. [Clima de referencia](CLIMA_REFERENCIA.md)

## 6. Trazabilidad de requisitos

| Requisito original | Estado en el prototipo |
| --- | --- |
| **RF-01** Medir humedad del suelo | Implementado con la sonda YL-69. El registro del despliegue confirma el envío desde la cama A. |
| **RF-02** Calibrar y convertir a porcentaje | Implementada la conversión con dos referencias. En la cama A se registró saturación de la lectura al 100 %. La recalibración en suelo y la validación de exactitud siguen pendientes. |
| **RF-03** Medir temperatura y humedad del aire | Implementado con DHT11 dentro de su rango físico. |
| **RF-04** Medir luz y acumular horas diarias | Parcial. El procesador calcula horas con datos en lux. Falta incorporar el sensor al montaje y mostrar en la ficha una comparación explícita de horas con el requerimiento del cultivo. |
| **RF-05** Validar y limpiar lecturas | Implementados los controles de ingreso y las marcas de calidad para análisis. |
| **RF-06** Fechar y transmitir lecturas | Implementado con NTP, envío HTTP y reintentos. La prueba de recuperación ante un corte de una hora con hardware real queda pendiente. |
| **RF-07** Mostrar la última lectura | Implementado en el tablero y el modo kiosco. La OLED muestra la medición local del nodo. |
| **RF-08** Gestionar avisos fuera de rango | Implementada la apertura, actualización y resolución de avisos, con registro de inicio y término. La latencia en campo queda por medir. |
| **RF-09** Configurar cultivo y rangos | Implementado en el panel docente para cultivos, zonas y camas. Los valores de ejemplo deben ajustarse para el piloto. |
| **RF-10** Señalizar con un LED | Implementado con un LED azul para conectividad y humedad fuera de rango. La señalización RGB de las tres variables queda fuera del montaje actual. |
| **RF-11** Detectar un sensor sin datos | Implementado para suelo y temperatura en la configuración actual. Puede incluir luz cuando se instale el sensor y se habilite su seguimiento. |
| **RF-12** Mostrar el estado en tarjetas | Implementado con colores y mensajes en el tablero. La evaluación de comprensión con estudiantes queda pendiente. |
| **RF-13** Guardar historial en la nube con respaldo | El despliegue en VPS guarda el historial y registra un respaldo previo a la migración. La guía describe una tarea diaria de respaldo. La sincronización desde una base local hacia la nube queda pendiente. |
| **RF-14** Consultar historial y recibir avisos en el celular | Parcial. El historial y los avisos se pueden consultar en el sitio desde el navegador. Queda pendiente el envío de notificaciones móviles. |
| **RF-15** Estimar la tendencia y el tiempo hasta el umbral | Implementado en el tablero y en la ficha, sujeto a cobertura y calidad de las lecturas. Falta evaluar su desempeño con los datos del piloto. |

Las historias HU-01 y HU-02 se reflejan en la consulta de la última lectura, los avisos de humedad y la tendencia. HU-03 tiene cobertura dentro del rango del DHT11. HU-04 depende del sensor de luz en el nodo, y HU-05 opera con los dos tipos de medición requeridos en el montaje actual. [Historias y criterios originales](<Documentación Proyecto Huerto Inteligente.md>) · [Sincronización](../central/procesador/procesador/sincronizador.py)

## 7. Validación del piloto

| Criterios | Evidencia disponible y medición pendiente |
| --- | --- |
| **CQ-01 · Exactitud de humedad** | Hay calibración por dos puntos. Para evaluar el error medio de hasta 5 puntos porcentuales se requieren al menos 10 muestras de suelo comparadas con un método de referencia. |
| **CQ-02 y CQ-03 · Tiempos de respuesta** | El kiosco registra el momento visible. Con esas marcas se debe calcular el percentil 95 y contrastarlo con las metas de menos de 5 minutos para avisos y hasta 10 segundos para visualización. |
| **CQ-04 y CQ-05 · Disponibilidad y calidad de avisos** | Los registros permiten contar lecturas recibidas y revisar avisos. Las metas son recibir al menos el 95 % de las lecturas esperadas por cama, detectar al menos el 90 % de las condiciones reales y tener como máximo una falsa alarma por cama en la semana de prueba. La comparación requiere un registro docente de las condiciones observadas. |
| **CQ-06 · Detección de sensor sin datos** | El umbral por defecto es de 120 minutos y la detección se ejecuta periódicamente. Falta medir el tiempo hasta el cambio a gris al desconectar un sensor real. |
| **CQ-07 y CQ-08 · Recuperación y estabilidad** | El firmware dispone de almacenamiento temporal y reenvío. Quedan pendientes la prueba de un corte de Wi-Fi de una hora sin pérdida de lecturas y siete días de operación exterior sin reinicios inesperados. |
| **CQ-09 · Comprensión** | Las tarjetas combinan colores y mensajes. La meta del 80 % se verifica observando cuántos estudiantes interpretan correctamente el estado sin explicación previa. |
| **CQ-10 a CQ-13 · Desempeño de la tendencia** | Hay una herramienta de evaluación con ventana temporal deslizante, comparación con una tasa histórica de secado y registro de tiempos. Con datos reales se debe comprobar el error medio de hasta 2 horas, la mejora respecto de esa referencia y el tiempo de cálculo de hasta 1 segundo en el equipo objetivo. |

La validación educativa y operativa debe registrar una actividad de clase que use los datos y comparar el consumo de agua y el estado de los cultivos con una referencia acordada para el piloto. [Metas originales](<Documentación Proyecto Huerto Inteligente.md#5-criterios-de-calidad>) · [Herramienta de evaluación](../tools/evaluar_tendencia.py) · [Estado del despliegue](ESTADO_DESPLIEGUE.md)

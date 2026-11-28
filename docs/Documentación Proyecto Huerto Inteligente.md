# Documentación Proyecto Huerto Inteligente



## 1. Planteamiento del problema

### 1.1 Contexto

Los huertos escolares y comunitarios se usan como recurso pedagógico: permiten que los estudiantes aprendan ciencias, alimentación y trabajo en equipo de forma práctica. La revisión de Blair (2009) encontró que nueve de 12 estudios cuantitativos reportaron efectos positivos significativos en pruebas de rendimiento, incluidas las de ciencias, y que los estudios cualitativos asocian el huerto con mayor motivación, orgullo por la escuela y trabajo en equipo. La propia autora advierte limitaciones metodológicas en esa literatura.

Este proyecto se desarrolla para un colegio con huerto comunitario, aún por definir, que cuenta con acceso a internet. Los usuarios son los estudiantes que participan del cuidado del huerto y los docentes que lo coordinan.

### 1.2 Descripción del problema

El valor educativo de un huerto depende de que los cultivos sobrevivan y de que los estudiantes puedan aprender de lo que ocurre en él. En la práctica, la literatura sobre huertos escolares identifica barreras que amenazan ambas cosas:

- **Dependencia del conocimiento del docente.** En un estudio cualitativo en cuatro colegios de Gante (Bélgica), los responsables indicaron que el crecimiento de las plantas exige experiencia previa en jardinería o un esfuerzo de autoformación considerable (Huys et al., 2017).
- **Carga de trabajo.** Los docentes percibían el huerto como una carga que requiere cuidado durante todo el año, y las tareas se realizaban en recreos o en la hora de almuerzo (Huys et al., 2017).
- **Continuidad en períodos sin clases.** Muchos cultivos maduran en julio y agosto, cuando el colegio está cerrado, por lo que los colegios dependían de padres y docentes para mantenerlos (Huys et al., 2017). En Chile, las vacaciones de verano coinciden con la temporada de mayor crecimiento y demanda de riego; este punto debe confirmarse con el calendario escolar del colegio piloto.
- **Sostenibilidad del programa.** En una encuesta con 1.301 respuestas, 135 programas de huertos escolares habían sido discontinuados. Los desafíos más frecuentes, comunes a programas vigentes y discontinuados, fueron el financiamiento, la estabilidad del personal (dependencia de docentes sin capacitación), el apoyo de la comunidad, la planificación y preparación docente, y el mantenimiento (Yu, 2012).

A esto se suma el riego, la decisión más crítica del cultivo. La evidencia disponible proviene de cultivadores domésticos, por lo que es solo indirecta: entre quienes perdieron plantas, el 33 % lo atribuyó al exceso de agua y el 32 % a su falta (<http://Trees.com> , 2022), y la extensión universitaria señala que el riego inadecuado es la principal causa de muerte de plantas en maceta (UConn Extension). El mismo error se comete en dos sentidos opuestos, por lo que solo la medición de la humedad real del suelo permite decidir.

Finalmente, se asume que el huerto se maneja hoy por observación directa, sin un registro sistemático de humedad, temperatura y luz. Este supuesto debe confirmarse con un diagnóstico en el colegio piloto. Si es correcto, no existen datos objetivos ni para decidir con oportunidad ni para que los estudiantes analicen y comparen.

### 1.3 Población afectada

| Grupo | Situación |
| --- | --- |
| Estudiantes | Participan del cuidado del huerto como parte de su aprendizaje, pero sin datos que relacionen sus decisiones con el estado del cultivo. |
| Docentes responsables | Coordinan el huerto junto a su carga docente y no necesariamente tienen formación agrícola. |
| Comunidad escolar | Directivos, apoderados y personal de apoyo que aportan recursos y, en períodos sin clases, ayudan a mantener el huerto. |

### 1.4 Impacto

- **Pedagógico:** se pierde la oportunidad de enseñar a observar, medir y comparar con datos reales, y la experiencia queda reducida a tareas sin retroalimentación.
- **Operativo:** pérdida de cultivos por riego inadecuado, heladas, calor o abandono en vacaciones, y mayor esfuerzo para los docentes.
- **Uso de recursos:** se desperdicia agua al regar sin saber si el suelo lo necesita.
- **Continuidad:** la frustración y la carga de trabajo aumentan el riesgo de discontinuar el programa, como ocurrió en parte de los casos de la encuesta de Yu (2012).

### 1.5 Enunciado de la problemática

Los huertos escolares comunitarios carecen de información objetiva, oportuna y comprensible sobre la humedad del suelo, la temperatura y la luz de sus cultivos. Esta carencia obliga a docentes y estudiantes a decidir por intuición, genera pérdidas evitables de plantas y de agua, desaprovecha el potencial educativo de los datos y pone en riesgo la continuidad del programa, sobre todo en períodos sin clases.

## 2. Objetivos del proyecto

### 2.1 Objetivo general

Desarrollar un sistema IoT de bajo costo que monitoree la humedad del suelo, la temperatura y la luz de las camas de un huerto escolar comunitario, y entregue a estudiantes y docentes datos y alertas comprensibles que apoyen el cuidado del huerto y su uso como herramienta de aprendizaje.

### 2.2 Objetivos específicos

1. Medir la humedad del suelo, la temperatura y la luz en cada cama de cultivo mediante nodos ESP32 con sensores de bajo costo.
2. Mostrar el estado actual de cada cama en tiempo real, en una pantalla ubicada en el huerto, con un lenguaje comprensible para los estudiantes del colegio.
3. Generar alertas oportunas, en menos de 5 minutos, cuando una variable salga del rango ideal del cultivo, con rangos configurables según el cultivo y la zona climática del colegio, y sin duplicar avisos mientras la condición persista.
4. En una segunda iteración, almacenar el historial de lecturas y alertas en la nube y habilitar su consulta, junto con alertas en dispositivos móviles, para el seguimiento de tendencias y la atención del huerto en períodos sin clases.
5. Validar el prototipo en el colegio piloto, evaluando el consumo de agua, el estado de los cultivos y el uso de los datos por parte de estudiantes y docentes.

### 2.3 Criterios de éxito

| Indicador | Criterio |
| --- | --- |
| Disponibilidad del dato | Cada cama muestra su última lectura con hora de medición, o el aviso "Sin lecturas" si no existen datos. |
| Oportunidad de alertas | Aviso de humedad o temperatura fuera de rango en menos de 5 minutos desde la lectura. |
| Comprensibilidad | Un estudiante interpreta el estado de cada cama (verde, rojo o gris) sin explicación técnica previa. |
| Uso educativo | Al menos una actividad de clase planificada junto al docente que use los datos del huerto; la meta se acordará con el colegio. |
| Impacto en el huerto piloto | Comparación del consumo de agua y del estado de los cultivos; las metas numéricas se definirán antes de la prueba. |

## 3. Alcance del proyecto

El alcance corresponde a un primer prototipo funcional para un huerto escolar comunitario, en un colegio por definir que cuenta con acceso a internet. Los usuarios son los estudiantes que cuidan el huerto y los docentes que lo coordinan. La priorización usa el método MoSCoW y se centra en tres variables: humedad del suelo, temperatura y luz. La humedad tiene prioridad máxima porque el riego es la decisión más crítica del cultivo.

### 3.1 Alcance incluido

| ID | Funcionalidad | Variable | Prioridad |
| --- | --- | --- | --- |
| HU-01 | Consultar la última lectura de humedad del suelo de cada cama, con su hora de medición. | Humedad | Must have |
| HU-02 | Alerta de suelo seco o encharcado cuando la humedad sale del rango ideal de la cama, en menos de 5 minutos y sin duplicar avisos. Además consultar calculo de tendencia. | Humedad | Must have |
| HU-03 | Alerta de temperatura extrema (helada o calor excesivo) según el rango del cultivo, con historial de inicio y término. | Temperatura | Should have |
| HU-04 | Horas de luz directa diarias por cama, comparadas con el requerimiento del cultivo. | Luz | Should have |
| HU-05 | Estado general de cada cama de un vistazo (verde, rojo o gris), integrando las tres variables. | Las tres | Could have |

El desarrollo se divide en dos iteraciones:

- **Iteración 1, visualización local.** Nodos ESP32 por cama con sensores de bajo costo, que envían lecturas y alertas simples a una pantalla ubicada en el huerto y muestran el estado en tiempo real. Funciona sin depender de internet.


- **Iteración 2, historial y alertas móviles.** Base de datos en la nube con limpieza de datos y respaldo, consulta de tendencias y alertas en dispositivos móviles para los docentes.

### 3.2 Alcance excluido (Won't have en esta versión)

- Medición de pH del suelo.
- Pronóstico del tiempo para planificar el riego.
- Riego automático (el sistema informa, pero no acciona el riego).
- Detección de plagas por imagen.
- Diseño de planificaciones didácticas o evaluación del aprendizaje de los estudiantes: el proyecto entrega los datos, no el contenido curricular.
- Cuentas o perfiles individuales de estudiantes: el sistema solo registra variables ambientales y no recopila datos personales.

Estas funcionalidades quedan como líneas de evolución para una etapa posterior.

### 3.3 Supuestos y restricciones

- El colegio piloto, su zona climática y sus cultivos están por definir. Los rangos ideales de temperatura, humedad y luz (por ejemplo, 15 °C a 30 °C y 6 h o más de luz para el tomate) son valores de ejemplo y deben confirmarse con fichas de cultivo de INIA o INDAP y ajustarse a la zona.
- El colegio cuenta con acceso a internet, necesario solo a partir de la iteración 2.
- La validación se limita a un colegio; los resultados no son extrapolables sin pruebas adicionales.
- Los períodos sin clases (fines de semana y vacaciones) dejan el huerto sin supervisión directa. La iteración 1 no los cubre, porque la pantalla solo sirve si hay alguien presente; las alertas móviles de la iteración 2 son la mitigación prevista.
- Los equipos quedan expuestos a lluvia, polvo, sol y manipulación por parte de los estudiantes, por lo que requieren protección física y una fuente de energía confiable en el sitio.

### 3.4 Próximos pasos

1. Definir el colegio piloto: zona climática, calendario escolar, conectividad, energía y ubicación de la pantalla.
2. Acordar con el docente responsable los cultivos, los rangos ideales y el nivel de lectura esperado de los estudiantes.
3. Prototipar el nodo de humedad.
4. Probar el sistema en el huerto piloto.
5. Medir el consumo de agua, el estado de los cultivos y el uso educativo de los datos.

## 4. Historias de usuario

Se mantienen las cinco historias priorizadas del planteamiento original, adaptadas al contexto escolar con dos roles: el **estudiante del equipo del huerto** y el **docente informatico responsable**. En la iteración 1 los avisos y lecturas se muestran en la pantalla del huerto; desde la iteración 2 los avisos también llegan al celular del docente. Los rangos y valores de los ejemplos son ilustrativos.

| ID | Historia | Rol | Variable | Prioridad |
| --- | --- | --- | --- | --- |
| HU-01 | Consultar la humedad del suelo | Estudiante / Docente Informatico | Humedad | Must have |
| HU-02 | Alerta de suelo seco o encharcado | Docente Informatico | Humedad | Must have |
| HU-03 | Alerta de temperatura extrema | Docente Informatico | Temperatura | Should have |
| HU-04 | Consultar horas de luz de cada cama | Estudiante / Docente Informatico | Luz | Should have |
| HU-05 | Estado general de la cama de un vistazo | Estudiante / Docente Informatico | Las tres | Could have |

### HU-01 · Consultar la humedad del suelo (Must have)

**Rol:** estudiante del equipo del huerto y docente.

**Necesidad:** quiero ver en la pantalla del huerto la última lectura de humedad del suelo de cada cama.

**Beneficio:** así decido si regar según el estado real del suelo y no a ojo, y aprendo a relacionar el dato con lo que observo en la planta.

**Criterios de aceptación**

1. Si el sensor de la cama A registra 28 % a las 09:00, la pantalla muestra «28 % de humedad», la cama A y la hora de medición.
2. Si a las 09:05 llega una lectura tomada a las 08:55, la pantalla mantiene como actual la de las 09:00; la anterior queda guardada para el historial (disponible desde la iteración 2).
3. Si la cama aún no tiene mediciones, la pantalla muestra «Sin lecturas» y deja vacío el valor de humedad.

**Fundamento:** el riego inadecuado es una causa principal de pérdida de plantas; entre quienes las perdieron, el 33 % lo atribuye al exceso y el 32 % a la falta de riego (<http://Trees.com> , 2022; evidencia indirecta, de cultivadores domésticos).

### HU-02 · Alerta de suelo seco o encharcado (Must have)

**Rol:** docente responsable del huerto.

**Necesidad:** quiero recibir un aviso cuando la humedad de una cama esté bajo o sobre su rango ideal.

**Beneficio:** así intervengo a tiempo, evito que la planta se seque o se riegue de más y no tengo que revisar cada cama a diario.

**Criterios de aceptación**

1. Si la cama B tiene un rango de 30 % a 70 % y a las 14:00 registra 22 %, aparece el aviso «Cama B seca: 22 % (ideal 30 % a 70 %)» en menos de 5 minutos.
2. Si a las 16:00 la cama B registra 85 %, aparece el aviso «Cama B con exceso de agua: 85 %. No riegues hoy».
3. Si la cama B sigue bajo 30 % a las 14:30, no se muestra un segundo aviso: la alerta abierta se actualiza con el nuevo valor.

**Uso educativo:** la alerta puede usarse en clase para que los estudiantes expliquen por qué el suelo quedó fuera de rango y qué acción corresponde.

**Fundamento:** la extensión universitaria señala que el riego inadecuado es la principal causa de muerte de plantas en maceta y que quienes tienen poca experiencia tienden a seguir regando (UConn Extension). Por eso la alerta cubre los dos extremos.

### HU-03 · Alerta de temperatura extrema (Should have)

**Rol:** docente responsable del huerto.

**Necesidad:** quiero recibir un aviso cuando la temperatura de una cama esté fuera del rango que tolera su cultivo.

**Beneficio:** así puedo proteger la planta a tiempo (taparla, moverla o darle sombra) ante una helada o un calor excesivo.

**Criterios de aceptación**

1. Si la cama A tiene «Tomate» (rango 15 °C a 30 °C) y a las 06:00 registra 4 °C, aparece el aviso «Riesgo de helada en cama A: 4 °C. Cubre la planta» en menos de 5 minutos.
2. Si a las 15:00 la cama A registra 36 °C durante más de 30 minutos seguidos, aparece el aviso «Calor excesivo en cama A: 36 °C. Dale sombra y revisa la humedad».
3. Si la temperatura vuelve al rango, la alerta se marca como resuelta y queda registrada con su hora de inicio y término.

**Nota:** el rango del tomate es un valor de ejemplo; debe confirmarse con la ficha de cultivo de INIA o INDAP y ajustarse a la zona climática del colegio.

### HU-04 · Horas de luz de cada cama (Should have)

**Rol:** estudiante del equipo del huerto y docente encargado.

**Necesidad:** quiero saber cuántas horas de luz directa recibe cada cama al día y si alcanza lo que necesita su cultivo.

**Beneficio:** así puedo elegir la mejor ubicación para cada planta, o cambiar de cultivo si el lugar es muy sombrío, y comprobar con datos mis hipótesis sobre la luz.

**Criterios de aceptación**

1. Al final de cada día, la ficha de la cama B muestra las horas de luz directa registradas (por ejemplo, «5,5 h de luz directa hoy»), contando las lecturas sobre el umbral del sensor.
2. Si la cama B tiene «Tomate» (necesita 6 h o más) y registra menos de 6 h durante 3 días seguidos, aparece el aviso «Cama B recibe poca luz para tomate. Considera moverla o elegir un cultivo de sombra, como lechuga».
3. Si el sensor de luz no envía lecturas durante el día, la ficha muestra «Sin datos de luz hoy» en lugar de 0 h.

**Nota:** el criterio de 3 días consecutivos requiere conservar el total diario de luz; si no está disponible en la iteración 1, se entrega con el historial de la iteración 2.

### HU-05 · Estado general de la cama de un vistazo (Could have)

**Rol:** estudiante del equipo del huerto y docente encargado.

**Necesidad:** quiero ver en una sola pantalla la humedad, la temperatura y la luz de cada cama, con un indicador simple de si está bien o necesita atención.

**Beneficio:** así entiendo en segundos cómo está el huerto sin interpretar números, y el equipo puede hacer una ronda de revisión diaria rápida.

**Criterios de aceptación**

1. Si las tres variables de la cama A están dentro de su rango, la tarjeta se muestra en verde con el texto «Todo bien».
2. Si una o más variables están fuera de rango, la tarjeta cambia a rojo e indica cuál es (por ejemplo, «Revisar: humedad 22 %»).
3. Si alguno de los tres sensores lleva más de 2 horas sin enviar datos, la tarjeta se muestra en gris con «Sensor de temperatura sin conexión», en lugar de verde o rojo.

**Uso educativo:** la tarjeta de estado permite que el grupo conecte lo que ve en el huerto con lo que miden los sensores y registre sus observaciones en clase.


## 5. Criterios de calidad

Estos criterios complementan los de la sección 2.3 con métricas medibles en el contexto del proyecto. Las metas son propuestas y deben acordarse con el profesor antes de la validación.

| ID | Criterio | Métrica | Meta propuesta | Cómo se mide |
| --- | --- | --- | --- | --- |
| CQ-01 | Exactitud de la humedad | Error absoluto medio (MAE) entre el valor del sensor calibrado y una referencia | ≤ 5 puntos porcentuales | Comparación con un método de referencia (por ejemplo, pesaje de muestras de suelo) en al menos 10 muestras con distintos niveles de humedad |
| CQ-02 | Tiempo de respuesta de alertas | Tiempo entre la lectura fuera de rango y el aviso visible (percentil 95) | \< 5 minutos | Marcas de tiempo de la lectura y del aviso en el registro del sistema |
| CQ-03 | Latencia de visualización | Tiempo entre la medición y su aparición en la pantalla (percentil 95) | ≤ 10 segundos | Marcas de tiempo del nodo y de la pantalla |
| CQ-04 | Disponibilidad de datos | Lecturas recibidas sobre lecturas esperadas, por cama | ≥ 95 % en la semana de prueba | Conteo de lecturas en el registro del equipo central |
| CQ-05 | Calidad de las alertas | Falsas alarmas por cama por semana y proporción de condiciones reales detectadas | ≤ 1 falsa alarma; ≥ 90 % detectadas | Comparación con el registro manual del docente durante la prueba |
| CQ-06 | Detección de sensor sin conexión | Tiempo hasta marcar la cama en gris | ≤ 2 horas (criterio de HU-05) | Desconexión provocada de un sensor |
| CQ-07 | Recuperación ante cortes de red | Lecturas perdidas tras un corte | 0 lecturas perdidas en cortes de hasta 1 hora | Corte provocado del WiFi y comparación de lecturas antes y después |
| CQ-08 | Estabilidad del nodo | Funcionamiento continuo sin reinicios inesperados | ≥ 7 días en exterior | Registro de reinicios del ESP32 durante la prueba |
| CQ-09 | Comprensibilidad | Proporción de estudiantes que interpreta correctamente el estado de una cama sin explicación previa | ≥ 80 % (tamaño del grupo por definir) | Prueba breve con estudiantes del colegio |

### 5.1 Desempeño del modelo predictivo

El prototipo no incluye un modelo de aprendizaje automático. El único componente predictivo previsto es la estimación del tiempo que falta para que una cama llegue a su umbral de humedad, calculada con una regresión lineal sobre las últimas horas de lecturas entre riegos. Si se incorpora, se evaluará con estas métricas, y si el curso exige un modelo más complejo, se aplican las mismas métricas y la misma validación.

| ID | Criterio | Métrica | Meta propuesta | Cómo se mide |
| --- | --- | --- | --- | --- |
| CQ-10 | Error de la predicción | Error absoluto medio (MAE) del tiempo estimado hasta el umbral, con horizonte de 6 horas | ≤ 2 horas | Comparación entre el tiempo predicho y el tiempo real observado |
| CQ-11 | Mejora sobre una referencia simple | MAE del modelo frente al de una regla ingenua (tasa de secado promedio histórica constante) | El modelo debe superar a la referencia | Mismos datos de evaluación para ambos |
| CQ-12 | Validación correcta | División de los datos por tiempo, sin mezclar el futuro con el entrenamiento | Evaluación con ventana deslizante | Las lecturas posteriores al momento predicho nunca se usan para ajustar el modelo |
| CQ-13 | Tiempo de cálculo | Tiempo de cálculo de una predicción en el equipo central | ≤ 1 segundo | Medición en el Raspberry Pi |

Las predicciones solo se calculan sobre tramos de secado entre riegos; un salto brusco de humedad reinicia la ventana. Las primeras semanas habrá pocos datos, por lo que la evaluación del modelo se hará al cierre del piloto.

## 6. Matriz de trazabilidad

La matriz relaciona cada requisito funcional (RF) con la historia de usuario que lo origina, los componentes que lo implementan, la iteración en que se entrega y la forma de verificarlo. Todas las historias están cubiertas por al menos un requisito, y todos los requisitos por al menos un componente. Todos los componentes están por desarrollar.

Los componentes siguen la arquitectura vigente: un nodo ESP32 por cama (sensores de suelo, ADS1115, BH1750, BME280, LED RGB y firmware), un equipo central en el huerto (broker MQTT, procesamiento y alertas, base de datos local, tablero web y pantalla LED) y, en la iteración 2, la nube (sincronizador, API, limpieza de datos, base de datos histórica y respaldo) con la app móvil y el dashboard web.

| RF | Requisito funcional | Historia | Verificación | Estado |
| --- | --- | --- | --- | --- |
| RF-01 | Medir la humedad del suelo de cada cama | HU-01, HU-02 | CQ-01 | Por desarrollar |
| RF-02 | Calibrar los sensores y convertir la lectura a porcentaje | HU-01 | CQ-01 | Por desarrollar |
| RF-03 | Medir temperatura y humedad del aire | HU-03, HU-05 | HU-03, criterios 1 y 2 | Por desarrollar |
| RF-04 | Medir la luz y acumular las horas de luz directa del día | HU-04 | HU-04, criterios 1 a 3 | Por desarrollar |
| RF-05 | Validar y limpiar las lecturas | HU-01 | HU-01, criterio 2 | Por desarrollar |
| RF-06 | Estampar la hora de medición y transmitir al equipo central | HU-01 | HU-01, criterio 2; CQ-03; CQ-07 | Por desarrollar |
| RF-07 | Mostrar la última lectura de cada cama en la pantalla | HU-01 | HU-01, criterios 1 y 3; CQ-03 | Por desarrollar |
| RF-08 | Generar alertas fuera de rango, sin duplicarlas y marcándolas como resueltas | HU-02, HU-03 | HU-02 y HU-03; CQ-02; CQ-05 | Por desarrollar |
| RF-09 | Configurar cultivo y rangos ideales por cama | HU-02 a HU-05 (requisito habilitante, sin historia propia) | Prueba de cambio de rango en una cama | Por desarrollar |
| RF-10 | Señalizar el estado de la cama con un LED | HU-05 | HU-05, criterios 1 y 2 | Por desarrollar |
| RF-11 | Detectar y mostrar un sensor sin conexión | HU-05 | HU-05, criterio 3; CQ-06 | Por desarrollar |
| RF-12 | Mostrar el estado general de cada cama en tarjetas | HU-05 | HU-05, criterios 1 a 3; CQ-09 | Por desarrollar |
| RF-13 | Guardar el historial en la nube con respaldo | HU-01 y HU-03 (historial y registro) | CQ-04; CQ-07 | Por desarrollar |
| RF-14 | Consultar el historial y recibir alertas en el celular | HU-02, HU-03 | HU-02 y HU-03 en celular; CQ-02 | Por desarrollar |
| RF-15 | Estimar la tendencia de humedad y el tiempo hasta el umbral | Historia propuesta de tendencia (Could, aún no incorporada) | CQ-10 a CQ-13 | Por desarrollar |

RF-09 y RF-15 no se originan en las cinco historias actuales; RF-09 es necesario para que las alertas funcionen y RF-15 depende de que se incorpore la historia de tendencia.


## Fuentes y limitaciones

La evidencia citada proviene de EE. UU. y Bélgica; no se encontró evidencia chilena equivalente, por lo que el diagnóstico en el colegio piloto debe confirmar estas barreras. Blair advierte limitaciones metodológicas en la literatura; la encuesta de Yu es voluntaria y se difundió por una lista de educadores; el estudio de Huys cubre cuatro colegios urbanos o periurbanos con baja tasa de respuesta (14,7 %); y la encuesta de <http://Trees.com>  es comercial y de cultivadores domésticos, por lo que se usa solo como evidencia indirecta.

1. Blair, D. (2009). [The child in the garden: an evaluative review of the benefits of school gardening](https://eepro.naaee.org/research/eeresearch/child-garden-evaluative-review-benefits-school-gardening). *Journal of Environmental Education*, 40(2).
2. Yu, F. (2012). [School garden sustainability: major challenges to the long-term maintenance and success of school garden programs](https://udspace.udel.edu/items/5bdc9007-8b94-479d-8108-2f0f8a736f7a). Universidad de Delaware (tesis de maestría).
3. Huys, N. et al. (2017). [School gardens: a qualitative study on implementation practices](https://research.usq.edu.au/download/d4890a01d5891d263e573d88976746b6bfdeee924e27ce65ccb53186086fde25/289504/Huys_etal_2017_SchoolGardens_IJERPH.pdf). *International Journal of Environmental Research and Public Health*, 14, 1454.
4. <http://Trees.com> , encuesta a 1.250 adultos de EE. UU., vía PRWeb (2022). Cifra tomada de la presentación del proyecto.
5. UConn Extension: *Houseplant Watering Recommendations*. Referencia tomada de la presentación del proyecto.

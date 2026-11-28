# Capa de clima exterior de referencia

## Qué es

El tablero muestra, junto a cada cama, el clima de la zona del colegio: temperatura del aire, humedad
relativa, radiación solar, lluvia y la evapotranspiración de referencia (ET0). Por defecto los datos
vienen de Open-Meteo para la zona sur de Santiago (San Ramón / La Pintana, lat −33,54, lon −70,64).
El docente puede cambiar la ubicación y el proveedor en la configuración.

Es una capa de **referencia de las condiciones actuales**, no un pronóstico. El pronóstico del tiempo
sigue fuera del alcance del proyecto (sección 3.2). Las lecturas, el estado de las camas y las alertas
**no dependen** de esta capa: sin internet, el tablero se ve igual y solo indica «Clima exterior no
disponible» o «Dato de hace 2 h».

Cómo funciona:

- Solo el equipo central consulta la API externa. El navegador nunca la llama y las claves no salen
  del servidor.
- El tablero guarda el último dato durante 20 minutos.
- El procesador guarda una instantánea por hora en la tabla `clima_referencia`. Con ella se grafican
  las diferencias en el tiempo, no solo en el momento actual.
- Cada lectura se compara con la instantánea más cercana a la hora en que se midió, con un máximo de
  60 minutos de diferencia. Si no hay ninguna dentro de ese margen, no se muestra la diferencia.

## Cómo se compara

| Variable | Qué se muestra | Por qué |
| --- | --- | --- |
| Temperatura del aire | La diferencia (cama − exterior), por ejemplo «+3 °C más que afuera». Si es menor a 2 °C: «similar al exterior». | El DHT11 tiene un error de ±2 °C: una diferencia menor no se puede distinguir del error del sensor. |
| Humedad relativa | La diferencia en puntos. Si es menor a 5 puntos: «similar al exterior». | Es el error del DHT11 para la humedad. |
| Humedad del suelo | **No se calcula diferencia.** Solo se muestra «Suelo de la zona (modelo): X % vol.». | Ver la sección siguiente. |
| ET0 | «La zona perdió X mm de agua hoy por evaporación». | Es un dato informativo para decidir el riego. |

Cuando la cama está 5 °C o más sobre el exterior con sol fuerte, aparece una sugerencia: «Posible
acumulación de calor: revisa sombra y ventilación». Es solo un texto: no crea alertas nuevas.

## Por qué la humedad del suelo no se compara directo

Los dos porcentajes miden cosas distintas:

- **El % de la cama** es una escala calibrada de la sonda resistiva YL-69: 0 % es la sonda en aire
  seco y 100 % es la sonda en agua. Indica si el suelo está más seco o más húmedo que en la
  calibración, pero no dice cuánta agua hay.
- **El % de la zona** es el contenido volumétrico de agua (m³ de agua por m³ de suelo, entre 0 y
  1 cm de profundidad). Lo calcula un modelo meteorológico para una celda de varios kilómetros, sin
  conocer el suelo de la cama ni sus riegos.

Restar los dos valores daría un número sin significado. Por eso el dato de la zona se muestra al lado
del de la cama, solo como referencia: sirve para ver si la zona está en un período seco o lluvioso.

## Relación con las historias de usuario y el objetivo educativo

- **HU-02 (suelo seco o encharcado):** la ET0 y la lluvia de la zona ayudan a interpretar la alerta.
  Por ejemplo, una cama que se seca rápido en un día de ET0 alta es esperable. La capa se integrará
  con el cálculo de tendencia que pide la HU-02.
- **HU-03 (temperatura extrema):** comparar la cama con el exterior separa un problema del lugar
  (calor acumulado por falta de sombra o ventilación) de un día caluroso en toda la zona.
- **Objetivo educativo:** los estudiantes comparan datos **medidos** con datos **de la zona**. En
  clase pueden discutir:
  - por qué los valores no coinciden: el microclima de la cama, el error del sensor y lo que mide
    realmente cada instrumento;
  - por qué dos porcentajes con el mismo nombre no siempre se pueden restar.

## Proveedores

| Proveedor | Clave | Datos |
| --- | --- | --- |
| Open-Meteo (por defecto) | No necesita | Temperatura, humedad, lluvia, radiación, suelo (modelo) y ET0 |
| DMC, estación automática (EMA) | `DMC_USER_EMAIL` + `DMC_API_TOKEN` | Temperatura, humedad, lluvia y radiación de la estación elegida |
| OpenWeatherMap (Current Weather) | `OPENWEATHER_API_KEY` | Temperatura, humedad y lluvia |

Si falta la clave de un proveedor, este aparece como «no configurado», sin errores. El adaptador de la
DMC sigue el formato de su documentación oficial, pero falta probarlo con un token real.

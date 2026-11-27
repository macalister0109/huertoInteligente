/* Detalle de cama: gráficos de las últimas 24 h con la franja ideal sombreada. */
"use strict";

(() => {
  const H = Huerto;
  const camaId = document.body.dataset.camaId;
  const RECARGA_MS = 60_000;
  const COLORES = { suelo: "#1a56b0", temp: "#c4570c", luz: "#a87a00", ideal: "rgba(27, 122, 54, 0.16)", borde: "rgba(27, 122, 54, 0.7)" };
  const graficos = {};

  Chart.defaults.font.size = 15;
  Chart.defaults.color = "#222";
  Chart.defaults.animation = false;

  function lineaHorizontal(etiqueta, y, desde, hasta, extra = {}) {
    return {
      label: etiqueta, data: [{ x: desde, y }, { x: hasta, y }],
      borderColor: COLORES.borde, borderWidth: 2, borderDash: [8, 5], pointRadius: 0, fill: false, ...extra,
    };
  }

  function conjuntos({ datos, clave, etiqueta, color, minimo, maximo, desde, hasta, referencia }) {
    const lista = [];
    if (minimo !== null && maximo !== null) {
      // Franja ideal: la línea del máximo se rellena hasta la del mínimo
      lista.push(lineaHorizontal("Rango ideal", maximo, desde, hasta, { fill: "+1", backgroundColor: COLORES.ideal }));
      lista.push(lineaHorizontal("_min", minimo, desde, hasta));
    } else if (minimo !== null) {
      lista.push(lineaHorizontal("Mínimo ideal", minimo, desde, hasta));
    } else if (maximo !== null) {
      lista.push(lineaHorizontal("Máximo ideal", maximo, desde, hasta));
    }
    if (referencia) lista.push(lineaHorizontal(referencia.etiqueta, referencia.valor, desde, hasta, { borderColor: COLORES.luz }));
    lista.push({
      label: etiqueta, data: datos.map((p) => ({ x: p.t, y: p[clave] })),
      borderColor: color, backgroundColor: color, borderWidth: 3, pointRadius: 0,
      spanGaps: false, tension: 0.2,
    });
    return lista;
  }

  function dibujar(id, opciones, unidad) {
    const datasets = conjuntos(opciones);
    if (graficos[id]) {
      graficos[id].data.datasets = datasets;
      graficos[id].options.scales.x.min = opciones.desde;
      graficos[id].options.scales.x.max = opciones.hasta;
      graficos[id].update("none");
      return;
    }
    graficos[id] = new Chart(document.getElementById(id), {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        scales: {
          x: {
            type: "linear", min: opciones.desde, max: opciones.hasta,
            ticks: { maxTicksLimit: 7, callback: (v) => H.hora(new Date(v).toISOString()) },
          },
          y: { ticks: { callback: (v) => `${H.entero(v)} ${unidad}` } },
        },
        plugins: {
          legend: { labels: { filter: (item) => !item.text.startsWith("_") } },
          tooltip: {
            filter: (item) => item.dataset.label === opciones.etiqueta,
            callbacks: {
              title: (items) => (items.length ? H.hora(new Date(items[0].parsed.x).toISOString()) : ""),
              label: (item) => `${opciones.etiqueta}: ${H.entero(item.parsed.y)} ${unidad}`,
            },
          },
        },
      },
    });
  }

  async function cargar() {
    let datos;
    try {
      datos = await H.obtenerJson(`/api/camas/${camaId}/serie?horas=24`);
      H.avisoConexion("");
    } catch (e) {
      H.avisoConexion("Sin conexión con el equipo central. Reintentando…");
      return;
    }
    const desde = Date.parse(datos.desde);
    const hasta = Date.parse(datos.hasta);
    const r = datos.rango;
    const base = { datos: datos.puntos, desde, hasta };

    dibujar("grafico-suelo", { ...base, clave: "suelo", etiqueta: "Humedad del suelo", color: COLORES.suelo,
      minimo: r.humedad_min, maximo: r.humedad_max }, "%");
    dibujar("grafico-temp", { ...base, clave: "temp", etiqueta: "Temperatura", color: COLORES.temp,
      minimo: r.temp_min, maximo: r.temp_max }, "°C");
    dibujar("grafico-luz", { ...base, clave: "lux", etiqueta: "Luz", color: COLORES.luz,
      minimo: null, maximo: null,
      referencia: { etiqueta: `Luz directa (sobre ${H.entero(datos.umbral_luz)} lux)`, valor: datos.umbral_luz } }, "lux");

    H.dibujarAvisos(document.getElementById("avisos-cama"), datos.alertas,
      "Sin avisos en los últimos 7 días.", false);
  }

  cargar();
  setInterval(cargar, RECARGA_MS);
})();

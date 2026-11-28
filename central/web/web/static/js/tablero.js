/* Tablero principal: una tarjeta por cama, actualizada en tiempo real (SSE).
 *
 * En la pantalla del huerto se abre con ?kiosco=1. Solo en ese modo se
 * miden las latencias (CQ-02 y CQ-03), porque el navegador usa el reloj de
 * la Raspberry Pi, el mismo que reparte la hora a los nodos.
 */
"use strict";

(() => {
  const H = Huerto;
  const KIOSCO = document.body.dataset.kiosco === "1";
  const RECARGA_MS = 60_000;
  const RECARGA_CLIMA_MS = 5 * 60_000;
  // clima.js es opcional: si no cargó, las tarjetas se ven igual que siempre
  const Clima = typeof HuertoClima === "undefined" ? null : HuertoClima;

  const contenedor = document.getElementById("camas");
  const listaAbiertos = document.getElementById("avisos-abiertos");
  const listaResueltos = document.getElementById("avisos-resueltos");

  const tarjetas = new Map();      // nodo_id -> datos de la tarjeta
  const ultimoSeq = new Map();     // nodo_id -> seq ya mostrado (para medir latencia una vez)
  const avisosConfirmados = new Set();
  const comparaciones = new Map(); // nodo_id -> comparación con el exterior (o null)
  const tendencias = new Map();    // nodo_id -> {etiqueta, estimacion}
  const FLECHA = { "Secándose rápido": "↘↘", "Secándose lento": "↘", "Estable": "→", "Subiendo": "↗" };

  const ICONO = { verde: "✔", rojo: "!", gris: "?", sin_configurar: "⚙" };

  // ------------------------------------------------------------ tarjetas

  function valor(etiqueta, numero, unidad, textoSinDato = "Sin dato") {
    const sinDato = numero === null || numero === undefined;
    return H.el("div", {},
      H.el("dt", {}, etiqueta),
      H.el("dd", { class: sinDato ? "sin-dato" : null }, sinDato ? textoSinDato : `${numero} ${unidad}`));
  }

  function textoLuz(t) {
    if (t.horas_luz_hoy !== null && t.horas_luz_hoy !== undefined) return [H.decimal(t.horas_luz_hoy), "h"];
    return [null, null, t.texto_luz || "—"];
  }

  function crearTarjeta(t) {
    const l = t.lectura;
    const [luz, unidadLuz, sinLuz] = textoLuz(t);
    const pie = [];
    if (l) pie.push(H.el("span", {}, `Medido: ${H.hora(l.medido_en)}`));
    else pie.push(H.el("span", {}, t.texto_lectura || "Sin lecturas"));
    if (t.conexion === "offline") pie.push(H.el("span", { class: "desconectado" }, "Equipo desconectado"));
    pie.push(H.el("a", { href: `/cama/${t.cama_id}` }, "Ver gráficos"));

    return H.el("article", { class: `tarjeta estado-${t.color}`, id: `cama-${t.nodo_id}`, "aria-live": "polite" },
      H.el("header", { class: "tarjeta-cabecera" },
        H.el("h2", {}, t.nombre),
        H.el("span", { class: "cultivo" }, t.cultivo ? t.cultivo : "sin cultivo")),
      H.el("p", { class: "mensaje" },
        H.el("span", { class: "icono", "aria-hidden": "true" }, ICONO[t.color] || "?"),
        H.el("span", {}, t.mensaje)),
      H.el("dl", { class: "valores" },
        valor("Humedad del suelo", l ? H.entero(l.suelo_prom) : null, "%"),
        valor("Temperatura", l ? H.entero(l.temp) : null, "°C"),
        valor("Luz hoy", luz, unidadLuz, sinLuz)),
      lineaTendencia(tendencias.get(t.nodo_id)),
      Clima ? Clima.lineaTarjeta(comparaciones.get(t.nodo_id)) : null,
      H.el("p", { class: "pie-tarjeta" }, pie));
  }

  /** «Suelo: ↘ Secándose lento» y, si hay, la estimación hasta el mínimo. */
  function lineaTendencia(t) {
    if (!t || !t.etiqueta || t.etiqueta === "Sin datos suficientes") return null;
    const clase = t.etiqueta.startsWith("Secándose rápido") ? "tendencia rapido" : "tendencia";
    return [
      H.el("p", { class: clase },
        H.el("span", { "aria-hidden": "true" }, `${FLECHA[t.etiqueta] || ""} `),
        "Suelo: ", H.el("strong", {}, t.etiqueta)),
      t.estimacion ? H.el("p", { class: "estimacion" }, t.estimacion) : null,
    ];
  }

  function dibujarTodas() {
    const ordenadas = [...tarjetas.values()].sort((a, b) => a.nombre.localeCompare(b.nombre, "es", { numeric: true }));
    contenedor.replaceChildren(...(ordenadas.length
      ? ordenadas.map(crearTarjeta)
      : [H.el("p", { class: "vacio" }, "Todavía no hay camas. Aparecen solas cuando un equipo envía su primera medición.")]));
  }

  function actualizarTarjeta(t) {
    const anterior = tarjetas.get(t.nodo_id) || {};
    // La tarjeta del procesador no trae el estado de conexión: se conserva
    const datos = { conexion: anterior.conexion, ...t };
    tarjetas.set(t.nodo_id, datos);
    const nodo = document.getElementById(`cama-${t.nodo_id}`);
    if (nodo && anterior.nombre === datos.nombre) nodo.replaceWith(crearTarjeta(datos));
    else dibujarTodas();
  }

  // ------------------------------------------------- mediciones de calidad

  function medirLatencia(t) {
    if (!KIOSCO || !t.lectura) return;
    if (ultimoSeq.get(t.nodo_id) === t.lectura.seq) return;
    ultimoSeq.set(t.nodo_id, t.lectura.seq);
    // Después de pintar la pantalla: ese es el momento en que el dato "se ve"
    requestAnimationFrame(() => setTimeout(() => {
      H.enviarJson("/api/latencia", {
        nodo_id: t.nodo_id, seq: t.lectura.seq, medido_en: t.lectura.medido_en,
        mostrado_en: new Date().toISOString(),
      }).catch(() => {});
    }, 0));
  }

  function confirmarAvisosVisibles(abiertos) {
    if (!KIOSCO) return;
    const nuevos = abiertos.map((a) => a.id).filter((id) => !avisosConfirmados.has(id));
    if (!nuevos.length) return;
    requestAnimationFrame(() => setTimeout(() => {
      H.enviarJson("/api/alertas/visibles", { ids: nuevos, visible_en: new Date().toISOString() })
        .then((r) => { if (r.ok) nuevos.forEach((id) => avisosConfirmados.add(id)); })
        .catch(() => {});
    }, 0));
  }

  // ---------------------------------------------------------------- datos

  async function cargarTablero() {
    try {
      const datos = await H.obtenerJson("/api/tablero");
      tarjetas.clear();
      for (const t of datos.camas) {
        tarjetas.set(t.nodo_id, t);
        // Lo que ya estaba al abrir la página no cuenta como latencia
        if (t.lectura && !ultimoSeq.has(t.nodo_id)) ultimoSeq.set(t.nodo_id, t.lectura.seq);
      }
      dibujarTodas();
      H.avisoConexion(datos.central_conectada ? "" : "El equipo central no está recibiendo datos");
    } catch (e) {
      H.avisoConexion("Sin conexión con el equipo central. Reintentando…");
    }
  }

  async function cargarAvisos() {
    try {
      const datos = await H.obtenerJson("/api/alertas");
      H.dibujarAvisos(listaAbiertos, datos.abiertas, "No hay avisos. ¡Todo en orden!");
      H.dibujarAvisos(listaResueltos, datos.resueltas_hoy, "Ninguno por ahora.");
      confirmarAvisosVisibles(datos.abiertas);
    } catch (e) { /* se reintenta en la próxima recarga */ }
  }

  // ------------------------------------- clima exterior (aparte, opcional)

  let ultimaComparacion = 0;

  async function cargarComparaciones() {
    if (!Clima) return;
    ultimaComparacion = Date.now();
    try {
      const datos = await H.obtenerJson("/api/clima/camas");
      comparaciones.clear();
      for (const c of datos.camas) comparaciones.set(c.nodo_id, c.comparacion);
      if (tarjetas.size) dibujarTodas();
    } catch (e) { /* sin clima: las tarjetas quedan como están */ }
  }

  /** Tras una lectura nueva: recalcula la comparación, como máximo una vez por minuto. */
  function compararPronto() {
    if (Date.now() - ultimaComparacion > RECARGA_MS) cargarComparaciones();
  }

  async function cargarTendencias() {
    try {
      const datos = await H.obtenerJson("/api/tendencias");
      tendencias.clear();
      for (const t of datos.camas) tendencias.set(t.nodo_id, t);
      if (tarjetas.size) dibujarTodas();
    } catch (e) { /* sin tendencia: las tarjetas quedan como están */ }
  }

  function cargarClima() {
    if (!Clima) return;
    Clima.cargarResumen(document.getElementById("clima-exterior"));
    cargarComparaciones();
  }

  // -------------------------------------------------- tiempo real (SSE)

  function escucharEventos() {
    const fuente = new EventSource("/api/eventos");
    fuente.addEventListener("open", () => { H.avisoConexion(""); cargarTablero(); cargarAvisos(); });
    fuente.addEventListener("error", () => H.avisoConexion("Sin conexión con el equipo central. Reintentando…"));
    fuente.addEventListener("tarjeta", (e) => {
      const t = JSON.parse(e.data);
      actualizarTarjeta(t);
      medirLatencia(t);
      compararPronto();
      if (t.alertas_nuevas && t.alertas_nuevas.length) cargarAvisos();
    });
    fuente.addEventListener("alertas", cargarAvisos);
    fuente.addEventListener("conexion", (e) => {
      const { nodo_id, estado } = JSON.parse(e.data);
      const t = tarjetas.get(nodo_id);
      if (t) { t.conexion = estado; actualizarTarjeta(t); }
    });
    fuente.addEventListener("central", (e) => {
      const { conectado } = JSON.parse(e.data);
      H.avisoConexion(conectado ? "" : "El equipo central no está recibiendo datos");
    });
  }

  cargarTablero();
  cargarAvisos();
  escucharEventos();
  // El clima se pide DESPUÉS y por separado: nunca retrasa las camas
  setTimeout(cargarClima, 0);
  setInterval(cargarClima, RECARGA_CLIMA_MS);
  // La tendencia también se pide aparte (cambia lento: cada 5 minutos basta)
  setTimeout(cargarTendencias, 0);
  setInterval(cargarTendencias, RECARGA_CLIMA_MS);
  // Respaldo por si se pierde algún evento
  setInterval(cargarTablero, RECARGA_MS);
  setInterval(cargarAvisos, RECARGA_MS);
})();

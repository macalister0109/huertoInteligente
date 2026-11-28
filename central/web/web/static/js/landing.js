/* Página del proyecto: menú móvil, simulador de cama (HU-05) y formulario.
   Sin dependencias. El formulario NO envía datos a este sitio: abre el correo
   del visitante con el mensaje listo (el sistema no guarda datos personales). */
"use strict";

(() => {
  // ------------------------------------------------------------- menú móvil
  const botonMenu = document.querySelector(".boton-menu");
  const menu = document.getElementById("menu-landing");
  if (botonMenu && menu) {
    botonMenu.addEventListener("click", () => {
      const abierto = menu.classList.toggle("abierto");
      botonMenu.setAttribute("aria-expanded", String(abierto));
    });
    menu.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => {
      menu.classList.remove("abierto");
      botonMenu.setAttribute("aria-expanded", "false");
    }));
  }

  // --------------------------------------------------- simulador de la cama
  const ESTADOS = {
    verde: {
      nombre: "Cama A", cultivo: "Tomates · zona central", icono: "✔", mensaje: "Todo bien",
      humedad: "54 %", ideal: "ideal 30 a 70 %", temp: "24 °C", luz: "6,8 h", pie: "Medido hace 1 min",
      nota: "Verde: la humedad, la temperatura y la luz están dentro del rango del cultivo.",
    },
    rojo: {
      nombre: "Cama B", cultivo: "Tomates · zona central", icono: "!", mensaje: "Revisar: humedad 22 %",
      humedad: "22 %", ideal: "ideal 30 a 70 %", temp: "31 °C", luz: "7,2 h", pie: "Aviso generado en menos de 5 min",
      nota: "Rojo: el calor de la tarde secó la cama. Aparece el aviso «Cama B seca: 22 % (ideal 30 % a 70 %)», una sola vez mientras siga seca.",
    },
    gris: {
      nombre: "Cama C", cultivo: "Lechugas · zona central", icono: "?", mensaje: "Sensor sin conexión",
      humedad: "—", ideal: "sin lecturas", temp: "—", luz: "—", pie: "Última lectura hace más de 2 h",
      nota: "Gris: el sensor lleva más de 2 horas sin enviar datos. Así nadie toma decisiones con lecturas viejas.",
    },
  };

  const tarjeta = document.getElementById("tarjeta-sim");
  const botones = document.querySelectorAll(".simulador-botones button");
  const nota = document.querySelector(".sim-nota");

  function mostrar(estado) {
    const datos = ESTADOS[estado];
    if (!datos || !tarjeta) return;
    botones.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.estado === estado)));
    tarjeta.classList.add("cambiando");
    setTimeout(() => {
      tarjeta.className = `tarjeta-sim estado-${estado}`;
      tarjeta.querySelectorAll("[data-campo]").forEach((el) => {
        const valor = datos[el.dataset.campo];
        if (valor !== undefined) el.textContent = valor;
      });
      if (nota) nota.textContent = datos.nota;
    }, 160);
  }

  botones.forEach((b, i) => {
    b.addEventListener("click", () => mostrar(b.dataset.estado));
    // Flechas del teclado entre las pestañas
    b.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const siguiente = botones[(i + (e.key === "ArrowRight" ? 1 : botones.length - 1)) % botones.length];
      siguiente.focus();
      mostrar(siguiente.dataset.estado);
    });
  });

  // ------------------------------------------------------------- formulario
  const formulario = document.getElementById("formulario-piloto");
  const confirmacion = document.getElementById("confirmacion");
  if (!formulario) return;
  const error = formulario.querySelector(".error-formulario");
  const correoDestino = formulario.dataset.correo || "";
  const CORREO_VALIDO = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function validar() {
    const problemas = [];
    const campos = {
      nombre: formulario.elements.nombre, estamento: formulario.elements.estamento, correo: formulario.elements.correo,
    };
    Object.values(campos).forEach((c) => c.removeAttribute("aria-invalid"));
    if (campos.nombre.value.trim().length < 3) {
      problemas.push("Escribe tu nombre completo.");
      campos.nombre.setAttribute("aria-invalid", "true");
    }
    if (!campos.estamento.value) {
      problemas.push("Elige tu estamento.");
      campos.estamento.setAttribute("aria-invalid", "true");
    }
    if (!CORREO_VALIDO.test(campos.correo.value.trim())) {
      problemas.push("Revisa tu correo electrónico.");
      campos.correo.setAttribute("aria-invalid", "true");
    }
    return problemas;
  }

  formulario.addEventListener("submit", (e) => {
    e.preventDefault();
    const problemas = validar();
    if (problemas.length) {
      error.textContent = problemas.join(" ");
      error.hidden = false;
      formulario.querySelector('[aria-invalid="true"]')?.focus();
      return;
    }
    error.hidden = true;
    if (!correoDestino) {
      error.textContent = "Todavía no hay un correo de contacto configurado para el piloto. Avísale al equipo del proyecto.";
      error.hidden = false;
      return;
    }
    const f = formulario.elements;
    const cuerpo = [
      `Nombre: ${f.nombre.value.trim()}`,
      `Estamento: ${f.estamento.value}`,
      `Correo: ${f.correo.value.trim()}`,
      "",
      "Comentario o propuesta de cultivo:",
      f.comentario.value.trim() || "(sin comentario)",
    ].join("\n");
    const asunto = `Quiero sumarme al piloto smartYusChaMau (${f.estamento.value})`;
    window.location.href = `mailto:${encodeURIComponent(correoDestino)}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(cuerpo)}`;
    const enlace = confirmacion.querySelector('[data-campo="correo"]');
    enlace.textContent = correoDestino;
    enlace.href = `mailto:${correoDestino}`;
    formulario.hidden = true;
    confirmacion.hidden = false;
    confirmacion.scrollIntoView({ behavior: "smooth", block: "center" });
  });
})();

"use client";

import { useEffect, useState } from "react";
import { buscarClientes, type Cliente } from "@/lib/pos/api";

/**
 * La clienta, buscada DENTRO del carrito.
 *
 * Antes era un botón «+ Asignar clienta» que abría un diálogo. Un botón se
 * salta; un campo con el cursor puesto es parte del flujo. Y el dato importa
 * más de lo que parece: sin documento no hay factura electrónica a nombre de
 * nadie, así que cada venta que se salta ese paso es una factura que después
 * hay que rehacer a mano.
 *
 * SÓLO POR NÚMERO DE IDENTIFICACIÓN, como el diálogo. Buscar por nombre en un
 * mostrador devuelve seis «María González» y la cajera tiene que adivinar
 * cuál; el documento es único y la clienta se lo sabe de memoria.
 *
 * CREAR SIGUE SIENDO UN DIÁLOGO. El alta pide tipo de documento, nombre,
 * teléfono y correo: cuatro campos más que no caben en un panel de 300px sin
 * comerse las líneas de la venta, que es lo que la cajera está mirando.
 *
 * NO ES OBLIGATORIO. La mayoría de las ventas de tienda no llevan clienta, y
 * obligar a buscar una salida son segundos de los treinta que dura la venta.
 */
export function BuscadorCliente({
  cliente,
  onAsignar,
  onQuitar,
  onCrear,
}: {
  cliente: Cliente | null;
  onAsignar: (c: Cliente) => void;
  onQuitar: () => void;
  onCrear: (documento: string) => void;
}) {
  const [documento, setDocumento] = useState("");
  const [resultados, setResultados] = useState<Cliente[]>([]);
  const [buscado, setBuscado] = useState(false);

  useEffect(() => {
    const digitos = documento.replace(/\D/g, "");
    if (digitos.length < 3) {
      setResultados([]);
      setBuscado(false);
      return;
    }
    let vigente = true;
    const t = setTimeout(async () => {
      try {
        const r = await buscarClientes(digitos);
        if (!vigente) return;
        setResultados(r);
        setBuscado(true);
      } catch {
        // Sin red no se busca, y no se dice nada: el buscador es opcional y un
        // error rojo aquí haría creer que la venta tiene un problema.
        if (vigente) setResultados([]);
      }
    }, 150);
    return () => {
      vigente = false;
      clearTimeout(t);
    };
  }, [documento]);

  // YA ASIGNADA: el bloque se encoge. Lo que ocupa sitio en el carrito son las
  // prendas, no un buscador que ya cumplió.
  if (cliente) {
    return (
      <div
        className="mt-3 flex items-start justify-between gap-2 rounded-[var(--pos-r-md)] border px-3 py-2"
        style={{ borderColor: "var(--pos-divider)", background: "var(--pos-100)" }}
      >
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium">{cliente.nombre}</p>
          <p className="tabular text-[12px]" style={{ color: "var(--pos-600)" }}>
            {cliente.tipo_documento} {cliente.numero_documento}
            {cliente.compras > 0 ? ` · ${cliente.compras} compras` : ""}
          </p>
        </div>
        <button
          onClick={onQuitar}
          className="shrink-0 px-1 text-[12px] underline"
          style={{ color: "var(--pos-600)" }}
        >
          quitar
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3">
      <input
        value={documento}
        onChange={(e) => setDocumento(e.target.value)}
        inputMode="numeric"
        autoComplete="off"
        aria-label="Buscar clienta por número de identificación"
        placeholder="Documento de la clienta"
        className="h-11 w-full rounded-[var(--pos-r-md)] border px-3 tabular text-[13px] outline-none focus:border-[var(--pos-accent)]"
        style={{ borderColor: "var(--pos-divider)", background: "#fff",
                 color: "var(--pos-text)" }}
      />

      {resultados.length > 0 && (
        <div className="mt-1.5">
          {resultados.slice(0, 4).map((c) => (
            <button
              key={c.id}
              onClick={() => {
                onAsignar(c);
                setDocumento("");
              }}
              className="flex w-full items-baseline justify-between gap-2 border-b px-1 py-2 text-left transition-colors duration-[var(--pos-transicion)] hover:bg-[var(--pos-100)]"
              style={{ borderColor: "var(--pos-divider)" }}
            >
              <span className="min-w-0 truncate text-[13px]">{c.nombre}</span>
              <span className="tabular shrink-0 text-[12px]"
                    style={{ color: "var(--pos-600)" }}>
                {c.numero_documento}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* CREAR VA DEBAJO, y lleva el documento ya tecleado. Quien llega aquí
          acaba de buscar y no encontrar: volver a pedirle el número sería
          hacerle teclear dos veces lo mismo delante de la clienta. */}
      <button
        onClick={() => onCrear(documento.replace(/\D/g, ""))}
        className="mt-1.5 h-11 w-full rounded-[var(--pos-r-md)] border border-dashed text-[13px] transition-colors duration-[var(--pos-transicion)] hover:bg-[var(--pos-100)]"
        style={{ borderColor: "var(--pos-400)", color: "var(--pos-700)" }}
        title="Necesaria para la factura electrónica"
      >
        + Crear nueva clienta
      </button>

      {buscado && resultados.length === 0 && (
        <p className="mt-1.5 text-[12px] leading-relaxed"
           style={{ color: "var(--pos-600)" }}>
          Sin resultados para ese documento.
        </p>
      )}
    </div>
  );
}

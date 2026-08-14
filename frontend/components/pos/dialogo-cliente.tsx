"use client";

import { useEffect, useRef, useState } from "react";
import { buscarClientes, crearCliente, type Cliente } from "@/lib/pos/api";
import { nuevoUlid } from "@/lib/pos/ulid";

/**
 * Asignar clienta — vista 4 del handoff.
 *
 * NO ES UN CRM. Es el dato mínimo que exige la factura electrónica: tipo de
 * documento, número, nombre, teléfono y correo. A ese correo le llega la
 * factura, así que un error de dedo ahí es una factura que nunca llega y una
 * clienta que llama tres días después.
 *
 * LA BÚSQUEDA ES SÓLO POR NÚMERO DE IDENTIFICACIÓN, como pide el diseño, y es
 * lo correcto: buscar por nombre en un mostrador devuelve seis «María
 * González» y la cajera tiene que adivinar cuál. El documento es único y la
 * clienta se lo sabe.
 *
 * «Venta sin registrar» está SIEMPRE visible. La mayoría de las ventas de
 * tienda no llevan clienta, y obligar a buscar una salida son segundos de los
 * treinta.
 */
const TIPOS = [
  { valor: "CC", etiqueta: "Cédula de ciudadanía" },
  { valor: "PP", etiqueta: "Pasaporte" },
  { valor: "CE", etiqueta: "Cédula de extranjería" },
];

export function DialogoCliente({
  onCerrar,
  onAsignar,
  documentoInicial,
}: {
  onCerrar: () => void;
  onAsignar: (c: Cliente) => void;
  /** El documento que la cajera ya tecleó en el buscador del carrito. Si
   *  viene, este diálogo ABRE DIRECTO EN EL ALTA: llegó aquí porque buscó y no
   *  encontró, así que devolverla a buscar de nuevo es un paso muerto. */
  documentoInicial?: string;
}) {
  const [modo, setModo] = useState<"buscar" | "crear">(
    documentoInicial ? "crear" : "buscar");
  const [documento, setDocumento] = useState(documentoInicial ?? "");
  const [resultados, setResultados] = useState<Cliente[]>([]);
  const [buscado, setBuscado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const primero = useRef<HTMLInputElement>(null);

  const [tipo, setTipo] = useState("CC");
  const [nombre, setNombre] = useState("");
  const [telefono, setTelefono] = useState("");
  const [correo, setCorreo] = useState("");

  useEffect(() => {
    primero.current?.focus();
  }, [modo]);

  useEffect(() => {
    if (modo !== "buscar") return;
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
        if (vigente) setResultados([]);
      }
    }, 150);
    return () => {
      vigente = false;
      clearTimeout(t);
    };
  }, [documento, modo]);

  async function guardar() {
    setError(null);
    setGuardando(true);
    try {
      const c = await crearCliente({
        cliente_id: nuevoUlid(),
        tipo_documento: tipo,
        numero_documento: documento,
        nombre,
        telefono,
        correo,
      });
      onAsignar(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear la clienta.");
    } finally {
      setGuardando(false);
    }
  }

  const completo =
    documento.replace(/\D/g, "").length >= 5 &&
    nombre.trim().length >= 3 &&
    telefono.replace(/\D/g, "").length >= 7 &&
    correo.includes("@");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Asignar clienta"
        className="blueprint w-full max-w-[520px] p-6"
        style={{ background: "var(--pos-surface)" }}
      >
        <i className="corner tl" aria-hidden /><i className="corner tr" aria-hidden />
        <i className="corner bl" aria-hidden /><i className="corner br" aria-hidden />

        <div className="mb-4 flex items-start justify-between">
          <h2 className="titular text-[18px]">
            {modo === "buscar" ? "Asignar clienta" : "Crear clienta"}
          </h2>
          <button onClick={onCerrar} aria-label="Cerrar" style={{ color: "var(--pos-600)" }}>
            ✕
          </button>
        </div>

        {modo === "buscar" ? (
          <>
            <label className="kicker" style={{ color: "var(--pos-600)" }}>
              Buscar por número de identificación
            </label>
            <input
              ref={primero}
              value={documento}
              onChange={(e) => setDocumento(e.target.value)}
              inputMode="numeric"
              placeholder="1.037.601.884"
              className="mt-1 h-11 w-full rounded-[var(--pos-r-md)] border px-3 text-[15px] outline-none"
              style={{ borderColor: "var(--pos-divider)", background: "var(--pos-bg)" }}
            />

            <div className="my-4 max-h-[240px] overflow-y-auto">
              {resultados.map((c) => (
                <button
                  key={c.id}
                  onClick={() => onAsignar(c)}
                  className="flex h-12 w-full items-center justify-between rounded-[var(--pos-r-sm)] px-3 text-left hover:bg-[var(--pos-100)]"
                >
                  <span className="text-[14px]">{c.nombre}</span>
                  <span className="text-[12px]" style={{ color: "var(--pos-600)" }}>
                    {c.tipo_documento} {c.numero_documento} · {c.compras} compras
                  </span>
                </button>
              ))}

              {buscado && resultados.length === 0 && (
                <p
                  className="rounded-[var(--pos-r-sm)] p-3 text-[13px] leading-relaxed"
                  style={{ background: "var(--pos-100)", color: "var(--pos-700)" }}
                >
                  Sin resultados para esa identificación. Crea la clienta abajo.
                </p>
              )}
            </div>

            <button
              onClick={() => setModo("crear")}
              className="h-11 w-full rounded-[var(--pos-r-md)] border border-dashed text-[14px] hover:bg-[var(--pos-100)]"
              style={{ borderColor: "var(--pos-400)", color: "var(--pos-800)" }}
            >
              + Crear clienta
            </button>
          </>
        ) : (
          <>
            <div className="grid gap-3" style={{ gridTemplateColumns: "180px 1fr" }}>
              <div>
                <label className="kicker" style={{ color: "var(--pos-600)" }}>
                  Tipo de documento
                </label>
                <select
                  value={tipo}
                  onChange={(e) => setTipo(e.target.value)}
                  className="mt-1 h-11 w-full rounded-[var(--pos-r-md)] border px-2 text-[14px]"
                  style={{ borderColor: "var(--pos-divider)", background: "var(--pos-bg)" }}
                >
                  {TIPOS.map((t) => (
                    <option key={t.valor} value={t.valor}>{t.etiqueta}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="kicker" style={{ color: "var(--pos-600)" }}>
                  Número de identificación
                </label>
                <input
                  ref={primero}
                  value={documento}
                  onChange={(e) => setDocumento(e.target.value)}
                  inputMode="numeric"
                  className="mt-1 h-11 w-full rounded-[var(--pos-r-md)] border px-3 text-[15px] outline-none"
                  style={{ borderColor: "var(--pos-divider)", background: "var(--pos-bg)" }}
                />
              </div>
            </div>

            <Campo etiqueta="Nombre completo" valor={nombre} onCambio={setNombre} />
            <Campo etiqueta="Teléfono" valor={telefono} onCambio={setTelefono} tipo="tel" />
            <Campo
              etiqueta="Correo electrónico"
              valor={correo}
              onCambio={setCorreo}
              tipo="email"
              ayuda="A este correo llega la factura electrónica."
            />

            {error && (
              <p
                className="mt-3 rounded-[var(--pos-r-sm)] border p-2.5 text-[13px]"
                style={{ borderColor: "var(--pos-700)", background: "var(--pos-100)", color: "var(--pos-900)" }}
              >
                {error}
              </p>
            )}

            <button
              disabled={!completo || guardando}
              onClick={guardar}
              className="mt-4 h-12 w-full text-[14px] font-semibold tracking-[0.1em]"
              style={{
                background: completo ? "var(--pos-accent)" : "var(--pos-300)",
                color: completo ? "#fff" : "var(--pos-600)",
                borderRadius: "var(--pos-r-md)",
              }}
            >
              {guardando ? "GUARDANDO…" : "GUARDAR Y ASIGNAR"}
            </button>

            <button
              onClick={() => { setModo("buscar"); setError(null); }}
              className="mt-3 w-full text-[13px] underline"
              style={{ color: "var(--pos-700)" }}
            >
              Volver a la lista
            </button>
          </>
        )}

        {/* Siempre visible: la mayoría de las ventas de tienda no llevan
            clienta, y obligar a buscar la salida son segundos de los treinta. */}
        <button
          onClick={onCerrar}
          className="mt-4 w-full text-[13px]"
          style={{ color: "var(--pos-600)" }}
        >
          Venta sin registrar
        </button>
      </div>
    </div>
  );
}

function Campo({
  etiqueta,
  valor,
  onCambio,
  tipo = "text",
  ayuda,
}: {
  etiqueta: string;
  valor: string;
  onCambio: (v: string) => void;
  tipo?: string;
  ayuda?: string;
}) {
  return (
    <div className="mt-3">
      <label className="kicker" style={{ color: "var(--pos-600)" }}>{etiqueta}</label>
      <input
        type={tipo}
        value={valor}
        onChange={(e) => onCambio(e.target.value)}
        className="mt-1 h-11 w-full rounded-[var(--pos-r-md)] border px-3 text-[15px] outline-none"
        style={{ borderColor: "var(--pos-divider)", background: "var(--pos-bg)" }}
      />
      {ayuda && (
        <p className="mt-1 text-[12px]" style={{ color: "var(--pos-600)" }}>
          {ayuda}
        </p>
      )}
    </div>
  );
}

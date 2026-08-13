"use client";

/**
 * Lo que pasó en la tienda, y si la cadena aguanta.
 *
 * La auditoría se venía escribiendo desde el primer día —encadenada con
 * SHA-256 para que una modificación a mano se note— y NADIE PODÍA LEERLA: no
 * había endpoint ni pantalla, y el verificador sólo lo llamaba una prueba. Un
 * control que no se puede consultar no es un control, es un archivo.
 *
 * EL VEREDICTO DE LA CADENA VA ARRIBA, no escondido en otra pantalla. Una
 * lista de eventos sin decir si están íntegros invita a creérselos — y son
 * justo los que alguien querría alterar.
 *
 * EL RESUMEN LO ARMA EL SERVIDOR. Aquí no se interpreta el payload: un
 * `switch` por tipo de evento en la pantalla se desincroniza del backend en
 * cuanto alguien agrega uno nuevo, y ese evento nuevo saldría como un volcado
 * de JSON justo el día que haga falta leerlo.
 */
import { useEffect, useState } from "react";
import { Panel } from "@/components/pos/marco";
import { leerAuditoria, type PaginaAuditoria } from "@/lib/pos/api";

const FILTROS = [
  { id: "", etiqueta: "Todo" },
  { id: "critico", etiqueta: "Crítico" },
  { id: "aviso", etiqueta: "Avisos" },
];

export function Auditoria({ tiendaId }: { tiendaId: string }) {
  const [datos, setDatos] = useState<PaginaAuditoria | null>(null);
  const [severidad, setSeveridad] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    (async () => {
      try {
        const d = await leerAuditoria({ tiendaId, severidad, limite: 100 });
        if (vivo) { setDatos(d); setError(null); }
      } catch (e) {
        if (vivo) setError(e instanceof Error ? e.message : "No se pudo leer.");
      }
    })();
    return () => { vivo = false; };
  }, [tiendaId, severidad]);

  if (error) {
    return (
      <Panel className="p-6">
        <p className="text-[13px] leading-relaxed text-[var(--pos-700)]">{error}</p>
      </Panel>
    );
  }

  return (
    <Panel className="flex min-h-0 flex-col gap-3 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="titular text-[17px] font-semibold">Auditoría</h2>
        <div className="flex gap-1.5">
          {FILTROS.map((f) => (
            <button
              key={f.id}
              onClick={() => setSeveridad(f.id)}
              className={`border px-2.5 py-1 text-[11px] transition-colors ${
                severidad === f.id
                  ? "border-[var(--pos-800)] bg-[var(--pos-800)] text-white"
                  : "border-[var(--pos-divider)] text-[var(--pos-700)]"
              }`}
            >
              {f.etiqueta}
            </button>
          ))}
        </div>
      </div>

      {/* EL VEREDICTO PRIMERO. Es lo único que dice si lo de abajo se puede
          creer. */}
      {datos && (
        <div
          className={`border-l-2 py-2 pl-3 text-[12px] leading-relaxed ${
            datos.integra
              ? "border-[var(--pos-divider)] bg-[var(--pos-100)] text-[var(--pos-700)]"
              : "border-[var(--pos-accent)] bg-[var(--pos-accent)]/10 text-[var(--pos-900)]"
          }`}
        >
          {datos.integra ? (
            <>
              Cadena íntegra · {datos.eventos_verificados} eventos verificados.
              Si alguien edita esta tabla desde la base, aquí se nota.
            </>
          ) : (
            <>
              <strong>La cadena está rota.</strong> Alguien modificó o borró
              registros directamente en la base
              {datos.evento_roto ? ` — el primer eslabón malo es «${datos.evento_roto}»` : ""}
              {datos.motivo_ruptura === "payload_alterado"
                ? " y su contenido no coincide con su firma."
                : " y no encadena con el anterior."}
            </>
          )}
        </div>
      )}

      {datos?.eventos.length === 0 && (
        <p className="text-[13px] text-[var(--pos-600)]">
          Nada registrado con este filtro.
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {datos?.eventos.map((e) => (
          <div
            key={e.id}
            className="flex gap-3 border-b border-[var(--pos-divider)]/60 py-2 last:border-0"
          >
            <span
              aria-hidden
              className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                e.severidad === "critico"
                  ? "bg-[var(--pos-accent)]"
                  : e.severidad === "aviso"
                    ? "bg-[var(--pos-800)]"
                    : "bg-[var(--pos-divider)]"
              }`}
            />
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                <span className="font-medium">{etiqueta(e.evento)}</span>
                <span className="text-[var(--pos-700)]">{e.resumen}</span>
              </p>
              <p className="tabular text-[10.5px] text-[var(--pos-600)]">
                {e.cuando} · {e.quien}
                {e.caja ? ` · ${e.caja}` : ""}
              </p>
            </div>
          </div>
        ))}
      </div>

      {datos && datos.total > datos.eventos.length && (
        <p className="tabular text-[10.5px] text-[var(--pos-600)]">
          Mostrando {datos.eventos.length} de {datos.total}.
        </p>
      )}
    </Panel>
  );
}

/** `venta.anulada` → «Venta anulada». El nombre técnico es para buscar en la
 *  base; en pantalla estorba. */
function etiqueta(evento: string): string {
  const partes = evento.split(".");
  const nombre = (partes[1] ?? evento).replace(/_/g, " ");
  const sujeto = partes[0] === "caja" ? "Caja" : "Venta";
  return `${sujeto} · ${nombre.charAt(0).toUpperCase()}${nombre.slice(1)}`;
}

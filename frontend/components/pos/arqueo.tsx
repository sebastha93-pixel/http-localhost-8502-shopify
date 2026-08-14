"use client";

/**
 * Arqueo de caja — el panel derecho de la vista 7 del handoff.
 *
 * DIFERENCIA DELIBERADA CON EL DISEÑO. El handoff pone, antes del input:
 *
 *     Base de caja        $200.000
 *     Efectivo en ventas  $1.040.000
 *     Efectivo esperado   $1.240.000
 *     [ Efectivo contado: ______ ]
 *
 * Con eso a la vista, el arqueo deja de medir. Nadie cuenta un cajón cuando la
 * pantalla ya le dijo el resultado: se teclea $1.240.000 y la diferencia da
 * cero todos los días, incluso los días en que no debería.
 *
 * El backend directamente NO manda esos números en cierre ciego (INV-C4), así
 * que aquí no hay nada que ocultar: no llegan. Se revelan después de declarar
 * —cuando ya no pueden influir en lo que se cuenta— o de entrada si quien está
 * mirando es un supervisor con permiso para revisar una caja ajena.
 *
 * Es la misma decisión que se tomó con el descuento: el diseñador no tenía por
 * qué saber que ese bloque era un control, no una etiqueta.
 *
 * Y OCULTAR EL ESPERADO NO BASTABA. Declarar seguía siendo escribir un número,
 * y quien lleva el día en la cabeza puede escribir una cifra plausible sin
 * abrir el cajón: el conteo ciego más débil que existe es el que se responde
 * de memoria. El efectivo se cuenta por denominación —cantidades, no total— y
 * el total lo saca el sistema.
 *
 * EXTENSIÓN SOBRE EL DISEÑO: el handoff sólo cuenta efectivo. Una venta con
 * tarjeta también hay que cuadrarla contra el datáfono, o el descuadre del
 * datáfono no lo detecta nadie hasta la conciliación bancaria del mes. Se
 * pinta una fila por medio con movimientos.
 */
import { useState } from "react";
import { Panel } from "@/components/pos/marco";
import { ContadorDenominaciones } from "@/components/pos/contador-denominaciones";
import { formatear, desdePesosTecleados } from "@/lib/pos/dinero";
import type { MedioResumen, ResumenCierre } from "@/lib/pos/api";

export interface Conteo {
  medio_pago_id: string;
  contado_centavos: number;
}

/** Dónde va a buscar la cajera el número que se le pide declarar. */
function fuenteDe(m: MedioResumen): string {
  if (m.tipo === "tarjeta") return "cierre del datáfono";
  if (m.tipo === "financiacion") return "informe del día en su app";
  if (m.tipo === "transferencia") return "movimientos recibidos hoy";
  return "informe del día";
}

export function Arqueo({
  resumen,
  contados,
  onContar,
  piezas,
  onPiezas,
  onCerrar,
  cerrando,
  error,
}: {
  resumen: ResumenCierre;
  contados: Record<string, string>;
  onContar: (medioId: string, texto: string) => void;
  piezas: Record<number, number>;
  onPiezas: (piezas: Record<number, number>) => void;
  onCerrar: () => void;
  cerrando: boolean;
  error: string | null;
}) {
  const esperado = resumen.esperado_por_medio;
  const efectivo = resumen.medios.find((m) => m.es_efectivo);

  // Todo medio con movimientos hay que declararlo, y el efectivo siempre
  // —aunque no se haya vendido nada, la base está en el cajón.
  const aDeclarar: MedioResumen[] = resumen.medios.length
    ? resumen.medios
    : [{
        medio_pago_id: "efectivo", nombre: "Efectivo", tipo: "efectivo",
        es_efectivo: true,
        entra_al_arqueo: true, total_centavos: resumen.base_inicial_centavos,
      }];

  // El efectivo se cuenta por denominación; los demás medios se declaran con
  // el total del cierre del datáfono, que no tiene billetes que contar.
  const contoElEfectivo = Object.keys(piezas).length > 0;
  const faltaAlguno = aDeclarar.some((m) =>
    m.es_efectivo
      ? !contoElEfectivo
      : m.entra_al_arqueo && !(contados[m.medio_pago_id] ?? "").trim());

  return (
    <Panel className="flex flex-col gap-4 self-start p-6">
      <h2 className="titular text-[17px] font-semibold">Arqueo de caja</h2>

      {esperado ? (
        <>
          <Fila label="Base de caja" valor={formatear(resumen.base_inicial_centavos)} />
          <Fila
            label="Efectivo en ventas"
            valor={formatear(
              (esperado[efectivo?.medio_pago_id ?? "efectivo"] ?? 0) -
                resumen.base_inicial_centavos,
            )}
          />
          <Fila
            label="Efectivo esperado"
            valor={formatear(esperado[efectivo?.medio_pago_id ?? "efectivo"] ?? 0)}
            fuerte
            separador
          />
        </>
      ) : (
        <p className="border-l-2 border-[var(--pos-accent)] bg-[var(--pos-100)] py-2.5 pl-3 pr-2 text-[12px] leading-relaxed text-[var(--pos-700)]">
          Cuenta el cajón y escribe lo que hay. El sistema no muestra cuánto
          debería ser hasta que declares — así el conteo mide algo.
        </p>
      )}

      <div className="mt-1 flex flex-col gap-4">
        {aDeclarar.map((m) => (
          <label key={m.medio_pago_id} className="block">
            {/* DE DÓNDE SALE EL NÚMERO, y eso depende del medio. Decía «cierre
                del datáfono» para todo lo que no era efectivo, así que a la
                cajera que cobró con Addi la mandaba a mirar el aparato
                equivocado. Un rótulo que indica mal la fuente hace que se
                declare cualquier cosa, y ahí el arqueo deja de medir. */}
            <span className="kicker text-[var(--pos-600)]">
              {m.es_efectivo ? "Efectivo contado" : `${m.nombre} · ${fuenteDe(m)}`}
            </span>
            {m.es_efectivo ? (
              // POR DENOMINACIÓN, no un total. El cierre ya era ciego, pero
              // declarar era ESCRIBIR UN NÚMERO, y quien lleva el día en la
              // cabeza puede escribir una cifra plausible sin abrir el cajón.
              // Metiendo cantidades, el total lo saca el sistema y deja de ser
              // algo que se pueda responder de memoria.
              <div className="mt-2">
                <ContadorDenominaciones
                  denominaciones={resumen.denominaciones}
                  piezas={piezas}
                  onCambio={onPiezas}
                  deshabilitado={cerrando}
                  columnas={1}
                />
              </div>
            ) : m.entra_al_arqueo ? (
              <input
                inputMode="numeric"
                autoComplete="off"
                placeholder="0"
                value={contados[m.medio_pago_id] ?? ""}
                onChange={(e) => onContar(m.medio_pago_id, e.target.value)}
                className="mt-1.5 h-12 w-full border border-[var(--pos-divider)] bg-white px-3 titular text-[18px] tabular text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
              />
            ) : (
              // No hay nada físico que contar (un crédito a 30 días). Se
              // declara el valor del sistema y se deja de sólo lectura: pedir
              // que lo teclee invita a teclear cualquier cosa.
              <input
                readOnly
                value={formatear(m.total_centavos)}
                className="mt-1.5 h-12 w-full border border-[var(--pos-divider)] bg-[var(--pos-100)] px-3 titular text-[18px] tabular text-[var(--pos-600)]"
              />
            )}
            {contados[m.medio_pago_id] && (
              <span className="mt-1 block tabular text-[12px] text-[var(--pos-600)]">
                {formatear(desdePesosTecleados(contados[m.medio_pago_id]))}
              </span>
            )}
          </label>
        ))}
      </div>

      <Fila
        label="Diferencia"
        valor={esperado ? diferenciaViva(esperado, contados, aDeclarar) : "—"}
        fuerte
        separador
        atenuado={!esperado}
      />
      {!esperado && (
        <p className="-mt-2 tabular text-[12px] leading-relaxed text-[var(--pos-600)]">
          Aparece al cerrar.
        </p>
      )}

      {error && (
        <p className="border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-[12px] leading-relaxed text-[var(--pos-900)]">
          {error}
        </p>
      )}

      <button
        onClick={onCerrar}
        disabled={faltaAlguno || cerrando}
        className="mt-1 h-[52px] w-full bg-[var(--pos-accent)] titular text-[15px] font-semibold tracking-[0.05em] text-white disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-muted)]"
      >
        {cerrando ? "CERRANDO…" : "CERRAR CAJA"}
      </button>
    </Panel>
  );
}

/** Sólo se puede calcular en vivo cuando el esperado es visible; en cierre
 *  ciego el número sale del servidor al cerrar. */
function diferenciaViva(
  esperado: Record<string, number>,
  contados: Record<string, string>,
  medios: MedioResumen[],
): string {
  const total = medios.reduce(
    (acc, m) =>
      acc +
      (desdePesosTecleados(contados[m.medio_pago_id] ?? "") -
        (esperado[m.medio_pago_id] ?? 0)),
    0,
  );
  return total > 0 ? `+${formatear(total)}` : formatear(total);
}

function Fila({
  label,
  valor,
  fuerte,
  separador,
  atenuado,
}: {
  label: string;
  valor: string;
  fuerte?: boolean;
  separador?: boolean;
  atenuado?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline justify-between ${
        fuerte ? "text-[14px]" : "text-[13px]"
      } ${separador ? "border-t border-[var(--pos-divider)] pt-3" : ""}`}
    >
      <span className="text-[var(--pos-700)]">{label}</span>
      <span
        className={`tabular ${
          fuerte ? "titular text-[18px] font-semibold" : "font-medium"
        } ${atenuado ? "text-[var(--pos-muted)]" : "text-[var(--pos-text)]"}`}
      >
        {valor}
      </span>
    </div>
  );
}

/**
 * El descuadre que no se puede cerrar sin explicación (INV-C5).
 *
 * Aquí había también un PIN de supervisor. Se quitó: a la plataforma se entra
 * con correo y contraseña y no hay una segunda credencial. El permiso lo trae
 * ahora el usuario que tiene la sesión abierta —o puede cerrar con descuadre,
 * o tiene que entrar quien pueda—, y quien cierra es quien firma.
 *
 * La justificación escrita se queda. Es lo que convierte un faltante en algo
 * revisable; sin ella el descuadre es un número sin historia.
 */
export function DialogoDescuadre({
  mensaje,
  onCancelar,
  onFirmar,
  error,
}: {
  mensaje: string;
  onCancelar: () => void;
  onFirmar: (justificacion: string) => void;
  error: string | null;
}) {
  const [justificacion, setJustificacion] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label="Autorizar descuadre"
        className="w-full max-w-[440px] bg-[var(--pos-bg)] p-6"
      >
        <h2 className="titular text-[15px] font-semibold tracking-[0.08em]">
          🔒 DESCUADRE POR ENCIMA DEL TOPE
        </h2>
        <p className="mt-3 text-[13px] leading-relaxed text-[var(--pos-700)]">
          {mensaje}
        </p>

        <label className="mt-5 block">
          <span className="kicker text-[var(--pos-600)]">Qué pasó</span>
          <textarea
            rows={3}
            autoFocus
            value={justificacion}
            onChange={(e) => setJustificacion(e.target.value)}
            placeholder="Faltante detectado al contar; se revisa con el supervisor."
            className="mt-1.5 w-full resize-none border border-[var(--pos-divider)] bg-white p-2.5 text-[13px] leading-relaxed text-[var(--pos-text)] outline-none focus:border-[var(--pos-accent)]"
          />
        </label>


        {error && (
          <p className="mt-4 border border-[var(--pos-800)] bg-[var(--pos-800)]/10 p-2.5 text-[12px] text-[var(--pos-900)]">
            {error}
          </p>
        )}

        <p className="mt-4 tabular text-[12px] leading-relaxed text-[var(--pos-600)]">
          El cierre queda marcado como crítico en la auditoría, con tu nombre y
          lo que escribas aquí.
        </p>

        <div className="mt-5 flex gap-3">
          <button
            onClick={onCancelar}
            className="h-12 flex-1 border border-[var(--pos-divider)] titular text-[13px] tracking-[0.08em] text-[var(--pos-700)]"
          >
            VOLVER A CONTAR
          </button>
          <button
            disabled={justificacion.trim().length < 5}
            onClick={() => onFirmar(justificacion.trim())}
            className="h-12 flex-1 bg-[var(--pos-accent)] titular text-[13px] font-semibold tracking-[0.08em] text-white disabled:bg-[var(--pos-divider)] disabled:text-[var(--pos-muted)]"
          >
            CERRAR CON DIFERENCIA
          </button>
        </div>
      </Panel>
    </div>
  );
}

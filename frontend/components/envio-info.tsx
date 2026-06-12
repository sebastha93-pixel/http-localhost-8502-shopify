"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";
import { Pedido } from "@/lib/types";
import { trackingUrl } from "@/lib/carriers";
import {
  Truck, ExternalLink, Copy, Check, Edit3, Loader2, X,
} from "lucide-react";

interface CarrierDef {
  name: string;
  short: string;
  url: string;
  color: string;
  match: RegExp;
}

// Mapeo de transportadoras conocidas → URL y matcher de nombre
const CARRIERS: CarrierDef[] = [
  { name: "Coordinadora",     short: "Coord.",  url: "https://coordinadora.com/portafolio-de-servicios/servicios-en-linea/rastreo-de-mercancia/", color: "bg-rust",    match: /coordinadora/i },
  { name: "Envía",            short: "Envía",   url: "https://www.envia.co/rastreo-de-envios",                                                       color: "bg-navy",    match: /env[ií]a/i },
  { name: "Servientrega",     short: "Servi.",  url: "https://www.servientrega.com/wps/portal/inicio/rastrea-tu-envio",                              color: "bg-khaki",   match: /servientrega/i },
];


export function EnvioInfo({ pedido }: { pedido: Pedido }) {
  const { user } = useAuth();
  const canWrite = puedeEscribir(user);
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const carrier = (pedido.carrier_real as string) || "";
  const guia = (pedido.guia_real as string) || "";
  const orden = pedido.orden_tienda || pedido.orden_melonn;
  const matched = CARRIERS.find((c) => c.match.test(carrier));

  const copyGuia = async () => {
    if (!guia) return;
    try {
      await navigator.clipboard.writeText(guia);
      setCopied("guia");
      setTimeout(() => setCopied(null), 2500);
    } catch {}
  };

  const openCarrier = async (c: CarrierDef, useGuia: boolean) => {
    const text = useGuia && guia ? guia : orden;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(c.name);
      setTimeout(() => setCopied(null), 2500);
    } catch {}
    window.open(c.url, "_blank", "noopener,noreferrer");
  };

  if (editing && canWrite) {
    return (
      <EditarEnvio
        pedido={pedido}
        onClose={() => setEditing(false)}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ["melonn"] });
          setEditing(false);
        }}
      />
    );
  }

  return (
    <div className="rounded-md border border-border bg-white p-3 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">
          Envío y rastreo
        </p>
        {canWrite && (
          <button
            onClick={() => setEditing(true)}
            className="inline-flex items-center gap-1 text-[0.7rem] font-semibold text-steel hover:text-navy"
          >
            <Edit3 className="h-3 w-3" />
            {carrier || guia ? "Editar" : "Agregar guía"}
          </button>
        )}
      </div>

      {/* Datos reales si están guardados */}
      {(carrier || guia) && (
        <div className="rounded-md bg-concrete/40 px-3 py-2 space-y-1">
          {carrier && (
            <div className="flex items-center gap-2 text-sm">
              <Truck className="h-3.5 w-3.5 text-graphite flex-none" />
              <span className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Transportadora</span>
              <span className="text-ink font-semibold">{carrier}</span>
            </div>
          )}
          {guia && (
            <div className="flex items-center gap-2 text-sm">
              <span className="h-3.5 w-3.5 flex-none" />
              <span className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Guía</span>
              {(() => {
                const url = trackingUrl(carrier, guia);
                if (url) {
                  return (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={copyGuia}
                      className="text-navy font-semibold tabular-nums underline decoration-dotted hover:text-ink inline-flex items-center gap-1"
                      title={`Rastrear ${guia} en ${carrier}`}
                    >
                      {guia}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  );
                }
                return <span className="text-ink font-semibold tabular-nums">{guia}</span>;
              })()}
              <button
                onClick={copyGuia}
                className="ml-1 text-graphite hover:text-ink"
                title="Copiar número de guía"
              >
                {copied === "guia" ? <Check className="h-3.5 w-3.5 text-teal" /> : <Copy className="h-3.5 w-3.5" />}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Botones de carrier — destacado el matched si hay */}
      <div>
        {!carrier && !guia && (
          <p className="text-[0.65rem] text-graphite mb-1.5">
            Click copia # de orden y abre el carrier. Si guardas la transportadora real, el botón usa # de guía.
          </p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {CARRIERS.map((c) => {
            const isMatch = matched?.name === c.name;
            return (
              <button
                key={c.name}
                onClick={() => openCarrier(c, isMatch)}
                className={`inline-flex items-center gap-1.5 rounded-md ${c.color} hover:opacity-90 px-2.5 py-1.5 text-xs font-semibold text-white transition-opacity ${isMatch ? "ring-2 ring-ink ring-offset-1" : ""}`}
                title={
                  isMatch && guia
                    ? `Abrir ${c.name} y copiar guía ${guia}`
                    : `Abrir ${c.name} y copiar orden ${orden}`
                }
              >
                <Truck className="h-3 w-3" />
                {c.short}
                {isMatch && <Check className="h-2.5 w-2.5" />}
              </button>
            );
          })}

          {pedido.link_guia && (
            <a
              href={pedido.link_guia as string}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-white hover:bg-concrete px-2.5 py-1.5 text-xs font-semibold text-graphite"
              title="Ver en Melonn (origen)"
            >
              <ExternalLink className="h-3 w-3" />
              Melonn
            </a>
          )}
        </div>
        {copied && copied !== "guia" && (
          <p className="text-[0.65rem] text-teal mt-1.5 font-semibold flex items-center gap-1">
            <Check className="h-3 w-3" />
            {matched?.name === copied
              ? `Guía ${guia} copiada · abrió ${copied}`
              : `Orden ${orden} copiada · abrió ${copied}`}
          </p>
        )}
      </div>
    </div>
  );
}


function EditarEnvio({
  pedido, onClose, onSaved,
}: { pedido: Pedido; onClose: () => void; onSaved: () => void }) {
  const orden = pedido.orden_tienda || pedido.orden_melonn;
  const [carrier, setCarrier] = useState((pedido.carrier_real as string) || "");
  const [guia, setGuia] = useState((pedido.guia_real as string) || "");

  const mut = useMutation({
    mutationFn: () => api.post(`/api/pedidos/${orden}/guia`, { carrier, guia }),
    onSuccess: onSaved,
  });

  return (
    <div className="rounded-md border border-steel/40 bg-steel/5 p-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">
          Editar datos de envío
        </p>
        <button onClick={onClose} className="text-graphite hover:text-ink">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="space-y-2">
        <div>
          <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1">
            Transportadora
          </label>
          <select
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
          >
            <option value="">— Seleccionar —</option>
            <option value="Coordinadora Mercantil">Coordinadora Mercantil</option>
            <option value="Envía">Envía</option>
            <option value="Interrapidísimo">Interrapidísimo</option>
            <option value="TCC">TCC</option>
            <option value="Servientrega">Servientrega</option>
            <option value="Otra">Otra…</option>
          </select>
        </div>

        {carrier === "Otra" && (
          <div>
            <input
              autoFocus
              placeholder="Nombre exacto de la transportadora"
              onChange={(e) => setCarrier(e.target.value)}
              className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
            />
          </div>
        )}

        <div>
          <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1">
            Número de guía
          </label>
          <input
            value={guia}
            onChange={(e) => setGuia(e.target.value)}
            placeholder="ej. 16143078876"
            className="w-full rounded-md border border-border bg-white px-3 py-2 text-sm tabular-nums text-ink focus:outline-none focus:ring-2 focus:ring-steel"
          />
        </div>
      </div>

      <p className="text-[0.6rem] text-graphite italic">
        Estos datos los obtienes del tracking de Melonn. Una vez guardados,
        cualquier usuario verá la info y podrá rastrear directo con el carrier.
      </p>

      <div className="flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-border bg-white px-3 py-1.5 text-xs font-semibold text-graphite hover:bg-concrete"
        >
          Cancelar
        </button>
        <button
          onClick={() => mut.mutate()}
          disabled={mut.isPending || (!carrier && !guia)}
          className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50"
        >
          {mut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Guardar"}
        </button>
      </div>
    </div>
  );
}

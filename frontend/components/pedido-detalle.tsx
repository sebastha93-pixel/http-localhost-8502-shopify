"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Pedido } from "@/lib/types";
import { useAuth } from "@/components/auth-provider";
import { puedeEscribir } from "@/lib/auth";
import { formatMoneyShort, fmtDateTime } from "@/lib/utils";
import {
  Phone, MessageCircle, ExternalLink, Send, FileText, AlertCircle,
  PhoneCall, CheckCircle, Truck, RotateCcw, X, Loader2, MapPin, User, Calendar,
  Edit3,
} from "lucide-react";

interface Accion {
  tipo: string;
  descripcion: string;
  autor: string;
  creada_en?: string;
}

interface Nota {
  autor: string;
  nota: string;
  creada_en?: string;
}

const QUICK_ACTIONS: Array<{ tipo: string; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { tipo: "llamada",                 label: "Llamado",        icon: PhoneCall },
  { tipo: "whatsapp",                label: "WhatsApp",       icon: MessageCircle },
  { tipo: "acuerdo_cliente",         label: "Acuerdo cliente",icon: CheckCircle },
  { tipo: "gestion_transportadora",  label: "Gestión trans.", icon: Truck },
  { tipo: "escalado",                label: "Escalado",       icon: AlertCircle },
  { tipo: "resuelto",                label: "Resuelto",       icon: CheckCircle },
  { tipo: "devolucion",              label: "Devolución",     icon: RotateCcw },
];

export function PedidoDetalle({ pedido, onClose }: { pedido: Pedido; onClose: () => void }) {
  const orden = pedido.orden_melonn || pedido.orden_tienda;
  const qc = useQueryClient();
  const { user } = useAuth();
  const canWrite = puedeEscribir(user);

  const accionesQ = useQuery({
    queryKey: ["acciones", orden],
    queryFn: () => api.get<Accion[]>(`/api/pedidos/${orden}/acciones`),
    enabled: !!orden,
  });

  const notasQ = useQuery({
    queryKey: ["notas", orden],
    queryFn: () => api.get<Nota[]>(`/api/pedidos/${orden}/notas`),
    enabled: !!orden,
  });

  const accionMut = useMutation({
    mutationFn: (body: { tipo: string; descripcion: string }) =>
      api.post<Accion>(`/api/pedidos/${orden}/acciones`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["acciones", orden] }),
  });

  const notaMut = useMutation({
    mutationFn: (body: { nota: string }) =>
      api.post<Nota>(`/api/pedidos/${orden}/notas`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notas", orden] }),
  });

  const [notaTxt, setNotaTxt] = useState("");
  const [editandoDatos, setEditandoDatos] = useState(false);

  const overrideMut = useMutation({
    mutationFn: (body: { nombre: string; telefono: string; ciudad: string }) =>
      api.post(`/api/pedidos/${orden}/override`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["melonn"] });
      setEditandoDatos(false);
    },
  });

  const registrarAccion = (tipo: string, label: string) => {
    accionMut.mutate({ tipo, descripcion: label });
  };

  const guardarNota = () => {
    if (!notaTxt.trim()) return;
    notaMut.mutate({ nota: notaTxt.trim() });
    setNotaTxt("");
  };

  // Timeline unificado (acciones + notas) ordenado por fecha desc
  const timeline = [
    ...(accionesQ.data || []).map((a) => ({ ...a, kind: "accion" as const })),
    ...(notasQ.data || []).map((n) => ({ ...n, kind: "nota" as const, tipo: "nota", descripcion: n.nota })),
  ].sort((a, b) => (b.creada_en || "").localeCompare(a.creada_en || ""));

  const tel = (pedido.telefono_comprador || "").replace(/\D/g, "");
  const currentUser = user?.nombre || "Sin identificar";

  return (
    <div className="bg-white border-2 border-steel/30 rounded-lg shadow-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 bg-gradient-to-r from-ink to-[#1A2B2F] text-white">
        <div className="flex items-center gap-3">
          <div>
            <p className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-steel/70">Orden</p>
            <p className="text-lg font-bold">{pedido.orden_tienda || pedido.orden_melonn}</p>
          </div>
          {pedido.orden_tienda && pedido.orden_melonn && pedido.orden_tienda !== pedido.orden_melonn && (
            <div className="text-xs text-steel/70">Melonn: {pedido.orden_melonn}</div>
          )}
          {pedido.link_guia && (
            <a
              href={pedido.link_guia as string}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 ml-3 rounded-md bg-white/10 hover:bg-white/20 px-3 py-1.5 text-xs font-semibold text-white"
            >
              <ExternalLink className="h-3 w-3" /> Ver guía Melonn
            </a>
          )}
        </div>
        <button onClick={onClose} className="text-white/60 hover:text-white">
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-0">
        {/* Columna izquierda — Info del pedido */}
        <div className="p-5 border-r border-border space-y-4">
          {editandoDatos && canWrite ? (
            <EditarDatos
              pedido={pedido}
              onCancel={() => setEditandoDatos(false)}
              onSubmit={(d) => overrideMut.mutate(d)}
              pending={overrideMut.isPending}
            />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <InfoRow icon={User}     label="Cliente"   value={pedido.nombre_comprador || "—"} />
                <InfoRow icon={MapPin}   label="Ciudad"    value={`${pedido.ciudad_destino || "—"} · ${pedido.zona || "—"}`} />
                <InfoRow icon={Calendar} label="Días"      value={`${pedido.dias_real ?? 0}d / SLA ${pedido.sla_critico ?? 0}`} />
                <InfoRow icon={Truck}    label="Transp."   value={pedido.transportadora || "—"} />
              </div>
              {canWrite && (
                <button
                  onClick={() => setEditandoDatos(true)}
                  className="inline-flex items-center gap-1.5 text-xs text-steel hover:text-navy font-semibold"
                >
                  <Edit3 className="h-3 w-3" />
                  {pedido.nombre_comprador ? "Editar datos cliente" : "Agregar datos cliente"}
                </button>
              )}
            </>
          )}

          {tel && (
            <div className="flex items-center gap-2 rounded-md bg-concrete/50 px-3 py-2">
              <span className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Contactar</span>
              <a href={`tel:+57${tel}`} className="inline-flex items-center gap-1 text-sm font-semibold text-ink hover:text-navy">
                <Phone className="h-3.5 w-3.5" /> Llamar
              </a>
              <a
                href={`https://wa.me/57${tel}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm font-semibold text-teal hover:text-ink"
              >
                <MessageCircle className="h-3.5 w-3.5" /> WhatsApp
              </a>
              <span className="ml-auto text-sm tabular-nums text-graphite">{pedido.telefono_comprador}</span>
            </div>
          )}

          {pedido.valor_num ? (
            <div className="rounded-md bg-navy/5 border border-navy/20 px-3 py-2">
              <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Valor COD</p>
              <p className="text-lg font-bold text-navy">{formatMoneyShort(pedido.valor_num)}</p>
            </div>
          ) : null}

          {pedido.motivo_riesgo && pedido.motivo_riesgo !== "—" && (
            <div className="rounded-md bg-rust/5 border border-rust/20 px-3 py-2">
              <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">Motivo de riesgo</p>
              <p className="text-sm font-semibold text-ink">{pedido.motivo_riesgo}</p>
            </div>
          )}

          {/* Acciones rápidas — solo si tiene permisos */}
          {canWrite && (
            <div>
              <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-2">Marcar acción</p>
              <p className="text-[0.65rem] text-graphite mb-2">
                Registrado como: <span className="font-semibold text-ink">{currentUser}</span>
              </p>
              <div className="flex flex-wrap gap-2">
                {QUICK_ACTIONS.map((a) => {
                  const Icon = a.icon;
                  return (
                    <button
                      key={a.tipo}
                      onClick={() => registrarAccion(a.tipo, a.label)}
                      disabled={accionMut.isPending}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-white px-3 py-1.5 text-xs font-semibold text-ink hover:bg-concrete hover:border-steel transition-colors disabled:opacity-50"
                    >
                      <Icon className="h-3 w-3" />
                      {a.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Nota libre — solo si tiene permisos */}
          {canWrite && (
            <div>
              <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-2">Agregar nota</p>
              <div className="flex gap-2">
                <input
                  value={notaTxt}
                  onChange={(e) => setNotaTxt(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && guardarNota()}
                  placeholder="Comentario, contexto, observación..."
                  className="flex-1 rounded-md border border-border bg-white px-3 py-2 text-sm text-ink placeholder:text-graphite/60 focus:outline-none focus:ring-2 focus:ring-steel"
                />
                <button
                  onClick={guardarNota}
                  disabled={!notaTxt.trim() || notaMut.isPending}
                  className="rounded-md bg-ink px-3 py-2 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50"
                >
                  {notaMut.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
                </button>
              </div>
            </div>
          )}

          {!canWrite && (
            <p className="text-xs text-graphite italic">
              Tu rol es solo lectura. Para registrar acciones contacta al administrador.
            </p>
          )}
        </div>

        {/* Columna derecha — Timeline */}
        <div className="p-5 bg-concrete/30">
          <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-3">
            Avance · Timeline ({timeline.length})
          </p>

          {accionesQ.isLoading || notasQ.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-graphite py-8 justify-center">
              <Loader2 className="h-4 w-4 animate-spin" /> Cargando avance...
            </div>
          ) : timeline.length === 0 ? (
            <div className="text-center py-8 text-sm text-graphite">
              <FileText className="h-6 w-6 mx-auto mb-2 text-graphite/50" />
              Sin acciones ni notas registradas todavía
            </div>
          ) : (
            <div className="space-y-3 max-h-[420px] overflow-y-auto">
              {timeline.map((t, i) => (
                <TimelineItem key={i} item={t} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function TimelineItem({ item }: { item: { tipo: string; descripcion: string; autor: string; creada_en?: string; kind: "accion" | "nota" } }) {
  const fecha = fmtDateTime(item.creada_en);

  const isNota = item.kind === "nota";

  return (
    <div className="flex gap-3">
      <div className={`flex-none w-1 rounded-full ${isNota ? "bg-graphite/30" : "bg-steel"}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={`text-[0.6rem] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
            isNota ? "bg-graphite/10 text-graphite" : "bg-steel/15 text-navy"
          }`}>
            {isNota ? "NOTA" : item.tipo.replace("_", " ").toUpperCase()}
          </span>
          <span className="text-[0.65rem] text-graphite tabular-nums">{fecha}</span>
        </div>
        <p className="text-sm text-ink">{item.descripcion}</p>
        <p className="text-[0.65rem] text-graphite mt-0.5">por <span className="font-semibold">{item.autor}</span></p>
      </div>
    </div>
  );
}

function EditarDatos({
  pedido, onCancel, onSubmit, pending,
}: {
  pedido: Pedido;
  onCancel: () => void;
  onSubmit: (d: { nombre: string; telefono: string; ciudad: string }) => void;
  pending: boolean;
}) {
  const [nombre, setNombre]   = useState(pedido.nombre_comprador || "");
  const [telefono, setTel]    = useState(pedido.telefono_comprador || "");
  const [ciudad, setCiudad]   = useState(pedido.ciudad_destino || "");

  return (
    <div className="rounded-md border border-steel/30 bg-steel/5 p-3 space-y-2">
      <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1">
        Editar datos manuales (override)
      </p>
      <div className="grid grid-cols-1 gap-2">
        <input
          value={nombre}
          onChange={(e) => setNombre(e.target.value)}
          placeholder="Nombre del cliente"
          className="rounded-md border border-border bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-steel"
        />
        <input
          value={telefono}
          onChange={(e) => setTel(e.target.value)}
          placeholder="Teléfono (solo dígitos)"
          className="rounded-md border border-border bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-steel"
        />
        <input
          value={ciudad}
          onChange={(e) => setCiudad(e.target.value)}
          placeholder="Ciudad"
          className="rounded-md border border-border bg-white px-3 py-1.5 text-sm uppercase focus:outline-none focus:ring-2 focus:ring-steel"
        />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button
          onClick={onCancel}
          className="rounded-md border border-border bg-white px-3 py-1.5 text-xs font-semibold text-graphite hover:bg-concrete"
        >
          Cancelar
        </button>
        <button
          onClick={() => onSubmit({ nombre, telefono, ciudad })}
          disabled={pending || (!nombre && !telefono && !ciudad)}
          className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50"
        >
          {pending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Guardar"}
        </button>
      </div>
      <p className="text-[0.6rem] text-graphite italic">
        Los datos manuales quedan registrados con tu nombre como autor y se aplican en todas las páginas.
      </p>
    </div>
  );
}


function InfoRow({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <Icon className="h-3.5 w-3.5 text-graphite mt-0.5 flex-none" />
      <div className="min-w-0">
        <p className="text-[0.6rem] font-bold uppercase tracking-wider text-graphite">{label}</p>
        <p className="text-sm font-semibold text-ink truncate">{value}</p>
      </div>
    </div>
  );
}

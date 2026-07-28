"use client";

/**
 * Planificador de turnos — la grilla semanal de tienda.
 *
 * Las tiendas abren 62 y 65 horas semanales. Ninguna persona puede trabajar
 * eso: el tope legal es 42 h. Aquí se decide quién cubre qué franja.
 *
 * La pantalla AVISA cuando alguien pasa de 42 h, pero no bloquea. A veces hay
 * una razón para una semana larga; lo inaceptable es que nadie se entere.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState, ErrorState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  AlertTriangle, ChevronLeft, ChevronRight, Copy, Loader2, Save,
} from "lucide-react";
import { Empleado, hoyISO, minutosAHoras } from "@/lib/personal";

interface Turno {
  empleado_id: string;
  fecha: string;
  hora_inicio?: string | null;
  hora_fin?: string | null;
  es_dia_laboral: boolean;
  minutos_esperados: number;
  sede_id?: string | null;
}

interface Semana {
  lunes: string;
  domingo: string;
  dias: string[];
  tope_semanal_horas: number;
  por_empleado: Record<string, {
    turnos: Record<string, Turno>;
    minutos: number;
    horas: number;
    excede_tope: boolean;
    minutos_sobre_tope: number;
  }>;
  apertura?: {
    dia_semana: number; es_dia_laboral: boolean;
    hora_inicio?: string | null; hora_fin?: string | null;
  }[];
}

const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

/** Celda en edición: "HH:MM" o null para descanso. */
type Celda = { inicio: string; fin: string } | "descanso" | undefined;

function lunesDe(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

function sumar(iso: string, dias: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + dias);
  return d.toISOString().slice(0, 10);
}

function minutosDe(c: Celda): number {
  if (!c || c === "descanso") return 0;
  const [h1, m1] = c.inicio.split(":").map(Number);
  const [h2, m2] = c.fin.split(":").map(Number);
  if ([h1, m1, h2, m2].some(Number.isNaN)) return 0;
  let t = h2 * 60 + m2 - (h1 * 60 + m1);
  if (t < 0) t += 24 * 60;                       // turno que cruza medianoche
  return Math.max(0, t);
}

export default function TurnosPage() {
  const qc = useQueryClient();
  const [lunes, setLunes] = useState(() => lunesDe(hoyISO()));
  const [sedeId, setSedeId] = useState("");
  const [cambios, setCambios] = useState<Record<string, Celda>>({});
  const [msg, setMsg] = useState<{ tipo: "ok" | "error" | "aviso"; texto: string } | null>(null);

  const sedesQ = useQuery<{ sedes: { id: string; nombre: string }[] }>({
    queryKey: ["personal", "sedes"],
    queryFn: () => api.get("/api/personal/sedes?solo_activas=true"),
  });

  const empQ = useQuery<{ empleados: Empleado[] }>({
    queryKey: ["personal", "empleados", "vigentes"],
    queryFn: () => api.get("/api/personal/empleados?solo_vigentes=true&limit=500"),
  });

  const semQ = useQuery<Semana>({
    queryKey: ["personal", "turnos", lunes, sedeId],
    queryFn: () => {
      const p = new URLSearchParams({ lunes });
      if (sedeId) p.set("sede_id", sedeId);
      return api.get(`/api/personal/turnos?${p}`);
    },
  });

  // Al cambiar de semana o de sede, los cambios sin guardar dejan de aplicar.
  useEffect(() => { setCambios({}); setMsg(null); }, [lunes, sedeId]);

  // Quién aparece en la grilla: los de la sede elegida más los que rotan
  // (la supernumeraria no tiene sede fija y debe poder planificarse en ambas).
  const empleados = useMemo(() => {
    const todos = empQ.data?.empleados ?? [];
    if (!sedeId) return todos.filter((e) => e.rota_entre_sedes || e.sede_id);
    return todos.filter((e) => e.sede_id === sedeId || e.rota_entre_sedes);
  }, [empQ.data, sedeId]);

  const clave = (emp: string, dia: string) => `${emp}|${dia}`;

  const celda = (emp: string, dia: string): Celda => {
    const k = clave(emp, dia);
    if (k in cambios) return cambios[k];
    const t = semQ.data?.por_empleado[emp]?.turnos[dia];
    if (!t) return undefined;
    if (!t.es_dia_laboral) return "descanso";
    return { inicio: (t.hora_inicio ?? "").slice(0, 5),
             fin: (t.hora_fin ?? "").slice(0, 5) };
  };

  /** Horas de la semana ya contando lo que está sin guardar. */
  const horasDe = (emp: string): number => {
    const dias = semQ.data?.dias ?? [];
    return dias.reduce((s, d) => s + minutosDe(celda(emp, d)), 0) / 60;
  };

  const guardar = useMutation({
    mutationFn: () => {
      const turnos = Object.entries(cambios)
        .map(([k, c]) => {
          const [empleado_id, fecha] = k.split("|");
          if (c === "descanso")
            return { empleado_id, fecha, es_dia_laboral: false,
                     sede_id: sedeId || null };
          if (!c || !c.inicio || !c.fin) return null;
          return { empleado_id, fecha, es_dia_laboral: true,
                   hora_inicio: c.inicio, hora_fin: c.fin,
                   sede_id: sedeId || null };
        })
        .filter(Boolean);
      if (turnos.length === 0) throw new Error("No hay cambios por guardar");
      return api.post("/api/personal/turnos", { turnos });
    },
    onSuccess: (r: any) => {
      setCambios({});
      qc.invalidateQueries({ queryKey: ["personal", "turnos"] });
      if (r.avisos?.length) {
        setMsg({ tipo: "aviso",
                 texto: `Guardado, pero ${r.avisos.length} persona(s) exceden el tope: ` +
                        r.avisos.map((a: any) => `${a.horas} h`).join(", ") });
      } else {
        setMsg({ tipo: "ok", texto: `${r.guardados} turno(s) guardados.` });
      }
    },
    onError: (e: Error) => setMsg({ tipo: "error", texto: e.message }),
  });

  const copiar = useMutation({
    mutationFn: () => api.post("/api/personal/turnos/copiar", {
      origen: sumar(lunes, -7), destino: lunes, sede_id: sedeId || null,
    }),
    onSuccess: (r: any) => {
      qc.invalidateQueries({ queryKey: ["personal", "turnos"] });
      setMsg({ tipo: "ok", texto: `${r.guardados} turno(s) copiados de la semana pasada.` });
    },
    onError: (e: Error) => setMsg({ tipo: "error", texto: e.message }),
  });

  if (semQ.isLoading || empQ.isLoading) return <LoadingState label="Cargando la semana…" />;
  if (semQ.isError) return <ErrorState error={semQ.error} onRetry={() => semQ.refetch()} />;

  const dias = semQ.data?.dias ?? [];
  const hayCambios = Object.keys(cambios).length > 0;
  const apertura = semQ.data?.apertura ?? [];

  return (
    <PageShell
      title="Turnos"
      subtitle={`Semana del ${lunes} al ${semQ.data?.domingo}`}
      isFetching={semQ.isFetching}
      onRefresh={() => semQ.refetch()}
    >
      {/* ── Controles ────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-4">
          <div className="flex items-center gap-1">
            <button onClick={() => setLunes(sumar(lunes, -7))}
              className="rounded-sm border border-border bg-card p-1.5 text-graphite hover:bg-cloud">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button onClick={() => setLunes(lunesDe(hoyISO()))}
              className="rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-medium text-graphite hover:bg-cloud">
              Esta semana
            </button>
            <button onClick={() => setLunes(sumar(lunes, 7))}
              className="rounded-sm border border-border bg-card p-1.5 text-graphite hover:bg-cloud">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          <select value={sedeId} onChange={(e) => setSedeId(e.target.value)}
            className="rounded-sm border border-border bg-card px-2 py-1.5 text-sm text-ink-900">
            <option value="">Todas las sedes</option>
            {(sedesQ.data?.sedes ?? []).map((s) => (
              <option key={s.id} value={s.id}>{s.nombre}</option>
            ))}
          </select>

          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => copiar.mutate()} disabled={copiar.isPending}
              title="Replica la planificación de la semana anterior"
              className="inline-flex items-center gap-1 rounded-sm border border-border bg-card px-3 py-1.5 text-xs font-medium text-graphite hover:bg-cloud disabled:opacity-50">
              {copiar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                : <Copy className="h-3.5 w-3.5" />}
              Copiar semana anterior
            </button>
            <button onClick={() => guardar.mutate()}
              disabled={!hayCambios || guardar.isPending}
              className="inline-flex items-center gap-1.5 rounded-sm bg-navy-600 px-4 py-1.5 text-xs font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-40">
              {guardar.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                 : <Save className="h-3.5 w-3.5" />}
              Guardar{hayCambios ? ` (${Object.keys(cambios).length})` : ""}
            </button>
          </div>
        </CardContent>
      </Card>

      {msg && (
        <p role="alert" className={`mt-3 rounded-sm border px-3 py-2 text-sm ${
          msg.tipo === "error" ? "border-terracotta/25 bg-terracotta/10 text-terracotta"
          : msg.tipo === "aviso" ? "border-ochre/25 bg-ochre/10 text-ochre"
          : "border-sage/25 bg-sage/10 text-sage"}`}>
          {msg.texto}
        </p>
      )}

      {/* ── Referencia: horas de apertura ────────────────────────────── */}
      {apertura.length > 0 && (
        <Card className="mt-3">
          <CardContent className="py-3">
            <p className="section-label">Horario de apertura del local</p>
            <p className="mt-1 text-xs text-graphite">
              Es el rango que hay que cubrir entre todos — no la jornada de una
              persona.
            </p>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
              {apertura.map((d) => (
                <span key={d.dia_semana} className="text-graphite">
                  <span className="font-medium text-ink-900">{DIAS[d.dia_semana]}</span>{" "}
                  {d.es_dia_laboral
                    ? `${(d.hora_inicio ?? "").slice(0, 5)}–${(d.hora_fin ?? "").slice(0, 5)}`
                    : "cerrado"}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Grilla ───────────────────────────────────────────────────── */}
      <Card className="mt-4">
        <CardContent className="p-0">
          {empleados.length === 0 ? (
            <p className="px-5 py-8 text-sm text-graphite">
              No hay empleados en esta sede. Elige otra o revisa las fichas.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border">
                  <tr className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-graphite">
                    <th className="sticky left-0 z-10 bg-card px-4 py-2.5 text-left">
                      Empleado
                    </th>
                    {dias.map((d, i) => (
                      <th key={d} className="px-2 py-2.5 text-center">
                        {DIAS[i]}<br />
                        <span className="font-normal normal-case tracking-normal">
                          {d.slice(8)}
                        </span>
                      </th>
                    ))}
                    <th className="px-4 py-2.5 text-right">Semana</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {empleados.map((e) => {
                    const horas = horasDe(e.id);
                    const excede = horas > (semQ.data?.tope_semanal_horas ?? 42);
                    return (
                      <tr key={e.id}>
                        <td className="sticky left-0 z-10 bg-card px-4 py-2 text-ink-900">
                          <div className="flex items-center gap-1.5">
                            <span className="whitespace-nowrap">
                              {e.nombre_completo.split(" ").slice(0, 2).join(" ")}
                            </span>
                            {e.rota_entre_sedes && (
                              <Badge tone="info">rota</Badge>
                            )}
                          </div>
                        </td>
                        {dias.map((d) => (
                          <td key={d} className="px-1 py-1.5 text-center align-top">
                            <CeldaTurno
                              valor={celda(e.id, d)}
                              onChange={(v) =>
                                setCambios({ ...cambios, [clave(e.id, d)]: v })}
                            />
                          </td>
                        ))}
                        <td className="px-4 py-2 text-right">
                          <span className={`tabular-nums ${
                            excede ? "font-medium text-terracotta" : "text-ink-900"}`}>
                            {horas.toFixed(1)} h
                          </span>
                          {excede && (
                            <AlertTriangle className="ml-1 inline h-3.5 w-3.5 text-terracotta" />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="mt-3 text-xs text-graphite">
        El tope legal es {semQ.data?.tope_semanal_horas ?? 42} h/semana
        (Ley 2101 de 2021). La pantalla avisa si alguien lo pasa, pero no lo
        impide — la decisión es de quien planifica.
      </p>
    </PageShell>
  );
}

function CeldaTurno({
  valor, onChange,
}: { valor: Celda; onChange: (v: Celda) => void }) {
  const esDescanso = valor === "descanso";
  const t = valor && valor !== "descanso" ? valor : { inicio: "", fin: "" };

  return (
    <div className="flex min-w-[92px] flex-col gap-0.5">
      <input
        type="time" value={t.inicio} disabled={esDescanso}
        onChange={(e) => onChange({ ...t, inicio: e.target.value })}
        className="w-full rounded-sm border border-border bg-card px-1 py-0.5 text-center text-xs text-ink-900 disabled:bg-cloud disabled:text-graphite"
      />
      <input
        type="time" value={t.fin} disabled={esDescanso}
        onChange={(e) => onChange({ ...t, fin: e.target.value })}
        className="w-full rounded-sm border border-border bg-card px-1 py-0.5 text-center text-xs text-ink-900 disabled:bg-cloud disabled:text-graphite"
      />
      <button
        onClick={() => onChange(esDescanso ? { inicio: "", fin: "" } : "descanso")}
        title={esDescanso ? "Quitar el descanso" : "Marcar descanso planificado"}
        className={`rounded-sm border px-1 py-0.5 text-[0.6rem] font-medium transition-colors ${
          esDescanso
            ? "border-navy-600 bg-navy-600 text-white"
            : "border-border bg-card text-graphite hover:bg-cloud"
        }`}
      >
        descanso
      </button>
    </div>
  );
}

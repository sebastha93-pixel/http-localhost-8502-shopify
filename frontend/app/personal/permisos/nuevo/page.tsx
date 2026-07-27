"use client";

/**
 * Nueva solicitud de permiso.
 *
 * Sin librería de formularios, como el resto del repo: useState por campo,
 * validación dentro del mutationFn, error mostrado arriba.
 *
 * La pantalla dice de frente si el permiso es compensable, porque eso cambia
 * lo que le pasa al trabajador: tendrá que reponer el tiempo.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageShell, LoadingState } from "@/components/page-shell";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Loader2 } from "lucide-react";
import { CATEGORIA_PERMISO, TipoPermiso, hoyISO, minutosAHoras } from "@/lib/personal";

export default function NuevoPermisoPage() {
  const router = useRouter();
  const [tipoId, setTipoId] = useState("");
  const [fecha, setFecha] = useState(hoyISO());
  const [horaInicio, setHoraInicio] = useState("08:00");
  const [horaFin, setHoraFin] = useState("10:00");
  const [motivo, setMotivo] = useState("");
  const [err, setErr] = useState("");

  const tiposQ = useQuery<{ tipos: TipoPermiso[] }>({
    queryKey: ["personal", "permisos", "tipos"],
    queryFn: () => api.get("/api/personal/permisos/tipos"),
  });

  const tipo = tiposQ.data?.tipos.find((t) => t.id === tipoId);

  const minutos = useMemo(() => {
    const [h1, m1] = horaInicio.split(":").map(Number);
    const [h2, m2] = horaFin.split(":").map(Number);
    if ([h1, m1, h2, m2].some(Number.isNaN)) return 0;
    return Math.max(0, h2 * 60 + m2 - (h1 * 60 + m1));
  }, [horaInicio, horaFin]);

  const mut = useMutation({
    mutationFn: () => {
      if (!tipoId) throw new Error("Selecciona el tipo de permiso");
      if (minutos <= 0) throw new Error("La hora de fin debe ser posterior a la de inicio");
      if (motivo.trim().length < 3) throw new Error("Escribe el motivo del permiso");
      if (tipo?.minutos_max_solicitud && minutos > tipo.minutos_max_solicitud)
        throw new Error(
          `Este tipo permite máximo ${minutosAHoras(tipo.minutos_max_solicitud)}`);
      return api.post("/api/personal/permisos", {
        tipo_permiso_id: tipoId,
        inicio: `${fecha}T${horaInicio}:00`,
        fin: `${fecha}T${horaFin}:00`,
        motivo: motivo.trim(),
        enviar: true,
      });
    },
    onSuccess: () => router.push("/personal/mi-tiempo"),
    onError: (e: Error) => setErr(e.message),
  });

  if (tiposQ.isLoading) return <LoadingState label="Cargando tipos de permiso…" />;

  return (
    <PageShell title="Nueva solicitud de permiso"
               subtitle="Se envía a tu jefe y luego a Talento Humano">
      <form
        onSubmit={(e) => { e.preventDefault(); setErr(""); mut.mutate(); }}
        className="max-w-2xl space-y-4"
      >
        {err && (
          <p role="alert" className="rounded-sm border border-terracotta/25 bg-terracotta/10 px-3 py-2 text-sm text-terracotta">
            {err}
          </p>
        )}

        <Card>
          <CardContent className="space-y-4">
            <div>
              <label className="section-label" htmlFor="tipo">Tipo de permiso</label>
              <select
                id="tipo" value={tipoId} onChange={(e) => setTipoId(e.target.value)}
                className="mt-1.5 w-full rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900"
              >
                <option value="">Selecciona…</option>
                {(tiposQ.data?.tipos ?? []).map((t) => (
                  <option key={t.id} value={t.id}>{t.nombre}</option>
                ))}
              </select>

              {tipo && (
                <div className="mt-2 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="info">
                      {CATEGORIA_PERMISO[tipo.categoria] ?? tipo.categoria}
                    </Badge>
                    {tipo.requiere_soporte && (
                      <Badge tone="pendiente">Requiere soporte</Badge>
                    )}
                  </div>
                  {tipo.descripcion && (
                    <p className="text-xs text-graphite">{tipo.descripcion}</p>
                  )}
                  {tipo.base_legal && (
                    <p className="text-xs text-graphite">Base legal: {tipo.base_legal}</p>
                  )}

                  {/* Decirlo de frente: este tiempo hay que reponerlo. */}
                  {tipo.es_compensable && (
                    <div className="flex items-start gap-2 rounded-sm border border-ochre/25 bg-ochre/10 px-3 py-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-ochre" />
                      <p className="text-xs text-ink-900">
                        Este permiso es <strong>compensable</strong>: si se aprueba,
                        tendrás que reponer el tiempo dentro del plazo que defina
                        Talento Humano.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <label className="text-xs text-graphite">
                Fecha
                <input type="date" value={fecha} onChange={(e) => setFecha(e.target.value)}
                       className="mt-1 block w-full rounded-sm border border-border bg-card px-2 py-1.5 text-sm text-ink-900" />
              </label>
              <label className="text-xs text-graphite">
                Desde
                <input type="time" value={horaInicio}
                       onChange={(e) => setHoraInicio(e.target.value)}
                       className="mt-1 block w-full rounded-sm border border-border bg-card px-2 py-1.5 text-sm text-ink-900" />
              </label>
              <label className="text-xs text-graphite">
                Hasta
                <input type="time" value={horaFin}
                       onChange={(e) => setHoraFin(e.target.value)}
                       className="mt-1 block w-full rounded-sm border border-border bg-card px-2 py-1.5 text-sm text-ink-900" />
              </label>
            </div>

            <p className="text-sm text-graphite">
              Tiempo solicitado:{" "}
              <span className="tabular-nums font-medium text-ink-900">
                {minutosAHoras(minutos)}
              </span>
            </p>

            <div>
              <label className="section-label" htmlFor="motivo">Motivo</label>
              <textarea
                id="motivo" rows={3} value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder="Explica brevemente por qué necesitas el permiso"
                className="mt-1.5 w-full rounded-sm border border-border bg-card px-3 py-2 text-sm text-ink-900"
              />
            </div>
          </CardContent>
        </Card>

        <div className="flex items-center gap-3">
          <button type="submit" disabled={mut.isPending}
            className="inline-flex items-center gap-2 rounded-sm bg-navy-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-navy-700 disabled:opacity-50">
            {mut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            Enviar solicitud
          </button>
          <button type="button" onClick={() => router.back()}
            className="text-sm text-graphite hover:text-ink-900">
            Cancelar
          </button>
        </div>
      </form>
    </PageShell>
  );
}

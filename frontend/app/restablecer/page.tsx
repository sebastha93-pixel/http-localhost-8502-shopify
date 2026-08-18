"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Lock, AlertCircle, CheckCircle2, ArrowLeft } from "lucide-react";

import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

const MINIMO = 8;

/**
 * Escribir la contraseña nueva, con el token que llegó por correo.
 *
 * ACÁ ES DONDE LA PERSONA ESCRIBE SU CLAVE, Y NADIE MÁS LA VE. Ni un admin, ni
 * quien mantiene el sistema: viaja del navegador al backend, se convierte en
 * hash bcrypt y el texto original se descarta. Es el punto de todo el flujo.
 */
export default function RestablecerPage() {
  const router = useRouter();

  // El token se lee del window y NO con useSearchParams, por lo mismo que
  // documenta la página de login: ese hook obliga a envolver la página en un
  // <Suspense> o el build de Next falla al prerenderizarla.
  const [token] = useState(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("token") || "";
  });

  const [password, setPassword] = useState("");
  const [repetir, setRepetir] = useState("");
  const [error, setError] = useState("");

  const mut = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/api/auth/restablecer", {
      token, password,
    }),
    onSuccess: () => {
      // Tres segundos para leer el "listo" y después al login, donde el
      // navegador va a ofrecer guardar la contraseña nueva.
      setTimeout(() => router.replace("/login"), 3000);
    },
    onError: (err: Error) => setError(err.message || "No se pudo cambiar la contraseña"),
  });

  const cortas = password.length > 0 && password.length < MINIMO;
  const distintas = repetir.length > 0 && password !== repetir;
  const listo = password.length >= MINIMO && password === repetir && !!token;

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-ink via-[#1A2B2F] to-black p-6">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <p className="text-[1.05rem] font-extrabold tracking-[0.35em] text-white leading-none">
            MALE&apos;DENIM
          </p>
          <p className="mt-1.5 text-[0.68rem] font-semibold tracking-[0.4em] text-steel/70 uppercase">
            Operating System
          </p>
        </div>

        <Card>
          <CardContent className="p-8">
            {/* Sin token no hay nada que hacer, y hay que decirlo antes de que
                la persona escriba una contraseña para nada. Pasa cuando el
                cliente de correo parte el enlace en dos líneas. */}
            {!token ? (
              <div className="space-y-3">
                <p className="flex items-center gap-2 text-sm font-semibold text-crimson">
                  <AlertCircle className="h-5 w-5 shrink-0" />
                  Enlace incompleto
                </p>
                <p className="text-sm leading-relaxed text-graphite">
                  Este enlace no trae el código. Suele pasar cuando el correo lo
                  parte en dos líneas: vuelve al correo y ábrelo de un solo clic,
                  o pide uno nuevo.
                </p>
                <Link
                  href="/recuperar"
                  className="inline-block text-xs font-semibold uppercase tracking-wider text-navy-600 hover:underline"
                >
                  Pedir un enlace nuevo
                </Link>
              </div>
            ) : mut.isSuccess ? (
              <div className="space-y-3">
                <p className="flex items-center gap-2 text-sm font-semibold text-teal">
                  <CheckCircle2 className="h-5 w-5 shrink-0" />
                  Contraseña cambiada
                </p>
                <p className="text-sm leading-relaxed text-graphite">
                  Ya puedes entrar con la nueva. Te llevamos al login…
                </p>
                <p className="text-xs leading-relaxed text-graphite">
                  Cuando entres, deja que el navegador <strong>actualice</strong> la
                  contraseña guardada — si conserva la vieja, el problema vuelve mañana.
                </p>
              </div>
            ) : (
              <>
                <h1 className="text-xl font-bold text-ink mb-1">Nueva contraseña</h1>
                <p className="text-sm text-graphite mb-6">
                  Escríbela dos veces. Mínimo {MINIMO} caracteres.
                </p>

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    setError("");
                    if (listo) mut.mutate();
                  }}
                  className="space-y-4"
                >
                  <div>
                    <label
                      htmlFor="password"
                      className="block text-[0.7rem] font-bold uppercase tracking-wider text-graphite mb-1.5"
                    >
                      Contraseña nueva
                    </label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
                      {/* `new-password` (y no `current-password`) es lo que le
                          dice al llavero del Mac que esto es una clave NUEVA:
                          así ofrece generarla y, sobre todo, ACTUALIZA la que
                          tenía guardada en vez de dejar la vieja. */}
                      <input
                        id="password"
                        name="new-password"
                        autoComplete="new-password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                        autoFocus
                        placeholder="••••••••"
                        className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
                      />
                    </div>
                    {cortas && (
                      <p className="mt-1 text-[0.7rem] text-crimson">
                        Le faltan {MINIMO - password.length} caracteres.
                      </p>
                    )}
                  </div>

                  <div>
                    <label
                      htmlFor="repetir"
                      className="block text-[0.7rem] font-bold uppercase tracking-wider text-graphite mb-1.5"
                    >
                      Repetirla
                    </label>
                    <div className="relative">
                      <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
                      <input
                        id="repetir"
                        name="repetir-password"
                        autoComplete="new-password"
                        type="password"
                        value={repetir}
                        onChange={(e) => setRepetir(e.target.value)}
                        required
                        placeholder="••••••••"
                        className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
                      />
                    </div>
                    {distintas && (
                      <p className="mt-1 text-[0.7rem] text-crimson">
                        Las dos no coinciden.
                      </p>
                    )}
                  </div>

                  {error && (
                    <div className="rounded-md bg-crimson/10 border border-crimson/30 px-3 py-2 text-sm text-crimson">
                      <p className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4 shrink-0" />
                        {error}
                      </p>
                      <p className="mt-1.5 pl-6 text-[0.75rem]">
                        <Link href="/recuperar" className="font-semibold underline">
                          Pedir un enlace nuevo
                        </Link>
                      </p>
                    </div>
                  )}

                  <button
                    type="submit"
                    disabled={!listo || mut.isPending}
                    className="w-full rounded-md bg-ink py-2.5 text-sm font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50 transition-colors"
                  >
                    {mut.isPending ? "Guardando…" : "Cambiar contraseña"}
                  </button>

                  <Link
                    href="/login"
                    className="flex items-center justify-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-graphite hover:text-ink"
                  >
                    <ArrowLeft className="h-3.5 w-3.5" /> Volver al login
                  </Link>
                </form>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

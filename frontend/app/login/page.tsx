"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { homePath } from "@/lib/nav";
import { User, setToken } from "@/lib/auth";
import { Card, CardContent } from "@/components/ui/card";
import { Loader2, Lock, Mail, AlertCircle } from "lucide-react";

interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export default function LoginPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  // Si la sesión venció a media tarea, api.ts nos manda acá con ?volver=…
  // para no perder la pantalla en la que estaba trabajando la persona.
  //
  // Se lee del window y NO con useSearchParams a propósito: ese hook obliga a
  // envolver la página en un <Suspense> o el build de Next falla al
  // prerenderizarla.
  //
  // Solo se aceptan rutas internas: un `volver` con http:// o //otro-host
  // sería un redirect abierto hacia un sitio ajeno.
  const [volver] = useState(() => {
    if (typeof window === "undefined") return "";
    const v = new URLSearchParams(window.location.search).get("volver") || "";
    return v.startsWith("/") && !v.startsWith("//") ? v : "";
  });

  const mut = useMutation({
    // El correo se normaliza ACÁ, no solo en el backend. Cuando el gestor de
    // contraseñas del Mac rellena el campo suele dejar un espacio al final, y
    // ese espacio hace que Pydantic rechace el correo con un 422 antes de que
    // el backend llegue a limpiarlo. La contraseña NO se toca: un espacio
    // puede ser parte legítima de ella y recortarla rompería a quien lo use.
    mutationFn: () => api.post<LoginResponse>("/api/auth/login", {
      email: email.trim().toLowerCase(),
      password,
    }),
    onSuccess: (data) => {
      setToken(data.access_token);
      qc.setQueryData(["auth", "me"], data.user);
      router.replace(volver || homePath(data.user));
    },
    onError: (err: Error) => {
      setError(err.message || "Error al iniciar sesión");
    },
  });

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
            <h1 className="text-xl font-bold text-ink mb-1">Iniciar sesión</h1>
            <p className="text-sm text-graphite mb-6">Acceso al panel operativo</p>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                setError("");
                mut.mutate();
              }}
              className="space-y-4"
            >
              <div>
                <label htmlFor="email" className="block text-[0.7rem] font-bold uppercase tracking-wider text-graphite mb-1.5">
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
                  {/* `name` + `autoComplete` no son decoración: son lo que el
                      gestor de contraseñas usa para saber QUÉ pareja
                      correo/clave rellenar. Sin ellos Safari y Chrome
                      adivinan, y con varias cuentas guardadas del mismo sitio
                      pueden meter el correo de una y la clave de otra — que se
                      ve exactamente como "credenciales inválidas" con la clave
                      bien guardada. También es lo que le permite al navegador
                      ACTUALIZAR la clave guardada cuando alguien la cambia. */}
                  <input
                    id="email"
                    name="email"
                    autoComplete="username"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoFocus
                    placeholder="tu@maledenim.com"
                    className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="password" className="block text-[0.7rem] font-bold uppercase tracking-wider text-graphite mb-1.5">
                  Contraseña
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
                  <input
                    id="password"
                    name="password"
                    autoComplete="current-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    placeholder="••••••••"
                    className="w-full rounded-md border border-border bg-white pl-9 pr-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-steel"
                  />
                </div>
              </div>

              {error && (
                <div className="rounded-md bg-crimson/10 border border-crimson/30 px-3 py-2 text-sm text-crimson">
                  <p className="flex items-center gap-2">
                    <AlertCircle className="h-4 w-4 shrink-0" />
                    {error}
                  </p>
                  {/* El backend responde "Credenciales inválidas" tanto si el
                      correo no existe como si la clave está mal, y eso es
                      correcto: distinguirlos le diría a un atacante qué correos
                      son reales. Pero para quien sí es dueño de la cuenta el
                      mensaje es un callejón sin salida —se queda mirando la
                      contraseña cuando a veces el que está mal es el correo—.
                      Por eso el aviso, y el del bloqueo: al quinto intento
                      fallido la cuenta queda 15 minutos sin poder entrar, y
                      enterarse DESPUÉS es peor. */}
                  {/^credenciales/i.test(error) && (
                    <p className="mt-1.5 pl-6 text-[0.75rem] leading-snug text-crimson/80">
                      Revisa también el <strong>correo completo</strong>, no solo la contraseña:
                      el aviso es el mismo en ambos casos. Si lo rellenó el navegador,
                      escríbelo a mano una vez. Al quinto intento fallido la cuenta
                      se bloquea 15 minutos —
                      <Link href="/recuperar" className="font-semibold underline">
                        mejor pide un enlace para cambiarla
                      </Link>.
                    </p>
                  )}
                </div>
              )}

              <button
                type="submit"
                disabled={mut.isPending}
                className="w-full rounded-md bg-ink py-2.5 text-sm font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50 transition-colors"
              >
                {mut.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin mx-auto" />
                ) : (
                  "Entrar"
                )}
              </button>

              {/* Visible SIEMPRE, no solo después de fallar: quien ya sabe que
                  no se acuerda de la clave no tiene por qué equivocarse
                  primero — y cada intento fallido lo acerca al bloqueo de 15
                  minutos. */}
              <Link
                href="/recuperar"
                className="block text-center text-xs font-semibold text-graphite hover:text-ink"
              >
                ¿Olvidaste tu contraseña?
              </Link>
            </form>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-[0.7rem] tracking-[0.25em] text-steel/40 uppercase">
          MALE&apos;DENIM OS · v3
        </p>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { Mail, ArrowLeft, CheckCircle2, AlertCircle } from "lucide-react";

import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

/**
 * Pedir el enlace para restablecer la contraseña.
 *
 * LA PANTALLA MIENTE A PROPÓSITO —o más bien, no cuenta—. Diga lo que diga el
 * servidor, acá siempre se ve "si ese correo existe, ya te llegó". Si dijera
 * "ese usuario no existe", cualquiera podría sentarse a probar direcciones y
 * averiguar quién trabaja acá. El backend responde igual por la misma razón.
 */
export default function RecuperarPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");

  const mut = useMutation({
    mutationFn: () => api.post<{ ok: boolean }>("/api/auth/recuperar", {
      email: email.trim().toLowerCase(),
    }),
    onError: (err: Error) => setError(err.message || "No se pudo enviar el enlace"),
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
            {mut.isSuccess ? (
              <div className="space-y-4">
                <p className="flex items-center gap-2 text-sm font-semibold text-teal">
                  <CheckCircle2 className="h-5 w-5 shrink-0" />
                  Revisa tu correo
                </p>
                <p className="text-sm leading-relaxed text-graphite">
                  Si <strong className="text-ink">{email.trim().toLowerCase()}</strong> tiene
                  una cuenta activa, ya salió un enlace para cambiar la contraseña.
                  Sirve <strong className="text-ink">una sola vez</strong> y vence
                  en 30 minutos.
                </p>
                <p className="text-xs leading-relaxed text-graphite">
                  No llega en un minuto o dos: mira en Correo no deseado. La contraseña
                  la escribes tú en la pantalla que abre el enlace — nadie más la ve.
                </p>
                <Link
                  href="/login"
                  className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-navy-600 hover:underline"
                >
                  <ArrowLeft className="h-3.5 w-3.5" /> Volver al login
                </Link>
              </div>
            ) : (
              <>
                <h1 className="text-xl font-bold text-ink mb-1">Recuperar contraseña</h1>
                <p className="text-sm text-graphite mb-6">
                  Te mandamos un enlace al correo con el que entras.
                </p>

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    setError("");
                    mut.mutate();
                  }}
                  className="space-y-4"
                >
                  <div>
                    <label
                      htmlFor="email"
                      className="block text-[0.7rem] font-bold uppercase tracking-wider text-graphite mb-1.5"
                    >
                      Email
                    </label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
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

                  {error && (
                    <p className="flex items-center gap-2 rounded-md bg-crimson/10 border border-crimson/30 px-3 py-2 text-sm text-crimson">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {error}
                    </p>
                  )}

                  <button
                    type="submit"
                    disabled={mut.isPending}
                    className="w-full rounded-md bg-ink py-2.5 text-sm font-semibold uppercase tracking-wider text-white hover:bg-black disabled:opacity-50 transition-colors"
                  >
                    {mut.isPending ? "Enviando…" : "Enviarme el enlace"}
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

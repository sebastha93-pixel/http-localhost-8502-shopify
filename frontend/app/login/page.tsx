"use client";

import { useState } from "react";
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

  const mut = useMutation({
    mutationFn: () => api.post<LoginResponse>("/api/auth/login", { email, password }),
    onSuccess: (data) => {
      setToken(data.access_token);
      qc.setQueryData(["auth", "me"], data.user);
      router.replace(homePath(data.user));
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
          <p className="mt-1.5 text-[0.55rem] font-semibold tracking-[0.4em] text-steel/70 uppercase">
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
                <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1.5">
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
                  <input
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
                <label className="block text-[0.6rem] font-bold uppercase tracking-wider text-graphite mb-1.5">
                  Contraseña
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-graphite" />
                  <input
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
                <div className="flex items-center gap-2 rounded-md bg-crimson/10 border border-crimson/30 px-3 py-2 text-sm text-crimson">
                  <AlertCircle className="h-4 w-4" />
                  {error}
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
            </form>
          </CardContent>
        </Card>

        <p className="mt-6 text-center text-[0.6rem] tracking-[0.25em] text-steel/40 uppercase">
          MALE&apos;DENIM OS · v3
        </p>
      </div>
    </div>
  );
}

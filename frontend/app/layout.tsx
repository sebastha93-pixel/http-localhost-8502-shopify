import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "MALE'DENIM OS",
  description: "Sistema operativo de MALE'DENIM",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={inter.variable}>
      <body className="font-sans">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="ml-60 flex-1 px-10 py-8">{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}

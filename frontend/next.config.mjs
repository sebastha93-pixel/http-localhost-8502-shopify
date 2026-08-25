/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Directorio de salida configurable. Sin esto, `next build` y `next dev`
  // comparten `.next` y construir con el dev server vivo lo corrompe — el
  // error es «Cannot find module './1331.js'» y hay que borrar todo.
  //
  // Eso es lo que obligaba a matar el dev server antes de cada verificación, y
  // matarlo por nombre de proceso tumbaba los de los otros proyectos. Con un
  // directorio aparte, verificar no exige matar NADA.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // Proxy /api/* al backend FastAPI durante desarrollo
  async rewrites() {
    const backend = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;

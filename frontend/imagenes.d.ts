// Los tipos de `import logo from "./x.png"`. Normalmente los trae
// `next-env.d.ts`, pero ese archivo lo genera Next al compilar y no está en el
// repositorio: el paso de «Tipos» del CI corre antes y no lo encuentra.
/// <reference types="next/image-types/global" />

/**
 * Flat config, natively.
 *
 * `eslint-config-next` 16 exports real flat-config arrays, so the `FlatCompat`
 * shim that 15 needed is gone — along with `@eslint/eslintrc`, which was a
 * dependency only that shim wanted. Under 16 the shim does not merely become
 * redundant, it breaks: `compat.extends` tries to `JSON.stringify` a config
 * whose plugin objects now reference each other, and ESLint dies on a circular
 * structure rather than on anything to do with our code.
 */
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

const config = [
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      // Generated, all three: `sw.js` by `scripts/build-sw.mjs`,
      // `schema.gen.ts` by `openapi-typescript`, and `next-env.d.ts` by Next
      // itself — whose triple-slash reference is not ours to change.
      "public/sw.js",
      "src/lib/api/schema.gen.ts",
      "next-env.d.ts",
    ],
  },
];

export default config;

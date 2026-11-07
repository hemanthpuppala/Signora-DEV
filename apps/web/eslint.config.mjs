import boundaries from "eslint-plugin-boundaries";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

/**
 * Frontend module boundaries (backbone LLD §8.3), mirroring the backend import contracts:
 * - app/ (routes) composes features and shared code;
 * - a feature may import shared code and its own files, never another feature;
 * - shared/ never imports features or routes.
 */
const boundaryRules = {
  files: ["src/**/*.{ts,tsx}"],
  plugins: { boundaries },
  settings: {
    "import/resolver": { typescript: { alwaysTryTypes: true } },
    // proxy.ts (request proxy) imports only Next.js; it is not part of the module structure.
    "boundaries/ignore": ["src/proxy.ts"],
    "boundaries/elements": [
      { type: "app", pattern: "src/app/**" },
      { type: "feature", pattern: "src/features/*", capture: ["name"] },
      { type: "shared", pattern: "src/shared/**" },
    ],
  },
  rules: {
    "boundaries/no-unknown-files": "error",
    "boundaries/dependencies": [
      "error",
      {
        default: "disallow",
        policies: [
          {
            from: { element: { type: "app" } },
            allow: { to: { element: { types: { anyOf: ["app", "feature", "shared"] } } } },
          },
          {
            from: { element: { type: "feature" } },
            allow: { to: { element: { type: "shared" } } },
          },
          {
            from: { element: { type: "shared" } },
            allow: { to: { element: { type: "shared" } } },
          },
          {
            allow: { to: { module: { origin: "external" } } },
          },
        ],
      },
    ],
  },
};

const config = [
  ...nextVitals,
  ...nextTs,
  boundaryRules,
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts", "coverage/**"] },
];

export default config;

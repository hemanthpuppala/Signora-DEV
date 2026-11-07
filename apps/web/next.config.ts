import type { NextConfig } from "next";

const apiDevPort = process.env.API_DEV_PORT ?? "8100";
const isDev = process.env.NODE_ENV === "development";

const config: NextConfig = {
  // Small self-contained Node server for the container image (backbone LLD §8.2).
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // The contracts package ships TypeScript source.
  transpilePackages: ["@signora/contracts"],
  // In production Caddy routes /api/* to the API on the same origin. In development there is no
  // Caddy, so `next dev` forwards /api/* to the local API server.
  async rewrites() {
    return isDev
      ? [{ source: "/api/:path*", destination: `http://127.0.0.1:${apiDevPort}/api/:path*` }]
      : [];
  },
};

export default config;

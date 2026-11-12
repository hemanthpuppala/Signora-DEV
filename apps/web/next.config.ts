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
  // `make web` passes the public host name, so the dev server can be reached through a tunnel.
  allowedDevOrigins: (process.env.WEB_DEV_ORIGINS ?? "").split(",").filter(Boolean),
  // In production Caddy routes /api/* to the API on the same origin. In development there is no
  // Caddy, so `next dev` forwards /api/* to the local API server.
  // The emails' logos are fetched by email apps' image proxies each time an email is opened unless
  // they may keep them: their addresses carry a version (notifications.layout.LOGO_VERSION), so a
  // new file is a new address and they may keep each one for a year.
  async headers() {
    return [
      {
        source: "/email/:file*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
  async rewrites() {
    return isDev
      ? [{ source: "/api/:path*", destination: `http://127.0.0.1:${apiDevPort}/api/:path*` }]
      : [];
  },
};

export default config;

import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "__Host-signora_session";
const CONSOLE_PATHS = new Set(["/", "/people", "/settings"]);
const isConsolePath = (path: string) =>
  CONSOLE_PATHS.has(path) || path.startsWith("/departments") || path.startsWith("/countersign");

/**
 * Next.js 16 request proxy (formerly middleware): sets a per-request nonce-based Content Security
 * Policy for HTML pages (backbone LLD §9.6) and sends visitors without a session cookie from console
 * pages to /login (Phase 2 LLD). Only the cookie's presence is checked; whether the session is valid
 * is the API's decision. No business logic belongs here.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (isConsolePath(pathname) && !request.cookies.has(SESSION_COOKIE)) {
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(login);
  }

  const nonce = btoa(crypto.randomUUID());
  const isDev = process.env.NODE_ENV === "development";
  const policy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    // Development injects styles without nonces for hot reload; production uses the nonce.
    isDev ? "style-src 'self' 'unsafe-inline'" : `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    // The PDF viewer's pdf.js worker, served from public/pdfjs (Phase 4 LLD topic 5).
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Static files (Next assets, the pdf.js worker and its data) need no page policy.
      source: "/((?!api|_next/static|_next/image|pdfjs/|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};

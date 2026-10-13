import type { NextConfig } from "next";

/**
 * Where the dev proxy forwards API requests. Server-side only, deliberately not
 * `NEXT_PUBLIC_`, because the browser never needs to know this address - the
 * whole point is that the browser keeps talking to its own origin.
 */
const apiTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

/**
 * Proxy `/api/v1/` to Django during `next dev` (spec §20.2).
 *
 * The alternative was to point the browser straight at `:8000` by setting
 * `NEXT_PUBLIC_API_BASE_URL`. That does not work, and it is worth recording why
 * rather than rediscovering it:
 *
 * Dev runs the app on :3000 and DRF on :8000, so the request is cross-origin,
 * and a cross-origin `fetch` carrying credentials is refused by the browser
 * unless the response carries `Access-Control-Allow-Origin` and
 * `Access-Control-Allow-Credentials`. The backend configures neither - there is
 * no CORS middleware and `django-cors-headers` is not a dependency. CSRF being
 * correct is not a substitute: `CSRF_TRUSTED_ORIGINS` is set for
 * `http://localhost:3000`, so Django would happily process the request and the
 * browser would still throw the response away.
 *
 * Proxying instead keeps the browser on one origin, which means no CORS
 * headers are needed, the session and CSRF cookies behave the way they do in
 * production, and the client code is identical in dev and prod.
 *
 * For a production build this is Nginx's job instead
 * (`infrastructure/nginx/conf.d/barket.conf`), so the proxy stays off unless
 * something asks for it. `API_PROXY_ENABLED=1` is that ask, and it exists for the
 * Playwright suite: `next start` is a production build, and driving a real
 * browser against a real Django needs the same one-origin arrangement dev gets
 * for free. Opt-in means a deployment that has not asked for a proxy still has
 * none, and the deployed Nginx keeps serving `/api/v1/` exactly as before.
 */
const proxyEnabled = process.env.API_PROXY_ENABLED === "1" || process.env.NODE_ENV !== "production";

const devApiProxy = proxyEnabled
  ? {
      /**
       * Stop Next redirecting `/api/v1/thing/` to `/api/v1/thing` before the
       * rewrite below gets a look at it.
       *
       * Found by requesting `/api/v1/auth/csrf/` through the proxy and getting
       * `308 Permanent Redirect, location: /api/v1/auth/csrf`. Trailing-slash
       * normalisation runs ahead of `afterFiles` rewrites, so the slash DRF
       * needs was gone before the proxy was consulted. Left alone, Django's
       * `APPEND_SLASH` answers the stripped path with a 301 back to the slashed
       * one, the browser follows it, Next strips the slash again, and the sign-in
       * form spins on redirects that never end. The request has to reach Django
       * byte-for-byte as the client wrote it.
       *
       * Application routes are unaffected: they are slash-less and stay so, so
       * there was nothing for this redirect to normalise in the first place.
       */
      skipTrailingSlashRedirect: true,
      async rewrites() {
        return [
          {
            source: "/api/v1/:path*",
            destination: `${apiTarget.replace(/\/+$/, "")}/api/v1/:path*/`,
          },
        ];
      },
    }
  : {};

/**
 * Extra hostnames allowed to load `next dev` assets (spec §20.2).
 *
 * Next's dev server refuses cross-origin requests to its own dev resources -
 * the JS chunks, the RSC endpoints and the HMR socket - unless the request's
 * hostname is `localhost` or is listed here. A public tunnel is a different
 * origin, so without this the page's JavaScript downloads but never hydrates
 * and the server-rendered "Checking your session…" placeholder stays on screen
 * forever. Entries are hostnames only: no scheme, no port. `*`/`**` wildcards
 * are supported. Read from the environment rather than hardcoded because a
 * Cloudflare Quick Tunnel hostname changes on every run.
 */
const allowedDevOrigins = (process.env.ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter((origin) => origin.length > 0);

const nextConfig: NextConfig = {
  output: "standalone",
  ...(allowedDevOrigins.length > 0 ? { allowedDevOrigins } : {}),
  ...devApiProxy,
};

export default nextConfig;

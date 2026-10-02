/**
 * The redirect target for `RequireAuth`, and the only page reachable without a
 * session.
 *
 * The sign-in form itself is B3. This page exists now because B2's gate is that
 * an unauthenticated visit to `/sales` redirects to `/login` — a redirect to a
 * 404 is not a gate, it is a different bug — and because a protected page is
 * useless to a user who cannot reach the one thing that lets them in.
 *
 * It deliberately does not read the `next` parameter yet. Wiring the return
 * journey before the form exists would be code with nothing to return from.
 */

import PagePlaceholder from "@/components/page-placeholder";

export default function LoginPage() {
  return <PagePlaceholder title="Sign in" />;
}

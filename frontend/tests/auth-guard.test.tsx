/**
 * Tests for the session provider and the protected-route guard (roadmap B2).
 *
 * The guard's gate is a redirect, but the states around it are what make the
 * redirect trustworthy, so they are asserted here rather than left to the E2E
 * test: a 500 must not look like an expired session, and protected content must
 * not appear before the answer arrives.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/features/auth/auth-provider";
import { RequireAuth } from "@/features/auth/require-auth";
import { ErrorCode } from "@/lib/api/errors";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/sales",
}));

const OWNER = {
  id: 1,
  username: "owner",
  display_name: "Owner",
  role: "owner",
  role_name: "Owner",
  permissions: ["sales.add_sale"],
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorResponse(code: string, message: string, status: number): Response {
  return jsonResponse({ error: { code, message } }, status);
}

function mockMe(response: () => Response): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (input: string | URL | Request) => {
      if (String(input).endsWith("/api/v1/auth/me/")) return response();
      throw new Error(`Unexpected request to ${String(input)}`);
    },
  );
}

function StatusProbe() {
  const { status } = useAuth();
  return <p data-testid="status">{status}</p>;
}

function RefreshButton() {
  const { refresh } = useAuth();
  return (
    <button type="button" onClick={() => void refresh()}>
      Re-check
    </button>
  );
}

beforeEach(() => {
  replace.mockClear();
  localStorage.clear();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  // The Vitest config does not set `globals: true`, so Testing Library cannot
  // register its own cleanup hook. Without this, renders pile up in one
  // document and `getByTestId` finds the previous test's element first.
  cleanup();
  vi.unstubAllGlobals();
});

describe("AuthProvider", () => {
  it("starts out checking rather than assuming anyone is signed in", async () => {
    mockMe(() => jsonResponse({ user: OWNER }));

    render(
      <AuthProvider>
        <StatusProbe />
      </AuthProvider>,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("checking");
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
  });

  it("reports an anonymous session when the API says not_authenticated", async () => {
    mockMe(() => errorResponse(ErrorCode.NotAuthenticated, "Sign in to continue.", 403));

    render(
      <AuthProvider>
        <StatusProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
  });

  it("reports a server failure as unavailable, not as an expired session", async () => {
    // Sending a user to /login because the API is down tells them their password
    // is the problem. Only `not_authenticated` may mean signed out.
    mockMe(() => errorResponse(ErrorCode.ServerError, "Server exploded.", 500));

    render(
      <AuthProvider>
        <StatusProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unavailable"));
    expect(screen.getByTestId("status")).not.toHaveTextContent("anonymous");
  });

  it("treats an unreadable response as unavailable, not as signed out", async () => {
    mockMe(() => new Response("<html>502</html>", { status: 502 }));

    render(
      <AuthProvider>
        <StatusProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unavailable"));
  });

  it("re-checks on refresh", async () => {
    const me = vi
      .fn()
      .mockImplementationOnce(() => errorResponse(ErrorCode.NotAuthenticated, "No.", 403))
      .mockImplementation(() => jsonResponse({ user: OWNER }));
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (input: string | URL | Request) => {
        if (String(input).endsWith("/api/v1/auth/me/")) return me();
        throw new Error("unexpected");
      },
    );

    render(
      <AuthProvider>
        <StatusProbe />
        <RefreshButton />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("anonymous"));
    expect(me).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Re-check" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(me).toHaveBeenCalledTimes(2);
  });

  it("keeps nothing in storage, because there is nothing to keep", async () => {
    mockMe(() => jsonResponse({ user: OWNER }));
    const setItem = vi.spyOn(Storage.prototype, "setItem");

    render(
      <AuthProvider>
        <StatusProbe />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(setItem).not.toHaveBeenCalled();
  });
});

describe("RequireAuth", () => {
  it("redirects to /login with the attempted path when signed out", async () => {
    mockMe(() => errorResponse(ErrorCode.NotAuthenticated, "No.", 403));

    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret sales data</p>
        </RequireAuth>
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fsales"));
  });

  it("never renders protected content, not even for a frame", async () => {
    let resolveMe!: () => void;
    const gate = new Promise<void>((resolve) => {
      resolveMe = resolve;
    });
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      async (input: string | URL | Request) => {
        if (String(input).endsWith("/api/v1/auth/me/")) {
          await gate;
          return errorResponse(ErrorCode.NotAuthenticated, "No.", 403);
        }
        throw new Error("unexpected");
      },
    );

    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret sales data</p>
        </RequireAuth>
      </AuthProvider>,
    );

    expect(screen.queryByText("secret sales data")).not.toBeInTheDocument();
    expect(screen.getByText(/Checking your session/)).toBeInTheDocument();

    resolveMe();
    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(screen.queryByText("secret sales data")).not.toBeInTheDocument();
  });

  it("renders children once the session is confirmed", async () => {
    mockMe(() => jsonResponse({ user: OWNER }));

    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret sales data</p>
        </RequireAuth>
      </AuthProvider>,
    );

    expect(screen.queryByText("secret sales data")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("secret sales data")).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
  });

  it("offers a retry when the server is unreachable, and does not redirect", async () => {
    mockMe(() => errorResponse(ErrorCode.ServerError, "Boom.", 500));

    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret sales data</p>
        </RequireAuth>
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByText(/Cannot reach the server/)).toBeInTheDocument());
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("throws a legible error when used outside the provider", () => {
    function Orphan() {
      useAuth();
      return null;
    }
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Orphan />)).toThrow(/must be used inside/);
    consoleError.mockRestore();
  });
});

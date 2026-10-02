/**
 * Tests for the sign-in and change-password screens (roadmap B3).
 *
 * The two behaviours worth the most attention are the ones that are wrong
 * quietly: a `next` parameter that turns the login page into an open redirect,
 * and a throttled sign-in reported to the user as a wrong password.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "@/features/auth/auth-provider";
import { RequireAuth } from "@/features/auth/require-auth";
import { describe as describeError } from "@/features/auth/form-parts";
import { safeNextPath } from "@/features/auth/next-path";
import type { AuthUser } from "@/lib/api/auth";
import { ApiError, ErrorCode } from "@/lib/api/errors";

const replace = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/login",
  useSearchParams: () => searchParams,
}));

const { default: LoginPage } = await import("@/app/(public)/login/page");
const { default: ChangePasswordPage } = await import("@/app/(public)/change-password/page");

const OWNER = {
  id: 1,
  username: "owner",
  display_name: "Selam",
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

function envelope(
  code: string,
  message: string,
  status: number,
  details?: Record<string, string[]>,
) {
  return jsonResponse({ error: { code, message, ...(details ? { details } : {}) } }, status);
}

/**
 * Route every API call by its path. The sign-in form triggers a CSRF bootstrap
 * before it posts, so a single canned response is not enough.
 */
function stubApi(routes: Record<string, () => Response>): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (input: string | URL | Request) => {
      const url = String(input);
      const match = Object.keys(routes).find((suffix) => url.endsWith(suffix));
      if (match === undefined) throw new Error(`Unexpected request to ${url}`);
      return routes[match]();
    },
  );
}

const CSRF_OK = () => jsonResponse({ token: "csrf-token" });
const ME_OWNER = () => jsonResponse({ user: OWNER });

function renderLogin() {
  return render(
    <AuthProvider>
      <LoginPage />
    </AuthProvider>,
  );
}

function renderChangePassword() {
  return render(
    <AuthProvider>
      <ChangePasswordPage />
    </AuthProvider>,
  );
}

async function fill(getLabel: string, value: string) {
  fireEvent.change(screen.getByLabelText(getLabel), { target: { value } });
}

beforeEach(() => {
  replace.mockClear();
  searchParams = new URLSearchParams();
  localStorage.clear();
  document.cookie = "csrftoken=test";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("safeNextPath", () => {
  it("keeps an ordinary in-app path", () => {
    expect(safeNextPath("/sales")).toBe("/sales");
    expect(safeNextPath("/inventory/products")).toBe("/inventory/products");
  });

  it("falls back to the dashboard when there is nothing to return to", () => {
    expect(safeNextPath(null)).toBe("/dashboard");
    expect(safeNextPath("")).toBe("/dashboard");
    expect(safeNextPath(undefined)).toBe("/dashboard");
  });

  it("refuses anything that would leave this origin", () => {
    // A redirect after sign-in that lands off-origin is how a phishing link
    // harvests a session: the user types a real password into a real form and
    // arrives somewhere that was never ours.
    expect(safeNextPath("https://evil.example/steal")).toBe("/dashboard");
    expect(safeNextPath("http://evil.example")).toBe("/dashboard");
    expect(safeNextPath("javascript:alert(1)")).toBe("/dashboard");
  });

  it("refuses the protocol-relative spelling, which starts with a slash", () => {
    // The case a naive `startsWith("/")` check waves through, and the browser
    // resolves as a different origin.
    expect(safeNextPath("//evil.example/steal")).toBe("/dashboard");
    expect(safeNextPath("///evil.example")).toBe("/dashboard");
  });

  it("refuses the backslash spelling of the same attack", () => {
    expect(safeNextPath("/\\evil.example")).toBe("/dashboard");
    expect(safeNextPath("/foo\\bar")).toBe("/dashboard");
  });
});

describe("error wording", () => {
  it("does not tell a throttled user their password was wrong", () => {
    // A5 allows five attempts a minute. Showing "not accepted" for the sixth is
    // a lie that sends someone to reset a password they never got wrong.
    const error = new ApiError(429, {
      code: ErrorCode.Throttled,
      message: "Too many requests. Wait a moment and try again.",
      details: null,
    });
    expect(describeError(error)).toMatch(/wait a minute/i);
  });

  it("prefers the server's own wording for a whole-form error", () => {
    const error = new ApiError(400, {
      code: ErrorCode.Validation,
      message: "The submitted data is invalid.",
      details: { non_field_errors: ["Those credentials were not accepted."] },
    });
    expect(describeError(error)).toBe("Those credentials were not accepted.");
  });
});

describe("sign-in form", () => {
  it("signs in and lands on the dashboard", async () => {
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () => jsonResponse({ user: OWNER }),
      "/auth/me/": ME_OWNER,
    });

    renderLogin();
    await fill("Username", "owner");
    await fill("Password", "hunter2");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("returns the user to the page they were trying to reach", async () => {
    searchParams = new URLSearchParams("next=%2Finventory%2Fproducts");
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () => jsonResponse({ user: OWNER }),
      "/auth/me/": ME_OWNER,
    });

    renderLogin();
    await fill("Username", "owner");
    await fill("Password", "hunter2");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/inventory/products"));
  });

  it("ignores an off-origin next and goes to the dashboard", async () => {
    searchParams = new URLSearchParams("next=https%3A%2F%2Fevil.example%2Fsteal");
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () => jsonResponse({ user: OWNER }),
      "/auth/me/": ME_OWNER,
    });

    renderLogin();
    await fill("Username", "owner");
    await fill("Password", "hunter2");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows rejected credentials and stays on the page", async () => {
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () =>
        envelope(ErrorCode.Validation, "The submitted data is invalid.", 400, {
          non_field_errors: ["Those credentials were not accepted."],
        }),
      "/auth/me/": () => envelope(ErrorCode.NotAuthenticated, "No.", 403),
    });

    renderLogin();
    await fill("Username", "owner");
    await fill("Password", "wrong");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Those credentials were not accepted.",
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("marks the offending input and links the message to it", async () => {
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () =>
        envelope(ErrorCode.Validation, "The submitted data is invalid.", 400, {
          username: ["This field is required."],
        }),
      "/auth/me/": () => envelope(ErrorCode.NotAuthenticated, "No.", 403),
    });

    renderLogin();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    const input = await screen.findByLabelText("Username");
    await waitFor(() => expect(input).toHaveAttribute("aria-invalid", "true"));
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
    expect(await screen.findByText("This field is required.")).toBeInTheDocument();
  });

  it("sends a temporary-password user to the change screen instead", async () => {
    // Every other endpoint answers password_change_required, so the dashboard
    // would be a page where nothing works and nothing explains why.
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () => jsonResponse({ user: { ...OWNER, is_temporary_password: true } }),
      "/auth/me/": () => jsonResponse({ user: { ...OWNER, is_temporary_password: true } }),
    });

    searchParams = new URLSearchParams("next=%2Fsales");
    renderLogin();
    await fill("Username", "new-hire");
    await fill("Password", "temp-1234");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/change-password"));
  });

  it("does not send the password anywhere but the login endpoint", async () => {
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/login/": () => jsonResponse({ user: OWNER }),
      "/auth/me/": ME_OWNER,
    });

    renderLogin();
    await fill("Username", "owner");
    await fill("Password", "hunter2");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalled());

    const seen = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
      ([input]) => String(input).endsWith("/auth/me/"),
    );
    expect(seen).toHaveLength(1);
    for (const [, init] of seen) {
      expect(String(init?.body ?? "")).not.toContain("hunter2");
    }
  });
});

describe("change-password form", () => {
  it("posts all three fields, adopts the refreshed user, and continues", async () => {
    const updated = { ...OWNER, is_temporary_password: false };
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/me/": () => jsonResponse({ user: { ...OWNER, is_temporary_password: true } }),
      "/auth/change-password/": () => jsonResponse({ user: updated }),
    });

    // Recorded outside render: the point is what the provider publishes, not
    // how often this component happens to run.
    const observed: AuthUser[] = [];
    function Probe() {
      const { user } = useAuth();
      useEffect(() => {
        if (user !== null) observed.push(user);
      }, [user]);
      return null;
    }

    render(
      <AuthProvider>
        <ChangePasswordPage />
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() => expect(observed[0]?.is_temporary_password).toBe(true));

    await fill("Current password", "temp-1234");
    await fill("New password", "a-much-better-one");
    await fill("Confirm new password", "a-much-better-one");
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));

    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
      ([input]) => String(input).endsWith("/auth/change-password/"),
    );
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      current_password: "temp-1234",
      new_password: "a-much-better-one",
      new_password_confirm: "a-much-better-one",
    });

    // Adopting the returned user is what stops the guard bouncing them back here.
    expect(observed.at(-1)?.is_temporary_password).toBe(false);
  });

  it("explains a mismatched confirmation on the field it belongs to", async () => {
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/me/": () => jsonResponse({ user: { ...OWNER, is_temporary_password: true } }),
      "/auth/change-password/": () =>
        envelope(ErrorCode.Validation, "The submitted data is invalid.", 400, {
          new_password_confirm: ["The two passwords do not match."],
        }),
    });

    renderChangePassword();
    await fill("Current password", "temp-1234");
    await fill("New password", "a-much-better-one");
    await fill("Confirm new password", "something-else");
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));

    expect(await screen.findByText("The two passwords do not match.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("reports a wrong current password without discarding what was typed", async () => {
    stubApi({
      "/auth/csrf/": CSRF_OK,
      "/auth/me/": () => jsonResponse({ user: { ...OWNER, is_temporary_password: true } }),
      "/auth/change-password/": () =>
        envelope(ErrorCode.Validation, "The submitted data is invalid.", 400, {
          current_password: ["That is not the current password."],
        }),
    });

    renderChangePassword();
    await fill("Current password", "not-it");
    await fill("New password", "a-much-better-one");
    await fill("Confirm new password", "a-much-better-one");
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));

    expect(await screen.findByText("That is not the current password.")).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toHaveValue("a-much-better-one");
  });
});

describe("an expired session is signed out, not an outage", () => {
  it("redirects to /login when the API reports session_expired", async () => {
    // The B2 guard treated anything that was not `not_authenticated` as a server
    // failure, so a user whose session simply idled out was told to wait for a
    // server that was perfectly healthy. The code is a 403, not a 401.
    stubApi({
      "/auth/me/": () => envelope(ErrorCode.SessionExpired, "Your session has expired.", 403),
    });

    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret sales data</p>
        </RequireAuth>
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Flogin"));
    expect(screen.queryByText("secret sales data")).not.toBeInTheDocument();
  });

  it("sends a temporary-password session to the change screen", async () => {
    stubApi({
      "/auth/me/": () => jsonResponse({ user: { ...OWNER, is_temporary_password: true } }),
    });

    render(
      <AuthProvider>
        <RequireAuth>
          <p>secret sales data</p>
        </RequireAuth>
      </AuthProvider>,
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/change-password"));
    expect(screen.queryByText("secret sales data")).not.toBeInTheDocument();
  });
});

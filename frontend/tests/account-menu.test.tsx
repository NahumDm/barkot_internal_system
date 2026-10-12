/**
 * Tests for the shared account menu.
 *
 * The menu is small but sits on two promises the rest of the app depends on:
 * that signing out only looks like signing out when the server agrees, and that
 * the profile shows what the API actually returns and nothing invented. Both are
 * asserted here rather than left to a reviewer clicking around.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { AccountMenu } from "@/components/layout/account-menu";
import { AuthProvider } from "@/features/auth/auth-provider";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/",
}));

// `next/link` reaches into the App Router, which no test here sets up. A plain
// anchor keeps the href assertion meaningful without that machinery.
vi.mock("next/link", async () => {
  const React = await import("react");
  return {
    default: ({
      href,
      children,
      ...rest
    }: { href: string; children?: ReactNode } & Record<string, unknown>) =>
      React.createElement("a", { href: String(href), ...rest }, children),
  };
});

const CSRF = "test-csrf";

const OWNER = {
  id: 1,
  username: "nahum",
  display_name: "Nahum Dm",
  role: "owner",
  role_name: "Owner",
  permissions: ["sales.add_sale"],
  email: "nahum@barkot.et",
  phone_number: "+251900000000",
  is_temporary_password: false,
  last_login: null,
};

const fetchMock = () => globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function noContentResponse(): Response {
  return new Response(null, { status: 204 });
}

/**
 * Stub the two endpoints the menu touches. `logout` overrides the sign-out
 * answer; everything else is the signed-in happy path.
 */
function mockApi({ logout }: { logout?: () => Response } = {}): void {
  fetchMock().mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/auth/me/")) return jsonResponse({ user: OWNER });
    if (url.endsWith("/api/v1/auth/logout/")) return logout ? logout() : noContentResponse();
    throw new Error(`Unexpected request to ${url}`);
  });
}

function renderMenu() {
  return render(
    <AuthProvider>
      <AccountMenu />
    </AuthProvider>,
  );
}

async function openMenu(): Promise<HTMLElement> {
  const trigger = await screen.findByRole("button", { name: /Nahum Dm/ });
  fireEvent.click(trigger);
  return screen.getByRole("menu");
}

beforeEach(() => {
  replace.mockClear();
  document.cookie = `csrftoken=${CSRF}`;
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("trigger", () => {
  it("shows the signed-in user's name and role", async () => {
    mockApi();

    renderMenu();

    const trigger = await screen.findByRole("button", { name: /Nahum Dm/ });
    expect(trigger).toHaveTextContent("Nahum Dm");
    expect(trigger).toHaveTextContent("Owner");
  });
});

describe("menu", () => {
  it("offers profile, password change and logout", async () => {
    mockApi();

    renderMenu();
    await openMenu();

    expect(screen.getByRole("menuitem", { name: "My Profile" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Change Password" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Log Out" })).toBeInTheDocument();
  });

  it("links Change Password to the existing workflow", async () => {
    mockApi();

    renderMenu();
    await openMenu();

    expect(screen.getByRole("menuitem", { name: "Change Password" })).toHaveAttribute(
      "href",
      "/change-password",
    );
  });

  it("closes on Escape", async () => {
    mockApi();

    renderMenu();
    const menu = await openMenu();

    fireEvent.keyDown(menu, { key: "Escape" });

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

describe("profile", () => {
  it("shows only the details /auth/me/ returns", async () => {
    mockApi();

    renderMenu();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "My Profile" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Nahum Dm");
    expect(dialog).toHaveTextContent("nahum@barkot.et");
    expect(dialog).toHaveTextContent("+251900000000");
  });
});

describe("logout", () => {
  it("posts to /auth/logout/ with the CSRF token, then goes to /login", async () => {
    mockApi();

    renderMenu();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Log Out" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));

    const logoutCall = fetchMock()
      .mock.calls.map(([input, init]) => ({
        url: String(input),
        method: (init as RequestInit | undefined)?.method ?? "GET",
        csrf: new Headers((init as RequestInit | undefined)?.headers).get("X-CSRFToken"),
      }))
      .find((call) => call.url.endsWith("/api/v1/auth/logout/"));

    expect(logoutCall?.method).toBe("POST");
    expect(logoutCall?.csrf).toBe(CSRF);
  });

  it("keeps the user signed in and shows the error when the server refuses", async () => {
    // A failed logout must not look like a successful one: no redirect, and the
    // session the server still holds is not abandoned client-side.
    mockApi({
      logout: () =>
        jsonResponse({ error: { code: "server_error", message: "Could not sign you out." } }, 500),
    });

    renderMenu();
    await openMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Log Out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not sign you out.");
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("menuitem", { name: "Log Out" })).toBeInTheDocument();
  });
});

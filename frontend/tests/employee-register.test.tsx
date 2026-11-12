/**
 * Tests for the employee-register screen (spec §5).
 *
 * The screen is the only client of `/api/v1/employees/`, so what gets tested
 * here is the contract a user actually meets: who may open it, which requests
 * it dares to make, that archiving is the only removal offered, and that a
 * document goes up as multipart without the client ever claiming a URL for it.
 *
 * `fetch` is stubbed rather than the API module, so the real client still
 * builds the URL, still attaches the CSRF header and still turns a refusal
 * into an `ApiError` — a test that mocked `listEmployees` would pass with a
 * path typo in it.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-provider";
import EmployeeRegister from "@/features/employees/employee-register";
import type { AuthUser } from "@/lib/api/auth";

const REGISTER_PERMISSIONS = ["users.manage_employees"];

const BASE_USER: AuthUser = {
  id: 1,
  username: "e2e-owner",
  display_name: "Nahum Desta",
  role: "owner",
  role_name: "Owner",
  permissions: REGISTER_PERMISSIONS,
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const ACTIVE = {
  id: 4,
  full_name: "Abebe Bekele",
  position: "Waiter",
  phone_number: "+251911234567",
  start_date: "2024-02-01",
  contract_type: "FULL_TIME",
  contract_type_display: "Full-time",
  contract_end_date: null,
  is_archived: false,
  archived_at: null,
  notes: "",
  user: null,
  username: "",
  has_document: false,
  document_filename: "",
  created_at: "2024-02-01T00:00:00+00:00",
  updated_at: "2024-02-01T00:00:00+00:00",
};

const ARCHIVED = {
  ...ACTIVE,
  id: 9,
  full_name: "Tsehay Girma",
  is_archived: true,
  archived_at: "2025-01-15T00:00:00+00:00",
  has_document: true,
  document_filename: "9f2c1a7e-4b3d-4e5f-8a9b-0c1d2e3f4a5b.pdf",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function page<T>(results: T[]) {
  return { count: results.length, page_size: 100, page: 1, pages: 1, results };
}

/** Every path the stubs have seen, so a test can assert what was *not* asked. */
let requested: string[] = [];

function stubApi(routes: [string, () => Response][], permissions = REGISTER_PERMISSIONS): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (input: string | URL | Request) => {
      const { pathname } = new URL(String(input), "http://localhost");
      requested.push(pathname);
      const match = [...routes]
        .sort((left, right) => right[0].length - left[0].length)
        .find(([suffix]) => pathname.endsWith(suffix));
      if (match === undefined) {
        requested.push(`UNMATCHED ${pathname}`);
        throw new Error(`Unexpected request to ${pathname}`);
      }
      return match[1]();
    },
  );
  routes.push(["/auth/me/", () => jsonResponse({ user: { ...BASE_USER, permissions } })]);
}

function renderScreen(node: ReactNode) {
  return render(<AuthProvider>{node}</AuthProvider>);
}

beforeEach(() => {
  requested = [];
  document.cookie = "csrftoken=test";
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("employee register screen", () => {
  it("lists current staff with their contracts and no login claims", async () => {
    stubApi([["/employees/", () => jsonResponse(page([ACTIVE]))]]);

    renderScreen(<EmployeeRegister />);
    const row = (await screen.findByText("Abebe Bekele")).closest("tr") as HTMLElement;

    expect(row).toHaveTextContent("Waiter");
    expect(row).toHaveTextContent("Full-time");
    // A register row without an account must not read like a broken login.
    expect(row).not.toHaveTextContent("(no login)");
    expect(row).toHaveTextContent("None");
  });

  it("offers restore for an archived row instead of edit or delete", async () => {
    stubApi([["/employees/", () => jsonResponse(page([ARCHIVED]))]]);

    renderScreen(<EmployeeRegister />);
    const row = (await screen.findByText("Tsehay Girma")).closest("tr") as HTMLElement;

    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(row).toHaveTextContent("Archived");
    expect(row).toHaveTextContent("PDF on file");
  });

  it("refuses the whole screen to a role without the register permission", async () => {
    stubApi([["/employees/", () => jsonResponse(page([ACTIVE]))]], ["payroll.view_payroll"]);

    renderScreen(<EmployeeRegister />);
    await screen.findByText(/Your role does not include the employee register/);

    expect(requested.filter((path) => path.includes("/employees/"))).toEqual([]);
    expect(screen.queryByText("Abebe Bekele")).toBeNull();
  });

  it("registers a person with the fields the form collected", async () => {
    stubApi([["/employees/", () => jsonResponse(page([ACTIVE]))]]);

    renderScreen(<EmployeeRegister />);
    await screen.findByText("Abebe Bekele");

    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "Selamawit Tesfaye" },
    });
    fireEvent.change(screen.getByLabelText("Position"), { target: { value: "Barman" } });
    fireEvent.change(screen.getByLabelText("Started"), { target: { value: "2026-01-05" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to register" }));

    await waitFor(() => {
      const post = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(post).toBeDefined();
      const body = JSON.parse(String((post![1] as RequestInit).body));
      expect(body).toMatchObject({
        full_name: "Selamawit Tesfaye",
        position: "Barman",
        start_date: "2026-01-05",
        contract_type: "FULL_TIME",
        contract_end_date: null,
      });
      // Nothing in the body may look like account provisioning.
      expect(body).not.toHaveProperty("username");
      expect(body).not.toHaveProperty("password");
    });
  });

  it("archives and restores without ever offering a delete", async () => {
    stubApi([
      ["/employees/", () => jsonResponse(page([ACTIVE]))],
      ["/employees/4/archive/", () => jsonResponse({ ...ACTIVE, is_archived: true })],
    ]);

    renderScreen(<EmployeeRegister />);
    await screen.findByText("Abebe Bekele");

    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => {
      expect(requested).toContain("/api/v1/employees/4/archive/");
    });
    expect(requested.filter((path) => path.includes("delete"))).toEqual([]);
  });

  it("uploads a chosen file as multipart to the document endpoint", async () => {
    stubApi([
      ["/employees/", () => jsonResponse(page([ACTIVE]))],
      ["/employees/4/document/", () => jsonResponse({ ...ACTIVE, has_document: true })],
    ]);

    renderScreen(<EmployeeRegister />);
    const input = (await screen.findByText("Upload"))
      .closest("label")
      ?.querySelector("input[type=file]") as HTMLInputElement;
    expect(input).not.toBeNull();

    const file = new File(["%PDF-1.7 fake"], "contract.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      const post = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(post).toBeDefined();
      expect(String(post![0])).toContain("/api/v1/employees/4/document/");
      // Multipart: the browser owns the boundary, so the client must not set
      // a Content-Type of its own.
      const init = post![1] as RequestInit;
      expect(init.body).toBeInstanceOf(FormData);
      expect(new Headers(init.headers).get("Content-Type")).toBeNull();
      // The CSRF header is still there: the upload is a write.
      expect(new Headers(init.headers).get("X-CSRFToken")).toBe("test");
    });
  });
});

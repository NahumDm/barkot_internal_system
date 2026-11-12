/**
 * Tests for the three payroll screens (roadmap C2).
 *
 * Two things get the most attention here. The first is **permission
 * presentation**: the role matrix in `backend/apps/accounts.permissions` is the
 * authority, but a button a user may never press should not be drawn in front of
 * them, and a screen their role does not cover should say so instead of showing
 * a table that will 403. The second is **what is not fetched** — a roster read
 * the signed-in account cannot make is not attempted, because the failure is
 * avoidable rather than informative.
 *
 * These stub `fetch`, not the API module, so the real client still builds the
 * URL, still parses the envelope and still rejects with `ApiError`. A test that
 * mocked `listPayrollRuns` would pass with a path typo in it.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "@/features/auth/auth-provider";
import DeductionRegister from "@/features/payroll/deduction-register";
import EmployeeRoster from "@/features/payroll/employee-roster";
import { currentMonthKey, money, monthLabel, monthToPeriod } from "@/features/payroll/format";
import PayrollRuns from "@/features/payroll/payroll-runs";
import type { AuthUser } from "@/lib/api/auth";

const PERIOD = monthToPeriod(currentMonthKey());
const PERIOD_LABEL = monthLabel(currentMonthKey());

const ALL_PAYROLL = [
  "payroll.view_payroll",
  "payroll.manage_payroll_employees",
  "payroll.generate_run",
  "payroll.approve_run",
  "payroll.mark_paid",
  "payroll.create_deduction",
];

const BASE_USER: AuthUser = {
  id: 1,
  username: "e2e-manager",
  display_name: "Selam Bekele",
  role: "manager",
  role_name: "Manager",
  permissions: ALL_PAYROLL,
  email: "",
  phone_number: "",
  is_temporary_password: false,
  last_login: null,
};

const RUN = {
  id: 7,
  period_month: PERIOD,
  status: "GENERATED",
  status_display: "Generated",
  currency: "ETB",
  gross_total: "36000.00",
  deduction_total: "0.00",
  net_total: "36000.00",
  generated_at: `${PERIOD}T08:00:00+00:00`,
  approved_at: null,
  approved_by: null,
  approved_by_username: null,
  paid_at: null,
  notes: "",
  created_at: `${PERIOD}T08:00:00+00:00`,
  updated_at: `${PERIOD}T08:00:00+00:00`,
};

const LINE = {
  id: 11,
  run: RUN.id,
  employee: 3,
  full_name: "Abebe Bekele",
  position: "Waiter",
  gross_amount: "18000.00",
  total_deductions: "500.00",
  net_amount: "17500.00",
  currency: "ETB",
  status: "PENDING",
  status_display: "Pending",
  paid_at: null,
  created_at: `${PERIOD}T08:00:00+00:00`,
  updated_at: `${PERIOD}T08:00:00+00:00`,
};

const DEDUCTION = {
  id: 3,
  payroll_item: 11,
  run: RUN.id,
  employee_name: "Abebe Bekele",
  deduction_type: "ADVANCE",
  deduction_type_display: "Salary advance",
  amount: "500.00",
  currency: "ETB",
  reason: "Requested on the 3rd",
  occurred_on: PERIOD,
  created_at: `${PERIOD}T09:00:00+00:00`,
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

function stubApi(routes: [string, () => Response][], permissions = ALL_PAYROLL): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (input: string | URL | Request) => {
      const { pathname } = new URL(String(input), "http://localhost");
      requested.push(pathname);
      // Longest suffix first, so a nested route cannot be swallowed by its
      // parent: `/payroll/runs/7/items/` must not match `/payroll/runs/`.
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

describe("payroll runs", () => {
  it("shows the month's KPI cards and its payslip lines", async () => {
    stubApi([
      ["/payroll/runs/", () => jsonResponse(page([RUN]))],
      [`/payroll/runs/${RUN.id}/items/`, () => jsonResponse(page([LINE]))],
    ]);

    renderScreen(<PayrollRuns />);
    await screen.findByRole("button", { name: "Approve run" });
    await screen.findByText(money("17500.00"));

    // The labels are plain paragraphs, and "Pending" is also a payslip status
    // further down the page, so the card is reached through the label's own tag
    // rather than by text alone.
    const card = (label: string) => {
      const heading = screen.getAllByText(label).find((node) => node.tagName === "P");
      expect(heading).toBeDefined();
      return heading!.parentElement as HTMLElement;
    };
    expect(card("Monthly payroll")).toHaveTextContent(money("36000.00"));
    expect(card("Employees")).toHaveTextContent("1");
    expect(card("Paid")).toHaveTextContent(money("0.00"));
    expect(card("Pending")).toHaveTextContent(money("36000.00"));

    expect(screen.getByText("Abebe Bekele")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: PERIOD_LABEL })).toBeInTheDocument();
  });

  it("offers to generate a month that has no run yet", async () => {
    stubApi([["/payroll/runs/", () => jsonResponse(page([]))]]);

    renderScreen(<PayrollRuns />);
    await screen.findByRole("heading", { name: `Generate payroll for ${PERIOD_LABEL}` });

    expect(screen.getByRole("button", { name: "Generate run" })).toBeInTheDocument();
  });

  it("does not draw an approve button for a role that cannot approve", async () => {
    stubApi(
      [
        ["/payroll/runs/", () => jsonResponse(page([RUN]))],
        [`/payroll/runs/${RUN.id}/items/`, () => jsonResponse(page([LINE]))],
      ],
      ALL_PAYROLL.filter((code) => code !== "payroll.approve_run"),
    );

    renderScreen(<PayrollRuns />);
    await screen.findByText("An owner approves this run before anything is paid.");

    expect(screen.queryByRole("button", { name: "Approve run" })).toBeNull();
    // The rest of the month still reads normally: withholding an action is not
    // the same as withholding the screen.
    expect(screen.getByText("Monthly payroll")).toBeInTheDocument();
  });

  it("says the module is not theirs instead of asking for it", async () => {
    stubApi([["/payroll/runs/", () => jsonResponse(page([RUN]))]], []);

    renderScreen(<PayrollRuns />);
    await screen.findByText(/Your role does not include payroll/);

    expect(requested.filter((path) => path.includes("/payroll/"))).toEqual([]);
  });
});

describe("payroll employees", () => {
  const EMPLOYEE = {
    id: 5,
    profile: 9,
    full_name: "Abebe Bekele",
    position: "Waiter",
    phone_number: "+251911234567",
    start_date: "2024-02-01",
    monthly_wage: "18000.00",
    currency: "ETB",
    status: "ACTIVE",
    status_display: "Active",
    terminated_on: null,
    created_at: "2024-02-01T00:00:00+00:00",
    updated_at: "2024-02-01T00:00:00+00:00",
  };

  const PROFILE = {
    id: 12,
    full_name: "Tsehay Girma",
    position: "Cashier",
    phone_number: "+251922334455",
    start_date: "2025-06-15",
    contract_type: "PART_TIME",
  };

  it("lists the roster and offers the register records not on it yet", async () => {
    stubApi([
      ["/payroll/employees/", () => jsonResponse(page([EMPLOYEE]))],
      ["/payroll/profiles/", () => jsonResponse(page([PROFILE]))],
    ]);

    renderScreen(<EmployeeRoster />);
    await screen.findByText("Abebe Bekele");

    expect(screen.getByRole("button", { name: "Add to payroll" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Tsehay Girma — Cashier" })).toBeInTheDocument();
    expect(screen.getByText(money("18000.00"))).toBeInTheDocument();
  });

  it("keeps the add form away from a role that cannot manage payroll employees", async () => {
    stubApi(
      [["/payroll/employees/", () => jsonResponse(page([EMPLOYEE]))]],
      ["payroll.view_payroll"],
    );

    renderScreen(<EmployeeRoster />);
    await screen.findByText("Abebe Bekele");

    expect(screen.queryByRole("button", { name: "Add to payroll" })).toBeNull();
    expect(requested).not.toContain("/api/v1/payroll/profiles/");
  });
});

describe("payroll deductions", () => {
  it("offers the record form when the role may create deductions", async () => {
    stubApi([
      ["/payroll/runs/", () => jsonResponse(page([RUN]))],
      ["/payroll/deductions/", () => jsonResponse(page([DEDUCTION]))],
      [`/payroll/runs/${RUN.id}/items/`, () => jsonResponse(page([LINE]))],
    ]);

    renderScreen(<DeductionRegister />);
    // The employee pick only fills in once the run's lines are back, and the
    // month appears both as an option and in the history table — so wait on the
    // option, which is the one the form cannot do without.
    await screen.findByRole("option", { name: "Abebe Bekele" });

    expect(screen.getByRole("button", { name: "Record deduction" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: PERIOD_LABEL })).toBeInTheDocument();
    expect(screen.getByText("Requested on the 3rd")).toBeInTheDocument();
    expect(screen.getByText(money("500.00"))).toBeInTheDocument();
  });

  it("shows the history without the form for a role that cannot deduct", async () => {
    stubApi(
      [
        ["/payroll/runs/", () => jsonResponse(page([RUN]))],
        ["/payroll/deductions/", () => jsonResponse(page([DEDUCTION]))],
        [`/payroll/runs/${RUN.id}/items/`, () => jsonResponse(page([LINE]))],
      ],
      ["payroll.view_payroll"],
    );

    renderScreen(<DeductionRegister />);
    await screen.findByText("Requested on the 3rd");

    expect(screen.queryByRole("button", { name: "Record deduction" })).toBeNull();
    // The permission gates the action column as a whole, not just the form.
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("switches the form into a locked correction and PATCHes it", async () => {
    stubApi([
      ["/payroll/runs/", () => jsonResponse(page([RUN]))],
      ["/payroll/deductions/", () => jsonResponse(page([DEDUCTION]))],
      [`/payroll/runs/${RUN.id}/items/`, () => jsonResponse(page([LINE]))],
    ]);

    renderScreen(<DeductionRegister />);
    const edit = await screen.findByRole("button", { name: "Edit" });
    fireEvent.click(edit);

    await screen.findByRole("button", { name: "Save correction" });
    // The line cannot be moved by a correction, so the two picks are locked.
    const [runSelect, employeeSelect] = screen.getAllByRole("combobox");
    expect(runSelect).toBeDisabled();
    expect(employeeSelect).toBeDisabled();

    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await waitFor(() => {
      const patch = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
        ([, init]) => (init as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(String(patch![0])).toContain(`/payroll/deductions/${DEDUCTION.id}/`);
    });
  });

  it("offers no correction once the run is approved", async () => {
    stubApi([
      ["/payroll/runs/", () => jsonResponse(page([{ ...RUN, status: "APPROVED" }]))],
      ["/payroll/deductions/", () => jsonResponse(page([DEDUCTION]))],
    ]);

    renderScreen(<DeductionRegister />);
    await screen.findByText("Requested on the 3rd");

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.getByText("Run approved")).toBeInTheDocument();
  });
});

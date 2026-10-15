/**
 * Settings in a real browser, with the API answered at the network layer
 * (roadmap C5; both kinds of browser evidence per `docs/ADDING_AN_ENDPOINT.md`).
 *
 * The Owner surface is three blocks — staff accounts, the roles catalogue and
 * the system settings row — and the states worth proving are: the blocks render
 * the real responses, create/update reach the API with the screen's values and
 * the list comes back refreshed, and a role with none of the settings
 * permissions is told so and is never asked for any of it. The account forms
 * also exercise the self-guard: a user edit of your own role or status never
 * sends those fields, because the backend refuses them.
 *
 * The session stubs come from `./session`. The permission list is what gates
 * the page, so a user with the three `accounts.*` grants is authored here
 * rather than taken from the default `OWNER`.
 */

import { expect, test, type Route } from "@playwright/test";

import { stubCsrf, stubSignedIn, type StubUser } from "./session";

const OWNER: StubUser = {
  id: 1,
  username: "owner",
  display_name: "Selam Bekele",
  role: "owner",
  role_name: "Owner",
  permissions: ["accounts.manage_users", "accounts.manage_roles", "accounts.manage_settings"],
  email: "selam@barkot.test",
  phone_number: "+251911000001",
  is_temporary_password: false,
  last_login: "2026-10-06T08:00:00Z",
};

const MANAGER: StubUser = {
  ...OWNER,
  id: 2,
  username: "manager",
  display_name: "Selam Bekele",
  role: "manager",
  role_name: "Manager",
  permissions: [],
  email: "",
  phone_number: "",
};

const OWNER_USER = {
  id: 1,
  username: "owner",
  display_name: "Selam Bekele",
  role: "owner",
  role_name: "Owner",
  email: "selam@barkot.test",
  phone_number: "+251911000001",
  is_active: true,
  is_staff: true,
  is_temporary_password: false,
  last_login: "2026-10-06T08:00:00Z",
};

const CASHIER_USER = {
  id: 2,
  username: "cashier",
  display_name: "Abel Girma",
  role: "cashier",
  role_name: "Cashier",
  email: "",
  phone_number: "",
  is_active: true,
  is_staff: true,
  is_temporary_password: true,
  last_login: null,
};

const ROLES = [
  {
    code: "owner",
    name: "Owner",
    description: "Full control of the business and its accounts.",
    is_staff_role: true,
    permissions: [
      "accounts.manage_roles",
      "accounts.manage_settings",
      "accounts.manage_users",
      "payroll.approve_run",
    ].sort(),
  },
  {
    code: "manager",
    name: "Manager",
    description: "Runs daily sales, inventory and payroll.",
    is_staff_role: true,
    permissions: ["payroll.mark_paid"].sort(),
  },
  {
    code: "cashier",
    name: "Cashier",
    description: "Registers sales at the counter.",
    is_staff_role: true,
    permissions: [],
  },
  {
    code: "barman",
    name: "Barman",
    description: "Serves drinks and records shortages.",
    is_staff_role: true,
    permissions: [],
  },
];

const SETTINGS = {
  session_timeout_minutes: 480,
  password_max_age_days: 0,
  require_password_change_for_new_users: true,
  updated_at: "2026-10-01T09:00:00Z",
  updated_by: null,
};

const PAGINATED_SETTINGS = {
  ...SETTINGS,
  updated_at: "2026-10-07T09:00:00Z",
  updated_by: "owner",
};

function json(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function usersList(users: unknown[]) {
  return { count: users.length, page_size: 200, page: 1, pages: 1, results: [...users] };
}

function rolesList() {
  return { count: ROLES.length, page_size: 200, page: 1, pages: 1, results: [...ROLES] };
}

test("the owner sees staff accounts, the roles catalogue and system settings", async ({ page }) => {
  await stubSignedIn(page, OWNER);
  await page.route("**/api/v1/users**", (route) =>
    route.fulfill(json(usersList([OWNER_USER, CASHIER_USER]))),
  );
  await page.route("**/api/v1/roles**", (route) => route.fulfill(json(rolesList())));
  await page.route("**/api/v1/settings**", (route) => route.fulfill(json(SETTINGS)));

  await page.goto("/settings");

  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Staff accounts" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Selam Bekele" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Abel Girma" })).toBeVisible();
  await expect(page.getByText("Temporary password — reset on sign-in")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Roles" })).toBeVisible();
  await expect(page.getByText("accounts.manage_users", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "System" })).toBeVisible();
  await expect(page.getByLabel("Session timeout (minutes)")).toHaveValue("480");
  await expect(page.getByText("Never modified.", { exact: true })).toBeVisible();
});

test("creating a staff member posts the screen's values and refetches the list", async ({
  page,
}) => {
  await stubSignedIn(page, OWNER);
  await stubCsrf(page);

  let created: unknown = null;
  await page.route("**/api/v1/users**", async (route: Route) => {
    const request = route.request();
    if (request.method() === "POST") {
      expect(request.postDataJSON()).toEqual({
        username: "new-barman",
        role: "barman",
        email: "new@barkot.test",
        // Required since the Phone field became mandatory for a new account,
        // and the screen sends what it collected.
        phone_number: "+251911000001",
        password: "S3cret!",
      });
      created = {
        id: 9,
        username: "new-barman",
        display_name: "New Hire Bebe",
        role: "barman",
        role_name: "Barman",
        email: "new@barkot.test",
        phone_number: "",
        is_active: true,
        is_staff: true,
        is_temporary_password: true,
        last_login: null,
      };
      return route.fulfill(json(created, 201));
    }
    return route.fulfill(
      json(
        usersList(created ? [...[OWNER_USER, CASHIER_USER], created] : [OWNER_USER, CASHIER_USER]),
      ),
    );
  });
  await page.route("**/api/v1/roles**", (route) => route.fulfill(json(rolesList())));
  await page.route("**/api/v1/settings**", (route) => route.fulfill(json(SETTINGS)));

  await page.goto("/settings");

  const form = page.locator("form");
  await expect(form.getByLabel("Role")).not.toBeDisabled();
  await form.getByLabel("Login name").fill("new-barman");
  await form.getByLabel("Role").selectOption("barman");
  await form.getByLabel("Email").fill("new@barkot.test");
  await form.getByLabel("Phone").fill("+251911000001");
  await form.getByLabel("Temporary password", { exact: true }).fill("S3cret!");
  await form.getByRole("button", { name: "Create staff account" }).click();

  await expect(page.getByRole("cell", { name: "New Hire Bebe" })).toBeVisible();
  await expect(page.getByText("new-barman", { exact: true })).toBeVisible();
  expect(created).not.toBeNull();
});

test("editing a staff member changes their role and status, but never your own", async ({
  page,
}) => {
  await stubSignedIn(page, OWNER);
  await stubCsrf(page);

  let patchBody: unknown = null;
  const updatedCashier = {
    ...CASHIER_USER,
    role: "barman",
    role_name: "Barman",
    is_active: false,
  };
  await page.route("**/api/v1/users**", async (route: Route) => {
    const request = route.request();
    if (request.method() === "PATCH") {
      patchBody = request.postDataJSON();
      return route.fulfill(json(updatedCashier));
    }
    return route.fulfill(json(usersList([OWNER_USER, CASHIER_USER])));
  });
  await page.route("**/api/v1/roles**", (route) => route.fulfill(json(rolesList())));
  await page.route("**/api/v1/settings**", (route) => route.fulfill(json(SETTINGS)));

  await page.goto("/settings");

  const row = page.getByRole("row", { name: /Abel Girma/ });
  await row.getByRole("button", { name: "Edit" }).click();
  await row.getByLabel("Role").selectOption("barman");
  await row.getByRole("checkbox").uncheck();
  await row.getByRole("button", { name: "Save" }).click();

  await expect(row.getByText("Barman", { exact: true })).toBeVisible();
  await expect(row.getByText("Inactive", { exact: true })).toBeVisible();
  expect(patchBody).toEqual({
    role: "barman",
    email: "",
    phone_number: "",
    is_active: false,
  });

  const selfRow = page.getByRole("row", { name: /Selam Bekele/ });
  await selfRow.getByRole("button", { name: "Edit" }).click();
  await expect(selfRow.getByRole("checkbox")).toBeDisabled();
  await expect(selfRow.getByLabel("Role")).toBeDisabled();
  await expect(selfRow.getByText("Your own status cannot be changed here.")).toBeVisible();
});

test("the system settings form saves the policy and shows who changed it", async ({ page }) => {
  await stubSignedIn(page, OWNER);
  await stubCsrf(page);

  let patchBody: unknown = null;
  await page.route("**/api/v1/users**", (route) =>
    route.fulfill(json(usersList([OWNER_USER, CASHIER_USER]))),
  );
  await page.route("**/api/v1/roles**", (route) => route.fulfill(json(rolesList())));
  await page.route("**/api/v1/settings**", async (route: Route) => {
    const request = route.request();
    if (request.method() === "PATCH") {
      patchBody = request.postDataJSON();
      return route.fulfill(json(PAGINATED_SETTINGS));
    }
    return route.fulfill(json(SETTINGS));
  });

  await page.goto("/settings");

  await page.getByLabel("Session timeout (minutes)").fill("30");
  await page.getByRole("button", { name: "Save settings" }).click();

  await expect(page.getByText("Saved.", { exact: true })).toBeVisible();
  await expect(page.getByText(/^Last changed by owner on /)).toBeVisible();
  expect(patchBody).toEqual({
    session_timeout_minutes: 30,
    password_max_age_days: 0,
    require_password_change_for_new_users: true,
  });
});

test("a role without settings access is told so and is never asked for the data", async ({
  page,
}) => {
  await stubSignedIn(page, MANAGER);
  let requests = 0;
  await page.route("**/api/v1/users**", (route) => {
    requests += 1;
    return route.fulfill(json({}));
  });
  await page.route("**/api/v1/roles**", (route) => {
    requests += 1;
    return route.fulfill(json({}));
  });
  await page.route("**/api/v1/settings**", (route) => {
    requests += 1;
    return route.fulfill(json({}));
  });

  await page.goto("/settings");

  await expect(
    page.getByText("Your role does not include account settings. Ask an owner if you need access."),
  ).toBeVisible();
  expect(requests).toBe(0);
});

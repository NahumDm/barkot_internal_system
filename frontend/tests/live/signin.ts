/**
 * The one live login path every spec shares (roadmap B5).
 *
 * The live suite is serial and shares one client address, so A5's five-attempts-
 * a-minute login limit is shared too, and a story that signs in twice can easily
 * find the window still counting the stories before it. Signing in is therefore
 * implemented once, here, rather than copied per spec (as it once was, with a
 * non-retrying copy that could flake under the same throttle).
 *
 * Throttle state is read from the login response itself — a 429 means the
 * window had not cleared — rather than guessed at from the page. A throttled
 * POST is never inserted into the rate-limit history (DRF checks the budget
 * before granting a slot), so waiting the window out and retrying cannot push
 * the limit further away. Each retry pays a full minute, so a spec that signs
 * in must set its own test timeout to 240_000.
 */

import { expect, type Page } from "@playwright/test";

import type { SeededUser } from "./environment";

export async function signIn(page: Page, user: SeededUser): Promise<void> {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    await page.goto("/login");
    await page.getByLabel("Username").fill(user.username);
    await page.getByLabel("Password").fill(user.password);

    const responsePromise = page.waitForResponse((response) =>
      response.url().includes("/api/v1/auth/login/"),
    );
    await page.getByRole("button", { name: "Sign in" }).click();
    const response = await responsePromise;

    if (response.status() === 429) {
      await page.waitForTimeout(62_000);
      continue;
    }

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    return;
  }
  throw new Error("Sign-in stayed throttled past four retries.");
}

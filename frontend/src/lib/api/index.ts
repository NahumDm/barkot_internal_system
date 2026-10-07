/**
 * The frontend's single entry point for talking to the API (roadmap B1).
 *
 * Import from `@/lib/api` rather than from the individual modules, so that a
 * caller cannot pick up `client.ts` without also getting the error type it
 * rejects with.
 */

export * from "./errors";
export * from "./client";
export * from "./auth";
export * from "./finance";
export * from "./inventory";
export * from "./payroll";
export * from "./reports";

import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],

    /**
     * One worker, one DOM, built once.
     *
     * The default pool rebuilds the jsdom environment for every file, which on
     * a machine with other work to do is measured in tens of seconds apiece —
     * long enough that the pool gives up waiting for a worker it has not
     * finished starting and reports no tests at all. A worker that outlives a
     * file pays for the environment once and keeps it, so the suite's duration
     * stops depending on how busy the box is.
     */
    pool: "vmThreads",

    /**
     * Sequential files rather than one DOM per file started at once.
     *
     * Parallel files buy time on a large machine and lose the run entirely on a
     * small one. Ordering them costs some wall clock and makes the answer about
     * the code instead of about the hardware it ran on.
     */
    fileParallelism: false,

    /**
     * The five-second default assumes the machine running the tests has nothing
     * else to do. A screen that awaits a session round trip before it renders
     * needs longer than that here, and a test that hangs still fails — just
     * fifteen seconds later rather than five.
     */
    testTimeout: 15_000,
  },
});

import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/artifacts",
  reporter: "list",
  use: {
    baseURL: process.env.TERRAPANEL_E2E_URL ?? "http://127.0.0.1:8082",
    trace: "retain-on-failure",
  },
});

import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import path from "node:path";
const sha =
  process.env.QA_SHA ??
  execFileSync("git", ["rev-parse", "--short", "HEAD"], {
    encoding: "utf8",
  }).trim();
const root = path.resolve("..", "qa", "screens", sha);
const viewports = [
  ["air13", 1470, 870],
  ["pro14", 1512, 895],
  ["pro16", 1728, 1030],
  ["windows100", 1920, 960],
  ["windows125", 1536, 730],
  ["windows150", 1280, 600],
  ["laptop", 1366, 650],
  ["four-three", 1024, 768],
  ["tablet", 1180, 820],
  ["ultrawide", 2560, 1000],
  ["phone", 390, 844],
];
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const [name, width, height] of viewports) {
    const page = await browser.newPage({ viewport: { width, height } }),
      errors = [],
      failed = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("requestfailed", (r) =>
      failed.push(`${r.url()}: ${r.failure()?.errorText}`),
    );
    page.on("response", (r) => {
      if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
    });
    await page.goto("http://127.0.0.1:8102/next/src/twin/preview.html");
    await page.locator("[data-webgl=ready]").waitFor();
    await page.waitForTimeout(800);
    assert.deepEqual(errors, [], `${name}: console errors`);
    assert.deepEqual(failed, [], `${name}: failed requests`);
    const folder = path.join(root, `${width}x${height}`);
    await mkdir(folder, { recursive: true });
    const capture = async (state) =>
      page.screenshot({
        path: path.join(folder, `twin-${state}.png`),
        fullPage: true,
      });
    for (const theme of ["dark", "light"]) {
      if (theme === "light")
        await page
          .getByRole("button", { name: "Light theme", exact: true })
          .click();
      await page.waitForTimeout(250);
      await capture(theme);
      const size = await page.evaluate(() => ({
        height: document.documentElement.scrollHeight,
        width: document.documentElement.scrollWidth,
        viewportHeight: innerHeight,
        viewportWidth: innerWidth,
      }));
      assert.ok(
        size.width <= size.viewportWidth,
        `${name}/${theme}: horizontal overflow ${JSON.stringify(size)}`,
      );
      if (name !== "phone")
        assert.ok(
          size.height <= size.viewportHeight,
          `${name}/${theme}: page scroll ${JSON.stringify(size)}`,
        );
    }
    if (name === "air13" || name === "phone") {
      await page
        .getByRole("button", { name: "Dark theme", exact: true })
        .click();
      for (const preset of ["Left passage", "Backyard", "Top-down", "Front"]) {
        await page.getByRole("tab", { name: preset, exact: true }).click();
        await page.waitForTimeout(600);
        await capture(`preset-${preset.toLowerCase().replaceAll(" ", "-")}`);
      }
      await page.getByRole("button", { name: "Zoom in", exact: true }).click();
      await page.getByRole("button", { name: "Zoom out", exact: true }).click();
      await page
        .getByRole("button", { name: "Toggle camera coverage" })
        .click();
      await capture("coverage-off");
      await page
        .getByRole("button", { name: "Toggle camera coverage" })
        .click();
      const cameraButtons = page.locator(".twin-camera-list button");
      for (let i = 0; i < (await cameraButtons.count()); i++) {
        await cameraButtons.nth(i).scrollIntoViewIfNeeded();
        await cameraButtons.nth(i).click();
        await capture(`camera-${i}`);
      }
      await page.getByRole("button", { name: "Reset view" }).click();
      await page.waitForTimeout(600);
      const canvas = page.locator("canvas"),
        box = await canvas.boundingBox();
      assert.ok(box);
      await page.mouse.move(
        box.x + box.width * 0.45,
        box.y + box.height * 0.25,
      );
      await page.mouse.down();
      await page.mouse.move(
        box.x + box.width * 0.45,
        box.y + box.height * 0.95,
        { steps: 12 },
      );
      await page.mouse.up();
      await page.waitForTimeout(300);
      const y = Number(
        await page
          .locator("[data-testid=twin-canvas]")
          .getAttribute("data-camera-y"),
      );
      assert.ok(y >= 0.6, `downward drag went underground: ${y}`);
      await capture("drag-down");
      await page.mouse.wheel(0, 10000);
      await page.waitForTimeout(300);
      const distance = Number(
        await page
          .locator("[data-testid=twin-canvas]")
          .getAttribute("data-orbit-distance"),
      );
      assert.ok(distance <= 55.0001 && distance >= 8, `zoom bound ${distance}`);
      await capture("zoom-bound");
      await page.getByRole("button", { name: "Reset view" }).click();
      await page.waitForTimeout(600);
      await page.locator("#evidence-time").fill("15280");
      await capture("gap");
      await page.locator("#evidence-time").fill("15304");
      await capture("observed");
      for (const control of await page
        .locator(
          ".twin-toolbar button,.twin-camera-list button,.twin-blind-label,.twin-pin",
        )
        .all()) {
        await control.scrollIntoViewIfNeeded();
        await control.hover();
        const label =
          (await control.getAttribute("aria-label")) ??
          (await control.textContent());
        await capture(
          `hover-${String(label)
            .toLowerCase()
            .replaceAll(/[^a-z0-9]+/g, "-")
            .slice(0, 40)}`,
        );
      }
      await page
        .getByRole("button", { name: "Light theme", exact: true })
        .focus();
      for (let i = 0; i < 24; i++) {
        await page.keyboard.press("Tab");
        await page.waitForTimeout(50);
        const focus = await page.evaluate(() => {
          const el = document.activeElement;
          return el instanceof HTMLElement
            ? {
                tag: el.tagName,
                label: el.getAttribute("aria-label") ?? el.textContent,
                outline: getComputedStyle(el).outlineStyle,
              }
            : null;
        });
        if (focus && focus.tag !== "BODY")
          assert.notEqual(
            focus.outline,
            "none",
            `visible keyboard focus: ${focus.label}`,
          );
      }
      await capture("keyboard-focus");
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.getByRole("tab", { name: "Top-down" }).click();
      await page.waitForTimeout(100);
      await capture("reduced-motion");
      await page.locator(".twin-camera-list").evaluate((el) => {
        el.scrollLeft = el.scrollWidth;
      });
      await capture("camera-scroll-end");
      await page.locator(".twin-camera-list").evaluate((el) => {
        el.scrollLeft = 0;
      });
    }
    assert.deepEqual(errors, [], `${name}: console errors after interaction`);
    assert.deepEqual(failed, [], `${name}: failed requests after interaction`);
    results.push({
      name,
      width,
      height,
      consoleErrors: errors,
      failedRequests: failed,
      status: "passed",
    });
    await page.close();
  }
  await writeFile(
    path.join(root, "twin-results.json"),
    JSON.stringify(
      {
        sha,
        url: "http://127.0.0.1:8102/next/src/twin/preview.html",
        viewports: results,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ sha, status: "passed", viewports: results.length, root }),
  );
} finally {
  await browser.close();
}

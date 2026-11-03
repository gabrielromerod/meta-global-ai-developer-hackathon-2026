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
const root = path.resolve("..", "qa", "screens", sha, "twin-narrow-panels");
const browser = await chromium.launch();
const results = [];
try {
  for (const [width, height, compact] of [
    [486, 440, true],
    [600, 520, true],
    [606, 520, false],
    [486, 524, false],
  ]) {
    const page = await browser.newPage({
        viewport: { width: 1024, height: 768 },
      }),
      errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("requestfailed", (request) => errors.push(request.url()));
    await page.goto(
      process.env.TWIN_QA_URL ??
        "http://127.0.0.1:8102/next/src/twin/preview.html",
    );
    await page.locator("[data-webgl=ready]").waitFor();
    await page.locator(".twin-preview-stage").evaluate(
      (element, { width, height }) => {
        element.style.flex = "none";
        element.style.width = `${width}px`;
        element.style.height = `${height}px`;
        element.style.display = "flex";
      },
      { width, height },
    );
    await page.waitForTimeout(700);
    const canvas = await page.locator("canvas").boundingBox();
    assert.ok(canvas);
    assert.equal(
      await page
        .getByRole("button", { name: "Select camera", exact: true })
        .isVisible(),
      compact,
      `${width}x${height}: camera chooser mode`,
    );
    if (compact)
      assert.ok(
        canvas.height > 300,
        `${width}x${height}: canvas too short (${canvas.height})`,
      );
    const folder = path.join(root, `${width}x${height}`);
    await mkdir(folder, { recursive: true });
    for (const theme of ["dark", "light"]) {
      if (theme === "light")
        await page
          .getByRole("button", { name: "Light theme", exact: true })
          .click();
      await page.waitForTimeout(100);
      await page.screenshot({
        path: path.join(folder, `twin-narrow-${theme}.png`),
      });
      if (compact) {
        await page
          .getByRole("button", { name: "Select camera", exact: true })
          .click();
        await page.screenshot({
          path: path.join(folder, `twin-narrow-${theme}-menu.png`),
        });
        await page.getByRole("menuitemradio", { name: /Backyard 2/ }).click();
      }
    }
    assert.deepEqual(errors, [], `${width}x${height}: console/network errors`);
    results.push({
      width,
      height,
      compact,
      canvasHeight: canvas.height,
      status: "passed",
    });
    await page.close();
  }
  await writeFile(
    path.join(root, "results.json"),
    JSON.stringify({ sha, results }, null, 2),
  );
  console.log(JSON.stringify({ status: "passed", sha, results }));
} finally {
  await browser.close();
}

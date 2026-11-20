import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

// Next only honors "use client" as the very first statement. A formatter that
// sees it below an import turns it into a plain expression, and the page breaks.
const roots = ["app", "components", "hooks", "lib"];
const directive = /^\s*\(?["']use client["']\)?;?\s*$/m;
const firstLine = /^["']use client["'];?$/;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

test('"use client" is the first line of every file that has it', () => {
  const files = roots
    .flatMap(sources)
    .map((path) => ({ path, text: readFileSync(path, "utf8") }))
    .filter(({ text }) => directive.test(text));
  expect(files.length).toBeGreaterThan(0);
  const misplaced = files
    .filter(({ text }) => !firstLine.test(text.split("\n")[0]))
    .map(({ path }) => path);
  expect(misplaced).toEqual([]);
});

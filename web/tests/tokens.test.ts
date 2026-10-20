import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const WEB = join(__dirname, "..");

function cssFiles(dir: string): string[] {
  return readdirSync(join(WEB, dir), { withFileTypes: true }).flatMap((e) => {
    const rel = join(dir, e.name);
    if (e.isDirectory()) return cssFiles(rel);
    return e.name.endsWith(".css") ? [rel] : [];
  });
}

describe("design tokens", () => {
  it("keeps raw colours in globals.css only", () => {
    const offenders = [...cssFiles("app"), ...cssFiles("components")]
      .filter((f) => !f.endsWith("globals.css"))
      .filter((f) => /#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(readFileSync(join(WEB, f), "utf8")));
    expect(offenders).toEqual([]);
  });

  it("uses the agreed fonts and accent", () => {
    const css = readFileSync(join(WEB, "app/globals.css"), "utf8");
    for (const s of ["Bricolage Grotesque", "Instrument Sans", "Instrument Serif", "Fragment Mono", "#e6904f", "#0b0a09"]) {
      expect(css).toContain(s);
    }
    expect(css).not.toContain("prefers-color-scheme");
  });
});

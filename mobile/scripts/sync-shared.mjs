/**
 * Copies the platform-neutral web modules into mobile/src/shared, so the app parses run events,
 * proof, health and the ledger with exactly the code the web app uses.
 *
 *   node scripts/sync-shared.mjs          write fresh copies
 *   node scripts/sync-shared.mjs --check  exit 1 when any copy differs from a fresh sync (CI)
 */
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, posix } from "node:path";
import { fileURLToPath } from "node:url";

const MOBILE = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(MOBILE, "..", "web");
const OUT = join(MOBILE, "src", "shared");

/** Web path (under web/) mapped to its copy (under mobile/src/shared/). */
const MODULES = {
  "lib/api/events.ts": "api/events.ts",
  "lib/api/proof.ts": "api/proof.ts",
  "lib/api/health.ts": "api/health.ts",
  "lib/verify/chain.ts": "verify/chain.ts",
  "lib/verify/verdict.ts": "verify/verdict.ts",
  "lib/format.ts": "format.ts",
};

const withoutExtension = (path) => path.replace(/\.ts$/, "");
const SHARED_BY_ALIAS = Object.fromEntries(
  Object.entries(MODULES).map(([web, shared]) => [withoutExtension(web), withoutExtension(shared)]),
);

function render(webPath, sharedPath) {
  const source = readFileSync(join(WEB, webPath), "utf8");
  const problems = [];
  const fromDir = posix.dirname(sharedPath);
  const body = source.replace(/from "@\/(lib\/[^"]+)"/g, (match, target) => {
    const mapped = SHARED_BY_ALIAS[target];
    if (!mapped) {
      problems.push(`web/${webPath} imports @/${target}, which is not one of the shared modules`);
      return match;
    }
    let relative = posix.relative(fromDir, mapped);
    if (!relative.startsWith(".")) relative = `./${relative}`;
    return `from "${relative}"`;
  });
  const header = `// GENERATED from web/${webPath} by mobile/scripts/sync-shared.mjs.\n// Do not edit this copy. Change the web file, then run: npm run sync\n\n`;
  return { text: header + body, problems };
}

function listFiles(dir, prefix = "") {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    const relative = prefix ? `${prefix}/${name}` : name;
    return statSync(full).isDirectory() ? listFiles(full, relative) : [relative];
  });
}

const check = process.argv.includes("--check");
const problems = [];
let stale = 0;

for (const [webPath, sharedPath] of Object.entries(MODULES)) {
  if (!existsSync(join(WEB, webPath))) {
    problems.push(`web/${webPath} does not exist`);
    continue;
  }
  const { text, problems: found } = render(webPath, sharedPath);
  problems.push(...found);
  const target = join(OUT, sharedPath);
  const current = existsSync(target) ? readFileSync(target, "utf8") : null;
  if (current === text) continue;
  if (check) {
    stale += 1;
    console.error(`STALE src/shared/${sharedPath} differs from web/${webPath}`);
  } else {
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, text);
    console.log(`wrote src/shared/${sharedPath}`);
  }
}

const expected = new Set(Object.values(MODULES));
for (const file of listFiles(OUT)) {
  if (!expected.has(file)) problems.push(`src/shared/${file} is not generated from web; delete it or add it to MODULES`);
}

for (const problem of problems) console.error(`ERROR ${problem}`);
const total = Object.keys(MODULES).length;
if (problems.length > 0 || stale > 0) {
  console.error(check ? `${stale} of ${total} shared modules are stale. Run: npm run sync` : "Sync did not complete.");
  process.exit(1);
}
console.log(check ? `All ${total} shared modules match web.` : `Synced ${total} shared modules from web.`);

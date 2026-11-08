import { createServer } from "node:http";
import { readFile, realpath, stat } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = await realpath(fileURLToPath(new URL("../dist", import.meta.url)));
await stat(resolve(root, "index.html"));
const port = Number(process.env.CLARIFY_TEST_PORT);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Set CLARIFY_TEST_PORT to a TCP port.");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const server = createServer(async (request, response) => {
  try {
    const path = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
    if (path === "/favicon.ico") { response.writeHead(204).end(); return; }
    const file = await realpath(resolve(root, `.${path === "/" ? "/index.html" : path}`));
    if (!file.startsWith(root + sep)) { response.writeHead(403).end(); return; }
    const body = await readFile(file);
    response.writeHead(200, { "Content-Type": types[extname(file)] ?? "application/octet-stream", "Cache-Control": "no-store" });
    response.end(body);
  } catch {
    // Never substitute index.html for a missing chunk or source file.
    response.writeHead(404).end("Missing built Settings asset");
  }
});
server.listen(port, "127.0.0.1", () => console.log(`Built Settings: http://127.0.0.1:${port}`));

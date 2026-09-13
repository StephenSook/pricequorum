import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

// The link preview shown when the site is shared in Slack, Devpost or a chat app.
export const alt = "PriceQuorum: one price change, three systems that agree";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Archivo is OFL licensed; static weights live in web/assets/fonts because the image renderer cannot read woff2.
const archivoHeavy = await readFile(join(process.cwd(), "assets/fonts/archivo-latin-800.woff"));
const archivoMedium = await readFile(join(process.cwd(), "assets/fonts/archivo-latin-500.woff"));

const APPS = ["Stripe", "Notion", "Airtable", "Slack"];

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#23280b",
          fontFamily: "Archivo",
        }}
      >
        <div
          style={{
            width: 1040,
            height: 470,
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "56px 64px",
            borderRadius: 18,
            background: "#efe6d2",
            color: "#1e2a1a",
            transform: "rotate(-1.2deg)",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 104, fontWeight: 800, letterSpacing: -2, textShadow: "5px 6px 0 #d9cdad" }}>
              PriceQuorum
            </div>
            <div style={{ marginTop: 18, fontSize: 38, fontWeight: 500, color: "#3d4a36", lineHeight: 1.3 }}>
              Change a price once. Approved in Slack, written to three apps, and read back until they agree.
            </div>
          </div>
          <div style={{ display: "flex", gap: 14 }}>
            {APPS.map((app) => (
              <div
                key={app}
                style={{
                  display: "flex",
                  padding: "10px 22px",
                  borderRadius: 999,
                  background: "#465016",
                  color: "#f6f0e1",
                  fontSize: 28,
                  fontWeight: 500,
                }}
              >
                {app}
              </div>
            ))}
          </div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Archivo", data: archivoHeavy, style: "normal", weight: 800 },
        { name: "Archivo", data: archivoMedium, style: "normal", weight: 500 },
      ],
    },
  );
}

import type { Metadata, Viewport } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Archivo carries both roles: extended heavy display (wdth 125) and normal-width UI text.
const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  axes: ["wdth"],
  display: "swap",
});

// Monospace is reserved for data a person may copy: hashes, idempotency keys, ids.
const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  display: "swap",
});

// Stamped at deploy time (vercel --prod --build-env NEXT_PUBLIC_BUILD_SHA=<commit>) so the
// deployed-smoke workflow can prove which commit the live site is serving.
const BUILD_SHA = process.env.NEXT_PUBLIC_BUILD_SHA ?? process.env.VERCEL_GIT_COMMIT_SHA ?? "unknown";

const DESCRIPTION =
  "Change a SaaS price once across Stripe, Notion and Airtable, approved in Slack and verified by reading every system back.";

export const metadata: Metadata = {
  metadataBase: new URL("https://pricequorum-web.vercel.app"),
  title: "PriceQuorum",
  description: DESCRIPTION,
  // The preview image comes from app/opengraph-image.tsx.
  openGraph: { title: "PriceQuorum", description: DESCRIPTION, url: "/", siteName: "PriceQuorum", type: "website" },
  twitter: { card: "summary_large_image", title: "PriceQuorum", description: DESCRIPTION },
  other: { "pq-build": BUILD_SHA },
};

export const viewport: Viewport = {
  themeColor: "#23280b",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${archivo.variable} ${jetbrains.variable} h-full`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}

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

export const metadata: Metadata = {
  title: "PriceQuorum",
  description:
    "Change a SaaS price once across Stripe, Notion and Airtable, approved in Slack and verified by reading every system back.",
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

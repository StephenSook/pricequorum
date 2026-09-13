/**
 * The painterly ledger-desk scene behind every page, darkened for text contrast, with the
 * ink-paper texture underneath as a fallback while the scene image loads.
 */
export function SceneBackdrop({ dim = "medium" }: { dim?: "light" | "medium" | "strong" }) {
  const overlay = {
    light: "linear-gradient(rgb(35 40 11 / 0.35), rgb(35 40 11 / 0.55))",
    medium: "linear-gradient(rgb(35 40 11 / 0.5), rgb(35 40 11 / 0.65))",
    strong: "linear-gradient(rgb(35 40 11 / 0.62), rgb(35 40 11 / 0.78))",
  }[dim];

  return (
    <div
      aria-hidden="true"
      className="fixed inset-0 z-[var(--z-canvas)] bg-cover bg-center"
      style={{ backgroundImage: `${overlay}, url(/scenes/ledger-desk.webp), url(/textures/ink-paper-dark.webp)` }}
    />
  );
}

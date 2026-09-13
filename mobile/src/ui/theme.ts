/** Ledger paper tokens, the same values as web/app/globals.css. */
export const colors = {
  paper: "#efe6d2",
  paperLight: "#f6f0e1",
  paperDeep: "#d9cdad",
  ink: "#1e2a1a",
  inkSoft: "#3d4a36",
  olive: "#465016",
  forest: "#23280b",
  bordeaux: "#764b41",
  brass: "#ac9b6e",
  success: "#3f6b2a",
  needsHuman: "#7f500d",
  refused: "#a3262a",
} as const;

export const fonts = {
  display: "Archivo_800ExtraBold",
  body: "Archivo_400Regular",
  medium: "Archivo_500Medium",
  semibold: "Archivo_600SemiBold",
  mono: "JetBrainsMono_400Regular",
} as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

/** Minimum touch target from the Apple and Material guidelines. */
export const TOUCH = 48;

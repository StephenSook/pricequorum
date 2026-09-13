import { Archivo_400Regular, Archivo_500Medium, Archivo_600SemiBold, Archivo_800ExtraBold } from "@expo-google-fonts/archivo";
import { JetBrainsMono_400Regular } from "@expo-google-fonts/jetbrains-mono";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { BackendProvider } from "../src/backend";
import { colors, fonts } from "../src/ui/theme";

SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function RootLayout() {
  const [loaded, error] = useFonts({
    Archivo_400Regular,
    Archivo_500Medium,
    Archivo_600SemiBold,
    Archivo_800ExtraBold,
    JetBrainsMono_400Regular,
  });

  useEffect(() => {
    if (loaded || error) SplashScreen.hideAsync().catch(() => undefined);
    if (error) console.warn("[PriceQuorum] fonts failed to load, using system fonts", error);
  }, [loaded, error]);

  if (!loaded && !error) return null;

  return (
    <SafeAreaProvider>
      <BackendProvider>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: colors.forest },
            headerTintColor: colors.paperLight,
            headerTitleStyle: { fontFamily: fonts.semibold },
            contentStyle: { backgroundColor: colors.forest },
          }}
        >
          <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
          <Stack.Screen name="runs/[id]" options={{ title: "Run" }} />
        </Stack>
      </BackendProvider>
    </SafeAreaProvider>
  );
}

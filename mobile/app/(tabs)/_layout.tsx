import { Tabs } from "expo-router/js-tabs";
import { Text, type ColorValue } from "react-native";

import { colors, fonts } from "../../src/ui/theme";

/** A plain glyph per tab keeps the bar legible without an icon font. */
function Glyph({ symbol, color }: { symbol: string; color: ColorValue }) {
  return (
    <Text accessible={false} style={{ fontFamily: fonts.display, fontSize: 18, color }}>
      {symbol}
    </Text>
  );
}

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: { backgroundColor: colors.forest, borderTopColor: colors.olive },
        tabBarActiveTintColor: colors.paperLight,
        tabBarInactiveTintColor: colors.brass,
        tabBarLabelStyle: { fontFamily: fonts.semibold, fontSize: 12 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: "Change", tabBarAccessibilityLabel: "Start a price change", tabBarIcon: ({ color }) => <Glyph symbol="$" color={color} /> }}
      />
      <Tabs.Screen
        name="ledger"
        options={{ title: "Ledger", tabBarAccessibilityLabel: "Check the ledger", tabBarIcon: ({ color }) => <Glyph symbol="#" color={color} /> }}
      />
      <Tabs.Screen
        name="evidence"
        options={{ title: "Evidence", tabBarAccessibilityLabel: "Evaluation evidence", tabBarIcon: ({ color }) => <Glyph symbol="%" color={color} /> }}
      />
      <Tabs.Screen
        name="settings"
        options={{ title: "Settings", tabBarAccessibilityLabel: "Backend settings", tabBarIcon: ({ color }) => <Glyph symbol="*" color={color} /> }}
      />
    </Tabs>
  );
}

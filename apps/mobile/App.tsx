import type { ComponentType } from 'react';
import { StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { StatusBar } from 'expo-status-bar';
import * as Notifications from 'expo-notifications';
import { DarkTheme, NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';

import { tokens } from '@homepilot/ui';

// MB9 — show push notifications while the app is foregrounded.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

// MB9 — tab icons (per route, shared with the design tokens for colour).
const TAB_ICONS: Record<string, keyof typeof Ionicons.glyphMap> = {
  Voice: 'mic',
  Chat: 'chatbubble-ellipses',
  Home: 'home',
  Imagine: 'image',
  Devices: 'hardware-chip',
  Account: 'person-circle',
};

import AccountScreen from './src/screens/AccountScreen';
import ChatScreen from './src/screens/ChatScreen';
import DevicesScreen from './src/screens/DevicesScreen';
import HomeScreen from './src/screens/HomeScreen';
import ImagineScreen from './src/screens/ImagineScreen';
import VoiceScreen from './src/screens/VoiceScreen';

const Tab = createBottomTabNavigator();

// Dark navigation theme from the shared design tokens.
const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: tokens.color.primary,
    background: tokens.color.bg,
    card: tokens.color.bg,
    text: tokens.color.text,
    border: tokens.color.surface,
  },
};

// Handle the top safe-area inset at the navigator boundary so the existing
// screens stay untouched (headers are hidden — each screen renders its own
// title). The tab bar handles the bottom inset itself.
function withSafeTop(Screen: ComponentType): ComponentType {
  return function SafeScreen() {
    return (
      <SafeAreaView edges={['top']} style={styles.safe}>
        <Screen />
      </SafeAreaView>
    );
  };
}

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <NavigationContainer theme={navTheme}>
        <Tab.Navigator
          screenOptions={({ route }) => ({
            headerShown: false,
            tabBarActiveTintColor: tokens.color.primary,
            tabBarInactiveTintColor: tokens.color.muted,
            tabBarStyle: {
              backgroundColor: tokens.color.bg,
              borderTopColor: tokens.color.surface,
            },
            tabBarLabelStyle: { fontSize: tokens.font.size.sm, fontWeight: '600' },
            tabBarIcon: ({ color, size }) => (
              <Ionicons name={TAB_ICONS[route.name] ?? 'ellipse'} color={color} size={size} />
            ),
          })}
        >
          <Tab.Screen name="Voice" component={withSafeTop(VoiceScreen)} />
          <Tab.Screen name="Chat" component={withSafeTop(ChatScreen)} />
          <Tab.Screen name="Home" component={withSafeTop(HomeScreen)} />
          <Tab.Screen name="Imagine" component={withSafeTop(ImagineScreen)} />
          <Tab.Screen name="Devices" component={withSafeTop(DevicesScreen)} />
          <Tab.Screen name="Account" component={withSafeTop(AccountScreen)} />
        </Tab.Navigator>
      </NavigationContainer>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: tokens.color.bg,
  },
});

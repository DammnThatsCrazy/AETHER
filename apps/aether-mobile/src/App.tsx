/**
 * Aether Mobile root — navigation skeleton.
 *
 * C4 lands a compiling shell: the SDK is wired (see ./client) and the app renders a
 * placeholder home surface. The full feature screens (Today / Copilot / Explore /
 * Pulse / exceptions) and governed mobile actions are C5–C7, not this session.
 */
import React from 'react';
import { SafeAreaView, StyleSheet, Text, View } from 'react-native';

export default function App(): React.JSX.Element {
  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.center}>
        <Text style={styles.title}>Aether</Text>
        <Text style={styles.subtitle}>Intelligence companion</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0b0d12' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { color: '#f5f7fa', fontSize: 28, fontWeight: '700' },
  subtitle: { color: '#8b93a7', fontSize: 15, marginTop: 6 },
});

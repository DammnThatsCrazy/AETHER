/**
 * Kyber Mobile root — navigation skeleton.
 *
 * C4 lands a compiling shell bound to the operator plane. Full operator surfaces
 * (Pulse / Exceptions / Incidents / Runs / Reviews) and governed Tier-0–3 actions
 * (challenge / step-up / device-sign over the Kyber command plane) are C5–C7.
 */
import React from 'react';
import { SafeAreaView, StyleSheet, Text, View } from 'react-native';

export default function App(): React.JSX.Element {
  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.center}>
        <Text style={styles.title}>Kyber</Text>
        <Text style={styles.subtitle}>Operator companion</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#0a0a0a' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { color: '#ffffff', fontSize: 28, fontWeight: '700' },
  subtitle: { color: '#9a9a9a', fontSize: 15, marginTop: 6 },
});

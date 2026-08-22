/**
 * Kyber Mobile root — typed navigator wiring the nine operator-companion
 * screens (Pulse / Exceptions / Incidents / Runs / Reviews / Briefings /
 * Actions / Receipts / Account).
 *
 * Navigation uses `createNavigator<KyberRoutes>()` from `@aether/mobile-ui`: the
 * app holds the active tab, pushes typed routes through the navigator, and
 * renders the matching screen inside the shared `Screen` shell. All screens are
 * read-only (M2 "no offline mutation" invariant); governed actions (approve /
 * suspend / revoke / resolve / suppress / acknowledge) live on the desktop
 * command plane and are never dispatched from this binary. M6b adds the
 * read-only Actions (tier 0-3 availability digest + device-bound step-up) and
 * Receipts (durable command-receipt visibility) surfaces.
 */
import React, { useState } from 'react';
import { SafeAreaView, StyleSheet, View } from 'react-native';

import { theme } from '@aether/mobile-ui';

import { TabBar } from './components/TabBar';
import { navigate } from './navigator';
import type { KyberTab } from './routes';
import AccountScreen from './screens/AccountScreen';
import ActionsScreen from './screens/ActionsScreen';
import BriefingsScreen from './screens/BriefingsScreen';
import ExceptionsScreen from './screens/ExceptionsScreen';
import IncidentsScreen from './screens/IncidentsScreen';
import PulseScreen from './screens/PulseScreen';
import ReceiptsScreen from './screens/ReceiptsScreen';
import ReviewsScreen from './screens/ReviewsScreen';
import RunsScreen from './screens/RunsScreen';

export default function App(): React.JSX.Element {
  const [tab, setTab] = useState<KyberTab>('Pulse');

  const selectTab = (next: KyberTab): void => {
    setTab(next);
    // Keep the typed navigator in sync — root tabs are pushed routes, so
    // deep-link / goBack semantics stay coherent with the registry.
    navigate(next);
  };

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.body}>
        {tab === 'Pulse' && <PulseScreen />}
        {tab === 'Exceptions' && <ExceptionsScreen />}
        {tab === 'Incidents' && <IncidentsScreen />}
        {tab === 'Runs' && <RunsScreen />}
        {tab === 'Reviews' && <ReviewsScreen />}
        {tab === 'Briefings' && <BriefingsScreen />}
        {tab === 'Actions' && <ActionsScreen />}
        {tab === 'Receipts' && <ReceiptsScreen />}
        {tab === 'Account' && <AccountScreen />}
      </View>
      <TabBar active={tab} onSelect={selectTab} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.colors.background },
  body: { flex: 1 },
});

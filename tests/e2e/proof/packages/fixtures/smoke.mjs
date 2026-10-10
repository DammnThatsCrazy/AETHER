import pkg from './dist/loaders.js';
const { findFixtureDir, loadRawFixture, loadExpectedNormalized, loadExpectedGraphOutputs, loadExpected360Outputs, loadExpectedLensOutput, fixturesDir, listAvailableFixtures } = pkg;

const log = (...args) => console.log(...args);

const test = async () => {
  log('fixturesDir:', fixturesDir());
  log('findFixtureDir("stripe-customer"):', findFixtureDir('stripe-customer'));
  log('findFixtureDir("sdk-heartbeat"):', findFixtureDir('sdk-heartbeat'));
  log('findFixtureDir("email-open"):', findFixtureDir('email-open'));
  log('findFixtureDir("360-profile"):', findFixtureDir('360-profile'));
  log('findFixtureDir("heartbeat"):', findFixtureDir('heartbeat'));
  log('findFixtureDir("offline-queued"):', findFixtureDir('offline-queued'));
  
  const raw = await loadRawFixture('stripe-customer');
  log('loadRawFixture("stripe-customer") keys:', Object.keys(raw));
  
  const sdkRaw = await loadRawFixture('sdk-heartbeat');
  log('loadRawFixture("sdk-heartbeat") isArray:', Array.isArray(sdkRaw));
  log('  first event:', JSON.stringify(sdkRaw[0]).slice(0, 80) + '...');
  
  const norm = await loadExpectedNormalized('stripe-customer');
  log('loadExpectedNormalized("stripe-customer") keys:', Object.keys(norm));
  
  const graph = await loadExpectedGraphOutputs('stripe-customer');
  log('loadExpectedGraphOutputs nodes:', graph.nodes.length, 'edges:', graph.edges.length);
  
  const r360 = await loadExpected360Outputs('stripe-customer');
  log('loadExpected360Outputs profile keys:', Object.keys(r360.profile));
  log('loadExpected360Outputs campaign keys:', Object.keys(r360.campaign));
  log('loadExpected360Outputs communications:', r360.communications.length);
  
  const lens = await loadExpectedLensOutput('stripe-customer');
  log('loadExpectedLensOutput keys:', Object.keys(lens));
  
  try { findFixtureDir('unknown-key'); } catch(e) { log('Unknown key error OK:', e.message.slice(0, 60) + '...'); }
  
  try { await loadRawFixture('nonexistent-foo'); } catch(e) { log('Missing file error OK:', e.message.slice(0, 60) + '...'); }
  
  const avail = await listAvailableFixtures(fixturesDir() + '/stripe');
  log('Available in stripe:', avail);
  
  log('\n=== ALL SMOKE TESTS PASSED ===');
};

test().catch(e => { console.error('SMOKE FAILED:', e); process.exit(1); });

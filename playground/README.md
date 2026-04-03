# Aether SDK Playground

An interactive **multi-VM Web3 wallet simulation** environment for the [Aether Web SDK](../packages/web) (`@aether/web` v8.7.0). Simulate wallet connections across all 7 VM families (EVM, Solana, Bitcoin, SUI, NEAR, TRON, Cosmos), trigger DeFi protocol interactions (Uniswap, AAVE, Jupiter, Marinade, Wormhole, Ref Finance, and more), view cross-chain portfolios, and inspect SDK event capture -- all from a single-page demo interface served by Vite.

## Tech Stack

| Layer     | Technology                |
|-----------|---------------------------|
| Markup    | HTML                      |
| Logic     | Vanilla JavaScript (ES Modules) |
| Dev Server| [Vite](https://vitejs.dev/) 5.x (port **5173**) |
| SDK       | `@aether/web` v8.7.0 (linked locally via `file:../packages/web`) |

## Features

- **Multi-VM wallet connections** -- simulate MetaMask (EVM), Ledger (EVM), Phantom (Solana/SVM), and UniSat (Bitcoin) wallet connections with realistic addresses and chain data
- **DeFi protocol simulations** -- trigger Uniswap swaps, AAVE supply, Jupiter swaps, Marinade staking, and Wormhole cross-chain bridge transfers
- **Cross-chain portfolio dashboard** -- view aggregated portfolio value, token balances, and DeFi positions across all connected wallets
- **Wallet classification** -- automatic wallet type tagging (hot, cold, smart, exchange) with visual badges
- **Event log** -- real-time, timestamped log of every SDK event (wallet connects, transactions, DeFi interactions, portfolio updates) with color-coded categories
- **Connected wallets panel** -- live view of all connected wallets with VM-specific icons, addresses, chain info, and classification tags
- **Tabbed detail views** -- Portfolio, Tokens, DeFi Positions, Identity, and Consent tabs with live JSON state
- **SDK initialization with debug mode** -- configure the API key, endpoint, privacy settings, Web3 tracking modules, and feature flags

## Quick Start

```bash
# From the repository root
cd playground

# Install dependencies (only required once)
npm install

# Start the dev server
npm run dev
```

Vite will start on **http://localhost:5173**. Open the URL in your browser to load the playground.

## Demo Interface

The playground presents a dark-themed single-page UI organized into action groups by VM family:

```
+------------------------------------------------------------------------------+
|  Aether SDK Playground  v8.7.0                                               |
|  Multi-VM Web3 Wallet Tracking                                               |
|  EVM • Solana • Bitcoin • SUI • NEAR • TRON • Cosmos                         |
|                                                                              |
|  SDK   [Init SDK] [Reset]                                                    |
|  EVM   [Connect MetaMask] [Connect Ledger] [Uniswap Swap] [AAVE Supply]     |
|  SVM   [Connect Phantom] [Jupiter Swap] [Marinade Stake]                     |
|  SUI   [Connect SUI Wallet] [SUI DeFi]                                      |
|  NEAR  [Connect NEAR Wallet] [Ref Finance]                                  |
|  Multi [Connect BTC] [Bridge ETH→SOL] [Portfolio] [Disconnect All]           |
|                                                                              |
|  ● SDK initialized  [EVM] [SVM] [BTC] [SUI] [NEAR] [5 wallets]             |
+--------------------------------------+---------------------------------------+
|  Event Log           (18 events)     |  Connected Wallets    (5 wallets)     |
|  ──────────────────────────────────  |  ───────────────────────────────────  |
|  [12:00:01] WALLET MetaMask...       |  ┌──────────────────────────────────┐ |
|  [12:00:03] TX Uniswap swap...       |  │ EVM  0xd8dA...6045  hot         │ |
|  [12:00:05] DEFI AAVE supply...      |  │ SVM  7xKX...9mP1   hot         │ |
|  [12:00:07] WALLET SUI connected...  |  │ BTC  bc1q...w508d   cold        │ |
|  [12:00:09] PORTFOLIO update...      |  │ SUI  0x2a9...f812   hot         │ |
|                                      |  │ NEAR acct.near      hot         │ |
|                                      |  └──────────────────────────────────┘ |
+------------------------------------------------------------------------------+
|  [Portfolio]  [Tokens]  [DeFi Positions]  [Identity]  [Consent]              |
|  ──────────────────────────────────────────────────────────────              |
|  Total Value     Wallets      Chains              24h Change                |
|  $256,847.32     5            5 (EVM/SVM/BTC/SUI/NEAR)  +2.4%              |
+------------------------------------------------------------------------------+
```

## Available Demo Actions

### SDK Actions

| Button            | SDK Method Called                          | Description                                      |
|-------------------|-------------------------------------------|--------------------------------------------------|
| **Init SDK**      | `aether.init({...})`                      | Initializes the SDK with Web3 multi-VM tracking enabled. |
| **Reset**         | `aether.reset()`                          | Resets the SDK, disconnects all wallets, clears state. |

### EVM Actions

| Button               | SDK Method Called                              | Description                                      |
|----------------------|------------------------------------------------|--------------------------------------------------|
| **Connect MetaMask** | `aether.wallet.connect(addr, {chainId, type})` | Simulates MetaMask wallet connection on Ethereum mainnet. |
| **Connect Ledger**   | `aether.wallet.connect(addr, {type: 'ledger'})` | Simulates Ledger hardware wallet (classified as cold wallet). |
| **Uniswap Swap**     | `aether.wallet.transaction(txHash, {...})`     | Simulates a WETH→USDC swap on Uniswap V3 with DeFi protocol tracking. |
| **AAVE Supply**      | `aether.wallet.transaction(txHash, {...})`     | Simulates an ETH supply position on AAVE V3 lending protocol. |

### SVM (Solana) Actions

| Button               | SDK Method Called                              | Description                                      |
|----------------------|------------------------------------------------|--------------------------------------------------|
| **Connect Phantom**  | `aether.wallet.connectSVM(addr, {type})`       | Simulates Phantom wallet connection on Solana mainnet. |
| **Jupiter Swap**     | `aether.wallet.transaction(sig, {...})`        | Simulates a SOL→USDC swap on Jupiter aggregator. |
| **Marinade Stake**   | `aether.wallet.transaction(sig, {...})`        | Simulates SOL staking via Marinade Finance for mSOL. |

### Multi-Chain Actions

| Button               | SDK Method Called                              | Description                                      |
|----------------------|------------------------------------------------|--------------------------------------------------|
| **Connect BTC**      | `aether.wallet.connectBTC(addr, {type})`       | Simulates UniSat wallet connection on Bitcoin mainnet. |
| **Bridge ETH→SOL**   | `aether.wallet.transaction(txHash, {...})`     | Simulates a cross-chain bridge transfer via Wormhole (EVM to Solana). |
| **Portfolio**        | `aether.wallet.getPortfolio()`                 | Refreshes the cross-chain portfolio aggregation view. |
| **Disconnect All**   | `aether.wallet.disconnect()`                   | Disconnects all wallets and clears wallet state. |

## Configuration Options

The SDK is initialized with the following default configuration in the playground. Edit `index.html` to customize these values:

```js
aether.init({
  apiKey: 'playground_demo_key',
  debug: true,
  endpoint: 'https://localhost:9999',
  modules: {
    autoDiscovery: true,
    performanceTracking: true,
    errorTracking: true,
    experiments: true,
    intentPrediction: true,
    walletTracking: true,
    svmTracking: true,
    bitcoinTracking: true,
    tokenTracking: true,
    nftDetection: true,
    defiTracking: true,
    portfolioTracking: true,
    walletClassification: true,
    crossChainTracking: true,
  },
  privacy: {
    maskSensitiveFields: true,
  },
});
```

| Option                             | Default                    | Description                                    |
|------------------------------------|----------------------------|------------------------------------------------|
| `apiKey`                           | `playground_demo_key`      | API key used for the demo (not a real key).    |
| `debug`                            | `true`                     | Enables verbose console logging from the SDK.  |
| `endpoint`                         | `https://localhost:9999`   | Event ingestion endpoint (demo/stub).          |
| `modules.walletTracking`           | `true`                     | EVM wallet connection and event tracking.      |
| `modules.svmTracking`              | `true`                     | Solana/SVM wallet and transaction tracking.    |
| `modules.bitcoinTracking`          | `true`                     | Bitcoin wallet and UTXO tracking.              |
| `modules.tokenTracking`            | `true`                     | ERC-20/SPL token balance tracking.             |
| `modules.nftDetection`             | `true`                     | NFT ownership detection.                       |
| `modules.defiTracking`             | `true`                     | DeFi protocol interaction tracking (15 categories). |
| `modules.portfolioTracking`        | `true`                     | Cross-chain portfolio value aggregation.       |
| `modules.walletClassification`     | `true`                     | Wallet type classification (hot, cold, smart, exchange). |
| `modules.crossChainTracking`       | `true`                     | Cross-chain bridge and transfer tracking.      |
| `privacy.maskSensitiveFields`      | `true`                     | Redacts sensitive field values before sending.  |

## UI Panels

| Panel                | Content                                                                 |
|----------------------|-------------------------------------------------------------------------|
| **Event Log**        | Color-coded real-time log: wallet (purple), tx (yellow), defi (green), portfolio (blue), system (grey), identity (violet) |
| **Connected Wallets**| Cards with VM-colored icons (EVM blue, SVM purple, BTC orange), addresses, chain info, classification tags |
| **Portfolio**        | Aggregated stats: total value, wallet count, chain count, 24h change    |
| **Tokens**           | Token balances across all chains with amounts and USD values            |
| **DeFi Positions**   | Active DeFi positions with protocol name, category, TVL, and APY       |
| **Identity**         | Live JSON view of the SDK's identity state                              |
| **Consent**          | Live JSON view of the SDK's consent state                               |

## License

Proprietary. All rights reserved.

/**
 * Hardhat Configuration — Aether Smart Contracts
 *
 * Supports multi-chain deployment to Ethereum, Polygon, Arbitrum, Base, and Optimism.
 * RPC URLs and deployer keys are loaded from environment variables so that
 * no secrets are committed to source control.
 *
 * Install dependencies before use:
 *   npm install --save-dev @nomicfoundation/hardhat-toolbox
 */

require("@nomicfoundation/hardhat-toolbox");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
      viaIR: true,
    },
  },

  networks: {
    // Local development network (default)
    hardhat: {},
    localhost: {
      url: "http://127.0.0.1:8545",
    },

    // ── Mainnet chains ──────────────────────────────────────────────
    mainnet: {
      url: process.env.ETHEREUM_RPC || "https://eth.llamarpc.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1,
    },
    // Legacy alias kept for backward compat with multichain_deployer.py
    ethereum: {
      url: process.env.ETHEREUM_RPC || "https://eth.llamarpc.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1,
    },
    polygon: {
      url: process.env.POLYGON_RPC || "https://polygon-rpc.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 137,
    },
    arbitrum: {
      url: process.env.ARBITRUM_RPC || "https://arb1.arbitrum.io/rpc",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 42161,
    },
    base: {
      url: process.env.BASE_RPC || "https://mainnet.base.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 8453,
    },
    optimism: {
      url: process.env.OPTIMISM_RPC || "https://mainnet.optimism.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 10,
    },
    bsc: {
      url: process.env.BSC_RPC || "https://bsc-dataseed.binance.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 56,
    },
    avalanche: {
      url: process.env.AVALANCHE_RPC || "https://api.avax.network/ext/bc/C/rpc",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 43114,
    },
    zksync: {
      url: process.env.ZKSYNC_RPC || "https://mainnet.era.zksync.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 324,
    },
    linea: {
      url: process.env.LINEA_RPC || "https://rpc.linea.build",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 59144,
    },
    scroll: {
      url: process.env.SCROLL_RPC || "https://rpc.scroll.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 534352,
    },
    mantle: {
      url: process.env.MANTLE_RPC || "https://rpc.mantle.xyz",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 5000,
    },
    blast: {
      url: process.env.BLAST_RPC || "https://rpc.blast.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 81457,
    },
    fantom: {
      url: process.env.FANTOM_RPC || "https://rpc.ftm.tools",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 250,
    },
    cronos: {
      url: process.env.CRONOS_RPC || "https://evm.cronos.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 25,
    },
    polygonZkEvm: {
      url: process.env.POLYGON_ZKEVM_RPC || "https://zkevm-rpc.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1101,
    },

    // ── Testnet chains ──────────────────────────────────────────────
    sepolia: {
      url: process.env.ETHEREUM_TESTNET_RPC || "https://rpc.sepolia.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 11155111,
    },
    amoy: {
      url: process.env.POLYGON_TESTNET_RPC || "https://rpc-amoy.polygon.technology",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 80002,
    },
    arbitrumSepolia: {
      url: process.env.ARBITRUM_TESTNET_RPC || "https://sepolia-rollup.arbitrum.io/rpc",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 421614,
    },
    baseSepolia: {
      url: process.env.BASE_TESTNET_RPC || "https://sepolia.base.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 84532,
    },
    optimismSepolia: {
      url: process.env.OPTIMISM_TESTNET_RPC || "https://sepolia.optimism.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 11155420,
    },
  },

  etherscan: {
    apiKey: {
      // Mainnets
      mainnet: process.env.ETHERSCAN_KEY || "",
      polygon: process.env.POLYGONSCAN_KEY || "",
      arbitrumOne: process.env.ARBISCAN_KEY || "",
      base: process.env.BASESCAN_KEY || "",
      optimisticEthereum: process.env.OPTIMISM_ETHERSCAN_KEY || "",
      bsc: process.env.BSCSCAN_KEY || "",
      avalanche: process.env.SNOWTRACE_KEY || "",
      zksync: process.env.ZKSYNC_EXPLORER_KEY || "",
      linea: process.env.LINEASCAN_KEY || "",
      scroll: process.env.SCROLLSCAN_KEY || "",
      mantle: process.env.MANTLE_EXPLORER_KEY || "",
      blast: process.env.BLASTSCAN_KEY || "",
      opera: process.env.FTMSCAN_KEY || "",
      cronos: process.env.CRONOSCAN_KEY || "",
      polygonZkEvm: process.env.POLYGON_ZKEVM_EXPLORER_KEY || "",
      // Testnets (use same keys — Etherscan API keys work across testnet/mainnet)
      sepolia: process.env.ETHERSCAN_KEY || "",
      polygonAmoy: process.env.POLYGONSCAN_KEY || "",
      arbitrumSepolia: process.env.ARBISCAN_KEY || "",
      baseSepolia: process.env.BASESCAN_KEY || "",
      optimismSepolia: process.env.OPTIMISM_ETHERSCAN_KEY || "",
    },
  },

  gasReporter: {
    enabled: process.env.REPORT_GAS === "true",
    currency: "USD",
  },
};

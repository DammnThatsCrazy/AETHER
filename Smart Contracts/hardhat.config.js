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

    // ── Tier 1 — High TVL / major ecosystems ────────────────────────
    gnosis: {
      url: process.env.GNOSIS_RPC || "https://rpc.gnosischain.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 100,
    },
    arbitrumNova: {
      url: process.env.ARBITRUM_NOVA_RPC || "https://nova.arbitrum.io/rpc",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 42170,
    },
    opBnb: {
      url: process.env.OPBNB_RPC || "https://opbnb-mainnet-rpc.bnbchain.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 204,
    },
    mode: {
      url: process.env.MODE_RPC || "https://mainnet.mode.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 34443,
    },
    taiko: {
      url: process.env.TAIKO_RPC || "https://rpc.mainnet.taiko.xyz",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 167000,
    },
    berachain: {
      url: process.env.BERACHAIN_RPC || "https://rpc.berachain.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 80094,
    },
    zora: {
      url: process.env.ZORA_RPC || "https://rpc.zora.energy",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 7777777,
    },
    kava: {
      url: process.env.KAVA_RPC || "https://evm.kava.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 2222,
    },
    moonbeam: {
      url: process.env.MOONBEAM_RPC || "https://rpc.api.moonbeam.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1284,
    },
    celo: {
      url: process.env.CELO_RPC || "https://forno.celo.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 42220,
    },

    // ── Tier 2 — Established chains ─────────────────────────────────
    metis: {
      url: process.env.METIS_RPC || "https://andromeda.metis.io/?owner=1088",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1088,
    },
    aurora: {
      url: process.env.AURORA_RPC || "https://mainnet.aurora.dev",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1313161554,
    },
    fraxtal: {
      url: process.env.FRAXTAL_RPC || "https://rpc.frax.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 252,
    },
    mantaPacific: {
      url: process.env.MANTA_RPC || "https://pacific-rpc.manta.network/http",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 169,
    },
    xlayer: {
      url: process.env.XLAYER_RPC || "https://rpc.xlayer.tech",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 196,
    },
    moonriver: {
      url: process.env.MOONRIVER_RPC || "https://rpc.api.moonriver.moonbeam.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1285,
    },
    klaytn: {
      url: process.env.KLAYTN_RPC || "https://public-node-api.klaytnapi.com/v1/cypress",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 8217,
    },
    boba: {
      url: process.env.BOBA_RPC || "https://mainnet.boba.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 288,
    },
    canto: {
      url: process.env.CANTO_RPC || "https://canto.gravitychain.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 7700,
    },
    astar: {
      url: process.env.ASTAR_RPC || "https://evm.astar.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 592,
    },

    // ── Tier 3 — Emerging / niche ────────────────────────────────────
    evmos: {
      url: process.env.EVMOS_RPC || "https://evmos-evm.publicnode.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 9001,
    },
    rootstock: {
      url: process.env.ROOTSTOCK_RPC || "https://public-node.rsk.co",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 30,
    },
    worldchain: {
      url: process.env.WORLDCHAIN_RPC || "https://worldchain-mainnet.g.alchemy.com/public",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 480,
    },
    lisk: {
      url: process.env.LISK_RPC || "https://rpc.api.lisk.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1135,
    },
    cyber: {
      url: process.env.CYBER_RPC || "https://cyber.alt.technology",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 7560,
    },
    soneium: {
      url: process.env.SONEIUM_RPC || "https://rpc.soneium.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1868,
    },

    // ── Tier 4 — Additional EVM chains ──────────────────────────────
    zetachain: {
      url: process.env.ZETACHAIN_RPC || "https://zetachain-evm.publicnode.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 7000,
    },
    flare: {
      url: process.env.FLARE_RPC || "https://flare-api.flare.network/ext/C/rpc",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 14,
    },
    wemix: {
      url: process.env.WEMIX_RPC || "https://api.wemix.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1111,
    },
    oktChain: {
      url: process.env.OKT_RPC || "https://exchainrpc.okex.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 66,
    },
    merlin: {
      url: process.env.MERLIN_RPC || "https://rpc.merlinchain.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 4200,
    },
    core: {
      url: process.env.CORE_RPC || "https://rpc.coredao.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1116,
    },
    fuse: {
      url: process.env.FUSE_RPC || "https://rpc.fuse.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 122,
    },
    iotex: {
      url: process.env.IOTEX_RPC || "https://babel-api.mainnet.iotex.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 4689,
    },
    bob: {
      url: process.env.BOB_RPC || "https://rpc.gobob.xyz",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 60808,
    },
    unichain: {
      url: process.env.UNICHAIN_RPC || "https://mainnet.unichain.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 130,
    },
    abstract: {
      url: process.env.ABSTRACT_RPC || "https://api.mainnet.abs.xyz",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 2741,
    },
    ink: {
      url: process.env.INK_RPC || "https://rpc-gel.inkonchain.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 57073,
    },
    gravity: {
      url: process.env.GRAVITY_RPC || "https://rpc.gravity.xyz",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1625,
    },
    apechain: {
      url: process.env.APECHAIN_RPC || "https://rpc.apechain.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 33139,
    },
    conflux: {
      url: process.env.CONFLUX_RPC || "https://evm.confluxrpc.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1030,
    },
    oasisSapphire: {
      url: process.env.OASIS_SAPPHIRE_RPC || "https://sapphire.oasis.io",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 23294,
    },
    neonEvm: {
      url: process.env.NEON_RPC || "https://neon-proxy-mainnet.solana.p2p.org",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 245022934,
    },
    thundercore: {
      url: process.env.THUNDERCORE_RPC || "https://mainnet-rpc.thundercore.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 108,
    },
    kcc: {
      url: process.env.KCC_RPC || "https://rpc-mainnet.kcc.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 321,
    },
    xdc: {
      url: process.env.XDC_RPC || "https://erpc.xinfin.network",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 50,
    },
    telos: {
      url: process.env.TELOS_RPC || "https://mainnet.telos.net/evm",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 40,
    },
    filecoin: {
      url: process.env.FILECOIN_RPC || "https://api.node.glif.io/rpc/v1",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 314,
    },
    seiEvm: {
      url: process.env.SEI_EVM_RPC || "https://evm-rpc.sei-apis.com",
      accounts: process.env.DEPLOYER_KEY ? [process.env.DEPLOYER_KEY] : [],
      chainId: 1329,
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
      // Tier 1
      gnosis: process.env.GNOSISSCAN_KEY || "",
      arbitrumNova: process.env.ARBISCAN_KEY || "",
      opBnb: process.env.OPBNB_EXPLORER_KEY || "",
      mode: process.env.MODE_EXPLORER_KEY || "",
      taiko: process.env.TAIKO_EXPLORER_KEY || "",
      berachain: process.env.BERACHAIN_EXPLORER_KEY || "",
      zora: process.env.ZORA_EXPLORER_KEY || "",
      kava: process.env.KAVA_EXPLORER_KEY || "",
      moonbeam: process.env.MOONBEAM_EXPLORER_KEY || "",
      celo: process.env.CELOSCAN_KEY || "",
      // Tier 2
      metis: process.env.METIS_EXPLORER_KEY || "",
      aurora: process.env.AURORA_EXPLORER_KEY || "",
      fraxtal: process.env.FRAXTAL_EXPLORER_KEY || "",
      mantaPacific: process.env.MANTA_EXPLORER_KEY || "",
      xlayer: process.env.XLAYER_EXPLORER_KEY || "",
      moonriver: process.env.MOONRIVER_EXPLORER_KEY || "",
      klaytn: process.env.KLAYTN_EXPLORER_KEY || "",
      boba: process.env.BOBA_EXPLORER_KEY || "",
      canto: process.env.CANTO_EXPLORER_KEY || "",
      astar: process.env.ASTAR_EXPLORER_KEY || "",
      // Tier 3
      evmos: process.env.EVMOS_EXPLORER_KEY || "",
      rootstock: process.env.ROOTSTOCK_EXPLORER_KEY || "",
      worldchain: process.env.WORLDCHAIN_EXPLORER_KEY || "",
      lisk: process.env.LISK_EXPLORER_KEY || "",
      cyber: process.env.CYBER_EXPLORER_KEY || "",
      soneium: process.env.SONEIUM_EXPLORER_KEY || "",
      // Tier 4
      zetachain: process.env.ZETACHAIN_EXPLORER_KEY || "",
      flare: process.env.FLARE_EXPLORER_KEY || "",
      wemix: process.env.WEMIX_EXPLORER_KEY || "",
      oktChain: process.env.OKT_EXPLORER_KEY || "",
      merlin: process.env.MERLIN_EXPLORER_KEY || "",
      core: process.env.CORE_EXPLORER_KEY || "",
      fuse: process.env.FUSE_EXPLORER_KEY || "",
      iotex: process.env.IOTEX_EXPLORER_KEY || "",
      bob: process.env.BOB_EXPLORER_KEY || "",
      unichain: process.env.UNICHAIN_EXPLORER_KEY || "",
      abstract: process.env.ABSTRACT_EXPLORER_KEY || "",
      ink: process.env.INK_EXPLORER_KEY || "",
      gravity: process.env.GRAVITY_EXPLORER_KEY || "",
      apechain: process.env.APECHAIN_EXPLORER_KEY || "",
      conflux: process.env.CONFLUX_EXPLORER_KEY || "",
      oasisSapphire: process.env.OASIS_SAPPHIRE_EXPLORER_KEY || "",
      neonEvm: process.env.NEON_EXPLORER_KEY || "",
      thundercore: process.env.THUNDERCORE_EXPLORER_KEY || "",
      kcc: process.env.KCC_EXPLORER_KEY || "",
      xdc: process.env.XDC_EXPLORER_KEY || "",
      telos: process.env.TELOS_EXPLORER_KEY || "",
      filecoin: process.env.FILECOIN_EXPLORER_KEY || "",
      seiEvm: process.env.SEI_EVM_EXPLORER_KEY || "",
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

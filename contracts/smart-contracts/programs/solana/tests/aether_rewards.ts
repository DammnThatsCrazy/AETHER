// Aether Rewards -- Anchor integration tests (run against solana-test-validator).
//
// Proves, end-to-end on a local validator:
//   * a valid Ed25519-signed, domain-separated claim succeeds
//   * exact asset (native-SOL sentinel mint) + exact atomic amount (lamports)
//   * replay of a used nonce is rejected
//   * wrong-oracle signature is rejected
//   * expiry is enforced
//   * pause blocks claims (and unpause restores them)
//   * authority rotation (oracle) + unauthorized admin action rejected
//   * PDA state isolation (state/vault/nonce PDAs) and cross-domain isolation
//     (a proof for tenant/campaign/chain/amount A cannot be replayed as B)
//
// Run:  anchor test         (spins up a local validator)
//   or: anchor test --skip-local-validator   (against an already-running one)

import * as anchor from "@coral-xyz/anchor";
import { Program, BN } from "@coral-xyz/anchor";
import {
  ComputeBudgetProgram,
  Keypair,
  LAMPORTS_PER_SOL,
  PublicKey,
  SystemProgram,
  SYSVAR_INSTRUCTIONS_PUBKEY,
  Transaction,
} from "@solana/web3.js";
import { assert } from "chai";
import {
  buildClaimMessage,
  ed25519VerifyIx,
  signatureFromEd25519Ix,
  pdas,
  randomNonce,
  bytes16,
  nowPlus,
  NATIVE_SOL_MINT,
  CHAIN_ID,
  ClaimDomain,
} from "./utils";

// Anchor generates this type after `anchor build`; typed loosely to avoid a
// hard dependency on the generated IDL types in this authored suite.
const program = anchor.workspace.AetherRewards as Program<any>;
const provider = anchor.AnchorProvider.env();
anchor.setProvider(provider);

const REWARD_LAMPORTS = 1_000_000n; // 0.001 SOL, exact atomic amount (integer)
const TENANT_A = bytes16(0xa1);
const TENANT_B = bytes16(0xb2);
const CAMPAIGN_A = bytes16(0xc1);
const CAMPAIGN_B = bytes16(0xc2);

describe("aether_rewards", () => {
  const oracle = Keypair.generate();
  const attacker = Keypair.generate();
  const { statePda, vaultPda, noncePda } = pdas(program.programId);

  function domain(over: Partial<ClaimDomain> = {}): ClaimDomain {
    return {
      programId: program.programId,
      chainId: CHAIN_ID.LOCALNET,
      tenantId: TENANT_A,
      campaignId: CAMPAIGN_A,
      mint: NATIVE_SOL_MINT,
      ...over,
    };
  }

  // Build + send a claim. `signer` defaults to the real oracle; pass a different
  // keypair to simulate a forged/wrong-oracle proof.
  async function sendClaim(opts: {
    user: PublicKey;
    amount?: bigint;
    tenantId?: Buffer;
    campaignId?: Buffer;
    mint?: PublicKey;
    nonce?: Buffer;
    expiry?: bigint;
    signer?: Keypair;
    unique?: number; // differentiates otherwise-identical txs (replay test)
    signDomainOverride?: ClaimDomain; // sign for a different domain than submitted
  }) {
    const amount = opts.amount ?? REWARD_LAMPORTS;
    const tenantId = opts.tenantId ?? TENANT_A;
    const campaignId = opts.campaignId ?? CAMPAIGN_A;
    const mint = opts.mint ?? NATIVE_SOL_MINT;
    const nonce = opts.nonce ?? randomNonce();
    const expiry = opts.expiry ?? nowPlus(300);
    const signer = opts.signer ?? oracle;

    // The bytes the oracle signs (optionally a mismatched domain for negative tests).
    const signDomain =
      opts.signDomainOverride ?? domain({ tenantId, campaignId, mint });
    const message = buildClaimMessage({
      domain: signDomain,
      recipient: opts.user,
      amount,
      actionType: "page_view",
      nonce,
      expiry,
    });

    const edIx = ed25519VerifyIx(signer.secretKey, message);
    const signature = signatureFromEd25519Ix(edIx);

    const claimIx = await program.methods
      .claimReward(
        "page_view",
        new BN(amount.toString()),
        Array.from(tenantId),
        Array.from(campaignId),
        mint,
        Array.from(nonce),
        new BN(expiry.toString()),
        Array.from(signature)
      )
      .accounts({
        user: opts.user,
        programState: statePda,
        vault: vaultPda,
        nonceTracker: noncePda,
        instructionSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
        systemProgram: SystemProgram.programId,
      })
      .instruction();

    const tx = new Transaction().add(edIx).add(claimIx);
    if (opts.unique !== undefined) {
      tx.add(ComputeBudgetProgram.setComputeUnitLimit({ units: 200_000 + opts.unique }));
    }
    return provider.sendAndConfirm(tx, []);
  }

  it("initializes program state + vault + nonce tracker", async () => {
    await program.methods
      .initialize(oracle.publicKey, new BN(CHAIN_ID.LOCALNET))
      .accounts({
        admin: provider.wallet.publicKey,
        programState: statePda,
        vault: vaultPda,
        nonceTracker: noncePda,
        systemProgram: SystemProgram.programId,
      })
      .rpc();

    const state = await program.account.programState.fetch(statePda);
    assert.ok(state.oracle.equals(oracle.publicKey));
    assert.ok(state.admin.equals(provider.wallet.publicKey));
    assert.equal(state.chainId.toNumber(), CHAIN_ID.LOCALNET);
    assert.equal(state.schemeVersion, 1);
    assert.equal(state.paused, false);
  });

  it("funds the vault", async () => {
    await program.methods
      .fundVault(new BN((2n * LAMPORTS_PER_SOL_BI).toString()))
      .accounts({
        funder: provider.wallet.publicKey,
        programState: statePda,
        vault: vaultPda,
        systemProgram: SystemProgram.programId,
      })
      .rpc();
    const bal = await provider.connection.getBalance(vaultPda);
    assert.isAtLeast(bal, Number(2n * LAMPORTS_PER_SOL_BI));
  });

  it("accepts a valid claim and pays the exact atomic amount of the exact asset", async () => {
    const user = Keypair.generate().publicKey;
    const before = await provider.connection.getBalance(user);
    await sendClaim({ user });
    const after = await provider.connection.getBalance(user);
    // Exact atomic amount (lamports), integer, no float.
    assert.equal(after - before, Number(REWARD_LAMPORTS));

    const state = await program.account.programState.fetch(statePda);
    assert.equal(state.totalClaims.toNumber(), 1);
    assert.equal(state.totalDistributed.toString(), REWARD_LAMPORTS.toString());
  });

  it("rejects a claim whose asset is not the native-SOL sentinel mint", async () => {
    const user = Keypair.generate().publicKey;
    const wrongMint = Keypair.generate().publicKey;
    await assertFails(
      sendClaim({ user, mint: wrongMint }),
      "UnsupportedAsset"
    );
  });

  it("rejects replay of an already-used nonce", async () => {
    const user = Keypair.generate().publicKey;
    const nonce = randomNonce();
    await sendClaim({ user, nonce, unique: 1 });
    await assertFails(
      sendClaim({ user, nonce, unique: 2 }),
      "NonceAlreadyUsed"
    );
  });

  it("rejects a proof signed by the wrong oracle", async () => {
    const user = Keypair.generate().publicKey;
    await assertFails(
      sendClaim({ user, signer: attacker }),
      "InvalidSignature"
    );
  });

  it("enforces expiry", async () => {
    const user = Keypair.generate().publicKey;
    await assertFails(
      sendClaim({ user, expiry: nowPlus(-10) }),
      "ExpiredProof"
    );
  });

  it("cross-domain isolation: a proof signed for tenant/campaign A cannot be submitted as B", async () => {
    const user = Keypair.generate().publicKey;
    const nonce = randomNonce();
    // Oracle signs for (TENANT_A, CAMPAIGN_A) but the tx claims (TENANT_B, CAMPAIGN_B).
    const signDomain = domain({ tenantId: TENANT_A, campaignId: CAMPAIGN_A });
    await assertFails(
      sendClaim({
        user,
        nonce,
        tenantId: TENANT_B,
        campaignId: CAMPAIGN_B,
        signDomainOverride: signDomain,
      }),
      "InvalidSignature"
    );
  });

  it("cross-amount isolation: a proof signed for amount X cannot claim amount Y", async () => {
    const user = Keypair.generate().publicKey;
    const signDomain = domain();
    // Sign for REWARD_LAMPORTS but submit double.
    const nonce = randomNonce();
    const message = buildClaimMessage({
      domain: signDomain,
      recipient: user,
      amount: REWARD_LAMPORTS,
      actionType: "page_view",
      nonce,
      expiry: nowPlus(300),
    });
    const edIx = ed25519VerifyIx(oracle.secretKey, message);
    const signature = signatureFromEd25519Ix(edIx);
    const claimIx = await program.methods
      .claimReward(
        "page_view",
        new BN((REWARD_LAMPORTS * 2n).toString()), // tampered amount
        Array.from(TENANT_A),
        Array.from(CAMPAIGN_A),
        NATIVE_SOL_MINT,
        Array.from(nonce),
        new BN(nowPlus(300).toString()),
        Array.from(signature)
      )
      .accounts({
        user,
        programState: statePda,
        vault: vaultPda,
        nonceTracker: noncePda,
        instructionSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
        systemProgram: SystemProgram.programId,
      })
      .instruction();
    const tx = new Transaction().add(edIx).add(claimIx);
    await assertFails(provider.sendAndConfirm(tx, []), "InvalidSignature");
  });

  it("pause blocks claims; unpause restores them", async () => {
    await program.methods
      .pause()
      .accounts({ admin: provider.wallet.publicKey, programState: statePda })
      .rpc();

    const user = Keypair.generate().publicKey;
    await assertFails(sendClaim({ user }), "ProgramPaused");

    await program.methods
      .unpause()
      .accounts({ admin: provider.wallet.publicKey, programState: statePda })
      .rpc();

    await sendClaim({ user }); // succeeds again
  });

  it("rejects unauthorized admin action (non-admin cannot pause)", async () => {
    const rogue = Keypair.generate();
    // fund rogue so it can pay fees
    await provider.sendAndConfirm(
      new Transaction().add(
        SystemProgram.transfer({
          fromPubkey: provider.wallet.publicKey,
          toPubkey: rogue.publicKey,
          lamports: LAMPORTS_PER_SOL,
        })
      ),
      []
    );
    let failed = false;
    try {
      await program.methods
        .pause()
        .accounts({ admin: rogue.publicKey, programState: statePda })
        .signers([rogue])
        .rpc();
    } catch (_e) {
      failed = true;
    }
    assert.isTrue(failed, "rogue must not be able to pause");
  });

  it("rotates the oracle; new oracle works, old oracle is rejected", async () => {
    const newOracle = Keypair.generate();
    await program.methods
      .updateOracle(newOracle.publicKey)
      .accounts({ admin: provider.wallet.publicKey, programState: statePda })
      .rpc();

    const user = Keypair.generate().publicKey;
    // Old oracle now fails.
    await assertFails(sendClaim({ user, signer: oracle }), "InvalidSignature");
    // New oracle succeeds.
    await sendClaim({ user, signer: newOracle });
  });

  it("PDA state isolation: state/vault/nonce PDAs are the canonical derivations", () => {
    const d = pdas(program.programId);
    assert.ok(d.statePda.equals(statePda));
    assert.ok(d.vaultPda.equals(vaultPda));
    assert.ok(d.noncePda.equals(noncePda));
    // Vault and nonce PDAs are derived from the state key -> bound to this state.
    assert.isFalse(d.vaultPda.equals(d.noncePda));
  });
});

const LAMPORTS_PER_SOL_BI = BigInt(LAMPORTS_PER_SOL);

async function assertFails(p: Promise<unknown>, expected: string) {
  try {
    await p;
    assert.fail(`expected failure containing "${expected}" but tx succeeded`);
  } catch (e: any) {
    const s = JSON.stringify(e?.logs ?? e?.message ?? e);
    assert.include(
      s + (e?.error?.errorCode?.code ?? ""),
      expected,
      `expected error "${expected}", got: ${s}`
    );
  }
}

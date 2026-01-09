"""
Pool NFT Minting Policy V3 - Creates legitimate pool identities.
PlutusV3 / OpShin 0.27+ compatible.

Only NFTs from this policy are trusted by the pool validator.
Token name = sha256(tx_id || output_index) ensures uniqueness.

IMPORTANT: No validator hashes are baked into this contract.
The pool_validator_hash is passed in the Mint redeemer.

Compile: opshin build pool_nft_policy_v3.py
"""
# Use PlutusV3 ledger types (TxId is bytes directly, not a wrapper)
from opshin.ledger.api_v3 import *


# =============================================================================
# DATUM (must match pool_validator_v3.py EXACTLY)
# =============================================================================

@dataclass
class PoolDatum(PlutusData):
    """Pool configuration - contains all validator hashes and platform config."""
    CONSTR_ID = 0

    # Pool Identity
    pool_nft_policy: bytes
    pool_nft_name: bytes

    # Stake/Reward Tokens
    stake_token_policy: bytes
    stake_token_name: bytes
    reward_token_policy: bytes
    reward_token_name: bytes

    # Pool Parameters
    yield_rate: int
    min_stake: int
    owner: bytes
    total_staked: int

    # Validator Hashes (read at runtime, not baked in)
    staking_validator_hash: bytes   # 28 bytes
    position_nft_policy_hash: bytes # 28 bytes

    # Platform Configuration
    platform_fee_pkh: bytes
    deposit_fee_bps: int
    burn_address_hash: bytes

    # Pool State
    paused: int                     # 0 = active, 1 = paused (no new stakes)


# =============================================================================
# REDEEMERS
# =============================================================================

@dataclass
class Mint(PlutusData):
    """Mint a new pool NFT."""
    CONSTR_ID = 0
    output_index: int           # Which output receives the NFT
    pool_validator_hash: bytes  # Hash of the pool validator (28 bytes)


@dataclass
class Burn(PlutusData):
    """Burn pool NFT (for pool closure)."""
    CONSTR_ID = 1


PoolNFTRedeemer = Union[Mint, Burn]


# =============================================================================
# HELPERS
# =============================================================================

def has_token(v: Value, policy: bytes, name: bytes, qty: int) -> bool:
    """Check if value has exactly qty of token."""
    if policy in v.keys():
        tokens = v[policy]
        if name in tokens.keys():
            return tokens[name] == qty
    return False


def output_to_validator(out: TxOut, script_hash: bytes) -> bool:
    """Check if output goes to script address with given hash."""
    cred = out.address.payment_credential
    if isinstance(cred, ScriptCredential):
        return cred.credential_hash == script_hash
    return False


def valid_datum(out: TxOut, policy: bytes, name: bytes) -> bool:
    """Check output has valid PoolDatum with correct NFT info."""
    d = out.datum
    if isinstance(d, SomeOutputDatum):
        datum: PoolDatum = d.datum
        # Datum must reference this NFT
        if datum.pool_nft_policy != policy:
            return False
        if datum.pool_nft_name != name:
            return False
        # Basic sanity checks
        if datum.yield_rate <= 0:
            return False
        if datum.yield_rate > 10000:
            return False
        if datum.min_stake <= 0:
            return False
        if len(datum.owner) != 28:
            return False
        if datum.total_staked != 0:
            return False
        # Verify validator hashes are proper length
        if len(datum.staking_validator_hash) != 28:
            return False
        if len(datum.position_nft_policy_hash) != 28:
            return False
        if len(datum.platform_fee_pkh) != 28:
            return False
        if len(datum.burn_address_hash) != 28:
            return False
        return True
    return False


# =============================================================================
# MINTING POLICY
# =============================================================================

def validator(ctx: ScriptContext) -> None:
    """
    Pool NFT minting policy (PlutusV3).

    No validator hashes are baked in.
    The pool_validator_hash comes from the Mint redeemer.

    MINT: Creates exactly 1 NFT, must go to pool validator with valid datum.
    BURN: Allows burning (for pool closure).
    """
    tx: TxInfo = ctx.transaction
    purpose = ctx.purpose
    assert isinstance(purpose, Minting)

    # Get redeemer from context (PlutusV3 style)
    redeemer: PoolNFTRedeemer = ctx.redeemer

    policy_id = purpose.policy_id
    minted = tx.mint[policy_id]

    # ==========================================================================
    # MINT
    # ==========================================================================
    if isinstance(redeemer, Mint):
        # Validate pool_validator_hash is proper length
        assert len(redeemer.pool_validator_hash) == 28, "Invalid pool_validator_hash length"

        # Compute unique token name from first input tx_id
        # This ensures one-shot minting (input can only be spent once)
        first_input = tx.inputs[0].out_ref
        token_name = sha2_256(first_input.id)

        # Must mint exactly 1 of this token
        assert len(minted) == 1, "Must mint exactly 1 token"
        assert token_name in minted.keys(), "Invalid token name"
        assert minted[token_name] == 1, "Must mint exactly 1"

        # Get target output
        assert redeemer.output_index >= 0, "Invalid output index"
        assert redeemer.output_index < len(tx.outputs), "Output index out of range"
        target_out = tx.outputs[redeemer.output_index]

        # NFT must go to pool validator (hash from redeemer, not baked in)
        assert output_to_validator(target_out, redeemer.pool_validator_hash), "NFT must go to pool validator"

        # Output must have the NFT
        assert has_token(target_out.value, policy_id, token_name, 1), "NFT not in output"

        # Output must have valid datum referencing this NFT
        assert valid_datum(target_out, policy_id, token_name), "Invalid pool datum"

    # ==========================================================================
    # BURN
    # ==========================================================================
    elif isinstance(redeemer, Burn):
        # All minted values must be negative (burning)
        for name in minted.keys():
            assert minted[name] < 0, "Must burn (negative quantity)"

    else:
        assert False, "Invalid redeemer"

"""
Platform Authority NFT Policy - One-shot NFT for platform config.
PlutusV3 / OpShin 0.27+ compatible.

This policy mints a single NFT that identifies the Platform Authority UTxO.
The authority UTxO contains the platform configuration including who can create pools.

One-shot: Token name = sha256(first_input.id) ensures only one can ever be minted.

Compile: opshin build platform_authority_nft_policy.py
"""
from opshin.ledger.api_v3 import *


# =============================================================================
# DATUM - Platform configuration stored with the authority NFT
# =============================================================================

@dataclass
class PlatformAuthorityDatum(PlutusData):
    """
    Platform configuration - stored in the Platform Authority UTxO.

    This datum defines who is authorized to perform platform-level operations
    like creating new pools.
    """
    CONSTR_ID = 0

    # Authorization
    pool_creator_pkh: bytes         # 28 bytes - PKH authorized to create pools
    platform_admin_pkh: bytes       # 28 bytes - PKH that can update this config

    # Platform identity (for verification)
    platform_nft_policy: bytes      # 28 bytes - This policy's ID (self-reference)
    platform_nft_name: bytes        # 32 bytes - The authority NFT name


# =============================================================================
# REDEEMERS
# =============================================================================

@dataclass
class MintAuthority(PlutusData):
    """Mint the platform authority NFT (one-time, during deployment)."""
    CONSTR_ID = 0
    output_index: int


@dataclass
class BurnAuthority(PlutusData):
    """Burn the authority NFT (for platform migration/shutdown)."""
    CONSTR_ID = 1


PlatformAuthorityRedeemer = Union[MintAuthority, BurnAuthority]


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


def valid_authority_datum(out: TxOut, policy: bytes, name: bytes) -> bool:
    """Check output has valid PlatformAuthorityDatum."""
    d = out.datum
    if isinstance(d, SomeOutputDatum):
        datum: PlatformAuthorityDatum = d.datum
        # Self-reference check
        if datum.platform_nft_policy != policy:
            return False
        if datum.platform_nft_name != name:
            return False
        # PKH length validation
        if len(datum.pool_creator_pkh) != 28:
            return False
        if len(datum.platform_admin_pkh) != 28:
            return False
        return True
    return False


# =============================================================================
# MINTING POLICY
# =============================================================================

def validator(ctx: ScriptContext) -> None:
    """
    Platform Authority NFT minting policy (PlutusV3).

    MINT: Creates exactly 1 NFT during platform deployment.
          Token name derived from first input ensures one-shot.

    BURN: Allows burning for platform migration/shutdown.
    """
    tx: TxInfo = ctx.transaction
    purpose = ctx.purpose
    assert isinstance(purpose, Minting)

    redeemer: PlatformAuthorityRedeemer = ctx.redeemer
    policy_id = purpose.policy_id
    minted = tx.mint[policy_id]

    # ==========================================================================
    # MINT AUTHORITY
    # ==========================================================================
    if isinstance(redeemer, MintAuthority):
        # Compute unique token name from first input (one-shot)
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

        # Output must have the NFT
        assert has_token(target_out.value, policy_id, token_name, 1), "NFT not in output"

        # Output must have valid datum
        assert valid_authority_datum(target_out, policy_id, token_name), "Invalid authority datum"

    # ==========================================================================
    # BURN AUTHORITY
    # ==========================================================================
    elif isinstance(redeemer, BurnAuthority):
        # All minted values must be negative (burning)
        for name in minted.keys():
            assert minted[name] < 0, "Must burn (negative quantity)"

    else:
        assert False, "Invalid redeemer"

"""
Position NFT Minting Policy V3 - CIP-68 style position tokens.
PlutusV3 / OpShin 0.27+ compatible.

Creates paired NFTs for staking positions:
- Reference NFT (100): Holds position datum at staking validator
- User NFT (222): Ownership token held by staker

IMPORTANT: No validator hashes are baked into this contract.
All configuration is read from the PoolDatum at runtime.

Compile: opshin build position_nft_policy_v3.py
"""
# Use PlutusV3 ledger types
from opshin.ledger.api_v3 import *

# CIP-68 NFT Labels - Universal Constants (never change)
# These are defined by CIP-68 specification
CIP68_REFERENCE_LABEL: bytes = bytes.fromhex("000643b0")  # Label 100 - Reference NFT
CIP68_USER_LABEL: bytes = bytes.fromhex("000de140")       # Label 222 - User NFT


# =============================================================================
# POOL DATUM (must match pool_validator_v3.py EXACTLY)
# =============================================================================

@dataclass
class PoolDatum(PlutusData):
    """Pool configuration - contains all validator hashes."""
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
# POSITION DATUM (stored in position UTxO - must match staking_shared_v3.py)
# =============================================================================

@dataclass
class UserPositionDatum(PlutusData):
    """User staking position datum - MUST match staking_shared_v3.py."""
    CONSTR_ID = 1
    pool_nft_policy: bytes      # 28 bytes - links to pool
    pool_nft_name: bytes        # 32 bytes - links to specific pool
    user_pkh: bytes             # 28 bytes
    position_nft_name: bytes    # 32 bytes
    stake_amount: int
    staked_at: int              # POSIX ms
    last_claim: int             # POSIX ms
    total_claimed: int


# =============================================================================
# REDEEMERS - Include pool NFT info to find config at runtime
# =============================================================================

@dataclass
class MintPosition(PlutusData):
    """Mint new position NFT pair when staking."""
    CONSTR_ID = 0
    position_id: bytes          # Unique identifier for this position
    pool_nft_policy: bytes      # To find pool config
    pool_nft_name: bytes        # To find pool config


@dataclass
class BurnPosition(PlutusData):
    """Burn position NFT pair when unstaking."""
    CONSTR_ID = 1
    position_id: bytes          # Position being burned
    pool_nft_policy: bytes      # To find pool config
    pool_nft_name: bytes        # To find pool config


@dataclass
class RemintPosition(PlutusData):
    """
    Burn old position and mint new position in one transaction.
    Used for partial withdrawals where the position needs to be updated.

    Burns: old reference NFT (sent to burn address by spending validator)
           old user NFT (negative mint)
    Mints: new reference NFT (+1, goes to staking validator)
           new user NFT (+1, goes to user)
    """
    CONSTR_ID = 2
    old_position_id: bytes      # Position being replaced (for burning old user NFT)
    new_position_id: bytes      # New position (for minting new pair)
    pool_nft_policy: bytes      # To find pool config
    pool_nft_name: bytes        # To find pool config


PositionNFTRedeemer = Union[MintPosition, BurnPosition, RemintPosition]


# =============================================================================
# HELPERS
# =============================================================================

def has_nft(v: Value, policy: bytes, name: bytes) -> bool:
    """Check if value contains the NFT."""
    if policy in v.keys():
        tokens = v[policy]
        if name in tokens.keys():
            return tokens[name] >= 1
    return False


def make_reference_name(position_id: bytes) -> bytes:
    """Create CIP-68 reference NFT name: (100) prefix + position_id."""
    return CIP68_REFERENCE_LABEL + position_id


def make_user_name(position_id: bytes) -> bytes:
    """Create CIP-68 user NFT name: (222) prefix + position_id."""
    return CIP68_USER_LABEL + position_id


def find_pool_config(tx: TxInfo, pool_nft_policy: bytes, pool_nft_name: bytes) -> PoolDatum:
    """
    Find pool config from inputs or reference inputs by Pool NFT.
    Returns the PoolDatum containing all validator hashes.
    """
    # Check spent inputs first (for when pool is being spent during Register)
    for inp in tx.inputs:
        if has_nft(inp.resolved.value, pool_nft_policy, pool_nft_name):
            inp_datum = inp.resolved.datum
            if isinstance(inp_datum, SomeOutputDatum):
                pool_data: PoolDatum = inp_datum.datum
                return pool_data
    # Check reference inputs (for when pool is referenced during Burn)
    for ref in tx.reference_inputs:
        if has_nft(ref.resolved.value, pool_nft_policy, pool_nft_name):
            ref_datum = ref.resolved.datum
            if isinstance(ref_datum, SomeOutputDatum):
                pool_data2: PoolDatum = ref_datum.datum
                return pool_data2
    assert False, "Pool config not found"
    # Dummy return for type checker
    return PoolDatum(
        pool_nft_policy=b"", pool_nft_name=b"",
        stake_token_policy=b"", stake_token_name=b"",
        reward_token_policy=b"", reward_token_name=b"",
        yield_rate=0, min_stake=0, owner=b"", total_staked=0,
        staking_validator_hash=b"", position_nft_policy_hash=b"",
        platform_fee_pkh=b"", deposit_fee_bps=0, burn_address_hash=b"",
        paused=0
    )


def get_pool_validator_hash_from_utxo(tx: TxInfo, pool_nft_policy: bytes, pool_nft_name: bytes) -> bytes:
    """
    Get pool validator hash from the UTxO address where pool config lives.
    Works for both spent inputs and reference inputs.
    """
    # Check spent inputs first
    for inp in tx.inputs:
        if has_nft(inp.resolved.value, pool_nft_policy, pool_nft_name):
            cred = inp.resolved.address.payment_credential
            if isinstance(cred, ScriptCredential):
                return cred.credential_hash
    # Check reference inputs
    for ref in tx.reference_inputs:
        if has_nft(ref.resolved.value, pool_nft_policy, pool_nft_name):
            cred = ref.resolved.address.payment_credential
            if isinstance(cred, ScriptCredential):
                return cred.credential_hash
    assert False, "Pool config not found"
    return b""


def authorized_validator_spent(tx: TxInfo, pool_validator_hash: bytes, staking_validator_hash: bytes) -> bool:
    """
    Check if pool validator OR staking validator is being spent.
    Hashes come from pool config at runtime, not baked in.
    """
    for inp in tx.inputs:
        cred = inp.resolved.address.payment_credential
        if isinstance(cred, ScriptCredential):
            if cred.credential_hash == pool_validator_hash:
                return True
            if cred.credential_hash == staking_validator_hash:
                return True
    return False


def valid_position_datum(out: TxOut) -> bool:
    """Check if output has a valid UserPositionDatum."""
    d = out.datum
    if isinstance(d, SomeOutputDatum):
        datum: UserPositionDatum = d.datum
        # Basic sanity checks
        if len(datum.pool_nft_policy) != 28:
            return False
        if len(datum.user_pkh) != 28:
            return False
        if datum.stake_amount <= 0:
            return False
        if datum.staked_at <= 0:
            return False
        return True
    return False


def output_to_staking_validator(out: TxOut, staking_validator_hash: bytes) -> bool:
    """Check if output goes to staking validator address. Hash from pool datum."""
    cred = out.address.payment_credential
    if isinstance(cred, ScriptCredential):
        return cred.credential_hash == staking_validator_hash
    return False


def has_token(v: Value, policy: bytes, name: bytes, qty: int) -> bool:
    """Check if value has exactly qty of token."""
    if policy in v.keys():
        tokens = v[policy]
        if name in tokens.keys():
            return tokens[name] == qty
    return False


def find_and_validate_ref_nft(outputs: List[TxOut], policy_id: bytes, ref_name: bytes, staking_validator_hash: bytes) -> bool:
    """Find reference NFT output and validate it goes to staking validator with valid datum."""
    ref_nft_count = 0
    for out in outputs:
        if has_token(out.value, policy_id, ref_name, 1):
            # Must go to staking validator (hash from pool datum)
            if not output_to_staking_validator(out, staking_validator_hash):
                return False
            # Must have valid position datum
            if not valid_position_datum(out):
                return False
            ref_nft_count = ref_nft_count + 1
    # Must find exactly one reference NFT
    return ref_nft_count == 1


# =============================================================================
# MINTING POLICY
# =============================================================================

def validator(ctx: ScriptContext) -> None:
    """
    Position NFT minting policy (CIP-68 style, PlutusV3).

    All validator hashes are read from PoolDatum at runtime.
    No hashes are baked into this contract.

    MINT: Creates reference NFT (100) + user NFT (222) pair.
          Only allowed when pool or staking validator authorizes (is being spent).

    BURN: Destroys the NFT pair.
          Only allowed when pool or staking validator authorizes (is being spent).
    """
    tx: TxInfo = ctx.transaction
    purpose = ctx.purpose
    assert isinstance(purpose, Minting)

    # Get redeemer from context (PlutusV3 style)
    redeemer: PositionNFTRedeemer = ctx.redeemer

    policy_id = purpose.policy_id
    minted = tx.mint[policy_id]

    # ==========================================================================
    # MINT POSITION
    # ==========================================================================
    if isinstance(redeemer, MintPosition):
        position_id = redeemer.position_id

        # Get pool config and validator hashes from reference/spent inputs
        pool = find_pool_config(tx, redeemer.pool_nft_policy, redeemer.pool_nft_name)
        pool_validator_hash = get_pool_validator_hash_from_utxo(tx, redeemer.pool_nft_policy, redeemer.pool_nft_name)

        # CRITICAL: Pool or staking validator must be spent to authorize minting
        assert authorized_validator_spent(tx, pool_validator_hash, pool.staking_validator_hash), "Pool or staking validator must authorize"

        # Compute expected token names
        ref_name = make_reference_name(position_id)
        user_name = make_user_name(position_id)

        # Must mint exactly 2 tokens: 1 reference NFT + 1 user NFT
        assert len(minted) == 2, "Must mint exactly 2 tokens"
        assert ref_name in minted.keys(), "Reference NFT name not found"
        assert user_name in minted.keys(), "User NFT name not found"
        assert minted[ref_name] == 1, "Must mint 1 reference NFT"
        assert minted[user_name] == 1, "Must mint 1 user NFT"

        # Reference NFT must go to staking validator with valid datum
        # staking_validator_hash comes from pool datum (not baked in)
        assert find_and_validate_ref_nft(tx.outputs, policy_id, ref_name, pool.staking_validator_hash), "Invalid reference NFT output"

    # ==========================================================================
    # BURN POSITION
    # ==========================================================================
    elif isinstance(redeemer, BurnPosition):
        position_id = redeemer.position_id

        # Get pool config and validator hashes from reference/spent inputs
        pool = find_pool_config(tx, redeemer.pool_nft_policy, redeemer.pool_nft_name)
        pool_validator_hash = get_pool_validator_hash_from_utxo(tx, redeemer.pool_nft_policy, redeemer.pool_nft_name)

        # CRITICAL: Pool or staking validator must be spent to authorize burning
        assert authorized_validator_spent(tx, pool_validator_hash, pool.staking_validator_hash), "Pool or staking validator must authorize"

        # Compute expected token names
        ref_name = make_reference_name(position_id)
        user_name = make_user_name(position_id)

        # Must burn both NFTs (negative quantities)
        assert ref_name in minted.keys(), "Reference NFT not being burned"
        assert user_name in minted.keys(), "User NFT not being burned"
        assert minted[ref_name] == -1, "Must burn 1 reference NFT"
        assert minted[user_name] == -1, "Must burn 1 user NFT"

        # Only these two tokens should be in minted for this policy
        assert len(minted) == 2, "Only 2 tokens should be burned"

    # ==========================================================================
    # REMINT POSITION (Partial Withdrawal)
    # ==========================================================================
    elif isinstance(redeemer, RemintPosition):
        old_position_id = redeemer.old_position_id
        new_position_id = redeemer.new_position_id

        # Get pool config and validator hashes from reference/spent inputs
        pool = find_pool_config(tx, redeemer.pool_nft_policy, redeemer.pool_nft_name)
        pool_validator_hash = get_pool_validator_hash_from_utxo(tx, redeemer.pool_nft_policy, redeemer.pool_nft_name)

        # CRITICAL: Pool or staking validator must be spent to authorize reminting
        assert authorized_validator_spent(tx, pool_validator_hash, pool.staking_validator_hash), "Pool or staking validator must authorize"

        # Compute expected token names for OLD position (being burned)
        old_user_name = make_user_name(old_position_id)

        # Compute expected token names for NEW position (being minted)
        new_ref_name = make_reference_name(new_position_id)
        new_user_name = make_user_name(new_position_id)

        # Validate minting:
        # - old user NFT burned (-1)
        # - new ref NFT minted (+1)
        # - new user NFT minted (+1)
        # Total: 3 distinct token operations
        assert len(minted) == 3, "Remint must have exactly 3 token operations"

        # Check old user NFT is being burned
        assert old_user_name in minted.keys(), "Old user NFT must be burned"
        assert minted[old_user_name] == -1, "Must burn exactly 1 old user NFT"

        # Check new pair is being minted
        assert new_ref_name in minted.keys(), "New reference NFT not found"
        assert new_user_name in minted.keys(), "New user NFT not found"
        assert minted[new_ref_name] == 1, "Must mint 1 new reference NFT"
        assert minted[new_user_name] == 1, "Must mint 1 new user NFT"

        # New reference NFT must go to staking validator with valid datum
        assert find_and_validate_ref_nft(tx.outputs, policy_id, new_ref_name, pool.staking_validator_hash), "Invalid new reference NFT output"

    else:
        assert False, "Invalid redeemer"

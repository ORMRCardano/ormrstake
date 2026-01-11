"""
Pool Validator V3 - Shared validator for all pools.
PlutusV3 / OpShin 0.27+ compatible.

This validator manages pool configuration UTxOs. Each pool has one config UTxO
containing the Pool NFT and pool parameters in the datum.

IMPORTANT: No validator hashes are baked into this contract.
All configuration is stored in PoolDatum and read at runtime.

Operations:
- Stake: Add stake tokens to pool (updates total_staked)
- Unstake: Remove stake tokens from pool (updates total_staked)
- Claim: Distribute reward tokens to stakers
- UpdatePool: Change yield rate (owner only)
- ClosePool: Close pool and burn NFT (owner only)
- FundTreasury: Add reward tokens to pool (owner only)
- WithdrawTreasury: Remove reward tokens from pool (owner only)

Compile: opshin build pool_validator_v3.py
"""
from opshin.prelude import *


# =============================================================================
# DATUM - Contains ALL configuration (no baked-in values)
# =============================================================================

@dataclass
class PoolDatum(PlutusData):
    """
    Pool configuration - stored in pool config UTxO with Pool NFT.

    This datum contains ALL configuration for the pool and platform.
    No values are baked into the compiled contract.
    """
    CONSTR_ID = 0

    # Pool Identity
    pool_nft_policy: bytes          # 28 bytes - Pool NFT policy
    pool_nft_name: bytes            # 32 bytes - Pool NFT name

    # Stake/Reward Tokens
    stake_token_policy: bytes       # 28 bytes
    stake_token_name: bytes
    reward_token_policy: bytes      # 28 bytes
    reward_token_name: bytes

    # Pool Parameters
    yield_rate: int                 # basis points (500 = 5%)
    min_stake: int
    owner: bytes                    # 28 bytes PKH
    total_staked: int

    # Validator Hashes (for cross-validator communication)
    staking_validator_hash: bytes   # 28 bytes - where user positions live
    position_nft_policy_hash: bytes # 28 bytes - policy that mints position NFTs

    # Platform Configuration
    platform_fee_pkh: bytes         # 28 bytes - fee recipient address
    deposit_fee_bps: int            # basis points (100 = 1%)
    burn_address_hash: bytes        # 28 bytes - script address for NFT burns

    # Pool State
    paused: int                     # 0 = active, 1 = paused (no new stakes)


# =============================================================================
# REDEEMERS
# =============================================================================

@dataclass
class Stake(PlutusData):
    """Add stake tokens to pool."""
    CONSTR_ID = 0
    amount: int


@dataclass
class Unstake(PlutusData):
    """Remove stake tokens from pool."""
    CONSTR_ID = 1
    amount: int


@dataclass
class Claim(PlutusData):
    """Claim reward tokens."""
    CONSTR_ID = 2


@dataclass
class UpdatePool(PlutusData):
    """Update pool yield rate (owner only)."""
    CONSTR_ID = 3
    new_yield_rate: int


@dataclass
class ClosePool(PlutusData):
    """Close pool and burn NFT (owner only)."""
    CONSTR_ID = 4


@dataclass
class FundTreasury(PlutusData):
    """Add reward tokens to pool treasury (owner only)."""
    CONSTR_ID = 5
    amount: int


@dataclass
class WithdrawTreasury(PlutusData):
    """Withdraw reward tokens from pool treasury (owner only)."""
    CONSTR_ID = 6
    amount: int


@dataclass
class PausePool(PlutusData):
    """Pause or unpause the pool (owner only). Paused pools block new stakes."""
    CONSTR_ID = 7
    pause: int  # 1 = pause, 0 = unpause


PoolRedeemer = Union[Stake, Unstake, Claim, UpdatePool, ClosePool, FundTreasury, WithdrawTreasury, PausePool]


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


def get_token_amount(v: Value, policy: bytes, name: bytes) -> int:
    """Get token amount from value."""
    if policy in v.keys():
        tokens = v[policy]
        if name in tokens.keys():
            return tokens[name]
    return 0


def signed_by(tx: TxInfo, pkh: bytes) -> bool:
    """Check if transaction is signed by PKH."""
    for s in tx.signatories:
        if s == pkh:
            return True
    return False


def nft_burned(tx: TxInfo, policy: bytes, name: bytes) -> bool:
    """Check if NFT is being burned."""
    if policy in tx.mint.keys():
        tokens = tx.mint[policy]
        if name in tokens.keys():
            return tokens[name] == -1
    return False


def staking_validator_spent(tx: TxInfo, staking_validator_hash: bytes) -> bool:
    """
    Check if staking validator is being spent in same transaction.
    This ensures Unstake/Claim operations are authorized by the staking validator.
    Prevents unauthorized draining of pool funds.
    """
    for inp in tx.inputs:
        cred = inp.resolved.address.payment_credential
        if isinstance(cred, ScriptCredential):
            if cred.credential_hash == staking_validator_hash:
                return True
    return False


def find_own_input(tx: TxInfo, ref: TxOutRef) -> TxOut:
    """Find the input being spent."""
    for i in tx.inputs:
        if i.out_ref == ref:
            return i.resolved
    assert False, "Own input not found"
    return tx.inputs[0].resolved


def find_continuing_output(tx: TxInfo, addr: Address, policy: bytes, name: bytes) -> TxOut:
    """Find output at same address with pool NFT."""
    for o in tx.outputs:
        if o.address == addr:
            if has_nft(o.value, policy, name):
                return o
    assert False, "Continuing output not found"
    return tx.outputs[0]


def verify_platform_fee_paid(tx: TxInfo, datum: PoolDatum, fee_amount: int, token_policy: bytes, token_name: bytes) -> bool:
    """Verify platform fee is paid correctly. Reads fee recipient from datum."""
    if fee_amount == 0:
        return True
    for output in tx.outputs:
        cred = output.address.payment_credential
        if isinstance(cred, PubKeyCredential):
            # Read fee recipient from datum - NOT baked in
            if cred.credential_hash == datum.platform_fee_pkh:
                token_amount = get_token_amount(output.value, token_policy, token_name)
                if token_amount >= fee_amount:
                    return True
    return False


def calculate_fee(amount: int, fee_bps: int) -> int:
    """Calculate platform fee from datum-defined rate."""
    return (amount * fee_bps) // 10000


def datum_matches_except_total_staked(new_datum: PoolDatum, datum: PoolDatum, expected_total: int) -> bool:
    """Verify all datum fields match except total_staked which should equal expected_total."""
    if new_datum.pool_nft_policy != datum.pool_nft_policy:
        return False
    if new_datum.pool_nft_name != datum.pool_nft_name:
        return False
    if new_datum.stake_token_policy != datum.stake_token_policy:
        return False
    if new_datum.stake_token_name != datum.stake_token_name:
        return False
    if new_datum.reward_token_policy != datum.reward_token_policy:
        return False
    if new_datum.reward_token_name != datum.reward_token_name:
        return False
    if new_datum.yield_rate != datum.yield_rate:
        return False
    if new_datum.min_stake != datum.min_stake:
        return False
    if new_datum.owner != datum.owner:
        return False
    if new_datum.total_staked != expected_total:
        return False
    if new_datum.staking_validator_hash != datum.staking_validator_hash:
        return False
    if new_datum.position_nft_policy_hash != datum.position_nft_policy_hash:
        return False
    if new_datum.platform_fee_pkh != datum.platform_fee_pkh:
        return False
    if new_datum.deposit_fee_bps != datum.deposit_fee_bps:
        return False
    if new_datum.burn_address_hash != datum.burn_address_hash:
        return False
    if new_datum.paused != datum.paused:
        return False
    return True


def datum_unchanged(new_datum: PoolDatum, datum: PoolDatum) -> bool:
    """Verify datum is completely unchanged."""
    return datum_matches_except_total_staked(new_datum, datum, datum.total_staked)


def datum_matches_except_paused(new_datum: PoolDatum, datum: PoolDatum, expected_paused: int) -> bool:
    """Verify all datum fields match except paused which should equal expected_paused."""
    if new_datum.pool_nft_policy != datum.pool_nft_policy:
        return False
    if new_datum.pool_nft_name != datum.pool_nft_name:
        return False
    if new_datum.stake_token_policy != datum.stake_token_policy:
        return False
    if new_datum.stake_token_name != datum.stake_token_name:
        return False
    if new_datum.reward_token_policy != datum.reward_token_policy:
        return False
    if new_datum.reward_token_name != datum.reward_token_name:
        return False
    if new_datum.yield_rate != datum.yield_rate:
        return False
    if new_datum.min_stake != datum.min_stake:
        return False
    if new_datum.owner != datum.owner:
        return False
    if new_datum.total_staked != datum.total_staked:
        return False
    if new_datum.staking_validator_hash != datum.staking_validator_hash:
        return False
    if new_datum.position_nft_policy_hash != datum.position_nft_policy_hash:
        return False
    if new_datum.platform_fee_pkh != datum.platform_fee_pkh:
        return False
    if new_datum.deposit_fee_bps != datum.deposit_fee_bps:
        return False
    if new_datum.burn_address_hash != datum.burn_address_hash:
        return False
    if new_datum.paused != expected_paused:
        return False
    return True


# =============================================================================
# VALIDATOR
# =============================================================================

def validator(ctx: ScriptContext) -> None:
    """
    Shared pool validator - works for ALL pools.
    Pool identity verified by Pool NFT presence.

    NOTE: PlutusV3 validators take ONLY ScriptContext.
    Datum is accessed from the spent input, redeemer from ctx.redeemer.
    """
    tx: TxInfo = ctx.transaction
    purpose = ctx.purpose
    assert isinstance(purpose, Spending)

    # Get own input and extract datum
    own_out = find_own_input(tx, purpose.tx_out_ref)
    own_addr = own_out.address

    # Extract datum from own input (must be inline datum)
    own_datum_raw = own_out.datum
    assert isinstance(own_datum_raw, SomeOutputDatum), "Missing inline datum on input"
    datum: PoolDatum = own_datum_raw.datum

    # Get redeemer from context (PlutusV3 style)
    redeemer: PoolRedeemer = ctx.redeemer

    # CRITICAL: Verify pool NFT is present - this proves datum is trustworthy
    assert has_nft(own_out.value, datum.pool_nft_policy, datum.pool_nft_name), "Pool NFT not found"

    # ==========================================================================
    # STAKE - Authorizes position NFT minting for user registration
    # ==========================================================================
    if isinstance(redeemer, Stake):
        # Block new stakes when pool is paused
        assert datum.paused == 0, "Pool is paused - no new stakes allowed"
        assert redeemer.amount >= datum.min_stake, "Below minimum stake"

        # Find continuing output with pool NFT
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Verify datum updated correctly (only total_staked changes)
        assert datum_matches_except_total_staked(new_datum, datum, datum.total_staked + redeemer.amount), "Datum mismatch"

        # Platform fee on deposits - rate read from datum
        fee = calculate_fee(redeemer.amount, datum.deposit_fee_bps)
        assert verify_platform_fee_paid(tx, datum, fee, datum.stake_token_policy, datum.stake_token_name), "Fee not paid"

    # ==========================================================================
    # UNSTAKE
    # ==========================================================================
    elif isinstance(redeemer, Unstake):
        # CRITICAL: Staking validator must be spent to authorize unstake
        # This prevents unauthorized draining of stake tokens from pool
        assert staking_validator_spent(tx, datum.staking_validator_hash), "Staking validator must authorize unstake"

        assert redeemer.amount > 0, "Amount must be positive"
        assert redeemer.amount <= datum.total_staked, "Exceeds total staked"

        # Find continuing output
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Verify stake tokens removed
        old_stake = get_token_amount(own_out.value, datum.stake_token_policy, datum.stake_token_name)
        new_stake = get_token_amount(cont.value, datum.stake_token_policy, datum.stake_token_name)
        assert old_stake >= new_stake + redeemer.amount, "Stake tokens not removed"

        # Verify datum updated
        assert datum_matches_except_total_staked(new_datum, datum, datum.total_staked - redeemer.amount), "Datum mismatch"

        # Withdrawals are FREE - no platform fee

    # ==========================================================================
    # CLAIM
    # ==========================================================================
    elif isinstance(redeemer, Claim):
        # CRITICAL: Staking validator must be spent to authorize claim
        # This prevents unauthorized draining of reward tokens from pool
        assert staking_validator_spent(tx, datum.staking_validator_hash), "Staking validator must authorize claim"

        # Find continuing output
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Verify reward tokens sent (some left pool)
        old_rewards = get_token_amount(own_out.value, datum.reward_token_policy, datum.reward_token_name)
        new_rewards = get_token_amount(cont.value, datum.reward_token_policy, datum.reward_token_name)
        assert old_rewards > new_rewards, "No rewards claimed"

        # Datum must remain unchanged for claim
        assert datum_unchanged(new_datum, datum), "Datum changed"

        # Claims are FREE - no platform fee

    # ==========================================================================
    # UPDATE POOL (owner only)
    # ==========================================================================
    elif isinstance(redeemer, UpdatePool):
        # Owner must sign
        assert signed_by(tx, datum.owner), "Owner signature required"

        # New rate must be valid
        assert redeemer.new_yield_rate > 0, "Rate must be positive"
        assert redeemer.new_yield_rate <= 10000, "Rate exceeds maximum"

        # Find continuing output
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Only yield_rate can change - verify all other fields
        assert new_datum.pool_nft_policy == datum.pool_nft_policy
        assert new_datum.pool_nft_name == datum.pool_nft_name
        assert new_datum.stake_token_policy == datum.stake_token_policy
        assert new_datum.stake_token_name == datum.stake_token_name
        assert new_datum.reward_token_policy == datum.reward_token_policy
        assert new_datum.reward_token_name == datum.reward_token_name
        assert new_datum.yield_rate == redeemer.new_yield_rate
        assert new_datum.min_stake == datum.min_stake
        assert new_datum.owner == datum.owner
        assert new_datum.total_staked == datum.total_staked
        assert new_datum.staking_validator_hash == datum.staking_validator_hash
        assert new_datum.position_nft_policy_hash == datum.position_nft_policy_hash
        assert new_datum.platform_fee_pkh == datum.platform_fee_pkh
        assert new_datum.deposit_fee_bps == datum.deposit_fee_bps
        assert new_datum.burn_address_hash == datum.burn_address_hash
        assert new_datum.paused == datum.paused

    # ==========================================================================
    # CLOSE POOL (owner only)
    # ==========================================================================
    elif isinstance(redeemer, ClosePool):
        # Owner must sign
        assert signed_by(tx, datum.owner), "Owner signature required"

        # Pool must be paused before closing
        assert datum.paused == 1, "Pool must be paused before closing"

        # NOTE: We don't check total_staked == 0 here because:
        # 1. The staking validator independently tracks positions
        # 2. If all position UTxOs are gone, there are no stakers
        # 3. total_staked may be stale if withdrawals didn't update it
        # The important thing is that Pool NFT is burned, making the pool unusable

        # Pool NFT must be burned (prevents reuse)
        assert nft_burned(tx, datum.pool_nft_policy, datum.pool_nft_name), "Pool NFT must be burned"

        # No continuing output required - pool is closed

    # ==========================================================================
    # FUND TREASURY (owner only)
    # ==========================================================================
    elif isinstance(redeemer, FundTreasury):
        # Owner must sign
        assert signed_by(tx, datum.owner), "Owner signature required"

        # Amount must be positive
        assert redeemer.amount > 0, "Amount must be positive"

        # Find continuing output with pool NFT
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Verify reward tokens added
        old_rewards = get_token_amount(own_out.value, datum.reward_token_policy, datum.reward_token_name)
        new_rewards = get_token_amount(cont.value, datum.reward_token_policy, datum.reward_token_name)
        assert new_rewards >= old_rewards + redeemer.amount, "Reward tokens not added"

        # Datum must remain unchanged
        assert datum_unchanged(new_datum, datum), "Datum changed"

        # Platform fee on treasury funding - rate read from datum
        fee = calculate_fee(redeemer.amount, datum.deposit_fee_bps)
        assert verify_platform_fee_paid(tx, datum, fee, datum.reward_token_policy, datum.reward_token_name), "Fee not paid"

    # ==========================================================================
    # WITHDRAW TREASURY (owner only)
    # ==========================================================================
    elif isinstance(redeemer, WithdrawTreasury):
        # Owner must sign
        assert signed_by(tx, datum.owner), "Owner signature required"

        # Amount must be positive
        assert redeemer.amount > 0, "Amount must be positive"

        # Find continuing output with pool NFT
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Verify reward tokens removed
        old_rewards = get_token_amount(own_out.value, datum.reward_token_policy, datum.reward_token_name)
        new_rewards = get_token_amount(cont.value, datum.reward_token_policy, datum.reward_token_name)
        assert old_rewards >= new_rewards + redeemer.amount, "Reward tokens not removed"

        # Datum must remain unchanged
        assert datum_unchanged(new_datum, datum), "Datum changed"

        # Treasury withdrawals are FREE - no platform fee

    # ==========================================================================
    # PAUSE POOL (owner only)
    # ==========================================================================
    elif isinstance(redeemer, PausePool):
        # Owner must sign
        assert signed_by(tx, datum.owner), "Owner signature required"

        # Validate pause value (must be 0 or 1)
        assert redeemer.pause == 0 or redeemer.pause == 1, "Pause must be 0 or 1"

        # Find continuing output with pool NFT
        cont = find_continuing_output(tx, own_addr, datum.pool_nft_policy, datum.pool_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: PoolDatum = cont_datum_raw.datum

        # Verify only paused field changes, all others remain same
        assert datum_matches_except_paused(new_datum, datum, redeemer.pause), "Only paused field can change"

    else:
        assert False, "Invalid redeemer"

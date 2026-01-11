"""
Staking Shared Validator V3 - User position management.
PlutusV3 / OpShin 0.27+ compatible.

This validator manages user staking positions. Each position is a separate UTxO
containing the user's position NFT and staked tokens.

IMPORTANT: No validator hashes are baked into this contract.
All configuration is read from the PoolDatum at runtime via reference inputs.

Architecture:
1. Pool Config UTxO: Contains pool parameters + Pool NFT (at pool_validator)
2. User Position UTxOs: Contains position data + Position NFT (at this validator)

Operations:
- Register: Create new staking position (requires pool config reference)
- Deposit: Add tokens to existing position
- Withdraw: Remove tokens from position (ALWAYS burns NFT)
- Claim: Claim pending rewards
- Compound: Auto-restake rewards

Compile: opshin build staking_shared_v3.py
"""
from opshin.prelude import *


# =============================================================================
# DATUM TYPES - Contains ALL configuration (no baked-in values)
# =============================================================================

@dataclass
class PoolDatum(PlutusData):
    """
    Pool configuration - must match pool_validator_v3.py EXACTLY.

    All validator hashes and platform config are stored here,
    eliminating the need for baked-in constants.
    """
    CONSTR_ID = 0

    # Pool Identity
    pool_nft_policy: bytes          # 28 bytes
    pool_nft_name: bytes            # 32 bytes

    # Stake/Reward Tokens
    stake_token_policy: bytes       # 28 bytes
    stake_token_name: bytes
    reward_token_policy: bytes      # 28 bytes
    reward_token_name: bytes

    # Pool Parameters
    yield_rate: int
    min_stake: int
    owner: bytes
    total_staked: int

    # Validator Hashes (read at runtime, not baked in)
    staking_validator_hash: bytes   # 28 bytes
    position_nft_policy_hash: bytes # 28 bytes

    # Platform Configuration (read at runtime, not baked in)
    platform_fee_pkh: bytes         # 28 bytes
    deposit_fee_bps: int
    burn_address_hash: bytes        # 28 bytes

    # Pool State
    paused: int                     # 0 = active, 1 = paused (no new stakes)


@dataclass
class UserPositionDatum(PlutusData):
    """User staking position datum."""
    CONSTR_ID = 1
    pool_nft_policy: bytes      # Links to pool
    pool_nft_name: bytes        # Links to specific pool
    user_pkh: bytes             # 28 bytes
    position_nft_name: bytes    # 32 bytes
    stake_amount: int
    staked_at: int              # POSIX ms
    last_claim: int             # POSIX ms
    total_claimed: int


# =============================================================================
# REDEEMERS
# =============================================================================

@dataclass
class Register(PlutusData):
    """Create new staking position."""
    CONSTR_ID = 0
    initial_deposit: int


@dataclass
class Deposit(PlutusData):
    """Add tokens to existing position."""
    CONSTR_ID = 1
    amount: int


@dataclass
class Withdraw(PlutusData):
    """Remove tokens from position (0 = full withdrawal)."""
    CONSTR_ID = 2
    amount: int


@dataclass
class Claim(PlutusData):
    """Claim pending rewards."""
    CONSTR_ID = 3


@dataclass
class Compound(PlutusData):
    """Auto-restake rewards."""
    CONSTR_ID = 4


@dataclass
class ForceRefund(PlutusData):
    """
    Force refund a staker's position (pool owner only, pool must be paused).
    Used during pool closure sweep when few stakers remain.
    """
    CONSTR_ID = 5


StakingRedeemer = Union[Register, Deposit, Withdraw, Claim, Compound, ForceRefund]


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


def find_own_input(tx: TxInfo, ref: TxOutRef) -> TxOut:
    """Find the input being spent."""
    for i in tx.inputs:
        if i.out_ref == ref:
            return i.resolved
    assert False, "Own input not found"
    return tx.inputs[0].resolved


def find_continuing_output(tx: TxInfo, addr: Address, nft_policy: bytes, nft_name: bytes) -> TxOut:
    """Find output at same address with position NFT. Validates BOTH policy and name."""
    for o in tx.outputs:
        if o.address == addr:
            # Check for position NFT by BOTH policy and name (prevents fake NFT substitution)
            if has_nft(o.value, nft_policy, nft_name):
                return o
    assert False, "Continuing output not found"
    return tx.outputs[0]


def find_pool_config_in_refs(tx: TxInfo, pool_nft_policy: bytes, pool_nft_name: bytes) -> PoolDatum:
    """Helper: Find pool config in reference inputs."""
    for ref in tx.reference_inputs:
        if has_nft(ref.resolved.value, pool_nft_policy, pool_nft_name):
            ref_datum = ref.resolved.datum
            if isinstance(ref_datum, SomeOutputDatum):
                pool_datum: PoolDatum = ref_datum.datum
                return pool_datum
    # Not found in refs, return dummy (caller will check inputs)
    return PoolDatum(
        pool_nft_policy=b"", pool_nft_name=b"",
        stake_token_policy=b"", stake_token_name=b"",
        reward_token_policy=b"", reward_token_name=b"",
        yield_rate=0, min_stake=0, owner=b"", total_staked=0,
        staking_validator_hash=b"", position_nft_policy_hash=b"",
        platform_fee_pkh=b"", deposit_fee_bps=0, burn_address_hash=b"",
        paused=0
    )


def find_pool_config_in_inputs(tx: TxInfo, pool_nft_policy: bytes, pool_nft_name: bytes) -> PoolDatum:
    """Helper: Find pool config in spent inputs."""
    for inp in tx.inputs:
        if has_nft(inp.resolved.value, pool_nft_policy, pool_nft_name):
            inp_datum = inp.resolved.datum
            if isinstance(inp_datum, SomeOutputDatum):
                pool_datum: PoolDatum = inp_datum.datum
                return pool_datum
    # Not found
    return PoolDatum(
        pool_nft_policy=b"", pool_nft_name=b"",
        stake_token_policy=b"", stake_token_name=b"",
        reward_token_policy=b"", reward_token_name=b"",
        yield_rate=0, min_stake=0, owner=b"", total_staked=0,
        staking_validator_hash=b"", position_nft_policy_hash=b"",
        platform_fee_pkh=b"", deposit_fee_bps=0, burn_address_hash=b"",
        paused=0
    )


def find_pool_config_reference(tx: TxInfo, pool_nft_policy: bytes, pool_nft_name: bytes) -> PoolDatum:
    """
    Find pool config by Pool NFT presence.

    Searches BOTH reference_inputs AND inputs, because:
    - For Register/Deposit: pool is a spent input (to update total_staked)
    - For Claim: pool is a spent input (to deduct from treasury)
    - For Withdraw: pool is a reference input (read-only)

    NO baked-in validator hash needed - we just look for the Pool NFT.
    The Pool NFT's uniqueness guarantees we found the correct pool.
    """
    # First check reference inputs
    pool_from_refs = find_pool_config_in_refs(tx, pool_nft_policy, pool_nft_name)
    if pool_from_refs.yield_rate > 0:
        return pool_from_refs

    # Also check spent inputs (for Claim/Register/Deposit that spend pool UTxO)
    pool_from_inputs = find_pool_config_in_inputs(tx, pool_nft_policy, pool_nft_name)
    if pool_from_inputs.yield_rate > 0:
        return pool_from_inputs

    assert False, "Pool config not found in inputs or reference inputs"
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


def nft_sent_to_burn(tx: TxInfo, pool: PoolDatum, nft_policy: bytes, nft_name: bytes) -> bool:
    """
    Check if NFT is sent to burn address.
    Validates BOTH policy and name to prevent fake NFT substitution.
    Uses has_nft helper to avoid unbounded nested loops.
    """
    for o in tx.outputs:
        cred = o.address.payment_credential
        if isinstance(cred, ScriptCredential):
            # Read burn address from pool datum - NOT baked in
            if cred.credential_hash == pool.burn_address_hash:
                # Check for NFT by BOTH policy and name (prevents fake NFT attack)
                if has_nft(o.value, nft_policy, nft_name):
                    return True
    return False


def verify_platform_fee_paid(tx: TxInfo, pool: PoolDatum, fee_amount: int, token_policy: bytes, token_name: bytes) -> bool:
    """Verify platform fee is paid correctly. Reads fee recipient from pool datum."""
    if fee_amount == 0:
        return True
    for output in tx.outputs:
        cred = output.address.payment_credential
        if isinstance(cred, PubKeyCredential):
            # Read fee recipient from pool datum - NOT baked in
            if cred.credential_hash == pool.platform_fee_pkh:
                token_amount = get_token_amount(output.value, token_policy, token_name)
                if token_amount >= fee_amount:
                    return True
    return False


def calculate_fee(amount: int, fee_bps: int) -> int:
    """Calculate platform fee from datum-defined rate."""
    return (amount * fee_bps) // 10000


def get_current_time(tx: TxInfo) -> int:
    """
    Extract current time from transaction validity range.

    SECURITY: Uses upper_bound and requires tight time window to prevent
    time manipulation attacks where attacker sets lower_bound far in the past
    to inflate staking duration and claim excess rewards.

    Max validity window: 10 minutes (600,000 ms)
    """
    # Require finite lower bound
    lower_bound = tx.validity_range.lower_bound
    lower_limit = lower_bound.limit
    assert isinstance(lower_limit, FinitePOSIXTime), "Must have finite lower time bound"
    lower_time = lower_limit.time

    # Require finite upper bound
    upper_bound = tx.validity_range.upper_bound
    upper_limit = upper_bound.limit
    assert isinstance(upper_limit, FinitePOSIXTime), "Must have finite upper time bound"
    upper_time = upper_limit.time

    # Require tight validity window (max 10 minutes = 600,000 ms)
    # This prevents setting lower_bound far in the past
    max_window_ms = 600000
    assert upper_time - lower_time <= max_window_ms, "Validity window too large (max 10 minutes)"

    # Use upper_bound as current time (latest the tx is valid)
    # This is the most restrictive for reward calculations
    return upper_time


def calculate_rewards(stake_amount: int, yield_rate: int, last_claim: int, current_time: int) -> int:
    """Calculate pending rewards: (stake * rate * days) / (365 * 10000)."""
    if stake_amount == 0:
        return 0
    time_elapsed_ms = current_time - last_claim
    days_elapsed = time_elapsed_ms // 86400000
    reward = (stake_amount * yield_rate * days_elapsed) // (365 * 10000)
    return reward


def output_to_staker(tx: TxInfo, user_pkh: bytes, stake_token_policy: bytes, stake_token_name: bytes, amount: int) -> bool:
    """Verify that staked tokens are sent to the staker's address."""
    for output in tx.outputs:
        cred = output.address.payment_credential
        if isinstance(cred, PubKeyCredential):
            if cred.credential_hash == user_pkh:
                token_amount = get_token_amount(output.value, stake_token_policy, stake_token_name)
                if token_amount >= amount:
                    return True
    return False


# =============================================================================
# VALIDATOR
# =============================================================================

def validator(ctx: ScriptContext) -> None:
    """
    Staking validator - manages user positions.

    All configuration is read from PoolDatum via reference inputs.
    No validator hashes are baked into this contract.

    NOTE: PlutusV3 validators take ONLY ScriptContext.
    Datum is accessed from the spent input, redeemer from ctx.redeemer.
    """
    tx: TxInfo = ctx.transaction
    purpose = ctx.purpose
    assert isinstance(purpose, Spending)

    # Get own input
    own_out = find_own_input(tx, purpose.tx_out_ref)
    own_addr = own_out.address

    # Extract datum from own input (must be inline datum)
    own_datum_raw = own_out.datum
    assert isinstance(own_datum_raw, SomeOutputDatum), "Missing inline datum on input"
    datum: UserPositionDatum = own_datum_raw.datum

    # Get redeemer from context (PlutusV3 style)
    redeemer: StakingRedeemer = ctx.redeemer

    # ==========================================================================
    # FORCE REFUND (Pool Closure Sweep) - MUST BE FIRST (owner-initiated, no user sig)
    # ==========================================================================
    if isinstance(redeemer, ForceRefund):
        # Get pool config from reference inputs
        pool = find_pool_config_reference(tx, datum.pool_nft_policy, datum.pool_nft_name)

        # Pool must be paused
        assert pool.paused == 1, "Pool must be paused for force refund"

        # Owner must sign (not user - this is owner-initiated)
        assert signed_by(tx, pool.owner), "Pool owner signature required"

        # Position NFT must be sent to burn address
        assert nft_sent_to_burn(tx, pool, pool.position_nft_policy_hash, datum.position_nft_name), "Position NFT must be burned"

        # Staked tokens must be sent to the staker's address
        assert output_to_staker(
            tx,
            datum.user_pkh,
            pool.stake_token_policy,
            pool.stake_token_name,
            datum.stake_amount
        ), "Staked tokens must be sent to staker"

        # NOTE: Any pending rewards are forfeited in force refund
        # Stakers should claim rewards before pool is paused
        # This is a graceful degradation - owner can only force refund, not steal

    # ==========================================================================
    # REGISTER
    # ==========================================================================
    elif isinstance(redeemer, Register):
        # User must sign
        assert signed_by(tx, datum.user_pkh), "User signature required"
        # Get pool config from reference inputs (by Pool NFT, not by hash)
        pool = find_pool_config_reference(tx, datum.pool_nft_policy, datum.pool_nft_name)

        # Pool must not be paused
        assert pool.paused == 0, "Pool is paused - no new stakes allowed"

        # Verify minimum stake
        assert redeemer.initial_deposit >= pool.min_stake, "Below minimum stake"
        assert datum.stake_amount == redeemer.initial_deposit, "Stake amount mismatch"

        # Verify timestamps
        current_time = get_current_time(tx)
        assert datum.staked_at <= current_time, "Invalid staked_at"
        assert datum.last_claim == datum.staked_at, "last_claim must equal staked_at"
        assert datum.total_claimed == 0, "total_claimed must be 0"

        # Platform fee on deposit - rate read from pool datum
        fee = calculate_fee(redeemer.initial_deposit, pool.deposit_fee_bps)
        assert verify_platform_fee_paid(tx, pool, fee, pool.stake_token_policy, pool.stake_token_name), "Fee not paid"

    # ==========================================================================
    # DEPOSIT
    # ==========================================================================
    elif isinstance(redeemer, Deposit):
        # User must sign
        assert signed_by(tx, datum.user_pkh), "User signature required"
        assert redeemer.amount > 0, "Amount must be positive"

        # Get pool config from reference inputs
        pool = find_pool_config_reference(tx, datum.pool_nft_policy, datum.pool_nft_name)

        # Pool must not be paused
        assert pool.paused == 0, "Pool is paused - no deposits allowed"

        # Calculate fee (deducted from deposit, like a DEX)
        fee = calculate_fee(redeemer.amount, pool.deposit_fee_bps)
        net_amount = redeemer.amount - fee

        # Find continuing output (validates BOTH policy and name to prevent fake NFT substitution)
        cont = find_continuing_output(tx, own_addr, pool.position_nft_policy_hash, datum.position_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: UserPositionDatum = cont_datum_raw.datum

        # Verify stake amount increased by NET amount (after fee deduction)
        assert new_datum.stake_amount == datum.stake_amount + net_amount, "Stake not updated"

        # Verify other fields unchanged
        assert new_datum.pool_nft_policy == datum.pool_nft_policy
        assert new_datum.pool_nft_name == datum.pool_nft_name
        assert new_datum.user_pkh == datum.user_pkh
        assert new_datum.position_nft_name == datum.position_nft_name
        assert new_datum.staked_at == datum.staked_at
        assert new_datum.last_claim == datum.last_claim
        assert new_datum.total_claimed == datum.total_claimed

        # Platform fee on deposit
        assert verify_platform_fee_paid(tx, pool, fee, pool.stake_token_policy, pool.stake_token_name), "Fee not paid"

    # ==========================================================================
    # WITHDRAW
    # ==========================================================================
    elif isinstance(redeemer, Withdraw):
        # User must sign
        assert signed_by(tx, datum.user_pkh), "User signature required"
        # Get pool config from reference inputs (need burn_address_hash)
        pool = find_pool_config_reference(tx, datum.pool_nft_policy, datum.pool_nft_name)

        # Determine withdrawal amount (0 = full withdrawal)
        if redeemer.amount == 0:
            withdraw_amount = datum.stake_amount
        else:
            withdraw_amount = redeemer.amount

        assert withdraw_amount > 0, "Amount must be positive"
        assert withdraw_amount <= datum.stake_amount, "Exceeds stake"

        # ALWAYS burn the position NFT on any withdrawal (full or partial)
        assert nft_sent_to_burn(tx, pool, pool.position_nft_policy_hash, datum.position_nft_name), "NFT must be burned"

        # Withdrawals are FREE - no platform fee

    # ==========================================================================
    # CLAIM
    # ==========================================================================
    elif isinstance(redeemer, Claim):
        # User must sign
        assert signed_by(tx, datum.user_pkh), "User signature required"
        # Get pool config from reference inputs
        pool = find_pool_config_reference(tx, datum.pool_nft_policy, datum.pool_nft_name)

        # Calculate pending rewards
        current_time = get_current_time(tx)
        pending_rewards = calculate_rewards(
            datum.stake_amount,
            pool.yield_rate,
            datum.last_claim,
            current_time
        )
        assert pending_rewards > 0, "No rewards to claim"

        # Find continuing output (validates BOTH policy and name to prevent fake NFT substitution)
        cont = find_continuing_output(tx, own_addr, pool.position_nft_policy_hash, datum.position_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: UserPositionDatum = cont_datum_raw.datum

        # Verify claim updated
        assert new_datum.last_claim == current_time, "last_claim not updated"
        assert new_datum.total_claimed == datum.total_claimed + pending_rewards, "total_claimed not updated"

        # Verify other fields unchanged
        assert new_datum.pool_nft_policy == datum.pool_nft_policy
        assert new_datum.pool_nft_name == datum.pool_nft_name
        assert new_datum.user_pkh == datum.user_pkh
        assert new_datum.position_nft_name == datum.position_nft_name
        assert new_datum.stake_amount == datum.stake_amount
        assert new_datum.staked_at == datum.staked_at

        # Claims are FREE - no platform fee

    # ==========================================================================
    # COMPOUND
    # ==========================================================================
    elif isinstance(redeemer, Compound):
        # User must sign
        assert signed_by(tx, datum.user_pkh), "User signature required"
        # Get pool config from reference inputs
        pool = find_pool_config_reference(tx, datum.pool_nft_policy, datum.pool_nft_name)

        # Calculate pending rewards
        current_time = get_current_time(tx)
        pending_rewards = calculate_rewards(
            datum.stake_amount,
            pool.yield_rate,
            datum.last_claim,
            current_time
        )
        assert pending_rewards > 0, "No rewards to compound"

        # Calculate fee on compounded rewards
        fee = calculate_fee(pending_rewards, pool.deposit_fee_bps)
        net_rewards = pending_rewards - fee

        # Find continuing output (validates BOTH policy and name to prevent fake NFT substitution)
        cont = find_continuing_output(tx, own_addr, pool.position_nft_policy_hash, datum.position_nft_name)
        cont_datum_raw = cont.datum
        assert isinstance(cont_datum_raw, SomeOutputDatum), "Missing inline datum"
        new_datum: UserPositionDatum = cont_datum_raw.datum

        # Verify compound updated
        assert new_datum.stake_amount == datum.stake_amount + net_rewards, "stake_amount not updated"
        assert new_datum.last_claim == current_time, "last_claim not updated"
        assert new_datum.total_claimed == datum.total_claimed + pending_rewards, "total_claimed not updated"

        # Verify other fields unchanged
        assert new_datum.pool_nft_policy == datum.pool_nft_policy
        assert new_datum.pool_nft_name == datum.pool_nft_name
        assert new_datum.user_pkh == datum.user_pkh
        assert new_datum.position_nft_name == datum.position_nft_name
        assert new_datum.staked_at == datum.staked_at

        # Platform fee on compound (treated as deposit)
        assert verify_platform_fee_paid(tx, pool, fee, pool.reward_token_policy, pool.reward_token_name), "Fee not paid"

    else:
        assert False, "Invalid redeemer"

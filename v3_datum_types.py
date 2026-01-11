"""
V3 Unified Datum Types - Shared Data Structures for All Smart Contracts

This file contains the canonical datum definitions used across all V3 contracts.
All contracts MUST import these types to ensure compatibility.

CRITICAL: Any change to these structures requires recompilation of ALL contracts.

Security Update (2026-01-11):
- PoolDatum now includes all 16 fields including validator hashes and platform config
- Added PlatformAuthorityDatum for platform authorization
"""

from opshin.prelude import *


# =============================================================================
# PLATFORM AUTHORITY DATUM (used by platform_authority_nft_policy and pool_nft_policy_v3)
# =============================================================================

@dataclass
class PlatformAuthorityDatum(PlutusData):
    """
    Platform configuration - stored in the Platform Authority UTxO.

    This UTxO contains the Platform Authority NFT which controls who can
    create new pools. Only the pool_creator_pkh can mint new Pool NFTs.

    Fields:
        pool_creator_pkh: PKH authorized to create pools (28 bytes)
        platform_admin_pkh: PKH that can update this config (28 bytes)
        platform_nft_policy: This policy's ID for self-reference (28 bytes)
        platform_nft_name: The authority NFT name (32 bytes)
    """
    CONSTR_ID = 0
    pool_creator_pkh: bytes         # 28 bytes
    platform_admin_pkh: bytes       # 28 bytes
    platform_nft_policy: bytes      # 28 bytes
    platform_nft_name: bytes        # 32 bytes


# =============================================================================
# POOL DATUM (used by pool_validator_v3 and pool_nft_policy_v3)
# =============================================================================

@dataclass
class PoolDatum(PlutusData):
    """
    Pool configuration datum - stored in pool config UTxO.

    This UTxO contains the Pool NFT which proves the datum is legitimate.
    All pool parameters and validator hashes are read from this datum at runtime.
    NO BAKED-IN HASHES - everything is stored here.

    Fields:
        pool_nft_policy: Policy ID of the pool NFT (28 bytes)
        pool_nft_name: Asset name of the pool NFT (32 bytes, sha256 of tx_id)
        stake_token_policy: Policy ID of token being staked (28 bytes)
        stake_token_name: Asset name of token being staked
        reward_token_policy: Policy ID of reward token (28 bytes)
        reward_token_name: Asset name of reward token
        yield_rate: Annual yield rate in basis points (500 = 5%)
        min_stake: Minimum stake amount in tokens
        owner: Pool owner's payment key hash (28 bytes)
        total_staked: Current total tokens staked in the pool
        staking_validator_hash: Hash of the staking validator (28 bytes)
        position_nft_policy_hash: Policy ID of position NFTs (28 bytes)
        platform_fee_pkh: Platform fee recipient PKH (28 bytes)
        deposit_fee_bps: Deposit fee in basis points (100 = 1%)
        burn_address_hash: Script hash for NFT burns (28 bytes)
        paused: Pool state (0 = active, 1 = paused)
    """
    CONSTR_ID = 0
    pool_nft_policy: bytes          # 28 bytes
    pool_nft_name: bytes            # 32 bytes
    stake_token_policy: bytes       # 28 bytes
    stake_token_name: bytes
    reward_token_policy: bytes      # 28 bytes
    reward_token_name: bytes
    yield_rate: int                 # basis points (500 = 5%)
    min_stake: int
    owner: bytes                    # 28 bytes PKH
    total_staked: int
    staking_validator_hash: bytes   # 28 bytes - for cross-validator auth
    position_nft_policy_hash: bytes # 28 bytes - for position NFT minting
    platform_fee_pkh: bytes         # 28 bytes - fee recipient
    deposit_fee_bps: int            # basis points (100 = 1%)
    burn_address_hash: bytes        # 28 bytes - for NFT burns
    paused: int                     # 0 = active, 1 = paused


# =============================================================================
# USER POSITION DATUM (used by staking_shared_v3 and position_nft_policy_v3)
# =============================================================================

@dataclass
class UserPositionDatum(PlutusData):
    """
    User staking position datum - stored in position UTxO.

    This UTxO contains the user's position NFT and staked tokens.
    Links to pool via pool_nft_policy and pool_nft_name.

    Fields:
        pool_nft_policy: Policy ID of the pool this position belongs to
        pool_nft_name: Asset name of the pool NFT
        user_pkh: User's payment key hash (28 bytes)
        position_nft_name: Unique identifier for this position (32 bytes)
        stake_amount: Currently staked tokens
        staked_at: Initial stake timestamp (POSIX milliseconds)
        last_claim: Last reward claim timestamp (POSIX milliseconds)
        total_claimed: Lifetime rewards claimed
    """
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
# POSITION REFERENCE DATUM (CIP-68 reference NFT datum)
# =============================================================================

@dataclass
class PositionRefDatum(PlutusData):
    """
    CIP-68 Reference NFT datum - holds position metadata.

    This is stored at the pool validator address with the (100) reference NFT.
    The (222) user NFT is held in the user's wallet.

    Fields:
        pool_nft_policy: Which pool this position belongs to
        pool_nft_name: Pool NFT token name
        staked_amount: Amount staked (for display)
        stake_timestamp: When stake was created
    """
    CONSTR_ID = 0
    pool_nft_policy: bytes      # 28 bytes
    pool_nft_name: bytes        # 32 bytes
    staked_amount: int
    stake_timestamp: int        # POSIX ms

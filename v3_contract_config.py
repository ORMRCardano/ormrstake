"""
V3 Contract Configuration - TRUE CONSTANTS ONLY

This file contains ONLY values that are universal standards and never change:
- CIP-68 NFT labels (defined by CIP-68 specification)

ALL other configuration (validator hashes, fee addresses, etc.) is stored
in the PoolDatum and read at runtime. This eliminates the need to recompile
contracts when deploying new validators.

Architecture:
- PoolDatum contains all pool-specific AND platform-specific config
- Contracts read this config from reference inputs at runtime
- No validator hashes are baked into compiled contracts
"""

# =============================================================================
# CIP-68 NFT LABELS - Universal Constants
# =============================================================================
# These are CIP-68 standard labels. They NEVER change.
# Reference: https://cips.cardano.org/cip/CIP-0068/

CIP68_REFERENCE_LABEL: bytes = bytes.fromhex("000643b0")  # Label 100 - Reference NFT
CIP68_USER_LABEL: bytes = bytes.fromhex("000de140")       # Label 222 - User NFT

# OpShin Staking Contracts - PlutusV3 Examples

Production-ready* Cardano smart contracts written in OpShin (Python) for token staking pools. These contracts power [OrmrStake](https://ormrstake.io).

## Overview

This repository contains a complete staking platform implementation using:
- **PlutusV3** smart contracts
- **OpShin** (Python-based Cardano smart contract language)
- **CIP-68** compliant NFTs for position tracking
- **Reference scripts** for efficient transaction sizes

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Pool Validator                           │
│  - Holds pool configuration (PoolDatum)                        │
│  - Manages treasury funds                                       │
│  - Contains Pool NFT proving legitimacy                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ references
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Staking Validator                          │
│  - Holds user positions (UserPositionDatum)                    │
│  - Manages stake/unstake/claim operations                      │
│  - Reads pool config from reference inputs                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ mints/burns
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Position NFT Policy                          │
│  - Mints CIP-68 position NFTs on registration                  │
│  - Burns NFTs on full withdrawal                               │
│  - Reference NFT (100) stays at validator                      │
└─────────────────────────────────────────────────────────────────┘
```

## Contracts

### pool_validator_v3.py
The pool configuration validator. Holds the `PoolDatum` which contains all pool parameters including yield rate, stake token, reward token, and owner information. Protected by a Pool NFT.

**Key Operations:**
- `FundTreasury` - Owner adds reward tokens
- `WithdrawTreasury` - Owner removes excess tokens
- `UpdateYield` - Owner adjusts APY
- `PausePool` / `ResumePool` - Owner controls pool state

### staking_shared_v3.py
The main staking validator where user positions live. Each position UTxO contains staked tokens and a `UserPositionDatum`.

**Key Operations:**
- `Register` - Create new position with initial stake
- `Deposit` - Add tokens to existing position
- `Withdraw` - Remove tokens (partial or full)
- `Claim` - Claim accrued rewards

### position_nft_policy_v3.py
CIP-68 compliant minting policy for position NFTs. When a user registers:
- Reference NFT (label 100) stays at the staking validator
- User NFT (label 222) goes to the user's wallet

### pool_nft_policy_v3.py
Minting policy for pool identity NFTs. Each pool has a unique NFT that proves the pool datum is legitimate.

### v3_datum_types.py
Shared data structures used across all contracts:
- `PoolDatum` - Pool configuration
- `UserPositionDatum` - User position data
- `PositionRefDatum` - CIP-68 reference metadata

### v3_contract_config.py
Universal constants (CIP-68 labels). All other configuration is stored on-chain in the `PoolDatum`.

## Key Design Principles

### 1. No Baked-In Hashes
Contracts read all configuration from on-chain data at runtime. This means:
- Contracts can be compiled once and reused
- No circular dependencies between contracts
- Easier upgrades and maintenance

### 2. Reference Scripts
All contracts are deployed as reference scripts. Transactions reference these scripts instead of including them, resulting in smaller transaction sizes and lower fees.

### 3. Pool NFT Pattern
Each pool has a unique NFT that:
- Proves the pool datum is legitimate
- Allows contracts to find the correct pool configuration
- Prevents spoofing attacks

### 4. CIP-68 Position NFTs
User positions use CIP-68 compliant NFTs:
- Reference token (100) holds metadata at validator
- User token (222) proves ownership in wallet
- Enables on-chain position verification

## Reward Calculation

Rewards are calculated using a simple linear formula:

```
rewards = (stake_amount * yield_rate * days_staked) / (365 * 10000)
```

Where:
- `stake_amount` = tokens staked
- `yield_rate` = APY in basis points (500 = 5%)
- `days_staked` = time since last claim

## Building

Requires OpShin and Python 3.10+:

```bash
pip install opshin-py

# Compile a contract
opshin build pool_validator_v3.py
```

## Testing

Contracts should be tested on Cardano testnet (preprod or preview) before mainnet deployment.

## Security Considerations

1. **Owner verification** - Pool operations require owner signature
2. **NFT verification** - All operations verify correct NFTs are present
3. **Amount validation** - Withdrawals cannot exceed staked amount
4. **Reward caps** - Claims limited to treasury balance
5. **Reference input validation** - Pool config read from verified reference inputs

## License

MIT License - See LICENSE file for details.

## Resources

- [OpShin Documentation](https://opshin.dev)
- [CIP-68 Specification](https://cips.cardano.org/cip/CIP-0068/)
- [PlutusV3 Documentation](https://plutus.readthedocs.io/)
- [OrmrStake Platform](https://ormrstake.io)

## Notes

* Production-ready means that you can use it and it works. However, it has not been professionally audited, so its use at your own risk. 

#!/usr/bin/env python3
import json

from models.rewards.rewards_model import safe_reward_failure_message


def reward_preflight(reward_config, dao, web3, account_factory, token_abi):
    sender = account_factory(reward_config["account_private_key"]).address
    token_address = web3.to_checksum_address(
        reward_config["token_contract_address"]
    )
    contract = web3.eth.contract(address=token_address, abi=token_abi)
    claims = dao.iter_query({
        "selector": {"document_type": "reward_payout_claim"},
        "fields": ["status", "transaction_hash"],
    })
    manual_reconciliation = 0
    retryable = 0
    for claim in claims:
        status = claim.get("status")
        has_hash = bool(claim.get("transaction_hash"))
        manual_reconciliation += status in {"calculating", "transferring"} or (
            status in {"failed", "transfer_failed"} and has_hash
        )
        retryable += status in {"failed", "transfer_failed"} and not has_hash
    configured_chain_id = int(reward_config["chain_id"])
    actual_chain_id = web3.eth.chain_id
    native_balance = web3.eth.get_balance(sender)
    minimum_gas_wei = web3.eth.gas_price * 100_000
    token_balance = contract.functions.balanceOf(sender).call()
    token_decimals = contract.functions.decimals().call()
    token_code_bytes = len(web3.eth.get_code(token_address))
    result = {
        "schema": "brainstem.reward-preflight/v1",
        "network": reward_config.get("network", ""),
        "configuredChainId": configured_chain_id,
        "actualChainId": actual_chain_id,
        "sender": sender,
        "senderPendingNonce": web3.eth.get_transaction_count(sender, "pending"),
        "senderNativeWei": native_balance,
        "minimumGasWei": minimum_gas_wei,
        "tokenContract": token_address,
        "tokenCodeBytes": token_code_bytes,
        "tokenSymbol": contract.functions.symbol().call(),
        "tokenDecimals": token_decimals,
        "senderTokenRaw": token_balance,
        "retryablePayoutClaims": retryable,
        "manualReconciliationClaims": manual_reconciliation,
    }
    result["ok"] = all((
        configured_chain_id == actual_chain_id,
        token_code_bytes > 0,
        token_decimals == 18,
        native_balance >= minimum_gas_wei,
        token_balance > 0,
        manual_reconciliation == 0,
    ))
    return result


def main():
    from eth_account import Account
    from web3 import HTTPProvider, Web3

    from config import config
    from dao.rewards_dao import rewards_dao
    from utils.abi.erc20_abi import ERC20_ABI

    reward_config = config["rewards"]
    web3 = Web3(HTTPProvider(
        reward_config["network_url"],
        request_kwargs={
            "timeout": reward_config.getfloat("rpc_timeout_seconds", 30)
        },
    ))
    try:
        result = reward_preflight(
            reward_config, rewards_dao, web3, Account.from_key, ERC20_ABI
        )
    except Exception as error:
        result = {
            "schema": "brainstem.reward-preflight/v1",
            "ok": False,
            "error": safe_reward_failure_message(error),
        }
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()

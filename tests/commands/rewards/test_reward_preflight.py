from commands.rewards.reward_preflight import reward_preflight


class Value:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class Functions:
    def balanceOf(self, _sender):
        return Value(2_000_000)

    def symbol(self):
        return Value("BEAT")

    def decimals(self):
        return Value(18)


class Eth:
    chain_id = 10
    gas_price = 1

    def contract(self, **_kwargs):
        return type("Contract", (), {"functions": Functions()})()

    def get_balance(self, _sender):
        return 100_000

    def get_transaction_count(self, _sender, _state):
        return 7

    def get_code(self, _address):
        return b"contract"


class Web3:
    eth = Eth()

    @staticmethod
    def to_checksum_address(value):
        return value


class Dao:
    def __init__(self, claims):
        self.claims = claims

    def iter_query(self, _query):
        yield from self.claims


class Account:
    address = "0x" + "1" * 40


CONFIG = {
    "account_private_key": "not-returned",
    "token_contract_address": "0x" + "2" * 40,
    "chain_id": "10",
    "network": "optimism",
}


def test_preflight_is_read_only_and_reports_only_aggregate_claim_state():
    result = reward_preflight(
        CONFIG,
        Dao([{"status": "failed", "transaction_hash": None}]),
        Web3(),
        lambda _key: Account(),
        [],
    )
    assert result["ok"] is True
    assert result["retryablePayoutClaims"] == 1
    assert result["manualReconciliationClaims"] == 0
    assert "account_private_key" not in result


def test_preflight_blocks_ambiguous_chain_state():
    result = reward_preflight(
        CONFIG,
        Dao([{"status": "transferring", "transaction_hash": "0xknown"}]),
        Web3(),
        lambda _key: Account(),
        [],
    )
    assert result["ok"] is False
    assert result["manualReconciliationClaims"] == 1


def test_preflight_requires_enough_native_currency_for_one_transfer():
    web3 = Web3()
    web3.eth = Eth()
    web3.eth.gas_price = 2
    web3.eth.get_balance = lambda _sender: 199_999
    result = reward_preflight(CONFIG, Dao([]), web3, lambda _key: Account(), [])
    assert result["ok"] is False
    assert result["minimumGasWei"] == 200_000


def test_preflight_rejects_a_token_with_incompatible_decimals():
    web3 = Web3()
    web3.eth = Eth()
    functions = Functions()
    functions.decimals = lambda: Value(6)
    web3.eth.contract = lambda **_kwargs: type(
        "Contract", (), {"functions": functions}
    )()

    result = reward_preflight(CONFIG, Dao([]), web3, lambda _key: Account(), [])

    assert result["ok"] is False
    assert result["tokenDecimals"] == 6

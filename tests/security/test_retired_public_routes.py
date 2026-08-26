import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def registered_routes(path):
    tree = ast.parse((ROOT / path).read_text())
    return {
        decorator.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
        if isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "route"
        and decorator.args
        and isinstance(decorator.args[0], ast.Constant)
        and isinstance(decorator.args[0].value, str)
    }


def route_decorators(path, route):
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = node.decorator_list
        if any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "route"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
            and decorator.args[0].value == route
            for decorator in decorators
        ):
            return decorators
    return []


def test_retired_public_routes_are_not_registered():
    assert "/api/v1/get-api-key" not in registered_routes("routes/authentication_routes.py")
    assert "/cron" not in registered_routes("routes/rewards.py")
    assert "/compute/download-zip" not in registered_routes("routes/training_routes.py")
    assert "/api/v1/bulk/upload-zip" not in registered_routes(
        "routes/metadata_routes.py"
    )
    assert "/api/v1/upload/user-data" not in registered_routes(
        "routes/metadata_routes.py"
    )
    assert "/api/v1/get-participants/<string:creator_id>" not in registered_routes(
        "routes/authentication_routes.py"
    )
    assert "/start-tutorial" not in registered_routes("routes/other_routes.py")
    assert "/team_status" not in registered_routes("routes/other_routes.py")
    assert "/litterbux/status" not in registered_routes("routes/rewards.py")
    assert "/litterbux/claim-time" not in registered_routes("routes/rewards.py")
    assert "/set-peaq-address" not in registered_routes("routes/authentication_routes.py")
    recovery_routes = registered_routes("routes/authentication_routes.py")
    assert not any(route.startswith("/api/v1/recovery/") for route in recovery_routes)
    metadata_routes = registered_routes("routes/metadata_routes.py")
    assert not {
        "/api/v1/metadata/create-data-share",
        "/api/v1/metadata/stop-data-share",
        "/api/v1/metadata/share-data",
        "/api/v1/metadata/consumer-share-data",
        "/api/v1/metadata/data-share-by-data-token-address",
    } & metadata_routes


def test_default_web_runtime_does_not_initialize_the_legacy_sensor_database():
    source = (ROOT / "app.py").read_text()
    assert "initialize_db" not in source
    assert "MONGODB_SETTINGS" not in source


def test_authenticated_wallet_claim_route_remains_registered():
    decorators = route_decorators("routes/rewards.py", "/claim")
    assert decorators
    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "jwt_required"
        for decorator in decorators
    )
    source = (ROOT / "routes/rewards.py").read_text()
    tree = ast.parse(source)
    claim_function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "claim_reward"
    )
    function_source = ast.get_source_segment(source, claim_function)
    assert "get_jwt_identity()" in function_source
    assert "request.args.get('source')" not in function_source
    assert "source == Source.brainstem" in function_source
    assert "expected_eligibility_commitment_sha256" in function_source
    assert "source.value" in (ROOT / "dao/rewards_dao.py").read_text()


def test_wallet_claim_preview_is_authenticated_and_identifier_free():
    decorators = route_decorators("routes/rewards.py", "/claim-preview")
    assert decorators
    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id == "jwt_required"
        for decorator in decorators
    )
    source = (ROOT / "routes/rewards.py").read_text()
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "claim_preview"
    )
    function_source = ast.get_source_segment(source, function)
    assert "get_jwt_identity()" in function_source
    assert "source != Source.brainstem" in function_source
    assert 'result.pop("wallet", None)' in function_source
    assert '"private, no-store"' in function_source


def test_wallet_claim_chain_calls_are_bounded_and_use_pending_nonce():
    source = (ROOT / "commands/rewards/claim_reward_command.py").read_text()
    tree = ast.parse(source)
    claim_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ClaimRewardCommand"
    )
    transfer = next(
        node for node in claim_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "transfer"
    )
    function_source = ast.get_source_segment(source, transfer)
    assert 'request_kwargs={"timeout": rpc_timeout}' in function_source
    assert 'get_transaction_count(account.address, "pending")' in function_source
    assert "with reward_sender_lock()" in function_source
    assert "timeout=receipt_timeout" in function_source


def test_dataunion_source_is_server_owned_for_tokens_and_rewards():
    authentication_source = (ROOT / "routes/authentication_routes.py").read_text()
    authentication_tree = ast.parse(authentication_source)

    for function_name in {"login", "refresh"}:
        function = next(
            node
            for node in authentication_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        function_source = ast.get_source_segment(authentication_source, function)
        assert "APPLICATION_SOURCE.value" in function_source
        assert 'data.get("source")' not in function_source
        assert 'claims.get("source"' not in function_source

    rewards_source = (ROOT / "routes/rewards.py").read_text()
    rewards_tree = ast.parse(rewards_source)
    reward_function = next(
        node
        for node in rewards_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_reward"
    )
    function_source = ast.get_source_segment(rewards_source, reward_function)
    assert 'claims.get("source")' in function_source
    assert "args.get('source')" not in function_source


def test_retired_ocean_marketplace_and_data_share_owners_are_deleted():
    app_source = (ROOT / "app.py").read_text()
    assert "register_blueprint(compute_routes" not in app_source
    retired_files = {
        "routes/compute.py",
        "commands/metadata/create_data_share_command.py",
        "commands/metadata/disable_data_share_command.py",
        "commands/metadata/share_data_to_user_command.py",
        "commands/metadata/register_algorithm_command.py",
        "commands/metadata/file_coin_encrypt_data_command.py",
        "commands/metadata/file_coin_decrypt_data_command.py",
        "helpers/generate_reward_history.py",
        "helpers/transfer_peaq_token.py",
    }
    assert not [path for path in retired_files if (ROOT / path).exists()]


def test_application_api_key_and_cleanapp_subsystems_are_deleted():
    forbidden_symbols = {
        "APIKeyManager",
        "UserApiKey",
        "api_key_check",
        "apikey_db",
        "flask_api_key",
        "UploadCSVFromUrlCommand",
        "commands.dataunions.litterbux",
        "CleanApp",
        "litterbux",
        "BrainstemRewardTransactions",
        "transfer_gas_ocean",
        "recovery_email_hash",
        "RecoveryCommand",
    }
    source = "\n".join(
        path.read_text(errors="ignore")
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".ini", ".txt", ".json"}
        and "specs" not in path.parts
        and "tests" not in path.parts
    )
    for symbol in forbidden_symbols:
        assert symbol not in source


def test_url_only_csv_upload_has_no_fetch_command():
    assert not (ROOT / "commands/training/upload_csv_from_url_command.py").exists()
    training_routes = (ROOT / "routes/training_routes.py").read_text()
    assert "requests.get" not in training_routes
    assert "request.form.get('url')" not in training_routes


def test_profile_username_routes_require_jwt_and_use_token_identity():
    source = (ROOT / "routes/authentication_routes.py").read_text()
    tree = ast.parse(source)
    for route in ("/get_or_create_username", "/update_username"):
        decorators = route_decorators("routes/authentication_routes.py", route)
        assert any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "jwt_required"
            for decorator in decorators
        )

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "get_or_create_username",
            "update_username",
        }:
            function_source = ast.get_source_segment(source, node)
            assert "get_jwt_identity()" in function_source
            assert 'data.get("public_address")' not in function_source


def test_couchdb_access_uses_the_bounded_shared_client():
    files = list((ROOT / "dao").glob("*.py")) + [ROOT / "helpers/create_db.py"]
    for path in files:
        if path.name == "couchdb_client.py":
            continue
        source = path.read_text()
        assert "requests.request(" not in source
        assert "requests.get(" not in source
        assert "requests.post(" not in source
        assert "@{2}" not in source

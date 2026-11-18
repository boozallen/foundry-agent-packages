# Foundry Auth Tests

## Running Tests

### With uv (recommended)
```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run all tests
uv run pytest tests/

# Run with coverage
uv run pytest tests/ --cov=src/foundry_auth --cov-report=term-missing

# Run specific test file
uv run pytest tests/unit/test_config.py
```

### With pip
```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src/foundry_auth --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_config.py
```

**Troubleshooting**: If you encounter `AttributeError: 'Package' object has no attribute 'obj'` with pytest-asyncio, ensure you're using pytest-asyncio>=0.24.0 which is compatible with Python 3.13+.

## Test Structure

Tests are tiered by directory: `tests/unit/` holds the fast, credential-free
tier and `tests/integration/` holds tests needing external services or
credentials. `conftest.py` stays at the `tests/` root so its fixtures reach both
tiers.

- `conftest.py` - Shared fixtures including WebSocket global state reset
- `unit/test_config.py` - AuthConfig tests (prefix-based config, CORS parsing)
- `unit/test_session.py` - Session storage tests (SQLite, Redis stub, OAuth state)
- `unit/test_websocket.py` - WebSocket registry tests (connection lifecycle, validation)
- `unit/test_routers.py` - Auth router endpoint tests (login, callback, logout)
- `unit/test_dependencies.py` - Dependency injection tests
- `unit/test_stores.py` - Session store backend tests
- `unit/test_utils.py` - Utility helper tests

## Current Status

**Passing Tests**: 113/113 (100%)
**Coverage**: 87% (target: 70%)

### Completed
- Configuration tests (prefix-based, CORS, validation)
- Session storage tests (CRUD, expiration, thread safety)
- WebSocket registry tests (registration, validation, cleanup)
- Router tests (login, callback, logout, httpx mocked via respx)
- Dependency injection tests (FastAPI test client)

## Test Coverage by Module

| Module | Coverage |
|--------|----------|
| config.py | 100% |
| stores.py | 100% |
| utils.py | 100% |
| oidc.py | 94% |
| session.py | 90% |
| dependencies.py | 89% |
| routers.py | 85% |
| __init__.py | 83% |
| websocket.py | 69% |

## CI Integration

To add tests to CI pipeline, add the following to your workflow:

```yaml
- name: Install dependencies
  run: pip install -e ".[dev]"

- name: Run tests with coverage
  run: pytest tests/ --cov=src/foundry_auth --cov-report=term --cov-report=xml

- name: Check coverage threshold
  run: |
    coverage=$(python -c "import xml.etree.ElementTree as ET; tree = ET.parse('coverage.xml'); print(tree.getroot().attrib['line-rate'])")
    if (( $(echo "$coverage < 0.70" | bc -l) )); then
      echo "Coverage $coverage is below 70% threshold"
      exit 1
    fi
```

## Notes

- WebSocket tests use auto-reset fixture to prevent state leakage
- Session tests use tmp_path for isolated SQLite databases
- All async tests use pytest-asyncio
- Coverage excludes Redis stub (NotImplementedError) and TYPE_CHECKING blocks
- Uses `respx` for httpx HTTP mocking in router tests

# foundry-agent-config

![Status: Available](https://img.shields.io/badge/status-available-brightgreen)
![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.13%2B-blue)

YAML configuration loader with environment-variable overrides for
Pydantic models. One function, `load_config`, reads a YAML file, merges
env-var overrides (double-underscore nesting), and validates the result
against a user-supplied `BaseModel`.

## Install

```bash
uv add foundry-agent-config
# or
pip install foundry-agent-config
```

## Quickstart

```python
from pathlib import Path
from pydantic import BaseModel
from foundry_agent_config import load_config

class AppConfig(BaseModel):
    host: str = "localhost"
    port: int = 8000

config = load_config(AppConfig, Path("config.yaml"), env_prefix="MYAPP")
# MYAPP__PORT=9000 overrides config.port to 9000
# MYAPP__MODEL__PROVIDER=ollama overrides config.model.provider
```

## What's in the box

| Surface | Highlights |
|---------|------------|
| `load_config(model, yaml_path, env_prefix="")` | Reads YAML, merges env-var overrides, validates against a Pydantic model |
| Env-var coercion | `int`, `float`, `bool`, `list[T]` (CSV or JSON), `dict`, `Optional[T]` |
| Nested overrides | `PREFIX__OUTER__INNER=value` traverses nested models |
| Bounded inputs | YAML file size, env var size, and key counts are bounded (DISA STIG V-222612) |
| `ConfigurationError` | Raised on missing file, invalid YAML, non-mapping root, or schema validation failure |

## Security

The loader bounds YAML file size, environment-variable size, and key
counts to prevent resource-exhaustion attacks (DISA STIG V-222612).
Command-execution sinks are prohibited and gated by Ruff `S6xx` rules
plus `bandit` narrow-set in CI (DISA STIG V-222604). See the
[STIG checklist](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-config/security/stig_checklist.json).

## Reference

- [README](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-config/README.md)
- [Changelog](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-config/CHANGELOG.md)
- [Source](https://github.com/boozallen/foundry-agent-packages/tree/main/packages/foundry-agent-config)
- [License (Apache-2.0)](https://github.com/boozallen/foundry-agent-packages/blob/main/packages/foundry-agent-config/LICENSE)

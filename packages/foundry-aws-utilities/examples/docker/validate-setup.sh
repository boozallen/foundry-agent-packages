#!/bin/bash
# DynamoDB MCP Server Docker Setup Validation Script

set -e

echo "🔍 Validating DynamoDB MCP Server Docker setup..."

# Check required files
echo "✅ Checking required files..."
for file in Dockerfile compose.yaml pyproject.toml uv.lock env.template README.md .gitignore; do
    if [[ -f "$file" ]]; then
        echo "   ✓ $file exists"
    else
        echo "   ❌ $file missing"
        exit 1
    fi
done

# Check environment template
echo "✅ Checking environment template..."
if grep -q "UV_EXTRA_INDEX_URL" env.template; then
    echo "   ✓ env.template present and configurable"
    echo "   ℹ️  Set the package index in pyproject.toml before building"
else
    echo "   ❌ UV_EXTRA_INDEX_URL missing from env.template"
    exit 1
fi

# Check the Dockerfile installs with uv and does not log in to a package index
echo "✅ Checking Dockerfile configuration..."
if grep -q "uv sync" Dockerfile && grep -q "ghcr.io/astral-sh/uv" Dockerfile; then
    echo "   ✓ uv-based dependency install found"
else
    echo "   ❌ uv-based dependency install missing"
    exit 1
fi

if grep -q "uv auth login" Dockerfile; then
    echo "   ❌ Dockerfile still authenticates to a package index"
    exit 1
else
    echo "   ✓ No index authentication required"
fi

# Check pyproject.toml configuration
echo "✅ Checking pyproject.toml configuration..."
if grep -q "foundry-aws-utilities" pyproject.toml; then
    echo "   ✓ foundry-aws-utilities dependency configured"
else
    echo "   ❌ foundry-aws-utilities dependency missing"
    exit 1
fi

if grep -q "tool.uv.sources" pyproject.toml; then
    echo "   ✓ Package source configured"
else
    echo "   ❌ Package source missing — foundry-aws-utilities will not resolve"
    exit 1
fi

echo ""
echo "🎉 All validation checks passed!"
echo ""
echo "📋 Next steps:"
echo "1. Copy env.template to .env (optional customization)"
echo "2. Run: docker compose up -d"
echo "3. Test health: curl http://localhost:9003/health"
echo ""

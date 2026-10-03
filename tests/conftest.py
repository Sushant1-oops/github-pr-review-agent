import os

# config.Settings() is instantiated at import time in several modules
# (github_tools.py, agents/base.py) and requires these to be present.
# Tests never make real network calls to NVIDIA NIM/GitHub, so dummy values
# are fine — this just satisfies pydantic-settings' required fields.
os.environ.setdefault("NVIDIA_API_KEY", "test-dummy-key")
os.environ.setdefault("GITHUB_TOKEN", "test-dummy-token")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")

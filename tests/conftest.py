"""Global pytest fixtures for vsa-agent tests."""

import os
import sys

_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _src not in sys.path:
    sys.path.insert(0, _src)

os.environ.setdefault("VSA_CONFIG", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "config.yaml")))
os.environ.setdefault("VSA_PROFILE", "test")

# Unset SSL_CERT_FILE if it points to a non-existent file
if "SSL_CERT_FILE" in os.environ and not os.path.exists(os.environ["SSL_CERT_FILE"]):
    del os.environ["SSL_CERT_FILE"]

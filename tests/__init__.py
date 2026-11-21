import sys
from unittest.mock import MagicMock

if "astrbot" not in sys.modules:
    mock_astrbot = MagicMock()
    mock_api = MagicMock()
    sys.modules["astrbot"] = mock_astrbot
    sys.modules["astrbot.api"] = mock_api

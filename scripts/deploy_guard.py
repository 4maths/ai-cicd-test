from __future__ import annotations

import logging
import sys

from aicicd.core.deploy_guard import run_deploy_guard

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


if __name__ == "__main__":
    sys.exit(run_deploy_guard())
"""
開発用 Flask 起動ラッパー。
WSL2 bind mount では inotify が伝播しないため、
watchdog の Observer を PollingObserver に差し替える。
"""
import os
import sys

# FLASK_ENV=development の時のみポーリングに切り替え
if os.getenv("FLASK_ENV", "").lower() == "development":
    try:
        from watchdog.observers.polling import PollingObserver
        import watchdog.observers
        watchdog.observers.Observer = PollingObserver
        print("[dev_server] watchdog Observer -> PollingObserver (WSL2/Docker対応)", file=sys.stderr)
    except ImportError:
        print("[dev_server] watchdog 未インストール。stat reloaderにフォールバック", file=sys.stderr)

from flask.cli import main
sys.exit(main())

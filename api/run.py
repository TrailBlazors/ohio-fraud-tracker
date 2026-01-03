#!/usr/bin/env python
"""
Quick start script for Ohio Fraud Tracker API

Usage:
    python run.py
    python run.py --port 8080
    python run.py --no-reload
"""

import os
import sys
import argparse

# Ensure we're in the right directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Add to path
sys.path.insert(0, script_dir)


def main():
    parser = argparse.ArgumentParser(description="Start Ohio Fraud Tracker API")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload on code changes")
    parser.add_argument("--prod", action="store_true", help="Production mode (no reload, bind to 0.0.0.0)")
    
    args = parser.parse_args()
    
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed")
        print("Activating venv and installing...")
        os.system(f'"{script_dir}\\.venv\\Scripts\\pip" install uvicorn')
        import uvicorn
    
    # Load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Configure
    host = args.host
    port = args.port
    reload = not args.no_reload
    
    if args.prod:
        host = "0.0.0.0"
        reload = False
    
    # Banner
    print()
    print("╔" + "═" * 48 + "╗")
    print("║" + "Ohio Fraud Tracker API".center(48) + "║")
    print("╠" + "═" * 48 + "╣")
    print(f"║  Server:    http://{host}:{port}".ljust(49) + "║")
    print(f"║  API Docs:  http://{host}:{port}/docs".ljust(49) + "║")
    print(f"║  Reload:    {reload}".ljust(49) + "║")
    print("╠" + "═" * 48 + "╣")
    print("║  Press Ctrl+C to stop".ljust(49) + "║")
    print("╚" + "═" * 48 + "╝")
    print()
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[script_dir] if reload else None,
    )


if __name__ == "__main__":
    main()

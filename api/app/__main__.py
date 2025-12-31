"""
Ohio Fraud Tracker API - Entry Point

Run with: python -m app
Or:       python run.py
"""

import os
import sys


def main():
    """Start the API server"""
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed")
        print("Run: pip install uvicorn")
        sys.exit(1)
    
    # Load settings from environment
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "true").lower() == "true"
    
    print("=" * 50)
    print("Ohio Fraud Tracker API")
    print("=" * 50)
    print(f"Starting server at http://{host}:{port}")
    print(f"API docs at http://{host}:{port}/docs")
    print(f"Hot reload: {reload}")
    print("=" * 50)
    print("Press Ctrl+C to stop")
    print()
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()

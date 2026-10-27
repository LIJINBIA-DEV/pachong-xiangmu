"""Start the WebUI for local and LAN access with the project's Mac runtime tools."""
import os
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["PATH"] = os.pathsep.join((
    str(ROOT / ".runtime/node/bin"),
    str(Path.home() / ".local/bin"),
    os.environ.get("PATH", ""),
))

private_settings = ROOT / '.runtime/ragent-secrets.json'
if private_settings.exists():
    for name, value in json.loads(private_settings.read_text()).items():
        if name in {'TYPESAFE_API_KEY', 'RAGENT_REVIEW_TOKEN', 'DEEPSEEK_API_KEY', 'AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL'}:
            os.environ[name] = value

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=18080)

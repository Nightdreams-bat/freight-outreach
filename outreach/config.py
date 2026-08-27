import json

from outreach.paths import CONFIG_PATH


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"No config.json found at {CONFIG_PATH}. Run the setup wizard first "
            f"(FreightOutreach.exe --setup, or `python -m outreach.setup`)."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

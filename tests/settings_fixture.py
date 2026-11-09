"""Synthetic settings-app data and generated geometry art, never user assets."""
import json
from pathlib import Path
import sys
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mxbridge.pets import DEFAULT_DISPLAY, import_pet
from mxbridge.state import atomic_json, empty
from test_settings import fixture_sheet

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
sheet = root / "fixture.png"
sheet.write_bytes(fixture_sheet())
local = import_pet(root, sheet, "fixture-local")
remote = import_pet(root, sheet, "fixture-remote")
with zipfile.ZipFile(root / "new-pet.codex-pet.zip", "w") as archive:
    archive.writestr("spritesheet.png", sheet.read_bytes())
    archive.writestr("pet.json", '{"id":"new-pet"}')
atomic_json(root / "display.json", dict(DEFAULT_DISPLAY, mode="pet", pet=local, fps=4,
    future_setting={"preserve": True},
    pet_rules=[dict(location="remote", pet=remote)]))
state = empty()
now = time.time()
for index in range(13):
    state["rows"].append(dict(key=f"chat-{index}", session_id=f"fixture-session-{index}",
        name="Local Pi" if index == 0 else f"Project {index}", client="pi" if index == 0 else "codex",
        kind="session", status="TOOL" if index % 3 == 0 else "READY", created_at=now - index * 5,
        updated_at=now - index, valid_until=now + 900, order=index))
state["remotes"]["desk"] = dict(received_at=now, error="", rows=[
    dict(key="@client/pi/remote-child", name="Remote Pi child", client="pi", kind="subagent",
         status="READY", created_at=now, updated_at=now, valid_until=now + 900, order=0)])
atomic_json(root / "state.json", state)
print(json.dumps(dict(local=local, remote=remote)))

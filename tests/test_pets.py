"""Geometry fixtures test sprite transport, not the quality of pet artwork."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mxbridge.pets import (DEFAULT_DISPLAY, STANDARD, configure, import_pet, layout_for,
                          list_pets, pillow, read_display, validate_display)

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

ROOT = Path(__file__).resolve().parent.parent


class DisplayConfigTests(unittest.TestCase):
    def test_default_text_does_not_require_pillow(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, {"PIL":None}):
            self.assertEqual(read_display(folder), DEFAULT_DISPLAY)
            self.assertEqual(configure(folder, mode="text")["mode"], "text")
            with self.assertRaisesRegex(ValueError, "Pillow"):
                pillow()

    def test_rejects_unsafe_ids_and_unbounded_animation(self):
        for changes in (dict(pet="../outside"), dict(mode="unknown"), dict(fps=60),
                        dict(fps=True), dict(fps=float("nan")), dict(animate="yes"), dict(mode="pet")):
            with self.assertRaises(ValueError):
                validate_display(dict(DEFAULT_DISPLAY, **changes))

    def test_text_mode_recovers_from_corrupt_config(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/"display.json").write_text("invalid")
            self.assertEqual(configure(folder, mode="text"), DEFAULT_DISPLAY)

    def test_label_switches_and_chat_names_survive_other_display_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"display.json"
            path.write_text(json.dumps(dict(DEFAULT_DISPLAY, show_status=False,
                show_client=False, name_overrides={"chat-key": "My chat", "remote/desktop/chat-key": "Build"})))
            result = configure(folder, fps=2)
            self.assertFalse(result["show_status"])
            self.assertFalse(result["show_client"])
            self.assertEqual(result["name_overrides"]["remote/desktop/chat-key"], "Build")
            self.assertEqual(read_display(folder), result)
            result = configure(folder, show_name=False, show_location=False)
            self.assertFalse(result["show_name"])
            self.assertFalse(result["show_location"])

    def test_invalid_label_values_never_replace_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"display.json"
            configure(folder, mode="text")
            before = path.read_bytes()
            for change in (dict(show_status="off"), dict(show_name=1),
                           dict(name_overrides={"chat": "bad\nname"}), dict(name_overrides=None),
                           dict(name_overrides={"chat": "x"*81})):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_display(dict(DEFAULT_DISPLAY, **change))
            with self.assertRaises(ValueError):
                configure(folder, show_name="yes")
            self.assertEqual(path.read_bytes(), before)

    def test_cli_can_toggle_label_visibility_without_touching_agent_state(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(ROOT/"bridge.py"), "--state-dir", folder,
                "display", "--show-status", "off", "--show-location", "off", "--use-chat-names", "on"],
                capture_output=True, text=True, check=True)
            value = json.loads(result.stdout)
            self.assertFalse(value["show_status"])
            self.assertFalse(value["show_location"])
            self.assertTrue(value["use_chat_names"])
            self.assertFalse((Path(folder)/"state.json").exists())

    def test_layout_requires_core_states_and_stays_inside_sheet(self):
        with self.assertRaises(ValueError):
            layout_for((1536,1873))
        with self.assertRaises(ValueError):
            layout_for((32,32), dict(frame_width=32,frame_height=32,columns=1,animations={}))
        layout = layout_for((1536,1872))
        layout["animations"]["idle"]["frames"] = 9
        with self.assertRaises(ValueError):
            layout_for((1536,1872), layout)


@unittest.skipIf(Image is None, "Install the optional pets extra (Pillow 13) to test the importer")
class PetImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="mx-sprite-fixtures-")
        cls.root = Path(cls.temp.name)
        image = Image.new("RGBA", (1536,1872), (0,0,0,0))
        draw = ImageDraw.Draw(image)
        for j,(state,(row,count)) in enumerate(STANDARD.items()):
            for i in range(count):
                draw.rectangle((i*192+30,row*208+40,i*192+140,row*208+190), fill=(j*20+30,i*20+10,100,255))
        cls.sheet = cls.root/"fixture.png"
        image.save(cls.sheet)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_import_v1_keeps_frame_geometry_and_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            pet = import_pet(folder, self.sheet, "buddy")
            root = Path(folder)/"pets"/pet
            manifest = json.loads((root/"manifest.json").read_text())
            self.assertEqual(sum(map(len,manifest["animations"].values())), 57)
            self.assertEqual((manifest["frame_width"],manifest["frame_height"]), (192,208))
            with Image.open(root/"running-1.png") as frame:
                self.assertEqual(frame.size,(192,208))
                self.assertEqual(frame.getpixel((0,0))[3],0)
                self.assertEqual(frame.getpixel((40,50)),(170,30,100,255))

    def test_import_v2_uses_standard_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            sheet = Path(folder)/"v2.png"
            image = Image.new("RGBA", (1536,2288))
            with Image.open(self.sheet) as original:
                image.paste(original, (0,0))
            image.save(sheet)
            pet = import_pet(folder,sheet,"v2")
            data = json.loads((Path(folder)/"pets"/pet/"manifest.json").read_text())
            self.assertEqual(len(data["animations"]),9)

    def test_import_is_repeatable_and_selection_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            pet = import_pet(folder,self.sheet,"buddy")
            self.assertEqual(import_pet(folder,self.sheet,"buddy"),pet)
            self.assertEqual(list_pets(folder),[pet])
            self.assertEqual(read_display(folder)["mode"],"text")
            selected = configure(folder,mode="pet",pet="buddy",fps=2,motion="off")
            self.assertEqual(selected["pet"],pet)
            self.assertFalse(selected["animate"])
            self.assertEqual(configure(folder,mode="text")["pet"],pet)

    def test_unknown_layout_accepts_explicit_mapping(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"small.png"
            image = Image.new("RGBA",(32,160))
            draw=ImageDraw.Draw(image)
            for row in range(5):
                draw.rectangle((8,row*32+8,24,row*32+24),fill="white")
            image.save(path)
            with self.assertRaisesRegex(ValueError,"Unknown sheet geometry"):
                import_pet(folder,path,"small")
            layout = dict(frame_width=32,frame_height=32,columns=1,
                animations={name:dict(row=i,frames=1) for i,name in enumerate(("idle","running","waiting","review","failed"))})
            spec=Path(folder)/"layout.json"
            spec.write_text(json.dumps(layout))
            pet=import_pet(folder,path,"small",spec)
            self.assertTrue((Path(folder)/"pets"/pet/"idle-0.png").exists())

    def test_empty_required_frame_does_not_publish_pack(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"blank.png"
            with Image.open(self.sheet) as image:
                image=image.convert("RGBA")
                ImageDraw.Draw(image).rectangle((0,0,191,207),fill=(0,0,0,0))
                image.save(path)
            with self.assertRaisesRegex(ValueError,"Empty required frame"):
                import_pet(folder,path,"blank")
            self.assertEqual(list_pets(folder),[])

    def test_opaque_sheet_and_path_names_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"opaque.png"
            Image.new("RGBA",(1536,1872),"white").save(path)
            with self.assertRaisesRegex(ValueError,"transparency"):
                import_pet(folder,path,"opaque")
            with self.assertRaises(ValueError):
                import_pet(folder,self.sheet,"../outside")

    def test_oversize_input_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"oversize.png"
            with path.open("wb") as f:
                f.truncate(20*1024*1024+1)
            with self.assertRaisesRegex(ValueError,"20 MiB"):
                import_pet(folder,path,"large")

    def test_cli_import_and_hot_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            base=[sys.executable,str(ROOT/"bridge.py"),"--state-dir",folder]
            imported=subprocess.run(base+["pet","import","--sheet",str(self.sheet),"--name","cli"],capture_output=True,text=True,check=True)
            pet=json.loads(imported.stdout)["pet"]
            configured=subprocess.run(base+["display","--mode","pet","--pet",pet,"--motion","off"],capture_output=True,text=True,check=True)
            self.assertFalse(json.loads(configured.stdout)["animate"])
            self.assertFalse((Path(folder)/"state.json").exists())
            self.assertTrue((Path(folder)/"display.json").is_file())

    def test_missing_or_ambiguous_pet_never_enables_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                configure(folder,mode="pet",pet="missing")
            self.assertFalse((Path(folder)/"display.json").exists())


if __name__ == "__main__":
    unittest.main()

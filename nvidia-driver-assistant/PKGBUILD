import pathlib
import tempfile
import unittest

from nvidia_driver_assistant import supported_chips


LATEST_HTML = """\
<p><a name="Current" id="Current"></a></p>
<h3>Current NVIDIA GPUs</h3>
<table>
  <tr id="devid2D98"><td>GeForce RTX example</td></tr>
  <tr id="devid1340"><td>GeForce legacy overlap example</td></tr>
</table>
<p><a name="legacy_580.xx" id="legacy_580.xx"></a></p>
<table><tr id="devid1340"><td>GeForce 830M</td></tr></table>
<p><a name="legacy_470.xx" id="legacy_470.xx"></a></p>
<table><tr id="devid0FC6"><td>GeForce GTX 650</td></tr></table>
<p><a name="legacy_173.14.xx" id="legacy_173.14.xx"></a></p>
<table><tr id="devid00C2"><td>Legacy GPU</td></tr></table>
"""


SUPPORTED_580_HTML = """\
<p><a name="Current" id="Current"></a></p>
<h3>Current NVIDIA GPUs</h3>
<table>
  <tr id="devid1340"><td>GeForce 830M</td></tr>
  <tr id="devid2D98_17AA_3E31"><td>GeForce RTX example subsystem variant</td></tr>
</table>
<p><a name="legacy_470.xx" id="legacy_470.xx"></a></p>
<table><tr id="devid1340"><td>Unrelated old-driver section</td></tr></table>
"""


class SupportedChipsParserTests(unittest.TestCase):
    def _write_temp(self, directory, filename, content):
        path = pathlib.Path(directory) / filename
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_latest_document_maps_current_and_legacy_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_temp(tmpdir, "supportedchips.html", LATEST_HTML)
            branch_map = supported_chips.parse(path)

        self.assertEqual(branch_map["2d98"], "current")
        self.assertEqual(branch_map["1340"], "580")
        self.assertEqual(branch_map["0fc6"], "470")
        self.assertEqual(branch_map["00c2"], "173")

    def test_580_current_only_ignores_later_legacy_sections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_temp(tmpdir, "supportedchips580.html", SUPPORTED_580_HTML)
            current_ids = supported_chips.parse_current(path)

        self.assertEqual(current_ids, {"1340", "2d98"})

    def test_subsystem_variants_reduce_to_base_device_id(self):
        rows = supported_chips.parse_html(SUPPORTED_580_HTML)
        self.assertIn("2d98", {row["device_id"] for row in rows})

    def test_legacy_entry_wins_over_duplicate_current_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_temp(tmpdir, "supportedchips.html", LATEST_HTML)
            branch_map = supported_chips.parse(path)
        self.assertEqual(branch_map["1340"], "580")

    def test_build_validation_requires_both_documents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            latest_path = self._write_temp(tmpdir, "supportedchips.html", LATEST_HTML)
            chips580_path = self._write_temp(tmpdir, "supportedchips580.html", SUPPORTED_580_HTML)
            latest, current580 = supported_chips.validate_documents(
                latest_path, chips580_path
            )

        self.assertEqual(latest["1340"], "580")
        self.assertEqual(latest["2d98"], "current")
        self.assertEqual(current580, {"1340", "2d98"})

    def test_empty_or_unrecognized_html_is_rejected(self):
        self.assertIsNone(
            supported_chips.parse_html("<html><body>not an NVIDIA list</body></html>")
        )


if __name__ == "__main__":
    unittest.main()

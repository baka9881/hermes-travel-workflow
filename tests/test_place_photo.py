import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/place-photo.py"
spec = importlib.util.spec_from_file_location("place_photo", SCRIPT)
place_photo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(place_photo)

PAGE = "https://www.hotel.example/rooms/double.html"


class ImageOnPageTests(unittest.TestCase):
    def test_relative_absolute_and_lazy_images_are_found(self):
        html = ('<img src="../images/room-1.jpg"><img data-src="https://cdn.hotel.example/a/b.webp">'
                '<div style="background:url(/img/hall.png)"></div>')
        for image in ("https://www.hotel.example/images/room-1.jpg", "https://cdn.hotel.example/a/b.webp",
                      "https://www.hotel.example/img/hall.png"):
            with self.subTest(image=image):
                self.assertTrue(place_photo.image_on_page(html, PAGE, image))

    def test_unrelated_picture_is_refused(self):
        html = '<img src="/images/room-1.jpg">'
        pikachu = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/25.png"
        self.assertFalse(place_photo.image_on_page(html, PAGE, pikachu))
        self.assertFalse(place_photo.image_on_page(html, PAGE, "https://other.example/images/room-1.jpg"))

    def test_http_addresses_are_refused(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "x", "--page", "http://a.example/", "--image",
                                 "https://a.example/b.jpg", "--label", "外觀"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

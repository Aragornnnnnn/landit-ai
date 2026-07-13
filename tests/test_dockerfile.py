# AI 컨테이너가 한국 표준시 로그를 출력하도록 시간대 설정을 검증한다.
import unittest
from pathlib import Path


class DockerfileTimezoneTests(unittest.TestCase):
    def test_container_installs_timezone_data_and_uses_seoul_timezone(self):
        dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()

        self.assertIn("tzdata", dockerfile)
        self.assertIn("TZ=Asia/Seoul", dockerfile)

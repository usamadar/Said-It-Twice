import unittest
from config import retries


class ConfigTests(unittest.TestCase):
    def test_positive_retry_count(self):
        self.assertEqual(retries('3'), 3)

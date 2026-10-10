from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / 'vendor' / 'OpenWar3AI-ffd7dd25a3c2478f457b74bde89d23e605b24243'
sys.path.insert(0, str(UPSTREAM / 'sdk' / 'python'))
sys.path.insert(0, str(UPSTREAM / 'runtime'))

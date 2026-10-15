import argparse
import json
from app.db import migrate
from app.pipeline import run

parser = argparse.ArgumentParser(description='Local Hudson property intelligence pipeline')
parser.add_argument('command', choices=['migrate', 'ingest'])
parser.add_argument('--snapshot', help='Replay an existing checksummed snapshot without downloading')
args = parser.parse_args()
if args.command == 'migrate':
    migrate()
else:
    print(json.dumps(run(args.snapshot), indent=2))

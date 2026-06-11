import json

from app import app
from worldcup26.sync import sync_tournament


with app.app_context():
    summary = sync_tournament()
    print(json.dumps(summary, indent=2))

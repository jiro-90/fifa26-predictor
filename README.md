# FIFA 26 Duel

Two-player World Cup prediction game built for basic Python hosting on cPanel.

## What it does

- Creates a private room with a unique code and password.
- Lets two players submit:
  - match score predictions
  - group-stage final standings predictions
- Hides each player's picks from the opponent until the relevant lock time:
  - match picks stay hidden until kick-off
  - group picks stay hidden until the first match in that group kicks off
- Locks match picks at kick-off.
- Locks group picks when the first match in that group kicks off.
- Scores picks automatically from synced results.
- Shows a human-readable breakdown of where each point came from.
- Uses JSON files instead of a database.

## Stack

- Python 3
- Flask
- JSON flat files in `data/`
- Optional external results sync provider

## Local run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m flask --app app run --debug
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

If you want the app to use your local env file in PowerShell first:

```powershell
Get-Content .env.example
$env:SECRET_KEY="dev-secret"
$env:RESULTS_PROVIDER="football-data"
$env:FOOTBALL_DATA_API_KEY="your-key"
$env:SYNC_INTERVAL_SECONDS="1800"
python -m flask --app app run --debug
```

## Local testing

You can test current behavior without waiting for real matches.

Useful helper commands:

```powershell
python demo_tools.py list-matches --limit 12
python demo_tools.py reset-runtime
python demo_tools.py set-kickoff M001 2099-06-12T18:00:00Z
python demo_tools.py set-kickoff M001 2000-06-12T18:00:00Z
python demo_tools.py finish-match M001 2 1
python demo_tools.py set-group-positions D usa par aus tur
python demo_tools.py reset-group-positions D
```

What these are good for:

- Future kickoff like `2099-...` keeps a match open, so opponent match picks stay hidden.
- Past kickoff like `2000-...` locks the match, so opponent match picks become visible.
- `finish-match` lets you immediately test point allocation for a completed match.
- `set-group-positions` lets you force a final group order and test group scoring.
- `reset-runtime` clears rooms and sync-state so you can start clean.

Simple local test flow:

1. Run `python demo_tools.py reset-runtime`
2. Start the Flask app
3. Create a room as Player 1
4. Open a private/incognito browser window and join as Player 2
5. Make different predictions in both windows
6. Use `set-kickoff` or `set-group-kickoff` to move a fixture/group from future to past
7. Refresh both pages to confirm hidden picks become visible only after lock
8. Use `finish-match` or `set-group-positions` to test scoring updates

## cPanel deployment

This project is shaped for Passenger / Python App style hosting on cPanel.

1. Create a Python app in cPanel.
2. Upload this project into the app root.
3. Set the startup file to `passenger_wsgi.py` or point the app at `app.py` depending on your host's UI.
4. Install requirements inside the app virtualenv:

```bash
pip install -r requirements.txt
```

5. Set environment variables:
   - `SECRET_KEY`
   - `ADMIN_SYNC_KEY`
   - optionally `RESULTS_PROVIDER=football-data`
   - optionally `FOOTBALL_DATA_API_KEY`

6. Restart the Python app from cPanel.

## Cron job for automatic updates

Do not rely on an in-process background thread on shared hosting. Use cron instead.

Example cPanel cron command every 30 minutes:

```bash
cd /home/USERNAME/path/to/app && /home/USERNAME/virtualenv/path/to/app/3.x/bin/python sync_results.py
```

If your host exposes only an HTTP trigger, you can also `POST` to `/admin/sync` with the `X-Admin-Sync-Key` header.

## Data files

- `data/tournament.json`
  - starter tournament data
  - groups, teams, kick-off times, matches
- `data/rooms.json`
  - room metadata
  - players
  - predictions
- `data/last_sync.json`
  - stores the latest sync summary

## Seed data

`data/tournament.json` now ships with a full 12-group, 104-match starter dataset.

The seed was normalized from a public World Cup 2026 JSON project:

- [rezarahiminia/worldcup2026](https://github.com/rezarahiminia/worldcup2026)

Use a live results provider for authoritative match statuses and knockout-team updates.

## Live data provider

The app includes a working provider hook for `football-data.org`.

Set:

```env
RESULTS_PROVIDER=football-data
FOOTBALL_DATA_API_KEY=your-key
FOOTBALL_DATA_COMPETITION=WC
SYNC_INTERVAL_SECONDS=1800
```

Get your key here:

- Register: [football-data.org client registration](https://www.football-data.org/client/register)
- Docs: [football-data.org API docs](https://www.football-data.org/documentation/api)
- Coverage: [football-data.org coverage](https://www.football-data.org/coverage)

Important:

- `football-data.org` currently lists `Worldcup` in its free coverage and its free plan allows 10 requests per minute for registered clients, which is more than enough for a 30-minute cron sync.
- The sync now pulls both `/competitions/WC/matches` and `/competitions/WC/standings`.
- Group standings from the API are written into `actual_positions` so group scoring follows the provider's published table order instead of only the local fallback sort.
- If the provider does not return official group standings tie-breaks, the app falls back to points, goal difference, goals scored, then alphabetical order.
- You can override any group's final ranking in `data/tournament.json` with an `actual_positions` array.

## Tournament coverage

The bundled dataset already includes all 12 groups and all 104 matches.

The sync layer can now:

1. Match API fixtures onto local fixtures even when `external_id` is initially empty
2. Update scores, statuses, kick-off times, and known knockout participants
3. Import published group standings for final group-position scoring

## Tests

```powershell
python -m unittest discover -s tests
```

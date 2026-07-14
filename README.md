# bmw3-series-watch

State-carrying repo for the RG Pick-A-Part BMW 3 Series junkyard watcher.

`watch.py` GETs the inventory, isolates BMW 3 SERIES rows, classifies each by
chassis generation (E30/E36/E46/E90/F30/G20), diffs stock numbers against
`snapshot.json`, stamps per-car first-seen dates, updates the snapshot, appends
to `history.log`, and prints a report with a machine-marker push line.

The snapshot is the memory. A cloud routine runs `python3 watch.py`, then
commits and pushes the updated `snapshot.json` + `history.log` so the next run
can diff against it.

Owner's car: F30 generation (2012–2018) — the priority match.

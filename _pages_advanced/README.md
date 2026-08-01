# Advanced pages (not in the demo navigation)

Streamlit builds its sidebar by auto-discovering `pages/*.py`. These six pages
are complete and working, but they are kept out of that directory so the
navigation stays at three entries: **Dashboard**, **Daily Brief**, and
**Source Library**.

Nine menu items asked a first-time visitor to choose before they understood any
of the options. Three tells a story in order: *what the system found* → *what to
publish* → *where every claim came from*.

| Page | What it does | Where its value now lives |
|---|---|---|
| `3_Trend_Radar.py` | Theme growth charts, trend-status filters | "Themes gaining ground" on the Dashboard |
| `4_Content_Pipeline.py` | Kanban of briefs by status | "More ideas" on the Daily Brief |
| `5_Content_Brief.py` | Full brief with evidence tabs | Folded into the Daily Brief |
| `6_Engagement_Watchlist.py` | Public conversations worth joining | — |
| `7_Voice_Library.py` | Approved public examples, derived style guide | — |
| `8_Settings.py` | Every input, weight and prompt | "How this is built" on the Dashboard |

To restore any of them, move the file back into `pages/`:

```bash
git mv _pages_advanced/3_Trend_Radar.py pages/
```

They are still covered by the test suite and still import cleanly; only the
navigation changed. Note that the read-only gating test in
`tests/test_database.py` scans both directories, so a mutating control added
here is still caught.

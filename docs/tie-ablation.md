# Ablation study of the eDisMax `tie`

`make tie-ablation` (`scripts/tie_ablation.py`) runs the four information needs on both setups with
`tie` = 0, 0.1, 0.2, 0.3, 0.5, 0.7 and 1. Results: `evaluation/tie_ablation.csv` and `runs/tie/*.run`.

## What `tie` does here

eDisMax scores a query term by the field where it matches best and adds `tie` times the scores of the other
fields: `tie = 0` keeps only the best field, `tie = 1` sums all of them. It only matters where a query searches
several fields:

| Part of the query | Fields | Affected by `tie` |
|---|---|---|
| Listing text (both setups) | `name^3 description^2 host_about^0.5` | yes |
| POIs (setup 2) | `poi_name^2 wikipedia_title^2 wikipedia_text` | yes |
| Reviews (setup 2) | `comments_en` | no (one field) |

Each value is applied the same way to every need and to every eDisMax query of a setup, so each value is one
configuration, never tuned per query.

## Results without judgements (17 Nov 2026)

Rankings are compared with the current value, 0.1. Means over the four needs; RBO is rank-biased overlap
(p = 0.9, depth 50), which weighs the top of the list most (0.99 = same ranking). QTime is the median of 3 runs.

| tie | Setup 1: top-10 shared | top-50 shared | RBO | QTime (ms) | Setup 2: top-10 shared | top-50 shared | RBO | QTime (ms) |
|---|---|---|---|---|---|---|---|---|
| 0.0 | 9.5 | 48.8 | 0.96 | 26 | 9.8 | 49.0 | 0.98 | 104 |
| **0.1** | **10** | **50** | **0.99** | 28 | **10** | **50** | **0.99** | 71 |
| 0.2 | 9.2 | 49.0 | 0.94 | 27 | 9.8 | 49.5 | 0.98 | 73 |
| 0.3 | 8.5 | 48.8 | 0.88 | 26 | 9.8 | 48.5 | 0.97 | 84 |
| 0.5 | 7.8 | 47.0 | 0.74 | 24 | 9.8 | 46.8 | 0.91 | 99 |
| 0.7 | 6.8 | 45.5 | 0.70 | 28 | 9.5 | 46.0 | 0.88 | 110 |
| 1.0 | 5.8 | 43.0 | 0.60 | 26 | 9.0 | 45.0 | 0.84 | 99 |

Per need (RBO against 0.1, for tie = 0 / 0.3 / 0.5 / 1):

| | IN1 | IN2 | IN3 | IN4 |
|---|---|---|---|---|
| Setup 1 | 0.95 / 0.93 / 0.85 / 0.61 | 0.99 / 0.89 / 0.86 / 0.78 | 0.93 / 0.80 / 0.61 / 0.51 | 0.97 / 0.89 / 0.62 / 0.49 |
| Setup 2 | 0.97 / 0.93 / 0.85 / 0.68 | 0.98 / 0.96 / 0.79 / 0.70 | 0.99 for every value | 0.99 for every value |

## Conclusions

1. **Low values are interchangeable.** From 0 to 0.3 the top 10 keeps 8.5 to 10 of its 10 listings and the
   RBO stays at 0.88 or more in setup 1 and 0.97 or more in setup 2, so the choice inside this range barely
   changes what a user sees.
2. **High values change setup 1 a lot.** At `tie = 1` setup 1 keeps only 5.8 of its top 10 (RBO 0.60, down to
   0.49 in IN4): the score becomes the sum over name, description and host text, so a term repeated across fields,
   including the host's own description, counts several times. This goes against the reason for the field
   boosts, that the name and the description of the listing are the main evidence.
3. **Setup 2 is less sensitive.** Its score also has the reviews (one field, unaffected) and the POIs, so `tie`
   moves only part of it. Its rankings for IN3 and IN4 do not change at all with `tie` (not yet explained);
   those of IN1 and IN2, whose terms (monuments, beach) can match several POI fields, do.
4. **Latency does not depend on `tie`.** `tie` changes scores, not the matched documents, and QTime varies
   without a trend (24 to 28 ms in setup 1, 71 to 110 ms in setup 2, with the first run of setup 2 slower
   because of a cold cache). Latency is therefore not a criterion for this parameter.
5. **The pool can include every variant.** Adding the top 50 of every tie value to the pool adds 39 listings
   (358 to 397: +21 in IN1, +11 in IN2, +2 in IN3, +5 in IN4), so all values are judged on the same pool and
   none is penalised by unjudged listings. `make pool` does this.

## Decision

- **Kept for now: `tie = 0.1`** in both setups. It is the conventional small value (the best field decides,
  the others only break ties), it sits in the range where rankings are stable, and the higher values change
  the ranking for a reason that does not fit the needs (conclusion 2).
- **To confirm with the judgements**, set before seeing them: run
  `make tie-ablation ARGS="--qrels evaluation/qrels.txt"` and keep the value with the highest MAP over both
  setups. If no value beats 0.1 by more than 0.01 MAP, keep 0.1. The value chosen is the same for every need
  and both setups.

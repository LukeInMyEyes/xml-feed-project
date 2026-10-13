# SA new car feed

Scrapes manufacturer sites into one catalogue per brand, then bundles those per
dealer. The output ends up on live dealer websites, so correctness beats
freshness every time.

```
discovery  ->  specs  ->  images  ->  compile  ->  diff
                                        |
                        output/brands/<brand>.json      per brand
                        output/dealers/<dealer>.json    per dealer bundle
```

Run it with `python3 run_feed.py --brands jac foton`, or `agent_compile.py` on
its own to rebuild the catalogues from whatever is already in `raw_data/`.

Client sites pull from `output/brands/`. On Midbay that is
`scripts/sync-new-cars.sh`, which copies the files into the repo and needs a
deploy afterwards.

## The two safety rules

Both exist because of a single bad run on 9 October 2026. It wrote model names
built out of URLs ("Jacmotors_Co_Za_Jac T6 Single Cab") across six brands and
dropped JAC's N56, N140 and both EVs entirely. Nothing checked and nothing
complained. The only reason no customer saw it is that nobody happened to run
the sync afterwards.

**1. A compile cannot shrink a catalogue.** If more than 10% of a brand's
models or priced variants would disappear, or any model name looks like a
hostname, the compile refuses that brand and keeps what was already on disk. It
says so loudly and carries on with the others.

When a manufacturer genuinely has pruned its range and you have confirmed it on
their site:

```bash
FEED_ALLOW_REGRESSION=1 python3 agent_compile.py jac
```

A refusal is not a failure. It means the scrape got less than last time, and
somebody needs to look at why before that reaches a dealer's customers.

**2. Verified corrections survive a recompile.** Scraped data is not always the
best data available. Changan publishes no cash prices at all, only monthly
offers, so the only scrapeable figures are from a May catalogue and they are
stale. Corrections confirmed against a manufacturer site or a dealer price list
live in `overrides/<brand>.json` and are applied after every compile:

```json
{
  "t6": {
    "variants": {
      "2.0T CTi S/C 4x2 Comfort": {
        "price_incl": 309900,
        "note": "jacmotors.co.za, T6 single cab page",
        "checked": "2026-10-13"
      }
    }
  }
}
```

Keep the note and the date honest. They are the only record of what was
actually checked, and a wrong price on a dealer site is the dealership's
consumer-law problem, not ours. An override that stops matching anything is
reported at compile time, because a correction that silently stopped applying
is worse than no correction.

## raw_data

One file per model per brand, plus `_images.json` alongside. Nothing is ever
deleted: a half-finished scrape must not be able to destroy good data. The
compile identifies a model by its `source_url`, not its filename, so when a
slug changes the old file is merged rather than compiled as a second phantom
model. Where two files describe the same model, the **fuller** one wins, not
the newer one, because the October manufacturer-site scrape is consistently
thinner than the catalogue it sits beside.

`raw_data_quarantine/` holds the 38 files from the 9 October run. They carry
current prices but no specs and mangled slugs, and the good prices from them
have already been applied by hand or through `overrides/`. They are kept rather
than deleted in case anything still needs lifting out of them.

## Known gaps

`raw_data` can no longer rebuild BAIC, Foton, JAC, GAC or Toyota to the quality
of what is live, so the compile refuses those brands and keeps the existing
catalogues. Those brands need a proper re-scrape; the live files are correct and
were verified against the manufacturer sites on 12 and 13 October 2026.

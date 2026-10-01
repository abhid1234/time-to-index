# AgentRoute launch standard → time-to-index

AgentRoute's launch surface, item by item, against this project's.

| AgentRoute | time-to-index | Status |
|---|---|---|
| **Playground**: agentroute-playground.vercel.app (hero, chips, 82s video, illustrative-data label, six stations) | **The Staleness Playground**: [abhid1234.github.io/time-to-index/playground.html](https://abhid1234.github.io/time-to-index/playground.html). It has a hero with chips, the 91s video, a simulation labelled hand-authored, and the real measured ledger. It started as the claude.ai artifact of the same name. | Live |
| **GitHub README**: what/what-not paragraph → hero diagram → "See it first" (video, playground, launch post, dataset) → data label → five-minute proof → release status | Same order, with a ledger-findings section and a BibTeX citation. 407 lines (AgentRoute has 329). | Done |
| **Repo hygiene**: CHANGELOG, SECURITY, CODE_OF_CONDUCT, CONTRIBUTING, Dependabot, CodeQL | All present, plus issue/PR templates and `CITATION.cff` | Done |
| **Site**: abhid1234.github.io/AgentRoute | [abhid1234.github.io/time-to-index](https://abhid1234.github.io/time-to-index/): live dashboard rebuilt on every probe run, with Open Graph cards | Live |
| **Package**: npm `@avee1234/agentroute` | Python `time-to-index`. Wheel and sdist are on the release; `pip install git+https://github.com/abhid1234/time-to-index@v0.1.0` works. The PyPI name is unclaimed, and `release.yml` publishes there once trusted publishing is on (`docs/RELEASING.md`). | Needs your PyPI account |
| **Release**: v0.2.1 (notes, install, assurance, artifacts, SBOM) | [v0.1.0](https://github.com/abhid1234/time-to-index/releases/tag/v0.1.0): notes from CHANGELOG, install line, assurance line, wheel, sdist, ledger snapshot, `SHA256SUMS`. Releases from the next one on also attach a CycloneDX SBOM. | Done |
| **Dataset**: HF `agentroute-fixtures` (card, SHA-256 manifest) | `launch/make_dataset.py` builds the card, with numbers read from the ledger, and the manifest. This is real measured data, not fixtures. | Needs your HF account (one command) |
| **Launch essay**: Substack, question title, ~800 words, playground CTA, reproduce block, "Get it" links | `launch/essay.md` / `essay.html`: question title, ~900 words, same shape | Ready to post |
| **Demo video**: 82s, music only | `media/time-to-index-short.mp4`: 91s, on-screen text, original music at the same loudness (−15 dB) | Done |
| **Repo homepage and topics** | Text is ready in the launch pack's `START-HERE.txt` | Needs your repo settings |

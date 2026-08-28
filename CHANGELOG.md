# Changelog

## [1.0.3](https://github.com/agrc/state-parks-skid/compare/v1.0.2...v1.0.3) (2026-08-28)


### Bug Fixes

* switch to using firestore to track skid runs ([2220a92](https://github.com/agrc/state-parks-skid/commit/2220a920c56a4282e7318a171856ed28e9a77b1a))

## [1.0.2](https://github.com/agrc/state-parks-skid/compare/v1.0.1...v1.0.2) (2026-08-18)


### Bug Fixes

* add prod worker url ([56c8b50](https://github.com/agrc/state-parks-skid/commit/56c8b500ebad47a7447aa0c7035d702c4e51369e))

## [1.0.1](https://github.com/agrc/state-parks-skid/compare/v1.0.0...v1.0.1) (2026-08-11)


### Bug Fixes

* resolve ruff lint failures after CI dependency bump ([b64c010](https://github.com/agrc/state-parks-skid/commit/b64c010da0bbf74440f6c29ccd37328dacb27bc9))

## 1.0.0 (2026-07-20)


### Features

* cloud run function services to respond to wp webhook and pull data from wp to agol ([30c9913](https://github.com/agrc/state-parks-skid/commit/30c99137f7efdfa5055f8e6f2eac90ccff22f79d))
* enhance data loading with backup restore and logging improvements ([15f3746](https://github.com/agrc/state-parks-skid/commit/15f3746bf0b57890279f9dca98a16e41a9fa8d96))
* update lat/long and geometry from wp ([05cc45c](https://github.com/agrc/state-parks-skid/commit/05cc45cb7a99a395ec7615809654cb99a95cc713))


### Bug Fixes

* better logging of unmatched data ([76e5c49](https://github.com/agrc/state-parks-skid/commit/76e5c4963dc7bbc49e696ffad755a67db5a49aa1))
* clean up logging ([1d12360](https://github.com/agrc/state-parks-skid/commit/1d123606056f4cbf3eeac35c421a7dcbc782c22d))
* more popup refinements ([6bcf7e4](https://github.com/agrc/state-parks-skid/commit/6bcf7e4eca122c4470fb226b5726f03730ac8568))
* popup layout refinements ([87fe2ac](https://github.com/agrc/state-parks-skid/commit/87fe2ac2e1fc21c49511b2452359e88cefc32de6))
* prevent duplicate tasks ([3e42b1d](https://github.com/agrc/state-parks-skid/commit/3e42b1d4623587e9e94e6e961c5de7ad8f50273f))
* switch to upsert palletjack solution for updating agol data ([0480830](https://github.com/agrc/state-parks-skid/commit/04808303b29bac5fb03280853e88558c5f4af504))


### Dependencies

* bump palletjack ([af74a8b](https://github.com/agrc/state-parks-skid/commit/af74a8bfa9ef9c17698a6974c44039738427e686))
* **dev:** update pytest requirement from &gt;=6 to &gt;=9.1.1 ([ed6fbb9](https://github.com/agrc/state-parks-skid/commit/ed6fbb9fbc444b3c1d7b158f91bc33a5a374bf66))


### Documentation

* update docs to reflect project specifics ([893fe3e](https://github.com/agrc/state-parks-skid/commit/893fe3e7a7e22762f9d7fe58177acaf51d9f2102))

## [1.0.1](https://github.com/agrc/skid/compare/v1.0.0...v1.0.1) (2026-01-29)


### Dependencies

* **dev:** update functions-framework requirement ([e8bf430](https://github.com/agrc/skid/commit/e8bf4307d9abf7f200061abda6812ab6f6517366))
* **dev:** update pytest requirement from &lt;9,&gt;=7 to &gt;=7,&lt;10 ([5350132](https://github.com/agrc/skid/commit/5350132e4edbfa599ed7cd6f7b9ea898d46d2ad2))

## 1.0.0 (2025-07-30)


### Features

* gen2 trigger function ([a8a415a](https://github.com/agrc/skid/commit/a8a415a2d6f44b4be9b807498908b29d87aae976))


### Bug Fixes

* dep qualifiers ([0af573f](https://github.com/agrc/skid/commit/0af573f6315008d47db3e72861ba9bbcab63a7e4))


### Dependencies

* bump agrc-supervisor in the safe-dependencies group ([6278c89](https://github.com/agrc/skid/commit/6278c89b9ab9625551146258a0324fdb707f8594))
* bump ci deps 🌲 ([#19](https://github.com/agrc/skid/issues/19)) ([80b15c9](https://github.com/agrc/skid/commit/80b15c9ff5d2ddc30ac4716a85f31710ed1bc427))
* bump the major-dependencies group across 1 directory with 4 updates ([33bf047](https://github.com/agrc/skid/commit/33bf04702268f2fe759b2bdc91d2f4f39bf0d969))
* bump the major-dependencies group with 1 update ([391a0d5](https://github.com/agrc/skid/commit/391a0d5f6daaf16a51fcdcf5224adcb0b1272575))
* bump the major-dependencies group with 6 updates ([bdbb79c](https://github.com/agrc/skid/commit/bdbb79c576b15e7b840082766f6007ae91379b6e))
* bump to python 3.11 ([#20](https://github.com/agrc/skid/issues/20)) ([1aad176](https://github.com/agrc/skid/commit/1aad176f6ef28af6c3a4e15dd8a7694c6e923049))
* **dev:** bump the major-dependencies group with 4 updates ([6a73219](https://github.com/agrc/skid/commit/6a73219cc4aa7b1b1b204331a12e1b3ae63780b8))
* update supervisor ([14dc504](https://github.com/agrc/skid/commit/14dc504c164db958fe447d420f2f2cc745e107d6))
* update ugrc-palletjack requirement from &lt;5.2,&gt;=5.0 to &gt;=5.0,&lt;5.3 ([35f9e2b](https://github.com/agrc/skid/commit/35f9e2b7876ffcfc6a45f6f475ad3bb13852ee7a))

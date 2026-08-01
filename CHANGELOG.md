# Changelog

## [0.1.8](https://github.com/westonplatter/ngv-trader/compare/v0.1.7...v0.1.8) (2026-08-01)


### Features

* **trades:** bring unsettled TWS fills to display parity with settled rows ([#100](https://github.com/westonplatter/ngv-trader/issues/100)) ([caf92af](https://github.com/westonplatter/ngv-trader/commit/caf92af21cc293e1119c50d95c98c95cdd660cb9))


### Bug Fixes

* **trades:** purge redundant live BAG summaries once their combo settles ([#98](https://github.com/westonplatter/ngv-trader/issues/98)) ([1dc5f6c](https://github.com/westonplatter/ngv-trader/commit/1dc5f6c36cf8f50cbfd883fed60f32085e357f6a))


### Miscellaneous Chores

* **ci:** use simple vX.Y.Z release tags ([#101](https://github.com/westonplatter/ngv-trader/issues/101)) ([cf3c3d5](https://github.com/westonplatter/ngv-trader/commit/cf3c3d54917ed5ac8365e3e9e4374675defde22a))

## [0.1.7](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.6...ngv-trader-v0.1.7) (2026-08-01)


### Features

* **positions:** add real-time option metrics overlay ([#83](https://github.com/westonplatter/ngv-trader/issues/83)) ([3d40cc8](https://github.com/westonplatter/ngv-trader/commit/3d40cc8c1f19f6d0ba4fd5252ccec1063a6cfd3a))
* **tagging:** add YAML management spec to trade groups ([#87](https://github.com/westonplatter/ngv-trader/issues/87)) ([1c37960](https://github.com/westonplatter/ngv-trader/commit/1c3796050df27cc1bc5641c2dcbe48f0b829daa9))
* **tagging:** apply privacy mode to trade tagging view ([#78](https://github.com/westonplatter/ngv-trader/issues/78)) ([f60e802](https://github.com/westonplatter/ngv-trader/commit/f60e80241eab1f741cafd3657279538c7208141c))
* Trade booking refinements: reconcile orphaned fills, tagging/trades UI, jobs params ([#93](https://github.com/westonplatter/ngv-trader/issues/93)) ([60849bf](https://github.com/westonplatter/ngv-trader/commit/60849bf903596182a9ab1efab5539d97d159f87b))
* trade-booking improvements for unsettled fills and tagging ([#94](https://github.com/westonplatter/ngv-trader/issues/94)) ([803ae9a](https://github.com/westonplatter/ngv-trader/commit/803ae9ad0c5becebfbd245a650b18a313a8ee89e))


### Bug Fixes

* **intraday:** widen the TWS fills window to a rolling two-day lookback ([#95](https://github.com/westonplatter/ngv-trader/issues/95)) ([c160918](https://github.com/westonplatter/ngv-trader/commit/c160918df75e149c42821ba1559634903432a8cc))


### Documentation

* condense the unsettled-TWS contract-parity plan ([#96](https://github.com/westonplatter/ngv-trader/issues/96)) ([77c1b83](https://github.com/westonplatter/ngv-trader/commit/77c1b8372bbf5417dc02ce16fbf77a8d9902a64e))
* fix stale details found in doc review pass ([#82](https://github.com/westonplatter/ngv-trader/issues/82)) ([8f760cb](https://github.com/westonplatter/ngv-trader/commit/8f760cb5e1a437a578401d0287b7ae8fd6f70930))
* fix stale worker handler table; sync frontend lockfile ([#88](https://github.com/westonplatter/ngv-trader/issues/88)) ([215083a](https://github.com/westonplatter/ngv-trader/commit/215083ab487c4526a7957ac10b827ad045ef8db8))
* routine doc review — realized-PnL spec banner update ([#92](https://github.com/westonplatter/ngv-trader/issues/92)) ([e38893d](https://github.com/westonplatter/ngv-trader/commit/e38893d1589aee6b9328bed73e43d83cb4b50fe5))


### Miscellaneous Chores

* default Taskfile ENV to prod; doc review fixes ([#80](https://github.com/westonplatter/ngv-trader/issues/80)) ([99d39cc](https://github.com/westonplatter/ngv-trader/commit/99d39cc14c2cf7b4c45b7882e7eb5304dc032969))

## [0.1.6](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.5...ngv-trader-v0.1.6) (2026-07-05)


### Features

* **semantic:** open-positions grain, premium & unrealized metrics, fuzzy trade-group find ([#74](https://github.com/westonplatter/ngv-trader/issues/74)) ([60970ee](https://github.com/westonplatter/ngv-trader/commit/60970ee2a95dfaebfef6f1acc6194e5713b12144))
* **ux:** hide dollar amounts and show relative returns in privacy mode ([#72](https://github.com/westonplatter/ngv-trader/issues/72)) ([47cc0b0](https://github.com/westonplatter/ngv-trader/commit/47cc0b01556b0a424b8a0807f03d84d54b0e2817))


### Documentation

* cross-check docs against codebase, fix stale/missing content ([#71](https://github.com/westonplatter/ngv-trader/issues/71)) ([c44bce8](https://github.com/westonplatter/ngv-trader/commit/c44bce81dbdc2c65df09a55b94cc0d703d2ea7f9))


### Continuous Integration

* regenerate uv.lock on release PR to keep self-version in sync ([#77](https://github.com/westonplatter/ngv-trader/issues/77)) ([5967b63](https://github.com/westonplatter/ngv-trader/commit/5967b6326b82738c3fb26f401539f450248ab693))

## [0.1.5](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.4...ngv-trader-v0.1.5) (2026-07-03)


### Features

* **positions:** default table sort to Symbol ascending ([#67](https://github.com/westonplatter/ngv-trader/issues/67)) ([8df5a77](https://github.com/westonplatter/ngv-trader/commit/8df5a77ec5e4660101df524613e03019027b3fa4))


### Bug Fixes

* **metrics:** boot the OSI semantic MCP server + source its DB URL from 1Password ([#69](https://github.com/westonplatter/ngv-trader/issues/69)) ([7d65aee](https://github.com/westonplatter/ngv-trader/commit/7d65aee57dfcb8481b74b08808f106c5e06b7421))


### Documentation

* fix stale claims and gaps found in scheduled doc review ([#66](https://github.com/westonplatter/ngv-trader/issues/66)) ([01fde62](https://github.com/westonplatter/ngv-trader/commit/01fde6284ebd1f954b76abb4bbe8d51b6e5458aa))

## [0.1.4](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.3...ngv-trader-v0.1.4) (2026-07-03)


### Features

* **intraday:** live TWS overlay for current-state P&L on FlexQuery positions ([#52](https://github.com/westonplatter/ngv-trader/issues/52)) ([d128cbd](https://github.com/westonplatter/ngv-trader/commit/d128cbd09c8de8b62e1126aca5c9b2d111953876))
* **positions:** associate real-time TWS positions with a trade group (execution-level) ([#53](https://github.com/westonplatter/ngv-trader/issues/53)) ([682d613](https://github.com/westonplatter/ngv-trader/commit/682d613c57f00580877db8fd553e75aa074b4435))
* **positions:** refine columns and add Trade Group links ([#49](https://github.com/westonplatter/ngv-trader/issues/49)) ([000a975](https://github.com/westonplatter/ngv-trader/commit/000a9751cc0f93dbb2073df9b217f882be11c248))
* **trade-groups:** per-account P&L, spread-aware capital, correct live marks ([#62](https://github.com/westonplatter/ngv-trader/issues/62)) ([fb9c2f4](https://github.com/westonplatter/ngv-trader/commit/fb9c2f47a34ab13472c207212ff0fcd5aa57aaf0))
* **tradebot:** OSI semantic layer + trade-group PnL for analyst queries ([#60](https://github.com/westonplatter/ngv-trader/issues/60)) ([6cca0b8](https://github.com/westonplatter/ngv-trader/commit/6cca0b80989cf96446a490c869f4ac924f9994d9))
* **trades:** add "Sync Since Last Trade" button with dynamic date range ([#33](https://github.com/westonplatter/ngv-trader/issues/33)) ([59b3e16](https://github.com/westonplatter/ngv-trader/commit/59b3e166cb62594c1fd1cca0a150e909bff2c5a2))
* **trades:** preemptively tag unsettled TWS fills, transition to settled on FlexQuery ([#55](https://github.com/westonplatter/ngv-trader/issues/55)) ([a9fd4f8](https://github.com/westonplatter/ngv-trader/commit/a9fd4f85fc891a7a3e7bda83a1bb46c881de23e8))
* **trades:** weekly-review refinements ([#44](https://github.com/westonplatter/ngv-trader/issues/44)) ([e03cf65](https://github.com/westonplatter/ngv-trader/commit/e03cf659a4017d5fd1954735e30202aae6347d01))
* **ui:** add status filter to Trade Groups list ([#50](https://github.com/westonplatter/ngv-trader/issues/50)) ([0d4dce4](https://github.com/westonplatter/ngv-trader/commit/0d4dce40c5628881bf168af791d6e346921601d7))
* **ui:** demo-data mode with a fetch interceptor for backend-free UI ([#51](https://github.com/westonplatter/ngv-trader/issues/51)) ([92aab3b](https://github.com/westonplatter/ngv-trader/commit/92aab3bc15ca6a93e3f5f4891be9a70cf3d2f82c))
* **ui:** filter untagged trades ([c53b86f](https://github.com/westonplatter/ngv-trader/commit/c53b86f694f0422c265baca4698f31432adbd148))
* **ux:** finance number formatting, searchable position tagging, nav lights ([#57](https://github.com/westonplatter/ngv-trader/issues/57)) ([30eab06](https://github.com/westonplatter/ngv-trader/commit/30eab061aae0a84bbec717f16ad7d39feabd6469))
* **ux:** make trade tagging better ([#32](https://github.com/westonplatter/ngv-trader/issues/32)) ([bd48108](https://github.com/westonplatter/ngv-trader/commit/bd48108aecd8842fa3d5362e6cca6242707ddda4))


### Bug Fixes

* **ui:** move Trade Groups + New button to the right above status ([#45](https://github.com/westonplatter/ngv-trader/issues/45)) ([cfea700](https://github.com/westonplatter/ngv-trader/commit/cfea700f12538470abfdab45247eaa25c594f327))
* **ui:** place Trade Groups + New button above list status badges ([#46](https://github.com/westonplatter/ngv-trader/issues/46)) ([bb5f8ba](https://github.com/westonplatter/ngv-trader/commit/bb5f8ba695f8bd7cd2de87bd8dc03f490de0f984))


### Documentation

* add activated-products security master spec ([#48](https://github.com/westonplatter/ngv-trader/issues/48)) ([4ae96e5](https://github.com/westonplatter/ngv-trader/commit/4ae96e55232126323b5b1007d0005f2904a63432))
* add doc_check.py and streamline doc-review process ([#64](https://github.com/westonplatter/ngv-trader/issues/64)) ([66b1508](https://github.com/westonplatter/ngv-trader/commit/66b1508c239de7361864889194c8254ea980b5c9))
* add screenshots to README ([#61](https://github.com/westonplatter/ngv-trader/issues/61)) ([a496528](https://github.com/westonplatter/ngv-trader/commit/a49652880fe50ae9c0e4571f2666a747126353c8))
* Add trades and positions to SSE event streaming ([#36](https://github.com/westonplatter/ngv-trader/issues/36)) ([e1a7b98](https://github.com/westonplatter/ngv-trader/commit/e1a7b9800a0285f1072cf5ce893cbbea5cbc899e))
* cross-check docs against codebase + UV cooldown policy ([#35](https://github.com/westonplatter/ngv-trader/issues/35)) ([f25ea76](https://github.com/westonplatter/ngv-trader/commit/f25ea761395b285916ed27568039a24278629a71))
* cross-check docs against codebase, fix stale/missing content ([#63](https://github.com/westonplatter/ngv-trader/issues/63)) ([83b30ee](https://github.com/westonplatter/ngv-trader/commit/83b30eea2eb0f5c858021dd977839804f4337897))
* document Conventional Commit PR title requirement ([#47](https://github.com/westonplatter/ngv-trader/issues/47)) ([bd2a575](https://github.com/westonplatter/ngv-trader/commit/bd2a5759b48bb2b1b2d168e106eb1e52848d2958))
* fix broken links, missing pages, and op run guidance ([#34](https://github.com/westonplatter/ngv-trader/issues/34)) ([8e7afba](https://github.com/westonplatter/ngv-trader/commit/8e7afba1f8c940a0ea1114f32b0d980a1f55dd6f))
* reconcile docs with current codebase, prune shipped specs ([#30](https://github.com/westonplatter/ngv-trader/issues/30)) ([bd78938](https://github.com/westonplatter/ngv-trader/commit/bd7893827ef3e5640d9687169d1102687142484f))
* Update documentation with corrected line numbers and scope ([#37](https://github.com/westonplatter/ngv-trader/issues/37)) ([1ec1326](https://github.com/westonplatter/ngv-trader/commit/1ec1326e0cc1139a583259dcfbdacde117bf905f))


### Miscellaneous Chores

* add SessionStart hook to install deps for Claude Code on the web ([#39](https://github.com/westonplatter/ngv-trader/issues/39)) ([1055d34](https://github.com/westonplatter/ngv-trader/commit/1055d34979c75f1991060803105413186a1f42f4))
* **db:** merge alembic heads (intraday overlay + activated products) ([2324f20](https://github.com/westonplatter/ngv-trader/commit/2324f20e1579fc3344e980304ca3e3fc280682cd))

## [0.1.3](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.2...ngv-trader-v0.1.3) (2026-06-06)


### Features

* setup flex query fetch process ([#28](https://github.com/westonplatter/ngv-trader/issues/28)) ([6f3e1ec](https://github.com/westonplatter/ngv-trader/commit/6f3e1ec6a27a957b95ba0bb10868290b58ddfc99))
* switch to FlexQuery for position and trade data ([#26](https://github.com/westonplatter/ngv-trader/issues/26)) ([54b8dc7](https://github.com/westonplatter/ngv-trader/commit/54b8dc78d3dda4a80d490d3e7de007bf83847045))
* **trades:** arrow-key tagging navigation + 30d sync button ([#29](https://github.com/westonplatter/ngv-trader/issues/29)) ([1089d76](https://github.com/westonplatter/ngv-trader/commit/1089d760c0e4c3f9997ee97630410a9cc8eabb8d))

## [0.1.2](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.1...ngv-trader-v0.1.2) (2026-04-29)


### Features

* Add trade-tagging schema, APIs, and migration ([#8](https://github.com/westonplatter/ngv-trader/issues/8)) ([4cb33d8](https://github.com/westonplatter/ngv-trader/commit/4cb33d85a55019e252e8ae8c1b4a694d7d336085))
* bring in src/data folder ([#22](https://github.com/westonplatter/ngv-trader/issues/22)) ([f8b8e3a](https://github.com/westonplatter/ngv-trader/commit/f8b8e3a1c8d4807e564cf8970f6929eae46e238f))
* **data:** fetch fut + fops data for CL and ES ([#11](https://github.com/westonplatter/ngv-trader/issues/11)) ([5df7f94](https://github.com/westonplatter/ngv-trader/commit/5df7f946a398c32d53fa0dbbf4593e553a199daa))
* finish data sec ([#10](https://github.com/westonplatter/ngv-trader/issues/10)) ([8a84f46](https://github.com/westonplatter/ngv-trader/commit/8a84f4650c720efa1d0c82986dab955f4e5191ea))
* **frontend:** migrate from node/npm to bun ([#19](https://github.com/westonplatter/ngv-trader/issues/19)) ([#20](https://github.com/westonplatter/ngv-trader/issues/20)) ([4a0e09a](https://github.com/westonplatter/ngv-trader/commit/4a0e09a3d35dc24888e6d6aeb7c05b68f2e618a5))
* **orders:** bring back syncing orders ([#1](https://github.com/westonplatter/ngv-trader/issues/1)) ([738cfec](https://github.com/westonplatter/ngv-trader/commit/738cfec1f63850fdf0aa7fc98a9572f49323418e))
* **privacy:** add user preferences API and privacy mode ([#3](https://github.com/westonplatter/ngv-trader/issues/3)) ([fdec878](https://github.com/westonplatter/ngv-trader/commit/fdec878e182c694cdde4b9028d9649271a7dd470))
* **structures:** basic Future Option structures pricer ([#17](https://github.com/westonplatter/ngv-trader/issues/17)) ([4ee1699](https://github.com/westonplatter/ngv-trader/commit/4ee1699e7ffd4710666cc88a13df2b8ed6cac2ba))
* **structures:** save a structure ([#21](https://github.com/westonplatter/ngv-trader/issues/21)) ([170bb54](https://github.com/westonplatter/ngv-trader/commit/170bb54e9a21d9daa199a028f924193da1eb1061))
* **sync:** trades + trade executions ([#2](https://github.com/westonplatter/ngv-trader/issues/2)) ([bdc4cf3](https://github.com/westonplatter/ngv-trader/commit/bdc4cf35d7db708c80250511b1027b3cfec457cd))
* **ux:** use SSE from FastAPI -&gt; UI ([#15](https://github.com/westonplatter/ngv-trader/issues/15)) ([2c272ef](https://github.com/westonplatter/ngv-trader/commit/2c272efd1e98675e7978aa7da2ad8136c8c98213))


### Bug Fixes

* **frontend:** use bunx --bun for tsc in build script ([0fd873b](https://github.com/westonplatter/ngv-trader/commit/0fd873b93b9725facbf9c64966248465e70e3fce))
* **tagging:** allow trade groups to live across multiple accounts ([#12](https://github.com/westonplatter/ngv-trader/issues/12)) ([bf257cb](https://github.com/westonplatter/ngv-trader/commit/bf257cb42527ca1d219058ddb161c4fcf2370549))


### Documentation

* add a getting started guide and environment validation ([#6](https://github.com/westonplatter/ngv-trader/issues/6)) ([4e3b256](https://github.com/westonplatter/ngv-trader/commit/4e3b25645b0a150b6a04eaabe5ee7a04a0ca02bb))


### Miscellaneous Chores

* change license terms and rename to ngv-trader ([46e7df1](https://github.com/westonplatter/ngv-trader/commit/46e7df1b0ff7d321f547bc0158b23d6387aadbc2))
* change license terms and rename to ngv-trader ([242d34a](https://github.com/westonplatter/ngv-trader/commit/242d34a829514c1352ea200cc6e5c044f6342fb3))
* **main:** release ngtrader-pro 0.1.1 ([#4](https://github.com/westonplatter/ngv-trader/issues/4)) ([c910ec2](https://github.com/westonplatter/ngv-trader/commit/c910ec2b2a47f1eafe4c2dcc5462df7f8718bc44))

## [0.1.1](https://github.com/westonplatter/ngv-trader/compare/ngv-trader-v0.1.0...ngv-trader-v0.1.1) (2026-03-01)

### Features

- **orders:** bring back syncing orders ([#1](https://github.com/westonplatter/ngv-trader/issues/1)) ([738cfec](https://github.com/westonplatter/ngv-trader/commit/738cfec1f63850fdf0aa7fc98a9572f49323418e))
- **privacy:** add user preferences API and privacy mode ([#3](https://github.com/westonplatter/ngv-trader/issues/3)) ([fdec878](https://github.com/westonplatter/ngv-trader/commit/fdec878e182c694cdde4b9028d9649271a7dd470))
- **sync:** trades + trade executions ([#2](https://github.com/westonplatter/ngv-trader/issues/2)) ([bdc4cf3](https://github.com/westonplatter/ngv-trader/commit/bdc4cf35d7db708c80250511b1027b3cfec457cd))

### Documentation

- add a getting started guide and environment validation ([#6](https://github.com/westonplatter/ngv-trader/issues/6)) ([4e3b256](https://github.com/westonplatter/ngv-trader/commit/4e3b25645b0a150b6a04eaabe5ee7a04a0ca02bb))

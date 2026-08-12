# Changelog

## [0.1.13](https://github.com/westonplatter/ngv-trader/compare/v0.1.12...v0.1.13) (2026-08-12)


### Features

* **strategies:** add IV column, totals row, and IBKR trade codes ([#154](https://github.com/westonplatter/ngv-trader/issues/154)) ([4402e28](https://github.com/westonplatter/ngv-trader/commit/4402e282e23f223503778ca593bb196db6ceca98))


### Documentation

* add flexquery_tokens router to AGENTS.md component list ([#153](https://github.com/westonplatter/ngv-trader/issues/153)) ([6b53454](https://github.com/westonplatter/ngv-trader/commit/6b53454b7085f5520b515df53784a5813e124e70))

## [0.1.12](https://github.com/westonplatter/ngv-trader/compare/v0.1.11...v0.1.12) (2026-08-08)


### Features

* **scripts:** block commits carrying real IBKR data ([#148](https://github.com/westonplatter/ngv-trader/issues/148)) ([8e3147c](https://github.com/westonplatter/ngv-trader/commit/8e3147c796aa5d6f7572776982dac660a390a3e1))
* **ux:** make strategy workspace panes horizontally resizable ([#151](https://github.com/westonplatter/ngv-trader/issues/151)) ([e394d34](https://github.com/westonplatter/ngv-trader/commit/e394d34da12d99286ad90b5a613cbf24f9f88b4a))
* **workers:** split flexquery sync into request and fetch phases ([#149](https://github.com/westonplatter/ngv-trader/issues/149)) ([fa613c9](https://github.com/westonplatter/ngv-trader/commit/fa613c94566db0e49ce1e609f96febd17242ac44))


### Documentation

* move ibkr sample-data guide into docs/, drop prompts/ ([#147](https://github.com/westonplatter/ngv-trader/issues/147)) ([1ce23e4](https://github.com/westonplatter/ngv-trader/commit/1ce23e4d8985a61ceaad25e62efa71e32601e2fc))
* **orders:** plan working-orders overlay on strategies ([#152](https://github.com/westonplatter/ngv-trader/issues/152)) ([337b81e](https://github.com/westonplatter/ngv-trader/commit/337b81ec8a3a542cfc4c61486743019fbc424d75))
* **plans:** plan tax-adjusted cost basis reporting ([#150](https://github.com/westonplatter/ngv-trader/issues/150)) ([073e054](https://github.com/westonplatter/ngv-trader/commit/073e05449141e21d7587b11fe774226a7664c9a2))


### Miscellaneous Chores

* **deps-dev:** bump vite, eslint, globals, and @vitejs/plugin-react in /frontend ([#144](https://github.com/westonplatter/ngv-trader/issues/144)) ([2a391f3](https://github.com/westonplatter/ngv-trader/commit/2a391f3dda0f677dac5585aa98b2615bb9500fe0))
* **scripts:** remove obsolete scripts and unreferenced screenshots ([#146](https://github.com/westonplatter/ngv-trader/issues/146)) ([88c6e3a](https://github.com/westonplatter/ngv-trader/commit/88c6e3a38817ac36cbf00ddb8c7f6fb8bea1c547))

## [0.1.11](https://github.com/westonplatter/ngv-trader/compare/v0.1.10...v0.1.11) (2026-08-08)


### Features

* **ux:** add focus mode to trade tagging page ([#143](https://github.com/westonplatter/ngv-trader/issues/143)) ([2921c3b](https://github.com/westonplatter/ngv-trader/commit/2921c3baeae01604c3483be0eafb81be1d031f09))


### Documentation

* cover real-time TWS overlay in getting-started guide ([#138](https://github.com/westonplatter/ngv-trader/issues/138)) ([6bcd9a4](https://github.com/westonplatter/ngv-trader/commit/6bcd9a48aef8910226e1be98c9bce67c198bd39f))


### Miscellaneous Chores

* **deps-dev:** bump @eslint/js from 9.39.4 to 10.0.1 in /frontend ([#124](https://github.com/westonplatter/ngv-trader/issues/124)) ([f84444c](https://github.com/westonplatter/ngv-trader/commit/f84444cea59091c8426e4c28a102132a6d365f60))
* **deps-dev:** bump typescript-eslint from 8.57.1 to 8.65.0 in /frontend ([#126](https://github.com/westonplatter/ngv-trader/issues/126)) ([5163aea](https://github.com/westonplatter/ngv-trader/commit/5163aea571278dd057839d3847bd1ddb6aa680dc))
* **deps:** bump ai from 6.0.116 to 7.0.37 in /frontend ([#117](https://github.com/westonplatter/ngv-trader/issues/117)) ([3b24c00](https://github.com/westonplatter/ngv-trader/commit/3b24c009f333685b944dc1df30a6728dc77e3629))
* **deps:** bump cryptography from 49.0.0 to 50.0.0 ([#136](https://github.com/westonplatter/ngv-trader/issues/136)) ([fa3bc2a](https://github.com/westonplatter/ngv-trader/commit/fa3bc2acf71a59dcf92fb2180562c5f061d038f4))
* **deps:** bump idna from 3.11 to 3.15 ([#133](https://github.com/westonplatter/ngv-trader/issues/133)) ([0ba3b33](https://github.com/westonplatter/ngv-trader/commit/0ba3b33209931477db185f99a38f22b47d30cdfe))
* **deps:** bump langsmith from 0.7.5 to 0.8.18 ([#134](https://github.com/westonplatter/ngv-trader/issues/134)) ([7c322f6](https://github.com/westonplatter/ngv-trader/commit/7c322f6db928f86a0af1eb66203c3761cd01d52b))
* **deps:** bump mako from 1.3.10 to 1.3.12 ([#141](https://github.com/westonplatter/ngv-trader/issues/141)) ([9d2b141](https://github.com/westonplatter/ngv-trader/commit/9d2b14175b29a450ec72321c57ac94d4299bf0a3))
* **deps:** bump pygments from 2.19.2 to 2.20.0 ([#140](https://github.com/westonplatter/ngv-trader/issues/140)) ([d7e0fc2](https://github.com/westonplatter/ngv-trader/commit/d7e0fc2727163057f6b12af506590bc871db9e86))
* **deps:** bump requests from 2.32.5 to 2.33.0 ([#142](https://github.com/westonplatter/ngv-trader/issues/142)) ([bdac2b9](https://github.com/westonplatter/ngv-trader/commit/bdac2b93487934cab2161e28e1e4394d273ef710))
* **deps:** bump starlette from 0.52.1 to 1.3.1 ([#137](https://github.com/westonplatter/ngv-trader/issues/137)) ([2f32cb0](https://github.com/westonplatter/ngv-trader/commit/2f32cb05e7ecf7a2d767ae22c99aba82d62b3375))
* **deps:** bump urllib3 from 2.6.3 to 2.7.0 ([#135](https://github.com/westonplatter/ngv-trader/issues/135)) ([17fa0ea](https://github.com/westonplatter/ngv-trader/commit/17fa0ea7b49812871178b980841a1c335eb988c1))

## [0.1.10](https://github.com/westonplatter/ngv-trader/compare/v0.1.9...v0.1.10) (2026-08-08)


### Features

* **secrets:** store flexquery tokens encrypted in postgres ([#130](https://github.com/westonplatter/ngv-trader/issues/130)) ([49d3a01](https://github.com/westonplatter/ngv-trader/commit/49d3a01ae9de1630c24f0ac12f6887203a144922))
* **workers:** scope flexquery syncs to one token and scale retry backoff ([#132](https://github.com/westonplatter/ngv-trader/issues/132)) ([491cbeb](https://github.com/westonplatter/ngv-trader/commit/491cbeb51d276c9df0807831ad38e37d836d44e5))


### Miscellaneous Chores

* **deps-dev:** bump @tailwindcss/vite from 4.2.1 to 4.3.3 in /frontend ([#115](https://github.com/westonplatter/ngv-trader/issues/115)) ([de606c5](https://github.com/westonplatter/ngv-trader/commit/de606c569f60abbffb5cbd245157d3a54beb7490))
* **deps:** bump psycopg2-binary from 2.9.11 to 2.9.12 ([#112](https://github.com/westonplatter/ngv-trader/issues/112)) ([180c7c1](https://github.com/westonplatter/ngv-trader/commit/180c7c1feb10a10db74311de6b600f0c027cc079))
* **deps:** bump react-dom from 19.2.4 to 19.2.8 in /frontend ([#120](https://github.com/westonplatter/ngv-trader/issues/120)) ([5d43340](https://github.com/westonplatter/ngv-trader/commit/5d433407c5cfbb4fffe99a4c7844870273ae6533))
* **deps:** bump react-router-dom from 7.13.1 to 7.18.1 in /frontend ([#116](https://github.com/westonplatter/ngv-trader/issues/116)) ([7a06b39](https://github.com/westonplatter/ngv-trader/commit/7a06b3984b9caf5dfcad0dac1a960294b79fe63c))
* **deps:** bump sqlalchemy from 2.0.46 to 2.0.51 ([#111](https://github.com/westonplatter/ngv-trader/issues/111)) ([77c8f72](https://github.com/westonplatter/ngv-trader/commit/77c8f7250165c084d4a248dbf0349560248069eb))


### Continuous Integration

* **deps:** bump actions/checkout from 4.4.0 to 7.0.1 ([#107](https://github.com/westonplatter/ngv-trader/issues/107)) ([2b27146](https://github.com/westonplatter/ngv-trader/commit/2b27146af765604e43b8cfc94bf87420e1f204d0))
* **deps:** bump astral-sh/setup-uv from 5.4.2 to 9.0.0 ([#108](https://github.com/westonplatter/ngv-trader/issues/108)) ([4289b97](https://github.com/westonplatter/ngv-trader/commit/4289b97047ade8652562f248ecb8feb370f8d74a))
* **deps:** bump googleapis/release-please-action from 4.4.1 to 5.0.0 ([#106](https://github.com/westonplatter/ngv-trader/issues/106)) ([90c4581](https://github.com/westonplatter/ngv-trader/commit/90c4581468a3505cd6aba55011d2d9d0e7234c57))

## [0.1.9](https://github.com/westonplatter/ngv-trader/compare/v0.1.8...v0.1.9) (2026-08-08)


### Features

* rename Tagging to Strategies, add pytest suite and CI ([#128](https://github.com/westonplatter/ngv-trader/issues/128)) ([dbf5484](https://github.com/westonplatter/ngv-trader/commit/dbf54841345d8dd8c5f7474766efab2aaa793504))


### Documentation

* clarify worker task defaults and simplify plan reference ([#102](https://github.com/westonplatter/ngv-trader/issues/102)) ([96b6753](https://github.com/westonplatter/ngv-trader/commit/96b67534b90ec338a39cf1a8428c28da6644d6dd))
* fix stale spec banner, index wording, and small omissions ([#104](https://github.com/westonplatter/ngv-trader/issues/104)) ([3390ad4](https://github.com/westonplatter/ngv-trader/commit/3390ad420db2b3366021179449de44603709b714))
* simplify readme ([61edff6](https://github.com/westonplatter/ngv-trader/commit/61edff6e735296c289e63a0a54c8c4df07531402))


### Miscellaneous Chores

* **ci:** add dependabot for uv, bun, and github-actions ([#105](https://github.com/westonplatter/ngv-trader/issues/105)) ([800bf48](https://github.com/westonplatter/ngv-trader/commit/800bf488405ee3d8c3108a25bfb9ae8dade77e52))
* **deps-dev:** bump ruff from 0.15.2 to 0.16.0 ([#123](https://github.com/westonplatter/ngv-trader/issues/123)) ([472e223](https://github.com/westonplatter/ngv-trader/commit/472e223d3db8fda2706ed52452340a71b71bacd9))
* **deps-dev:** bump typer from 0.24.1 to 0.27.0 ([#114](https://github.com/westonplatter/ngv-trader/issues/114)) ([d6e8ea6](https://github.com/westonplatter/ngv-trader/commit/d6e8ea67f2b5cfdc61b639020cb05223784a8427))
* **deps:** bump alembic from 1.18.4 to 1.18.5 ([#125](https://github.com/westonplatter/ngv-trader/issues/125)) ([d746fb3](https://github.com/westonplatter/ngv-trader/commit/d746fb3b2ede3c5d92bd999c1d13b317e32a63c6))
* **deps:** bump fastapi from 0.135.1 to 0.139.2 ([#110](https://github.com/westonplatter/ngv-trader/issues/110)) ([8587c7f](https://github.com/westonplatter/ngv-trader/commit/8587c7f6be57b81ea6e238edc013808d02f71581))
* **deps:** bump langgraph from 1.0.9 to 1.2.9 ([#127](https://github.com/westonplatter/ngv-trader/issues/127)) ([a56035f](https://github.com/westonplatter/ngv-trader/commit/a56035f16fee40433b28871b26e9bc898d500f62))
* **deps:** bump python-dotenv from 1.2.1 to 1.2.2 ([#118](https://github.com/westonplatter/ngv-trader/issues/118)) ([04d53c2](https://github.com/westonplatter/ngv-trader/commit/04d53c2d7ff51e49f4b651906324de9d5ae4a584))
* **deps:** update uvicorn[standard] requirement from &gt;=0.34 to &gt;=0.51.0 ([#121](https://github.com/westonplatter/ngv-trader/issues/121)) ([93b0176](https://github.com/westonplatter/ngv-trader/commit/93b0176c11edcfe11cb54ce9c1653b8167b8bb9e))


### Continuous Integration

* pin github actions to commit shas and harden workflows ([#129](https://github.com/westonplatter/ngv-trader/issues/129)) ([6119bde](https://github.com/westonplatter/ngv-trader/commit/6119bdecbd9bb68efee0ffbb2c71235a703f72c3))

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

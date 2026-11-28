# Changelog

All notable changes to el-capitan are recorded here, grouped under the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) section names (Added, Changed, Removed,
Fixed), and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

[release-please](https://github.com/googleapis/release-please) writes each entry from the
conventional commits merged to `main` and opens a release pull request; merging it updates
`VERSION`, this file and the tag. Edit an entry in that pull request, not here.

## [0.2.0](https://github.com/crespocarlos/el-capitan/compare/v0.1.0...v0.2.0) (2026-11-28)


### Added

* capture every crew agent's reply and usage, in Cursor and Claude Code (Cursor speed phase B) ([ec38327](https://github.com/crespocarlos/el-capitan/commit/ec38327aaa79f23a5d9326a2ab018b09ca967fe0))
* capture every crew agent's reply and usage, in Cursor and Claude Code (Cursor speed phase B) ([3e2f9ee](https://github.com/crespocarlos/el-capitan/commit/3e2f9ee2266ee2169f931882603d3bf7bc6c6c68))
* **crew:** crew agents reach your docs and code-search MCP servers, and nothing else ([b7113ed](https://github.com/crespocarlos/el-capitan/commit/b7113ed8dbd2576baf1f0b52ec4865d292cc7b45))
* **crew:** crew memory is the only memory; install covers every Claude config dir ([e1b0ddc](https://github.com/crespocarlos/el-capitan/commit/e1b0ddc36e63e5e15fecd47f17c02ad05f01dfeb))
* **crew:** crew memory is the only memory; install covers every Claude config dir ([e5cc170](https://github.com/crespocarlos/el-capitan/commit/e5cc17006194adec09fab761451bbd3f3191285a))
* **crew:** default repo scope in config, PR lookup on forks, one crew ls --json shape ([70f2626](https://github.com/crespocarlos/el-capitan/commit/70f262613c5672cc62561cb4063934d75cd42781))
* **crew:** default repo scope in config, PR lookup on forks, one crew ls --json shape ([0651dd7](https://github.com/crespocarlos/el-capitan/commit/0651dd7354f96bb43f2b2f14af87c0db95ea2c30))
* **crew:** DONE when a PR is open; TUI shows issue, PR, progress and activity ([4401644](https://github.com/crespocarlos/el-capitan/commit/4401644b834a5f129d12f2ccc9475b707aaf59e7))
* **crew:** DONE when a PR is open; TUI shows issue, PR, progress and activity ([d0a34e2](https://github.com/crespocarlos/el-capitan/commit/d0a34e2f595b3740067459106143dd781f09abd8))
* **crew:** every agent can consult the configured MCP servers; doctor reports them correctly ([5b15ba4](https://github.com/crespocarlos/el-capitan/commit/5b15ba409991356ae972e1bb948d7494711e85dc))
* **crew:** every agent can consult the configured MCP servers; doctor reports them correctly ([58c961b](https://github.com/crespocarlos/el-capitan/commit/58c961b0b7faf8ebfef1788e4a20d91e25ca3d53))
* **crew:** one command ships a task (hardening phase 2) ([5aad384](https://github.com/crespocarlos/el-capitan/commit/5aad384eb8c964b3ce0ee1cbd6f8afbfb7a94444))
* **crew:** one command ships a task (hardening phase 2) ([233a1c2](https://github.com/crespocarlos/el-capitan/commit/233a1c2163103e17f0582648d41a8aa1c9d4b200))
* **crew:** read-only agents get an install-rendered MCP allowlist; merge main ([2402473](https://github.com/crespocarlos/el-capitan/commit/240247378d4ae3720ec0c67d8be655f36dabea5f))
* **crew:** read-only agents render their docs and code-search MCP servers; stale copies refresh at session start ([c6a4fbf](https://github.com/crespocarlos/el-capitan/commit/c6a4fbfc2041db6f066fa66bd6d1e4b9b4ea767d))
* **crew:** record every PR on its task, capture reviewer replies, record token usage ([f494e16](https://github.com/crespocarlos/el-capitan/commit/f494e165092a4e77755be7ce50e3052e50a4b5ee))
* **crew:** record every PR on its task, capture reviewer replies, record token usage ([130353e](https://github.com/crespocarlos/el-capitan/commit/130353e79605dc486633c23eae0ffa830412391c))
* **crew:** uninstall, doctor, gc, ls filters and report ([a160334](https://github.com/crespocarlos/el-capitan/commit/a1603340808ddb11112919832efee65b627d7416))
* **crew:** uninstall, doctor, gc, ls filters and report ([7fa0299](https://github.com/crespocarlos/el-capitan/commit/7fa029936a8bdf5c5cb3d61c877e3dc28fe31991))
* **eval:** seeded-defect reviewer eval and lens questions (hardening phase 3, part 1) ([6ced387](https://github.com/crespocarlos/el-capitan/commit/6ced38759f5c9f8a47a39fe67d692807a701b3a7))
* **eval:** seeded-defect reviewer eval and lens questions (hardening phase 3, part 1) ([104e2aa](https://github.com/crespocarlos/el-capitan/commit/104e2aa52b32b203904f89dc77388f07ce2e3a37))
* harness adapters, one crew-hook entry, Cursor local plugin (Phase 4) ([f3951a6](https://github.com/crespocarlos/el-capitan/commit/f3951a605382f7e58b85abb308559cf28d4ffc93))
* harness adapters, one crew-hook entry, Cursor local plugin (Phase 4) ([20204e1](https://github.com/crespocarlos/el-capitan/commit/20204e1d987261667849e8f2d4673042c2a5f314))
* harness adapters, one crew-hook entry, Cursor local plugin (Phase 4) ([0c82958](https://github.com/crespocarlos/el-capitan/commit/0c82958aa041ed184620137e76429e44a97c20ff))
* harness adapters, one crew-hook entry, Cursor local plugin (Phase 4) ([976efa3](https://github.com/crespocarlos/el-capitan/commit/976efa3f4a751a487d6a87363e76bcc31dec4479))
* harness adapters, one crew-hook entry, Cursor local plugin (Phase 4) ([e756dcb](https://github.com/crespocarlos/el-capitan/commit/e756dcbac558909ff664ef5a4581bc52c4bc6eed))
* **review:** personas rewritten as attacks, architecture as a principal engineer (hardening phase 3, part 2) ([335afae](https://github.com/crespocarlos/el-capitan/commit/335afae3118a52dbf9af8aa7c058cebc4fc28de7))
* **review:** personas rewritten as attacks, architecture as a principal engineer (hardening phase 3, part 2) ([f01a52b](https://github.com/crespocarlos/el-capitan/commit/f01a52b7fc562a9e1439877c43ead32c748989a3))
* **tools:** one agent surface over typed core functions; shfmt from uv (Phase 5a) ([d3f7c1e](https://github.com/crespocarlos/el-capitan/commit/d3f7c1e12e35fca14799574b2b46182514362fa5))
* **tools:** one agent surface over typed core functions; shfmt from uv (Phase 5a) ([0b87a7f](https://github.com/crespocarlos/el-capitan/commit/0b87a7fc053d5000788f810ae1e79ca756d5bdb3))
* **tools:** one agent surface over typed core functions; shfmt from uv (Phase 5a) ([fbb0ae5](https://github.com/crespocarlos/el-capitan/commit/fbb0ae53ec32685fd0cf0586d993f52905326298))
* **tui:** change a task's status with s, through crew-task.py after a confirm ([1962080](https://github.com/crespocarlos/el-capitan/commit/19620805080333e448ec3016f51390088a3d758b))
* **tui:** change a task's status with s, through crew-task.py after a confirm ([13a9d6b](https://github.com/crespocarlos/el-capitan/commit/13a9d6b8ebf98998beeb3255f25d7d37af49384f))
* **tui:** close any stale task as done ([958491d](https://github.com/crespocarlos/el-capitan/commit/958491d3be5578b8bb5c1869df7909377b4e091b))
* **tui:** close any stale task as done ([229cff2](https://github.com/crespocarlos/el-capitan/commit/229cff22c4ab35f2b3e2683b2b8f7a61a2d60d3e))
* **tui:** Ongoing with phases, Tasks·PRs·Issues summary, Runs, automatic landed (Phase 7b) ([4215513](https://github.com/crespocarlos/el-capitan/commit/4215513e9d2d928790e15b87aaf260bd2b134b62))
* **tui:** Ongoing with phases, Tasks·PRs·Issues summary, Runs, automatic landed (Phase 7b) ([6bf201a](https://github.com/crespocarlos/el-capitan/commit/6bf201af9c38f6c1e1b455d3ff7a100ab858ce47))
* **tui:** read-only Textual dashboard over the crew ls and report data ([88bae2e](https://github.com/crespocarlos/el-capitan/commit/88bae2e08e6fad1ee4a0d954857ab196342fd947))
* **tui:** read-only Textual dashboard over the crew ls and report data ([bbffa64](https://github.com/crespocarlos/el-capitan/commit/bbffa64a25b371f31368440230caa7a961f65f92))
* **tui:** tokens per task, the total, and what running agents are using ([54fc98e](https://github.com/crespocarlos/el-capitan/commit/54fc98e797215da9c972aaf5b30ea278d8f744be))
* **tui:** tokens per task, the total, and what running agents are using ([6508d11](https://github.com/crespocarlos/el-capitan/commit/6508d11792de2ea29f1a2cb348b958daaa71ec41))


### Fixed

* **capture:** find Cursor subagent transcripts by the parent conversation id ([76184fd](https://github.com/crespocarlos/el-capitan/commit/76184fd67f0570411d6eff94cc59e72226b7841e))
* **capture:** find Cursor subagent transcripts by the parent conversation id ([13ec7d5](https://github.com/crespocarlos/el-capitan/commit/13ec7d54a1268dd5bab67190122bd694e30e081f))
* **capture:** find the Cursor subagent transcript, save once, ask once for an unanswered reply ([6e81879](https://github.com/crespocarlos/el-capitan/commit/6e8187958c2da4c3acfeb6c5e7b890bf51870185))
* **capture:** find the Cursor subagent transcript, save once, ask once for an unanswered reply ([3c11b2f](https://github.com/crespocarlos/el-capitan/commit/3c11b2fedb988797f1746be1b436517999ee60e7))
* **ci:** drop an unused variable shellcheck reports in sync-skills ([62f31a0](https://github.com/crespocarlos/el-capitan/commit/62f31a0fb5d518af6dae7b1ed27a6fcc45d07820))
* **ci:** put uv's interpreter on PATH ([7daed22](https://github.com/crespocarlos/el-capitan/commit/7daed22a2f95d830417f3fe0064482f455efd1b4))
* **ci:** Python from uv on every leg; the lock-age check no longer depends on suite speed ([30c532e](https://github.com/crespocarlos/el-capitan/commit/30c532eefb30bab4deaf6c01daf7dd78cba014c7))
* **crew:** record-pr finds the task that already holds the PR, and runs the DONE gate from its checkout ([e2addb6](https://github.com/crespocarlos/el-capitan/commit/e2addb675741284baa25e0d1ef886954e4bfe7dd))
* **crew:** record-pr finds the task that already holds the PR, and runs the DONE gate from its checkout ([6d3dd14](https://github.com/crespocarlos/el-capitan/commit/6d3dd1427942688bdeeced991289611a3b5bb723))
* **crew:** status integrity, shell tripwire for task files, Cursor guards fail closed (hardening phase 5) ([60da2c0](https://github.com/crespocarlos/el-capitan/commit/60da2c04d41fbb9e2979d131d45d299cae2a2772))
* **crew:** status integrity, shell tripwire for task files, Cursor guards fail closed (hardening phase 5) ([dfa5e26](https://github.com/crespocarlos/el-capitan/commit/dfa5e26f41cf4f419ba5d9702aa50e2772e9ea17))
* **crew:** subagents need no hand-holding (hardening phase 1) ([0af6e4d](https://github.com/crespocarlos/el-capitan/commit/0af6e4daf3a4b02e28bc0e00609a00ef54ce2f50))
* **crew:** subagents need no hand-holding (hardening phase 1) ([39bd187](https://github.com/crespocarlos/el-capitan/commit/39bd187e01014e9695259de61eae732d733c0517))
* **guard:** edits go through the Edit tool, in every harness (T4.5) ([003b0a0](https://github.com/crespocarlos/el-capitan/commit/003b0a0cf4eaafb6f4b1c47993d08895a64699d7))
* **guard:** edits go through the Edit tool, in every harness (T4.5) ([8f91135](https://github.com/crespocarlos/el-capitan/commit/8f91135a5b3602121304e9417ebdae71c3641987))
* **guard:** spec edits without a prompt; the status rule holds Status moves in every harness ([2c5faf7](https://github.com/crespocarlos/el-capitan/commit/2c5faf71394cf2a3d566a9c459243fbfc5ecc7ba))
* **guard:** spec edits without a prompt; the status rule holds Status moves in every harness ([2b26624](https://github.com/crespocarlos/el-capitan/commit/2b266246edeb9d50247df4605177ac23613357da))
* **hooks:** each hook runs once per harness (Cursor speed phase A) ([9cd15eb](https://github.com/crespocarlos/el-capitan/commit/9cd15eb7dc05987fa6a715e3587682bde1bd405e))
* **hooks:** each hook runs once per harness (Cursor speed phase A) ([265c5f8](https://github.com/crespocarlos/el-capitan/commit/265c5f84d2825bd7f02085ff927f32d9b7c86ce8))
* **hooks:** quiet idle notifications; task files writable without prompts, Status guarded ([2112b9b](https://github.com/crespocarlos/el-capitan/commit/2112b9bc16b351dcd344d5957d57fc675650f5b9))
* **hooks:** quiet idle notifications; task files writable without prompts, Status guarded ([478206d](https://github.com/crespocarlos/el-capitan/commit/478206dcea03f1d95254254ad5024e4227491ebc))
* **memory:** a MEMORY.md heading and an entry naming its own repo are not review cases ([2b80c64](https://github.com/crespocarlos/el-capitan/commit/2b80c6467ea8a888fdd7379a35c15eca173d8e8b))
* **memory:** a MEMORY.md heading and an entry naming its own repo are not review cases ([80fc870](https://github.com/crespocarlos/el-capitan/commit/80fc870df25523f58d82a30cd6ce11bdbcf5de69))
* Phase 1 hotfixes from the 360 analysis ([1924d0a](https://github.com/crespocarlos/el-capitan/commit/1924d0a99e26085ebfe9ee841aa08dcb8be208da))
* Phase 1 hotfixes from the 360 analysis ([62fbdb6](https://github.com/crespocarlos/el-capitan/commit/62fbdb63de3f41755b7001a201d7afc41fd568f4))
* **review:** PR-mode normalize leaves out --repo and --head ([871dfc3](https://github.com/crespocarlos/el-capitan/commit/871dfc320f4187be0d89ccea83b86150e143978e))
* **review:** PR-mode normalize leaves out --repo and --head ([0651f3f](https://github.com/crespocarlos/el-capitan/commit/0651f3f71255cdd2e78ae580cc280b90249474a2))
* **test:** pick the exported unit by name, not the first .md in global/ ([93e0aa0](https://github.com/crespocarlos/el-capitan/commit/93e0aa095df88db9c10f2cfa176a4a9e0f60f995))
* **test:** pick the exported unit by name, not the first .md in global/ ([954fe90](https://github.com/crespocarlos/el-capitan/commit/954fe901395bca0e7903bd8d895e4141b6925b68))
* **test:** the deep-pipeline bound allows a loaded CI runner ([a4a7c91](https://github.com/crespocarlos/el-capitan/commit/a4a7c91f250e7ac0dfc3241ffd58e952c286bdc8))
* **tui:** keyed rows, workers, live tokens, one status dialog (Phase 7a) ([d92b2e0](https://github.com/crespocarlos/el-capitan/commit/d92b2e02e9fee226d34b4b4dd603203b56fd3463))
* **tui:** keyed rows, workers, live tokens, one status dialog (Phase 7a) ([919e869](https://github.com/crespocarlos/el-capitan/commit/919e8692571cdc7428a50146ed4705aff8b8aa0f))
* **tui:** show a move's refusal, and offer close as done for a task with a PR ([a497bb5](https://github.com/crespocarlos/el-capitan/commit/a497bb586ee2c29a77bd5e3922ac09a5fb0678c8))
* **tui:** show a move's refusal, and offer close as done for a task with a PR ([f4752f9](https://github.com/crespocarlos/el-capitan/commit/f4752f9787738e5ab8809e8133fc457f60c3126f))


### Changed

* **crew:** prompt headroom by moving text, module splits, growth rule (hardening phase 4) ([9bfe063](https://github.com/crespocarlos/el-capitan/commit/9bfe0635dc829122ea60e7b209673b829d0504c8))
* **crew:** prompt headroom by moving text, module splits, growth rule (hardening phase 4) ([fe52a65](https://github.com/crespocarlos/el-capitan/commit/fe52a65ab5fc488a03c73428ec4330e4e5111e82))
* hooks diet, one dispatcher, gitleaks, narrowed permissions (Phase 3) ([1313520](https://github.com/crespocarlos/el-capitan/commit/13135207e53a1fcfc7e7dfaae1f3775978f651a3))
* hooks diet, one dispatcher, gitleaks, narrowed permissions (Phase 3) ([50a5dbf](https://github.com/crespocarlos/el-capitan/commit/50a5dbfacaca9de913eea1e3db23bb5ae511fd9d))
* hooks diet, one dispatcher, gitleaks, narrowed permissions (Phase 3) ([250e9f1](https://github.com/crespocarlos/el-capitan/commit/250e9f14d4b0a058a812dd563bbc5ba4658bcbf9))
* setup in one call for every crew workflow, PR-head files in one GraphQL call (Cursor speed phase C) ([0811ba0](https://github.com/crespocarlos/el-capitan/commit/0811ba05913c4817e4306c7daee3dd8ce2ca307b))
* setup in one call for every crew workflow, PR-head files in one GraphQL call (Cursor speed phase C) ([b82f3b3](https://github.com/crespocarlos/el-capitan/commit/b82f3b3689c39f3e3b788075980ceabdc1375de2))
* smaller prompts for every agent (Cursor speed phase D) ([0a2a77b](https://github.com/crespocarlos/el-capitan/commit/0a2a77b6d96a21e2129768b0cb424f33c601d00e))
* smaller prompts for every agent (Cursor speed phase D) ([1ad81ac](https://github.com/crespocarlos/el-capitan/commit/1ad81acd5d3131497313920063e2a9971820f5e9))

## 0.1.0 (2026-11-27)

The baseline: the first version release-please tracks. It includes persistent memory, hook
adapters for Cursor and Claude Code, the guard hooks, and `crew-lint`; earlier history is in
`git log`.

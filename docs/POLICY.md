# Riot policy, monetization and the Mac platform

Checked 2026-11-17 against Riot's developer portal ([general policies](https://developer.riotgames.com/policies/general), last updated 2025-05-29; [TFT docs](https://developer.riotgames.com/docs/tft)). This is a reading of Riot's published rules, not legal advice.

## Two rulebooks

1. **Developer policy** binds products registered with Riot: anything shipped to other people or using a production API key. Breaking it costs the key or the product's approval.
2. **Player rules** (Terms of Service plus Riot's third-party application guidance) bind you as a player. Using a tool that breaks game integrity risks account penalties up to permanent suspension, **whether or not the tool is published**. Riot publishes no list of approved apps and advises that "if you have any doubt about an app you should not use it" (as quoted by a secondary source).

Building a screen-reading tool breaks no rule by itself. What decides the risk is what the tool **shows you during a game**.

## What a TFT tool may show, by moment

| Moment | Allowed | Not allowed |
|---|---|---|
| Before the game | Anything static: comps, items, augment metadata, unlock conditions, a chosen plan | Win rates for Legends and Legend-based augments (anywhere, any time) |
| Loading screen | A static plan | Tracking opponents; any player's or lobby's most-played champ, trait or augment |
| During the game | "Game overlays that provide static data that is available prior to the game" | "suggestions based on the player's current game state"; "real-time data that would improve a player's performance immediately"; "information that was not available prior to the game"; scouting ("tracking the champions opponents have on their boards"); predicted next plays; "Apps that dictate player decisions" |
| After the game | "Pre-game best practices or post-game analysis are great spaces for this"; tools that improve a player over time | Identifying players the game deliberately hides |

Also prohibited everywhere: MMR/ELO calculators ("alternatives for official skill ranking systems"), betting or gambling, closely imitating Riot's games.

Consequence for this project: **live advice (buy/skip, roll/level now, slam this, take this augment, pivot) is prohibited during a game, for a private tool as much as a published one.** Everything the engine computes stays legal after the game.

## Monetization, if this is ever shipped

From Riot's general and TFT policies:

- **Register first.** "All products must be registered in, and audited by Riot Games through the Developer Portal." New features are audited too. Monetizing is allowed only for registered, approved products.
- **Free tier required.** It "may include advertising."
- **Charging requires transformative content.** Allowed: subscriptions, donations or crowdfunding, currencies that "cannot be exchanged back into fiat", tournament entry fees (70% to the prize pool, 20+ players). "Your monetization cannot gouge players or be unfair, as decided by Riot."
- **No ads in Riot properties:** in-game, loading screens, or the Riot Client. An overlay cannot carry ads.
- **Keys.** Personal keys cover "personal sites, school projects, and proof-of-concept work for a production key request". Showing a player their own stats needs a production key with Riot Sign-On (RSO). One production key per product.
- **Data sources.** "Products should use supported services from Riot Games for data ingestion." CommunityDragon is a community mirror of game files, not a Riot service: fine for development, but a shipped product needs Riot's API and Data Dragon, or Riot's agreement, for unlock data.
- **Branding.** Show Riot's "isn't endorsed by Riot Games" boilerplate where players can see it. Use Riot logos and trademarks only where "inevitable to serve the core value of the product". Don't imply endorsement.

Paid live-coaching tools exist (TFTSense sells buy/skip calls; MetaBot shows live win odds and a "Riot Approved" badge). Their features contradict the written TFT rules and their approval claims are unverified, so they are not a model to copy.

Overwolf, where most TFT overlays live, is Windows-only. Since 2026-11-01 it approves only apps using its own monetization, and Riot approval is still required on top. It is irrelevant on a Mac.

## The Mac

- **Native TFT on macOS** was dropped "temporarily" in patch 18.1 for the Unreal Engine move, came back on PBE in 18.2b ([Riot FAQ](https://support.riotgames.com/en-us/tft/client/tft-unreal-engine-migration-faq)), and evidently returned on live (Set 18 ranked games were played on this Mac). The standalone client that launched 2026-11-04 is described as a PC client; check which client the Mac uses after 18.6, since the screen layout depends on it.
- **No Overwolf on Mac**, so no MetaTFT, Mobalytics or Blitz overlays and no Overwolf game events. Screen capture is the only round-by-round data source. Mac TFT players have almost no tooling.
- **Anti-cheat.** Vanguard for Mac has been reported as coming; its current status is unverified. It doesn't change anything here: the rules above apply on every OS, and this project won't rely on what a platform fails to detect.
- **Capture** uses ScreenCaptureKit, Apple's supported API (older CoreGraphics window capture is deprecated). The process doing the capture needs Screen Recording permission. Capture works in physical pixels on Retina displays, so layout files key on the window's pixel size. OBS on Mac is fine for recording fixtures.

## What this means for the solver

| Piece | Decision | Why |
|---|---|---|
| Post-game review (engine over a recorded game, plus API-only report) | **Main product** | Explicitly encouraged; uses everything the engine computes |
| Pre-game planner that exports a **Team Planner code** | **Build** | Static and allowed; the game's own Team Planner then highlights planned units in the shop and tracks pinned unlocks, so nothing third-party is shown during the game |
| Static plan card on screen during a game | Optional | Allowed only if it never changes during the game |
| Recorder: captures your screen, shows nothing in game | **Build** | Riot's rules address what is shown, not passive recording; needed for review mode and for unlock and accumulator data |
| Live advice (shop, roll/level, slam, augment, pivot) | **Drop** | Prohibited during the game; account risk applies to private use |
| Opponent boards and lobby data | Review only | Scouting is prohibited during the game |
| Legend / Legend-augment win rates | Never | Prohibited everywhere |
| Shipping to others or charging | Later, optional | Needs registration, production key with RSO, free tier, Riot-supported data sources |

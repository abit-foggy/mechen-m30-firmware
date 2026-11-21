# Community ports for the M30 development firmware

## Library indexing

Open **Settings → Library indexing** and select **Manual** or **Automatic**. An empty or unrecognized preference selects Manual. After adding, removing, or renaming music, run **Settings → Update Playlist** to refresh the indexed Music views. The card's existing library stays in use until the next rebuild. The menu labels are English in every language group.

The player stores one four-byte mode word in its native settings store at offset `0x7e00`. The selector reads the value back after writing it. Automatic restores the stock decision for each trigger. The boot and USB hooks conditionally implement the community branches at `config.ap+0x1e0d` and `udisk.ap+0x1909`. Powered card insertion has a separate path. In the shared foreground UI bank, event `0xb0` produces playlist-update request `0x861c`. Manual suppresses that request in the main menu, browser, Music, Settings, configuration and playlist applications. The explicit Settings command retains its own launch path.

## Playback changes

The patch manifest records each guarded range, its expected input bytes, replacement bytes and donor release. Each range was compared with the accepted V1.292.00 payload. The project keeps its 24,000-track builder and SD theme loader. See the [manifest](../tools/community/playback.json) and [original release history](https://github.com/dev-zetta/mechen-m30-community-firmware/blob/e1b97fee5fea0c26f778f7fa0a1f9394572977fa/CHANGELOG.md).

| Donor | Behavior | Member |
|---|---|---|
| V1.101.11 | Gate end-of-track audio drain so the track tail can finish playing | mengine.ap |
| V1.101.11 | Honor Repeat Folder during CUE playback | music.ap |
| V1.200.00 | Seek backward within the final CUE track | music.ap |
| V1.200.00 | Reject favorite position zero before the counter wraps and traverses 65,536 records | music.ap, mainmenu.ap |
| V1.200.00 | Initialize the decoder write callback with a rejecting function | mengine.ap |
| V1.201.00 | Validate the coefficient set, seek, two reads and close before marking the set loaded. A failed load disables DAC output and permits a retry | mengine.ap |

## Research documents

The [integration history](community/community-integration.md) records the fork's accepted and reverted changes. The [indexing guards](community/findings-index-guards.md) and [music library node layout](community/findings-music-lib-node-format.md) support library work. Other references cover [browser names and sorting](community/findings-browser-names-sort.md), [artwork startup](community/findings-artwork-start.md), [QEMU coverage](community/qemu-coverage.md) and the fork's [research index](community/knowledge-index.md). Linked upstream test results describe that project's builds.

## Device checks for this build

| Check | Expected result |
|---|---|
| Manual, add a track over USB and eject | Return to the UI without a full scan. The new track appears in Music after Update Playlist. |
| Manual, cold boot with the card present | No boot-triggered full scan. The setting still reads Manual. |
| Manual, remove and reinsert an idle card with the player powered | No insertion-triggered full scan. Opening the card and running Update Playlist still work. |
| Automatic, restart and repeat all three checks | The selector persists. The player follows its stock triggers, including powered insertion. |
| Play a track with a known audible fade into the next track | Listen for the complete fade and a clean transition. |
| Play a multi-track CUE with Repeat Folder and seek back inside its final track | Playback stays within the intended repeat scope and seeks to the requested position. |

The QEMU policy test runs extracted boot, USB and foreground card-event instructions with a simulated settings store. The actual card controller, DAC, and persistence across a real power cycle require testing on the player.

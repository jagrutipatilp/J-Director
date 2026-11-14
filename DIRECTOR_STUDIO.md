# J Director — implementation and operating guide

The browser workspace lives in `director_studio/` alongside the original KupkaProd application. It does not replace the existing desktop GUI, web app, model downloads, or configuration.

## Launch

Run `Open J Director.cmd`, then open http://127.0.0.1:8790/.

Install any missing web dependencies with `.venv\Scripts\python.exe -m pip install -r requirements-director.txt`.

Start Ollama/ComfyUI with the repository's existing `start-services.ps1` when needed. The director app reports actual service availability. Its launcher does not silently install models or stop other GPU jobs.

All projects have one fixed root: `C:\src\J-Director\projects`. The API does not accept a project root from a browser.

## Architecture and state

- `director_studio/app.py`: FastAPI HTTP API, media responses, reference uploads and live WebSocket snapshots.
- `director_studio/store.py`: atomic project JSON, Markdown context, lifecycle actions and bounded undo/redo snapshots.
- `director_studio/jobs.py`: persistent serialized background queue for breakdown, enhancement and generation.
- `director_studio/engines.py`: Ollama planning/enhancement, the existing local Qwen/H3 runtime adapter, and the configurable ComfyUI API adapter.
- `director_studio/static/`: responsive browser UI. Phones and computers use the same served application.

Each project has `project.json`, an immutable `story.md`, editable `story-working.md`, `outline/arcs.md`, nested episode/scene/sequence context files, keyframe and clip prompt folders, a series-level `characters` and `backgrounds` library, `.engine` working files, and `exports`. Folder suffixes use stable identifiers to avoid collisions. The original pasted story is never replaced by enhancement.

The normalized node schema is:

```
id, kind, title, parent, order, text, prompt, negative,
status, locked, redo_seen, references[], depends_on,
output, progress, dialogue, sound, seconds
```

Kinds: arc, episode, scene, sequence, keyframe, clip, character, location, reference. Reference nodes carry a category: Outfits, Expressions, Accessories, Dialogs, Hairstyles, Poses, or Angles.

Statuses: idle -> queued -> running -> succeeded/failed. Saving a successful media result sets saved/locked. Redo sets redo/yellow and exposes the negative prompt. Its tracked image/video is removed; a dependent clip is reset and its tracked output removed too. Redo never deletes arbitrary paths. Undo does not pretend to restore media that has already been deleted: affected boxes become editable again.

Every video clip points at its preceding keyframe with `depends_on`; reference selections point at shared reference nodes, not copies defined by each episode. Reference uploads become real JPG assets that can guide generation. Actual character similarity and lip sync remain model-dependent.

## API route structure

- `GET/POST /api/projects`: list/create projects, preserving the original story.
- `GET/PATCH /api/projects/{id}`: load a project, update working story or draft/final quality.
- `POST /api/projects/{id}/nodes`: add a character, location or reference.
- `PATCH /api/projects/{id}/nodes/{node}`: edit allowed fields; locked or running boxes reject edits.
- `POST /api/projects/{id}/action`: `breakdown`, `enhance`, `enhanceAllOutline`, `run`, `runAll`, `enhanceAll`, `save`, `saveAll`, `redo`, `undo`, `redo_history`, `move`, `refresh`, `assets`.
- `POST /api/projects/{id}/references/{node}/upload`: upload an image to an editable reference box.
- `GET /api/projects/{id}/asset?path=...`: serve image/video media constrained to that project.
- `POST /api/projects/{id}/export`: merge saved episode clips to an MP4.
- `GET /api/health`: inspect Ollama/ComfyUI and configured runtime files.
- `WS /ws/{id}`: live project revisions, progress and timestamped logs; reconnects automatically.
- `GET /docs`: interactive OpenAPI route documentation.

The single worker keeps GPU tasks serialized. Queued work is persistent. If the server exits during a task, that task is marked interrupted on restart; already completed results remain. It does not claim interrupted subprocesses are still producing a valid take.

## Review flow

1. Create a project and paste the full story.
2. Enhance the working text if needed. Keep edits, then generate arcs.
3. Open an arc, review/reorder/edit its episodes. Repeat for scenes, sequences, then keyframe/clip pairs.
4. The first completed sequence makes its episode pipeline available. Other episodes can be planned later.
5. Character/location reference prompts are extracted into the shared library. Initial reference generation queues after keyframes are planned. Review, replace or upload references and attach the desired ones to each frame.
6. Use Run on one box, or Run All on the current episode. Save to approve/lock results. Redo invalidates stale paired clips.
7. Save all clip results before exporting an episode.

The command bar supports `/run`, `/runAll`, `/enhanceAll`, `/updateAll` (refresh from disk), `/saveAll`. Plain text goes to Ollama as an editing instruction for the selected box. It cannot execute arbitrary shell commands.

## Generation adapters

J Director now uses native local ComfyUI workflows for Qwen-Image 2512 text-to-image, Qwen-Image-Edit 2511 reference edits, and MiniMax H3 image-to-video with audio. The WanGP application adapter is removed. Existing shared H3 weights and completed outputs are preserved; engine-specific Qwen quanto files were retired with the user's approval.

Workflow manifests are supplied as `qwen.json`, `qwen_text.json` and `h3.json`. `settings.json` points to the existing ComfyUI installation. Generation starts ComfyUI locally when it is offline. Model presence is validated before submission. Omnichar exports selected character references to versioned `.char` files; this does not mean a character LoRA has been trained.

Manifest contract:

```json
{
  "graph": {"NODE_ID": {"class_type": "A_REAL_INSTALLED_NODE", "inputs": {}}},
  "bindings": {
    "prompt": [["PROMPT_NODE", "text"]],
    "negative": [["NEGATIVE_NODE", "text"]],
    "seed": [["SAMPLER_NODE", "seed"]],
    "steps": [["SAMPLER_NODE", "steps"]],
    "reference1": [["LOAD_IMAGE_NODE", "image"]]
  },
  "output_node": "SAVE_NODE"
}
```

Binding keys also include `reference2`, `reference3`, `seconds`, `frames`, `dialogue`, `sound`. Node identifiers come from the supplied native graphs and are checked against the running ComfyUI schema. The adapter uploads reference/keyframe images, submits `/prompt`, reads actual sampler progress through `/ws`, polls `/history/{prompt_id}`, and retrieves media through `/view`. It rejects obvious cloud/API node types to avoid accidental hosted generation.

## Tailscale access

The app initially binds **127.0.0.1:8790**. Keep Ollama, ComfyUI and this server private. Tailscale is connected on this PC. The director workspace is served privately at `https://loki.tailce5743.ts.net:8443/`; an HTTPS request returned 200 during verification. The previous port 443 Serve route was preserved. This is not a public Funnel route. Remote requests are restricted to the owner identity injected by Tailscale Serve; shared-device users with different identities are rejected.

Once this home PC is signed into your tailnet, use Tailscale Serve to proxy the local app, for example:

```
tailscale serve --bg --https=8443 http://127.0.0.1:8790
```

Use the private HTTPS address shown by `tailscale serve status` from your work PC and phones, signed into the same tailnet. Do **not** use Funnel or add public router port forwarding. The app permits same-origin writes and supports `.ts.net` hosts. No public deployment, ACL changes, account creation, or Tailscale login was performed. Only the dedicated private 8443 proxy route was added. The owner setting is stored in ignored `director_studio/.remote-owner.json`.

## Validation and current limits

`python -m unittest discover -s tests -p test_director_studio.py -v` checks temporary projects, exact story preservation, path confinement, Save locking, Redo invalidation, undo behavior, background generation and origin checks.

This is an implementation prototype. It does not include a trained consistency LoRA, Omnichar integration, automatic lip-sync scoring, feedback-driven model training, a timeline editor, or automatic approved-episode style extraction. The installed small Ollama model's outline quality needs human review. Voice/mouth accuracy and identity continuity are not guaranteed by having a reference library. The private HTTPS route was tested from this PC; access from your work PC and both phones still needs a device-side check while signed into your own tailnet identity. Hardware claims in the supplied brief are not treated as measured requirements for this particular machine.


## Observed smoke tests

The browser created an example project, local Ollama generated real arcs and a reference inventory, and the new Qwen adapter rendered a draft image in the example pipeline. WebSocket state messages and actual sampler progress were observed. Native ComfyUI H3 produced a verified five-frame H.264/AAC compatibility MP4 during migration. This small test verifies the pipeline, not full-scene quality. A separate normal-setting Qwen reference edit is used for visual comparison.

The example projects are explicitly labelled as examples. One is a real Ollama breakdown; Pipeline Tour has a handwritten demonstration outline and a real Qwen image. No generated clips are simulated.
## J Director ribbon and shared library

The application is now branded **J Director**. Project names appear in the title bar. The top ribbon separates History, File, Generate, Refine and Production commands, with dedicated Characters and Locations tabs.

Shared user-created assets live in `library/`, outside every story project. Character/location names are entered by the user; story breakdown no longer invents library entries. References can be uploaded or generated in an active project and explicitly published back to the global library. Every published image gets a new versioned JPG. Attaching an asset to a project pins that version; updating the library does not replace images used by earlier stories.

The episode strip displays scenes horizontally with arrows between scene panels. Selecting a keyframe or clip shows its media in a black central preview, with prompt controls in the right inspector. The Output log is docked to the bottom and can be collapsed.


### Pause, Resume and Stop
The small Generate ribbon includes Pause and Stop for work in the open project. Pause finishes the current image, video, or outline operation, then waits before continuing. The same button becomes Resume. Stop finishes the current operation and cancels the remaining queued work for that project; completed outputs are retained for review and Save. These controls do not freeze a model halfway through a render. Other projects are unaffected.


### Accuracy-first drama continuity
New projects default to Final quality. Draft remains an explicit preview option; there is no automatic final rerender. Characters, Locations and Props are shared versioned assets, attached as pinned project references. Shot reference suggestions match attached asset names and deduplicate by asset; review the shot checkboxes to choose the exact outfit/view. More than three keyframe references fail clearly rather than being silently truncated by Qwen.

Story planning stops at arcs and episodes. Subsequent planning receives the season's arc/episode outline and attached asset descriptions. Existing plans are preserved.

After every final video clip in an episode is reviewed, saved and locked, select the episode and click Approve episode. This explicitly snapshots actual video frames at 0.5 seconds into a versioned library/continuity catalog, outside episode output files. Draft, unsaved and legacy clips without final-render metadata cannot be approved. No current episode is automatically approved.

Later keyframes can reuse the most recent earlier approved episode frame whose full reference variant/version signature matches exactly. Canonical references stay first. The extra rendered frame is used only when Qwen's three-image limit has space; a two-character-plus-location shot keeps all three canonical inputs. No references flow backwards in story chronology or across mismatched assets. Each render writes reference-manifest.json with exact reference files and approval lineage. This is reference conditioning, not training or guaranteed identity preservation. Human review is still required; no 100-episode visual benchmark has been run.

Final resolution now explicitly uses 832×1472 for Qwen and 768×1344 for H3; Draft retains 576×1024 and 480×832 respectively. Existing files are not upgraded automatically. Higher resolution increases memory requirements and is not a guarantee of photorealism or likeness.


### Scene → sequence → keyframe selections
Scene: choose an optional location/background reference and camera view in the main panel. Sequence: tick characters, choose each identity/hairstyle reference and outfit, tick accessory references, and optionally add props. Add assets from the shared library without leaving the setup panel. Keyframe: tick which sequence characters appear, choose their Expressions references, and optionally disable background inheritance. No selection is mandatory; prompts and additional image references remain available.

Qwen receives background + selected cast identity/outfit/accessories/expression + props + additional shot references. Related source images are grouped into up to three labeled image boards because the active Qwen adapter accepts three inputs. Every selected source is included and logged; boards can reduce fine detail when many images share a model input, so use only relevant references. Boards are conditioning inputs, not guaranteed identity locks. The render manifest and node render_references preserve the original source IDs and versions. Existing saved images are not silently regenerated when parent selections change. Use Redo and generate a new take after changing direction.

Story planning is one click through all arcs and episodes, and stops there. Open an episode, write the detailed treatment/dialogue, Keep edits, then generate scenes; edit each scene and generate sequences; set cast/wardrobe and break each sequence into keyframes and paired clips. Run All is optional and explicit.


### Direct episode planning and writer startup
New story plans now create episodes directly under the story, with no mandatory arc layer. Existing arc-based projects remain readable and are not migrated or deleted. Episode cards can be edited and reordered with ↑ / ↓; pending card edits are committed before a move. Open an episode to write its detailed treatment, then generate scenes at your own pace. The installed local Ollama writer starts automatically on demand using J Director/local-models/ollama, CPU mode, cloud disabled. Remote/custom writer addresses are never replaced by a local service.


### Story requirements versus catalogue
Characters and backgrounds in the story tree belong to that project. Outline breakdown plans episodes and discovers named character/background requirements; their folders, descriptions, blank reference slots, requirements.md and used-in.md are created without image generation. Breakdown of edited episodes/scenes/frames also refreshes requirement documents. Existing developed breakdowns are retained on ordinary Breakdown; explicit Redo is required to replace undeveloped scenes. Refresh story requirements can update just the inventory. Saving edits updates the current Markdown and links to known named assets; new unnamed entities are discovered on the next Breakdown/Refresh/Run All.

The catalogue is independent. Each story asset offers Generate from prompt, Pick from system, and Pick from catalogue. Catalogue selection copies a specific version into the project; no generated story image is published back automatically. New image references become that asset's primary reference. Images only generate on explicit Generate or Run All for work that needs a missing reference.

Scene/episode/keyframe/video panels show only story character and background bindings. Run All resolves the selected scope's linked references, including inherited requirements; explicit empty choices are respected. Used in is calculated in codes such as ep1s2k2kv3 (episode 1, scene 2, keyframe 2, third video variant). Existing props, wardrobe/expression data and catalogue assets are retained on disk for compatibility, but no longer dominate the story selection panels.

When upgrading during an active render, the new backend requires a later restart. The UI detects the old server and blocks new reference-source actions with a clear message rather than sending unsupported requests. Never restart automatically during active generation.


### Manage projects and two-episode tests
Manage projects lists active projects with Open/Delete controls and a Deleted projects section with Restore. Delete first exports project-owned characters, backgrounds and props, all reference images, prompt-only variants and requirement documents into independent catalogue entries. Matching names never overwrite unrelated catalogue identities. Existing JPEG files are copied byte-for-byte. Export failures or missing referenced images leave the project active; active queued/running work blocks deletion. Repeating deletion after an unchanged restore reuses the preserved snapshots.

Deletion is recoverable: the project folder remains on disk with a .deleted-project.json marker and leaves the active picker. Story and rendered outputs remain restorable. It is not a disk-cleanup command. Restoring the project keeps its catalogue copies. Other open browsers are notified that a project was deleted.

New Project includes Episode count (1–100), initially 2 for the requested short-story test. Leave it blank to infer the length. The explicit count is enforced in the local writer's output schema. No example story or project is created automatically; the user supplies the new outline.


### Prewritten episode/scene/keyframe scripts
Numbered EPISODE headings with titles are imported directly; numbered Scene headings keep the scene level even when each scene already contains keyframes. Keyframe prompt and Video prompt (1.1) labels are parsed separately, preserving authored dialogue in the video prompt. A fully written script creates all supplied metadata and Markdown without asking the writer to rewrite it. Import written episodes, scenes & keyframes can replace an unrendered outline with a backed-up, undoable import; rendered/active work blocks replacement. Image/video generation remains explicit. Declared Format: 2 Episodes wins over incidental phrases such as not a 150-episode serial.


### Required character references and episode review
User-attached references are optional. Run All discovers story assets, asks Ollama to write missing master prompts, and generates the required references before the shots. Existing user images and custom prompts are preserved. Voice-only/offscreen characters do not require portraits, and characters from other episodes are not prepared.

Select the episode, review/edit its scenes and frames, then Run All. After every clip is ready, Save & assemble episode explicitly saves the results, concatenates clips in story-tree order and opens the complete MP4 in the main viewer. Assembly uses the installed working FFmpeg runtime, keeps the first clip's native dimensions, avoids enlarging smaller sources and adds silence for clips without audio. The user can then select Episode 2 and repeat.


### Background view library and automatic reference preparation
Each background has a canonical master and metadata for left, right, high, low, close/detail and reverse views. All derived images reference the same master. Ollama selects one supplied view ID per keyframe/background pair using shot text, labels and descriptions; it does not inspect image pixels. Invalid/unknown/incomplete selections fail clearly. The chosen ID and reason appear in the shot panel/log and render manifest. Explicit user-selected background images take priority. Decisions and master prompts are reused unless their inputs change.

Only the angles needed by the selected shots are generated, after their master image. Unused angle entries remain named prompts until needed. This builds a reusable multi-view image set over the story without forcing six extra renders for every new room. Derived views are regenerated as new reference entries when their master changes; old images are retained. Multi-angle generation is reference-conditioned and still needs visual review for unseen geometry.


## Character Forge

Open a story character and choose Create multi-angle sheet. The local-only bridge runs the upstream Character Forge service with the installed Qwen workflow, creating front/side portraits and front/side/rear body views plus a combined sheet. The original master is retained. Generated references require review; Save approves a view. Pause and Stop take effect between generated views. The downloaded source and AGPL license are in tools/CharacterForge.

The bridge imports and workflow have been validated, and master-preservation/queue behavior have automated tests. A complete five-view sheet is a separate multi-render job; installation checks are not a completed character sheet.

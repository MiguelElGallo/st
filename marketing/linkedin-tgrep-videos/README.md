# LinkedIn videos for tgrep

This folder contains two editable, LinkedIn-ready product videos:

- `output/tgrep-vscode-linkedin-1080x1350.mp4`
- `output/tgrep-codex-linkedin-1080x1350.mp4`

Each video is 24 seconds, 1080×1350, H.264 with AAC English voiceover. Matching
PNG thumbnails and SRT caption files are in `output/`. The key messages are also
burned into the video for muted-feed viewing.

The animations use illustrative UI while preserving the real install commands,
repository URL, plugin/tool names, and example prompt. See `storyboard.md` for
the timing, voiceover copy, and claim boundaries.

## Render again

Requires Node.js 22.12 or newer and Google Chrome or Chromium. On macOS, the
render script uses the built-in Samantha voice through `say`; elsewhere it
produces a sound-off video. The approved `ffmpeg-static` install script downloads
the platform-specific encoder during `npm ci` and is recorded in `package.json`.

```bash
cd marketing/linkedin-tgrep-videos
npm ci
npm run render
```

Temporary frames are stored under `.render/` and removed after encoding.

The lockfile pins the Node.js dependency graph. Rendering still uses the locally
installed Chrome or Chromium executable, and macOS voice output depends on the
system Samantha voice, so regenerated videos are not expected to be
bit-for-bit identical across machines.

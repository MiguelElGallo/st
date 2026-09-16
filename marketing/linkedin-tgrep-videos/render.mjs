import { mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import puppeteer from "puppeteer-core";
import ffmpegPath from "ffmpeg-static";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const renderDirectory = path.join(scriptDirectory, ".render");
const outputDirectory = path.join(scriptDirectory, "output");
const chromeCandidates = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
].filter(Boolean);
const chromePath = chromeCandidates.find((candidate) => existsSync(candidate));

if (!chromePath) {
  throw new Error("Google Chrome or Chromium was not found. Set CHROME_PATH.");
}
if (!ffmpegPath) {
  throw new Error("The ffmpeg-static package did not provide a binary.");
}

const fps = 25;
const durationSeconds = 24;
const totalFrames = fps * durationSeconds;
const videos = [
  {
    id: "vscode",
    filename: "tgrep-vscode-linkedin-1080x1350.mp4",
    thumbnail: "tgrep-vscode-linkedin-thumbnail.png",
    voice:
      "Install tgrep in V S Code in a few simple steps. Open the Command Palette, choose Chat: Install Plugin From Source, and paste the repository URL. Start a new chat, build the index once, then search with focused results. That can mean less waiting, fewer tokens spent on broad context, and more precise repository exploration.",
  },
  {
    id: "codex",
    filename: "tgrep-codex-linkedin-1080x1350.mp4",
    thumbnail: "tgrep-codex-linkedin-thumbnail.png",
    voice:
      "Add tgrep to Codex with two commands. Register the marketplace, install the plugin, then start a new task in your repository. Ask Codex to build the index and find the symbol you need. Focused, indexed results can mean less waiting, fewer tokens spent on broad context, and more precise answers.",
  },
];

function run(command, args) {
  return new Promise((resolve, reject) => {
    const processHandle = spawn(command, args, { stdio: "inherit" });
    processHandle.once("error", reject);
    processHandle.once("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} exited with code ${code}`));
    });
  });
}

await mkdir(renderDirectory, { recursive: true });
await mkdir(outputDirectory, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--hide-scrollbars", "--disable-gpu"],
});

try {
  for (const video of videos) {
    const frameDirectory = path.join(renderDirectory, `${video.id}-frames`);
    const audioPath = path.join(renderDirectory, `${video.id}-voice.aiff`);
    const videoPath = path.join(outputDirectory, video.filename);
    const thumbnailPath = path.join(outputDirectory, video.thumbnail);
    await mkdir(frameDirectory, { recursive: true });
    const finalFramePath = path.join(
      frameDirectory,
      `frame-${String(totalFrames - 1).padStart(4, "0")}.png`,
    );

    if (!existsSync(finalFramePath)) {
      await rm(frameDirectory, { recursive: true, force: true });
      await mkdir(frameDirectory, { recursive: true });
      const page = await browser.newPage();
      await page.setViewport({ width: 1080, height: 1350, deviceScaleFactor: 1 });
      const url = new URL(pathToFileURL(path.join(scriptDirectory, "video.html")));
      url.searchParams.set("video", video.id);
      await page.goto(url.href, { waitUntil: "networkidle0" });
      await page.evaluate(() => document.fonts.ready);

      for (let frame = 0; frame < totalFrames; frame += 1) {
        const milliseconds = (frame / fps) * 1000;
        await page.evaluate(
          (time) =>
            new Promise((resolve) => {
              window.renderVideoAt(time);
              requestAnimationFrame(() => requestAnimationFrame(resolve));
            }),
          milliseconds,
        );
        await page.screenshot({
          path: path.join(frameDirectory, `frame-${String(frame).padStart(4, "0")}.png`),
          type: "png",
        });
        if (frame % 100 === 0) {
          process.stdout.write(`${video.id}: rendered ${frame}/${totalFrames} frames\n`);
        }
      }

      await page.evaluate(() => window.renderVideoAt(22_600));
      await page.screenshot({ path: thumbnailPath, type: "png" });
      await page.close();
    } else {
      process.stdout.write(`${video.id}: reusing ${totalFrames} completed frames\n`);
    }

    const hasSay = existsSync("/usr/bin/say");
    if (hasSay) {
      await run("/usr/bin/say", [
        "-v",
        "Samantha",
        "-r",
        "172",
        "-o",
        audioPath,
        video.voice,
      ]);
    }

    const ffmpegArgs = [
      "-y",
      "-framerate",
      String(fps),
      "-i",
      path.join(frameDirectory, "frame-%04d.png"),
    ];
    if (hasSay) {
      ffmpegArgs.push("-i", audioPath);
    }
    ffmpegArgs.push(
      "-c:v",
      "libx264",
      "-preset",
      "slow",
      "-crf",
      "18",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
    );
    if (hasSay) {
      ffmpegArgs.push(
        "-af",
        `apad=pad_dur=${durationSeconds},afade=t=out:st=23:d=1`,
        "-c:a",
        "aac",
        "-b:a",
        "160k",
      );
    } else {
      ffmpegArgs.push("-an");
    }
    ffmpegArgs.push("-t", String(durationSeconds), videoPath);
    await run(ffmpegPath, ffmpegArgs);
    await rm(frameDirectory, { recursive: true, force: true });
    process.stdout.write(`Created ${videoPath}\nCreated ${thumbnailPath}\n`);
  }
} finally {
  await browser.close();
}

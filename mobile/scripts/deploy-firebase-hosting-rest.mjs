import { createHash, createSign } from "node:crypto";
import { existsSync } from "node:fs";
import { appendFile, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { gzipSync } from "node:zlib";

const API_BASE = "https://firebasehosting.googleapis.com/v1beta1";
const TOKEN_URL = "https://oauth2.googleapis.com/token";
const FIREBASE_HOSTING_SCOPE = "https://www.googleapis.com/auth/firebase.hosting";
const MAX_ATTEMPTS = 4;

let accessToken = process.env.FIREBASE_ACCESS_TOKEN;
const project = process.env.FIREBASE_PROJECT;
const site = process.env.FIREBASE_SITE ?? project;
const channelId = process.env.FIREBASE_CHANNEL_ID ?? "live";
const channelTtl = process.env.FIREBASE_CHANNEL_TTL ?? "604800s";

if (!project) {
  throw new Error("FIREBASE_PROJECT is required.");
}

if (!site) {
  throw new Error("FIREBASE_SITE is required.");
}

if (!/^[a-zA-Z0-9-]+$/.test(channelId)) {
  throw new Error("FIREBASE_CHANNEL_ID can only contain letters, numbers, and hyphens.");
}

const cwd = process.cwd();

class RequestError extends Error {
  constructor(message, retriable = true) {
    super(message);
    this.name = "RequestError";
    this.retriable = retriable;
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function base64UrlEncode(value) {
  const buffer = Buffer.isBuffer(value) ? value : Buffer.from(value);

  return buffer
    .toString("base64")
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function requireAccessToken() {
  if (!accessToken) {
    throw new Error("Firebase access token has not been initialized.");
  }

  return accessToken;
}

function isRetriableStatus(status) {
  return status === 408 || status === 409 || status === 429 || status >= 500;
}

function errorMessageFromBody(body) {
  if (body && typeof body === "object" && "error" in body) {
    return body.error?.message ?? JSON.stringify(body.error);
  }

  if (typeof body === "string" && body.length > 0) {
    return body;
  }

  return "No response body";
}

async function parseResponse(response) {
  const text = await response.text();

  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function requestJson(url, options = {}) {
  const { allowCurrentActive = false, body, headers, ...fetchOptions } = options;
  let lastError;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(url, {
        ...fetchOptions,
        body: body === undefined ? undefined : JSON.stringify(body),
        headers: {
          Authorization: `Bearer ${requireAccessToken()}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...headers
        }
      });

      const responseBody = await parseResponse(response);
      const responseMessage = errorMessageFromBody(responseBody);

      if (response.ok) {
        return responseBody;
      }

      if (
        allowCurrentActive &&
        response.status === 400 &&
        responseMessage.includes("is the current active version")
      ) {
        console.log("Firebase Hosting release is already active; treating retry as success.");
        return { alreadyActive: true };
      }

      lastError = new RequestError(
        `HTTP ${response.status} from ${url}: ${responseMessage}`,
        isRetriableStatus(response.status)
      );

      if (!lastError.retriable || attempt === MAX_ATTEMPTS) {
        throw lastError;
      }
    } catch (error) {
      lastError = error;

      if (error instanceof RequestError && !error.retriable) {
        throw error;
      }

      if (attempt === MAX_ATTEMPTS) {
        throw lastError;
      }
    }

    await delay(1000 * attempt);
  }

  throw lastError;
}

async function requestMultipart(url, createBody) {
  let lastError;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(url, {
        method: "POST",
        body: createBody(),
        headers: {
          Authorization: `Bearer ${requireAccessToken()}`
        }
      });

      const responseBody = await parseResponse(response);

      if (response.ok) {
        return responseBody;
      }

      lastError = new RequestError(
        `HTTP ${response.status} from ${url}: ${errorMessageFromBody(responseBody)}`,
        isRetriableStatus(response.status)
      );

      if (!lastError.retriable || attempt === MAX_ATTEMPTS) {
        throw lastError;
      }
    } catch (error) {
      lastError = error;

      if (error instanceof RequestError && !error.retriable) {
        throw error;
      }

      if (attempt === MAX_ATTEMPTS) {
        throw lastError;
      }
    }

    await delay(1000 * attempt);
  }

  throw lastError;
}

async function requestAccessToken(assertion) {
  const body = new URLSearchParams({
    grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    assertion
  });
  let lastError;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
    try {
      const response = await fetch(TOKEN_URL, {
        method: "POST",
        body,
        headers: {
          "Content-Type": "application/x-www-form-urlencoded"
        }
      });
      const responseBody = await parseResponse(response);

      if (response.ok && responseBody.access_token) {
        return responseBody.access_token;
      }

      lastError = new RequestError(
        `HTTP ${response.status} from ${TOKEN_URL}: ${errorMessageFromBody(responseBody)}`,
        isRetriableStatus(response.status)
      );

      if (!lastError.retriable || attempt === MAX_ATTEMPTS) {
        throw lastError;
      }
    } catch (error) {
      lastError = error;

      if (error instanceof RequestError && !error.retriable) {
        throw error;
      }

      if (attempt === MAX_ATTEMPTS) {
        throw lastError;
      }
    }

    await delay(1000 * attempt);
  }

  throw lastError;
}

async function resolveAccessToken() {
  if (accessToken) {
    return accessToken;
  }

  if (!process.env.FIREBASE_SERVICE_ACCOUNT_JSON) {
    throw new Error("FIREBASE_SERVICE_ACCOUNT_JSON or FIREBASE_ACCESS_TOKEN is required.");
  }

  const serviceAccount = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT_JSON);

  if (!serviceAccount.client_email || !serviceAccount.private_key) {
    throw new Error("FIREBASE_SERVICE_ACCOUNT_JSON must include client_email and private_key.");
  }

  const now = Math.floor(Date.now() / 1000);
  const header = base64UrlEncode(
    JSON.stringify({
      alg: "RS256",
      typ: "JWT"
    })
  );
  const payload = base64UrlEncode(
    JSON.stringify({
      iss: serviceAccount.client_email,
      scope: FIREBASE_HOSTING_SCOPE,
      aud: TOKEN_URL,
      iat: now,
      exp: now + 3600
    })
  );
  const unsignedJwt = `${header}.${payload}`;
  const signature = createSign("RSA-SHA256").update(unsignedJwt).sign(serviceAccount.private_key);
  const assertion = `${unsignedJwt}.${base64UrlEncode(signature)}`;

  return requestAccessToken(assertion);
}

async function readHostingConfig() {
  const firebaseJsonPath = path.join(cwd, "firebase.json");
  const firebaseJson = JSON.parse(await readFile(firebaseJsonPath, "utf8"));
  const hostingConfig = Array.isArray(firebaseJson.hosting)
    ? firebaseJson.hosting.find((config) => config.site === site) ?? firebaseJson.hosting[0]
    : firebaseJson.hosting;

  if (!hostingConfig) {
    throw new Error("firebase.json does not define a hosting config.");
  }

  return hostingConfig;
}

function convertHeaders(headers = []) {
  return headers.map((entry) => ({
    glob: entry.source ?? entry.glob,
    headers: Object.fromEntries(entry.headers.map((header) => [header.key, header.value]))
  }));
}

function convertRewrites(rewrites = []) {
  return rewrites.map((entry) => {
    const rewrite = {
      glob: entry.source ?? entry.glob
    };

    if (entry.destination) {
      rewrite.path = entry.destination;
    }

    if (entry.function) {
      rewrite.function = entry.function;
    }

    if (entry.run) {
      rewrite.run = entry.run;
    }

    return rewrite;
  });
}

function toVersionConfig(hostingConfig) {
  const config = {};

  if (hostingConfig.headers?.length) {
    config.headers = convertHeaders(hostingConfig.headers);
  }

  if (hostingConfig.rewrites?.length) {
    config.rewrites = convertRewrites(hostingConfig.rewrites);
  }

  return config;
}

function shouldIgnore(relativePath) {
  const normalized = relativePath.replaceAll(path.sep, "/");
  const parts = normalized.split("/");

  return (
    normalized === "firebase.json" ||
    parts.includes("node_modules") ||
    parts.some((part) => part.startsWith("."))
  );
}

async function collectFiles(rootDir, currentDir = rootDir, files = {}, compressedByHash = new Map()) {
  const entries = (await readdir(currentDir, { withFileTypes: true })).sort((a, b) =>
    a.name.localeCompare(b.name)
  );

  for (const entry of entries) {
    const fullPath = path.join(currentDir, entry.name);
    const relativePath = path.relative(rootDir, fullPath);

    if (shouldIgnore(relativePath)) {
      continue;
    }

    if (entry.isDirectory()) {
      await collectFiles(rootDir, fullPath, files, compressedByHash);
      continue;
    }

    if (!entry.isFile()) {
      continue;
    }

    const fileContents = await readFile(fullPath);
    const compressed = gzipSync(fileContents, { level: 9 });
    const hash = createHash("sha256").update(compressed).digest("hex");
    const firebasePath = `/${relativePath.replaceAll(path.sep, "/")}`;

    files[firebasePath] = hash;
    compressedByHash.set(hash, compressed);
  }

  return { files, compressedByHash };
}

function requireUploadBody(hash, compressedByHash) {
  const compressed = compressedByHash.get(hash);

  if (!compressed) {
    throw new Error(`Missing compressed file content for hash ${hash}.`);
  }

  const formData = new FormData();
  formData.append("file", new Blob([compressed]), hash);
  return formData;
}

async function writeGithubOutput(outputs) {
  if (!process.env.GITHUB_OUTPUT) {
    return;
  }

  const lines = Object.entries(outputs).map(([key, value]) => {
    const escapedValue = String(value)
      .replaceAll("%", "%25")
      .replaceAll("\r", "%0D")
      .replaceAll("\n", "%0A");

    return `${key}=${escapedValue}`;
  });

  await appendFile(process.env.GITHUB_OUTPUT, `${lines.join("\n")}\n`);
}

async function ensurePreviewChannel(parent) {
  if (channelId === "live") {
    return undefined;
  }

  const channelName = `${parent}/channels/${encodeURIComponent(channelId)}`;

  return requestJson(`${API_BASE}/${channelName}?updateMask=${encodeURIComponent("ttl")}`, {
    method: "PATCH",
    body: {
      ttl: channelTtl
    }
  });
}

async function main() {
  accessToken = await resolveAccessToken();

  const hostingConfig = await readHostingConfig();
  const publicDir = path.resolve(cwd, hostingConfig.public ?? "public");

  if (!existsSync(publicDir)) {
    throw new Error(`Hosting public directory does not exist: ${publicDir}`);
  }

  const versionConfig = toVersionConfig(hostingConfig);
  const { files, compressedByHash } = await collectFiles(publicDir);
  const fileCount = Object.keys(files).length;

  const parent = `projects/${encodeURIComponent(project)}/sites/${encodeURIComponent(site)}`;
  const releaseParent = `${parent}/channels/${encodeURIComponent(channelId)}`;

  console.log(`Preparing Firebase Hosting deploy for ${site}/${channelId}: ${fileCount} files.`);

  await ensurePreviewChannel(parent);

  const version = await requestJson(`${API_BASE}/${parent}/versions`, {
    method: "POST",
    body: {}
  });

  if (!version.name) {
    throw new Error(`Firebase did not return a version name: ${JSON.stringify(version)}`);
  }

  console.log(`Created Firebase Hosting version ${version.name}.`);

  const populate = await requestJson(`${API_BASE}/${version.name}:populateFiles`, {
    method: "POST",
    body: {
      files
    }
  });

  const uploadRequiredHashes = populate.uploadRequiredHashes ?? [];
  console.log(`Uploading ${uploadRequiredHashes.length} required file hash(es).`);

  for (const hash of uploadRequiredHashes) {
    await requestMultipart(`${populate.uploadUrl}/${hash}`, () =>
      requireUploadBody(hash, compressedByHash)
    );
  }

  await requestJson(
    `${API_BASE}/${version.name}?updateMask=${encodeURIComponent("status,config")}`,
    {
      method: "PATCH",
      body: {
        status: "FINALIZED",
        config: versionConfig
      }
    }
  );

  console.log(`Finalized Firebase Hosting version ${version.name}.`);

  await requestJson(
    `${API_BASE}/${releaseParent}/releases?versionName=${encodeURIComponent(version.name)}`,
    {
      method: "POST",
      body: {},
      allowCurrentActive: true
    }
  );

  const channel = await requestJson(`${API_BASE}/${releaseParent}`, {
    method: "GET"
  });
  const hostingUrl = channel.url ?? "";

  await writeGithubOutput({
    hosting_url: hostingUrl,
    channel_id: channelId,
    version_name: version.name
  });

  console.log(`Released Firebase Hosting version ${version.name} to ${site}/${channelId}.`);

  if (hostingUrl) {
    console.log(`Firebase Hosting URL: ${hostingUrl}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

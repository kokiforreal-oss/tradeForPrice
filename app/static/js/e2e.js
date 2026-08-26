const E2E_NAME_KEYS = new Set(["customer_name", "supplier_name", "partner_name", "supplier_bank", "supplier_account"]);
const E2E_MONEY_KEYS = new Set([
  "total",
  "amount",
  "unit_price",
  "target_price",
  "cost_price",
  "cash_discount",
  "this_amount",
  "discount_amount",
  "tax_amount",
  "freight",
  "extra_tax",
  "deposit",
  "first_payment_amount",
  "balance_amount",
  "settle_total",
  "final_amount",
  "pending",
  "unpaid_total",
  "contract_amount",
  "received",
  "paid",
  "written",
  "written_off",
  "open_ar",
  "open_ap",
  "invoiced",
  "po_amount",
  "so_amount",
  "profit",
  "order_amount",
  "quote_total",
  "remaining",
  "goods_amount",
  "payable",
  "alloc_cash",
  "alloc_discount",
  "open",
]);
const E2E_QUERY_NAME_KEYS = new Set(["partner", "customer_name", "supplier_name", "partner_name"]);

let e2eAesKey = null;
let e2eHmacKey = null;

function e2eSubtle() {
  const subtle = globalThis.crypto && globalThis.crypto.subtle;
  if (!subtle) {
    throw new Error("当前是 HTTP 公网访问，浏览器禁止加密接口。请用 https:// 打开后再登录（或本机 http://127.0.0.1）。");
  }
  return subtle;
}

function e2eIsEnc(v) {
  return typeof v === "string" && (v.startsWith("m1.") || v.startsWith("n1."));
}

function e2eBytesToB64url(bytes) {
  let bin = "";
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  for (let i = 0; i < arr.length; i++) bin += String.fromCharCode(arr[i]);
  return btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function e2eB64urlToBytes(text) {
  const pad = "=".repeat((4 - (text.length % 4)) % 4);
  const b64 = (text + pad).replaceAll("-", "+").replaceAll("_", "/");
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function e2eB64ToBytes(text) {
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function e2eLoadKeys() {
  if (e2eAesKey) return true;
  const tok = localStorage.getItem("token") || "";
  if (!tok) return false;
  const res = await fetch("/api/crypto/org-key", { headers: { Authorization: "Bearer " + tok } });
  if (!res.ok) return false;
  const data = await res.json();
  const raw = e2eB64ToBytes(data.key_b64);
  e2eAesKey = await e2eSubtle().importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
  e2eHmacKey = await e2eSubtle().importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return true;
}

function e2eClearKeys() {
  e2eAesKey = null;
  e2eHmacKey = null;
}

async function e2eEncryptRaw(plain, iv) {
  const buf = await e2eSubtle().encrypt({ name: "AES-GCM", iv }, e2eAesKey, new TextEncoder().encode(plain));
  const packed = new Uint8Array(iv.byteLength + buf.byteLength);
  packed.set(new Uint8Array(iv), 0);
  packed.set(new Uint8Array(buf), iv.byteLength);
  return e2eBytesToB64url(packed);
}

async function e2eDecryptBlob(blob) {
  const raw = e2eB64urlToBytes(blob);
  const iv = raw.slice(0, 12);
  const data = raw.slice(12);
  const buf = await e2eSubtle().decrypt({ name: "AES-GCM", iv }, e2eAesKey, data);
  return new TextDecoder().decode(buf);
}

async function e2eEncryptMoney(value) {
  if (value === null || value === undefined || value === "") return value;
  if (e2eIsEnc(value)) return value;
  if (!e2eAesKey) return value;
  const n = Number(value);
  const plain = Number.isFinite(n) ? (Math.round(n * 100) / 100).toFixed(2) : String(value);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  return "m1." + (await e2eEncryptRaw(plain, iv));
}

async function e2eEncryptName(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  if (e2eIsEnc(text)) return text;
  if (!e2eHmacKey || !e2eAesKey) return text;
  const sig = await e2eSubtle().sign("HMAC", e2eHmacKey, new TextEncoder().encode("n1|" + text));
  const iv = new Uint8Array(sig).slice(0, 12);
  return "n1." + (await e2eEncryptRaw(text, iv));
}

async function e2eDecryptOne(value) {
  if (!e2eIsEnc(value) || !e2eAesKey) return value;
  try {
    if (value.startsWith("m1.")) return await e2eDecryptBlob(value.slice(3));
    return await e2eDecryptBlob(value.slice(3));
  } catch {
    return value;
  }
}

async function e2eWalkEncrypt(node) {
  if (!e2eAesKey || node == null) return node;
  if (Array.isArray(node)) return Promise.all(node.map((item) => e2eWalkEncrypt(item)));
  if (typeof node !== "object") return node;
  const keys = Object.keys(node);
  const vals = await Promise.all(
    keys.map((k) => {
      const v = node[k];
      if (v == null) return v;
      if (E2E_NAME_KEYS.has(k) && (typeof v === "string" || typeof v === "number")) return e2eEncryptName(v);
      if (E2E_MONEY_KEYS.has(k) && (typeof v === "number" || typeof v === "string")) return e2eEncryptMoney(v);
      if (typeof v === "object") return e2eWalkEncrypt(v);
      return v;
    })
  );
  const out = {};
  for (let i = 0; i < keys.length; i++) out[keys[i]] = vals[i];
  return out;
}

async function e2eWalkDecrypt(node) {
  if (node == null) return node;
  if (typeof node === "string") {
    if (e2eIsEnc(node) && e2eAesKey) return e2eDecryptOne(node);
    return node;
  }
  if (typeof node !== "object") return node;
  if (Array.isArray(node)) return Promise.all(node.map((item) => e2eWalkDecrypt(item)));
  const keys = Object.keys(node);
  const vals = await Promise.all(keys.map((k) => e2eWalkDecrypt(node[k])));
  const out = {};
  for (let i = 0; i < keys.length; i++) out[keys[i]] = vals[i];
  return out;
}

async function e2eProtectPath(path) {
  if (!e2eAesKey || !path) return path;
  const u = new URL(path, location.origin);
  let changed = false;
  for (const key of [...u.searchParams.keys()]) {
    if (!E2E_QUERY_NAME_KEYS.has(key)) continue;
    const val = u.searchParams.get(key);
    if (!val || e2eIsEnc(val)) continue;
    u.searchParams.set(key, await e2eEncryptName(val));
    changed = true;
  }
  return changed ? u.pathname + u.search : path;
}

function e2eSkipPath(path) {
  return path.startsWith("/api/auth/login") || path.startsWith("/api/crypto/") || path.startsWith("/api/assistant");
}

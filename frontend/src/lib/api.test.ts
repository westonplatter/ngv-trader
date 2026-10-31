import { afterEach, describe, expect, test } from "bun:test";
import { API_BASE_URL } from "../config";
import {
  ApiError,
  api,
  errorMessage,
  query,
  readErrorMessage,
  request,
  setApiFetch,
} from "./api";

type Call = { url: string; init?: RequestInit };

// Install a transport that records each call and answers with `respond`.
function stub(respond: (call: Call) => Response): Call[] {
  const calls: Call[] = [];
  setApiFetch(async (url, init) => {
    const call = { url, init };
    calls.push(call);
    return respond(call);
  });
  return calls;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => setApiFetch(null));

describe("request", () => {
  test("prefixes the API base and decodes JSON", async () => {
    const calls = stub(() => json({ ok: 1 }));
    const result = await api.get<{ ok: number }>("/positions");
    expect(result).toEqual({ ok: 1 });
    expect(calls[0].url).toBe(`${API_BASE_URL}/positions`);
    expect(calls[0].init?.method).toBe("GET");
    expect(calls[0].init?.body).toBeUndefined();
  });

  test("encodes a JSON body with the content-type header", async () => {
    const calls = stub(() => json({ id: 7 }, 201));
    await api.post("/tags", { value: "long-beta" });
    expect(calls[0].init?.method).toBe("POST");
    expect(calls[0].init?.headers).toEqual({
      "Content-Type": "application/json",
    });
    expect(calls[0].init?.body).toBe(JSON.stringify({ value: "long-beta" }));
  });

  test("resolves undefined on 204 and on an empty body", async () => {
    stub(() => new Response(null, { status: 204 }));
    expect(await api.delete("/tasks/1")).toBeUndefined();
    stub(() => new Response("", { status: 200 }));
    expect(await api.get("/nothing")).toBeUndefined();
  });

  test("uses another base when asked", async () => {
    const calls = stub(() => json({}));
    await api.post("/expected-pnl", {}, { base: "/pricing-api" });
    expect(calls[0].url).toBe("/pricing-api/expected-pnl");
  });

  test("throws ApiError carrying the API detail", async () => {
    stub(() => json({ detail: "Tag already exists" }, 409));
    const err = await api.post("/tags", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    expect((err as ApiError).message).toBe("Tag already exists");
  });

  test("falls back to the caller's label and the status", async () => {
    stub(() => new Response("", { status: 500 }));
    const err = await request("GET", "/x", { fallback: "Unable to load" }).catch(
      (e: unknown) => e,
    );
    expect((err as ApiError).message).toBe("Unable to load (500)");
  });
});

describe("readErrorMessage", () => {
  test("prefers detail, then a plain-text body, then the status", async () => {
    expect(
      await readErrorMessage(json({ detail: "bad filter" }, 400)),
    ).toBe("bad filter");
    expect(
      await readErrorMessage(new Response("worker offline", { status: 503 })),
    ).toBe("worker offline");
    expect(
      await readErrorMessage(new Response("<html>", { status: 502 })),
    ).toBe("HTTP 502");
  });
});

describe("helpers", () => {
  test("query drops empty values and repeats arrays", () => {
    expect(
      query({ q: "cl", include_archived: undefined, any: ["a", "b"], n: "" }),
    ).toBe("?q=cl&any=a&any=b");
    expect(query({})).toBe("");
  });

  test("errorMessage reads an Error and otherwise the fallback", () => {
    expect(errorMessage(new Error("boom"), "x")).toBe("boom");
    expect(errorMessage("boom", "x")).toBe("x");
  });
});

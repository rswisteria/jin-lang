import { expect, test } from "vitest";

import { mulberry32 } from "../src/random";

test("同じ種なら同じ列、違う種なら違う列、値は [0, 1)", () => {
	const a = mulberry32(41);
	const b = mulberry32(41);
	const c = mulberry32(42);
	const xs = Array.from({ length: 50 }, () => a());
	expect(Array.from({ length: 50 }, () => b())).toEqual(xs);
	expect(Array.from({ length: 50 }, () => c())).not.toEqual(xs);
	expect(xs.every((x) => x >= 0 && x < 1)).toBe(true);
});

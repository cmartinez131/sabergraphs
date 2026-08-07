import { applyLabelMapToText, labelizeId } from "./labels";

describe("applyLabelMapToText", () => {
  test("replaces whole-word stat tokens using the label map", () => {
    expect(
      applyLabelMapToText("Top home_run in 2015", { home_run: "Home Runs" })
    ).toBe("Top Home Runs in 2015");
  });

  test("returns input untouched without a label map", () => {
    expect(applyLabelMapToText("woba by season", null)).toBe("woba by season");
  });
});

describe("labelizeId", () => {
  const lm = { woba: "wOBA", home_run: "Home Runs" };

  test("maps a bare stat id", () => {
    expect(labelizeId("woba", lm)).toBe("wOBA");
  });

  test("preserves the 'Projected ' prefix", () => {
    expect(labelizeId("Projected woba", lm)).toBe("Projected wOBA");
  });

  test("preserves the ' percentile' suffix", () => {
    expect(labelizeId("home_run percentile", lm)).toBe("Home Runs percentile");
  });

  test("falls back to the raw id when unmapped", () => {
    expect(labelizeId("mystery_stat", lm)).toBe("mystery_stat");
  });
});

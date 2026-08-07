import { sanitizeFileName, csvFromBarOrLine } from "./csv";

describe("sanitizeFileName", () => {
  test("replaces unsafe characters", () => {
    expect(sanitizeFileName("Top 10: HR/2015")).toBe("Top_10_HR_2015");
  });

  test("defaults to 'chart' when empty", () => {
    expect(sanitizeFileName("")).toBe("chart");
  });
});

describe("csvFromBarOrLine", () => {
  test("single series produces x column + labeled value column", () => {
    const series = [
      {
        id: "home_run",
        data: [
          { x: "Chris Davis", y: 47 },
          { x: "Mike Trout", y: 41 },
        ],
      },
    ];
    const csv = csvFromBarOrLine(series, { label_map: { home_run: "Home Runs" } });
    expect(csv.split("\n")).toEqual([
      "Player,Home Runs",
      "Chris Davis,47",
      "Mike Trout,41",
    ]);
  });

  test("escapes cells containing commas and quotes", () => {
    const series = [{ id: "hr", data: [{ x: 'Say "Hey", Kid', y: 10 }] }];
    const csv = csvFromBarOrLine(series, {});
    expect(csv.split("\n")[1]).toBe('"Say ""Hey"", Kid",10');
  });

  test("multi-series pivots to one column per series, years sorted", () => {
    const series = [
      { id: "David Ortiz", data: [{ x: 2016, y: 38 }, { x: 2015, y: 37 }] },
      { id: "Torii Hunter", data: [{ x: 2015, y: 22 }] },
    ];
    const csv = csvFromBarOrLine(series, {});
    expect(csv.split("\n")).toEqual([
      "Year,David Ortiz,Torii Hunter",
      "2015,37,22",
      "2016,38,",
    ]);
  });
});

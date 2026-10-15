import {
  distribute,
  distributePositive,
  evenRows,
  evenValues,
  initialValues,
  isEvenSplit,
  makeRows,
  rowsTotal,
  sameAllocations,
  setRowValue,
  summarize,
  toAllocationWrites,
  toggleLock,
  unallocated,
} from "./allocation";

const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
const values = (rows: { value: number }[]) => rows.map((row) => row.value);

describe("distribute", () => {
  it("splits by weight and always sums to the total", () => {
    expect(distribute(100, [1, 1, 1])).toEqual([34, 33, 33]);
    expect(distribute(100, [2, 1])).toEqual([67, 33]);
    expect(distribute(10, [1, 1, 1, 1, 1, 1, 1])).toEqual([2, 2, 2, 1, 1, 1, 1]);
    for (const total of [0, 1, 7, 99, 100]) {
      for (const weights of [[1], [1, 2], [5, 5, 5], [3, 0, 9, 1]]) {
        expect(sum(distribute(total, weights))).toBe(total);
      }
    }
  });

  it("falls back to an even split when every weight is zero and ignores negatives", () => {
    expect(distribute(100, [0, 0])).toEqual([50, 50]);
    expect(distribute(100, [-5, 10])).toEqual([0, 100]);
  });

  it("breaks fraction ties toward the earlier row", () => {
    expect(distribute(2, [1, 1, 1])).toEqual([1, 1, 0]);
  });

  it("handles no rows and rounds a fractional total", () => {
    expect(distribute(100, [])).toEqual([]);
    expect(distribute(99.6, [1, 1])).toEqual([50, 50]);
  });
});

describe("evenValues", () => {
  it("gives the extra percents to the first rows", () => {
    expect(evenValues(2)).toEqual([50, 50]);
    expect(evenValues(3)).toEqual([34, 33, 33]);
    expect(evenValues(6)).toEqual([17, 17, 17, 17, 16, 16]);
    expect(evenValues(0)).toEqual([]);
  });
});

describe("distributePositive", () => {
  it("never gives a row less than 1", () => {
    expect(distributePositive(100, [1, 1, 98])).toEqual([1, 1, 98]);
    expect(distributePositive(3, [50, 50, 50])).toEqual([1, 1, 1]);
    expect(distributePositive(100, [1, 99])).toEqual([1, 99]);
  });

  it("keeps the total when it can", () => {
    expect(sum(distributePositive(90, [60, 30, 10]))).toBe(90);
    expect(distributePositive(60, [30, 30])).toEqual([30, 30]);
  });
});

describe("initialValues", () => {
  it("is an even split when nothing is stored", () => {
    expect(initialValues([{ id: 1, name: "a" }, { id: 2, name: "b" }])).toEqual([50, 50]);
    expect(initialValues([{ id: 1, name: "a", bp: 0 }, { id: 2, name: "b", bp: 0 }, { id: 3, name: "c" }])).toEqual([34, 33, 33]);
  });

  it("reads stored basis points as whole percents", () => {
    expect(initialValues([{ id: 1, name: "a", bp: 6000 }, { id: 2, name: "b", bp: 4000 }])).toEqual([60, 40]);
  });

  it("rounds 3333/3333/3334 back to 100% with the largest remainder", () => {
    const rows = [
      { id: 1, name: "a", bp: 3333 },
      { id: 2, name: "b", bp: 3333 },
      { id: 3, name: "c", bp: 3334 },
    ];
    const result = initialValues(rows);
    expect(sum(result)).toBe(100);
    expect(result).toEqual([33, 33, 34]);
  });

  it("keeps a partial split partial", () => {
    expect(initialValues([{ id: 1, name: "a", bp: 5000 }, { id: 2, name: "b", bp: 2000 }])).toEqual([50, 20]);
  });

  it("scales a legacy over-allocation (10000bp each) back to 100%", () => {
    expect(initialValues([{ id: 1, name: "a", bp: 10000 }, { id: 2, name: "b", bp: 10000 }])).toEqual([50, 50]);
    expect(initialValues([{ id: 1, name: "a", bp: 10000 }, { id: 2, name: "b", bp: 10000 }, { id: 3, name: "c", bp: 10000 }])).toEqual([34, 33, 33]);
  });
});

describe("makeRows", () => {
  it("orders by id and can ignore stored values", () => {
    const items = [
      { id: 9, name: "later", bp: 7000 },
      { id: 2, name: "earlier", bp: 3000 },
    ];
    expect(makeRows(items).map((row) => [row.id, row.value])).toEqual([[2, 30], [9, 70]]);
    expect(values(makeRows(items, true))).toEqual([50, 50]);
    expect(makeRows(items).every((row) => !row.locked)).toBe(true);
  });
});

describe("setRowValue", () => {
  const three = () => makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }, { id: 3, name: "c" }], true);

  it("rebalances the other rows in proportion and keeps the total at 100", () => {
    const rows = setRowValue(makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }]), 0, 70);
    expect(values(rows)).toEqual([70, 30]);
    const next = setRowValue(three(), 0, 50);
    expect(values(next)).toEqual([50, 25, 25]);
    expect(rowsTotal(next)).toBe(100);
  });

  it("clamps so every other unlocked row keeps 1%", () => {
    expect(values(setRowValue(three(), 0, 100))).toEqual([98, 1, 1]);
    expect(values(setRowValue(three(), 0, 0))).toEqual([1, 50, 49]);
    expect(values(setRowValue(three(), 0, Number.NaN))).toEqual([1, 50, 49]);
  });

  it("rounds fractional input", () => {
    expect(values(setRowValue(makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }]), 0, 33.6))).toEqual([34, 66]);
  });

  it("leaves locked rows alone and shares only what is left", () => {
    let rows = three();
    rows = toggleLock(rows, 2); // c locked at 33
    rows = setRowValue(rows, 0, 50);
    expect(rows[2]!.value).toBe(33);
    expect(values(rows)).toEqual([50, 17, 33]);
    expect(rowsTotal(rows)).toBe(100);
    expect(rows[2]!.locked).toBe(true);
  });

  it("ignores edits to a locked row", () => {
    const rows = toggleLock(three(), 0);
    expect(setRowValue(rows, 0, 90)).toBe(rows);
  });

  it("caps a row at what the locked rows leave over", () => {
    let rows = three();
    rows = toggleLock(rows, 1);
    rows = toggleLock(rows, 2); // 33 + 33 locked, 34 free
    expect(values(setRowValue(rows, 0, 100))).toEqual([34, 33, 33]);
  });

  it("lets the total fall short of 100 when no other row is free", () => {
    let rows = makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }], true);
    rows = toggleLock(rows, 1); // b locked at 50
    rows = setRowValue(rows, 0, 20);
    expect(values(rows)).toEqual([20, 50]);
    expect(unallocated(rows)).toBe(30);
  });

  it("does not mutate its input", () => {
    const rows = three();
    const snapshot = JSON.stringify(rows);
    setRowValue(rows, 0, 70);
    expect(JSON.stringify(rows)).toBe(snapshot);
  });
});

describe("even split", () => {
  it("detects the even split only while nothing is locked", () => {
    const rows = makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }, { id: 3, name: "c" }], true);
    expect(isEvenSplit(rows)).toBe(true);
    expect(isEvenSplit(toggleLock(rows, 0))).toBe(false);
    expect(isEvenSplit(setRowValue(rows, 0, 60))).toBe(false);
  });

  it("evenRows resets values and releases locks", () => {
    let rows = makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }], true);
    rows = toggleLock(setRowValue(rows, 0, 80), 0);
    const reset = evenRows(rows);
    expect(values(reset)).toEqual([50, 50]);
    expect(reset.some((row) => row.locked)).toBe(false);
    expect(isEvenSplit(reset)).toBe(true);
  });
});

describe("API conversion", () => {
  it("converts percents to basis points, in id order, totalling 10000", () => {
    const rows = makeRows([{ id: 3, name: "c" }, { id: 1, name: "a" }, { id: 2, name: "b" }], true);
    const writes = toAllocationWrites(rows);
    expect(writes).toEqual([
      { subproject_id: 1, allocation_bp: 3400 },
      { subproject_id: 2, allocation_bp: 3300 },
      { subproject_id: 3, allocation_bp: 3300 },
    ]);
    expect(sum(writes.map((w) => w.allocation_bp))).toBe(10000);
    expect(writes.every((w) => w.allocation_bp >= 1 && w.allocation_bp % 100 === 0)).toBe(true);
  });

  it("every edit leaves values the API accepts", () => {
    let rows = makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }, { id: 3, name: "c" }, { id: 4, name: "d" }], true);
    for (const [index, raw] of [[0, 97], [3, 1], [1, 40], [2, 55]] as const) {
      rows = setRowValue(rows, index, raw);
      const writes = toAllocationWrites(rows);
      expect(writes.every((w) => w.allocation_bp >= 100)).toBe(true);
      expect(sum(writes.map((w) => w.allocation_bp))).toBeLessThanOrEqual(10000);
    }
  });

  it("compares splits regardless of order", () => {
    const a = [{ subproject_id: 1, allocation_bp: 6000 }, { subproject_id: 2, allocation_bp: 4000 }];
    expect(sameAllocations(a, [...a].reverse())).toBe(true);
    expect(sameAllocations(a, [{ subproject_id: 1, allocation_bp: 5000 }, { subproject_id: 2, allocation_bp: 5000 }])).toBe(false);
    expect(sameAllocations(a, [a[0]!])).toBe(false);
  });
});

describe("summarize", () => {
  it("reads like the old collapsed header", () => {
    const even = makeRows([{ id: 1, name: "a" }, { id: 2, name: "b" }], true);
    expect(summarize(even)).toBe("Even split · 50 / 50");
    expect(summarize(setRowValue(even, 0, 70))).toBe("Custom · 70 / 30");
    expect(summarize(setRowValue(toggleLock(even, 1), 0, 20))).toBe("Custom · 20 / 50 · 30% unallocated");
  });
});

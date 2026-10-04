import { Commit } from './forge.models';

/** Lane layout of a commit list (newest first) for a small git graph drawn row by row. */
export interface GraphRow {
  lane: number;            // column of this commit's node
  width: number;           // lanes used by this row (max of before/after)
  /** Segments in row-local coordinates: from (x1, y1) to (x2, y2), y ∈ {0 top, 1 centre, 2 bottom}. */
  segs: { x1: number; y1: number; x2: number; y2: number; c: number }[];
  color: number;
}

export function layoutGraph(commits: Commit[]): GraphRow[] {
  let lanes: (string | null)[] = [];
  const colorOf = new Map<string, number>();
  let nextColor = 0;
  const rows: GraphRow[] = [];

  for (const c of commits) {
    let lane = lanes.indexOf(c.sha);
    if (lane < 0) {
      lane = lanes.indexOf(null);
      if (lane < 0) { lane = lanes.length; lanes.push(null); }
      lanes[lane] = c.sha;
      colorOf.set(c.sha, nextColor++ % 8);
    }
    const color = colorOf.get(c.sha) ?? 0;
    const before = [...lanes];
    const segs: GraphRow['segs'] = [];

    // Other lanes waiting for this same commit merge into its node.
    before.forEach((sha, j) => {
      if (sha === c.sha && j !== lane) { segs.push({ x1: j, y1: 0, x2: lane, y2: 1, c: colorOf.get(sha) ?? 0 }); lanes[j] = null; }
    });
    // Incoming line into the node (only if a child above pointed here).
    if (rows.length && rows[rows.length - 1].segs.some(s => s.y2 === 2 && s.x2 === lane)) segs.push({ x1: lane, y1: 0, x2: lane, y2: 1, c: color });

    // Parents: first keeps the lane, others reuse a lane already waiting for them or open a new one.
    lanes[lane] = c.parents[0] ?? null;
    if (c.parents[0] && !colorOf.has(c.parents[0])) colorOf.set(c.parents[0], color);
    if (c.parents[0]) segs.push({ x1: lane, y1: 1, x2: lane, y2: 2, c: color });
    for (const p of c.parents.slice(1)) {
      let pl = lanes.indexOf(p);
      if (pl < 0) {
        pl = lanes.indexOf(null);
        if (pl < 0) { pl = lanes.length; lanes.push(null); }
        lanes[pl] = p;
        if (!colorOf.has(p)) colorOf.set(p, nextColor++ % 8);
      }
      segs.push({ x1: lane, y1: 1, x2: pl, y2: 2, c: colorOf.get(p) ?? 0 });
    }
    // Pass-through lanes.
    lanes.forEach((sha, j) => {
      if (sha && j !== lane && before[j] === sha) segs.push({ x1: j, y1: 0, x2: j, y2: 2, c: colorOf.get(sha) ?? 0 });
    });
    while (lanes.length && lanes[lanes.length - 1] === null) lanes.pop();
    rows.push({ lane, width: Math.max(before.length, lanes.length, lane + 1), segs, color });
  }
  return rows;
}

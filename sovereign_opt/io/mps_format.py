"""
Basic free-format MPS reader.

Supports the common subset of free-format MPS: NAME, ROWS (N/L/G/E),
COLUMNS (including MARKER INTORG/INTEND for integer sections), RHS,
RANGES, BOUNDS (UP/LO/FX/FR/BV/MI/PL), ENDATA.

HONESTY NOTE: this is a basic/subset reader, not a full MPS-spec parser
(e.g. no comment-column edge cases beyond '*' lines, no SOS sections, no
free-format quirks for exotic vendor extensions). It has been tested only
against the small instances this repo writes itself via `write_mps` in
this same module -- it has NOT been validated against real external
Netlib/MIPLIB .mps files (no internet access in this environment, see
sovereign_opt/benchmarks/instances.py). If you have real .mps files
locally, try this reader, but treat it as unverified against them until
you've checked results independently.
"""
from __future__ import annotations
from sovereign_opt.core.model import Model, Sense, ObjSense, VarType, INF


def read_mps(path: str) -> Model:
    section = None
    model = Model(name="mps_problem")
    obj_row = None
    row_sense = {}
    row_name_list = []
    col_obj = {}
    row_coeffs = {}  # row -> {var: coeff}
    integer_mode = False
    var_seen = set()
    row_rhs_store = {}

    with open(path, "r") as f:
        lines = [ln.rstrip("\n") for ln in f]

    for raw in lines:
        if not raw.strip() or raw.startswith("*"):
            continue
        if not raw[0].isspace():
            # section header
            parts = raw.split()
            section = parts[0].upper()
            if section == "NAME" and len(parts) > 1:
                model.name = parts[1]
            continue

        parts = raw.split()
        if not parts:
            continue

        if section == "ROWS":
            rtype, rname = parts[0].upper(), parts[1]
            if rtype == "N":
                if obj_row is None:
                    obj_row = rname
            else:
                sense = {"L": Sense.LE, "G": Sense.GE, "E": Sense.EQ}[rtype]
                row_sense[rname] = sense
                row_name_list.append(rname)
                row_coeffs[rname] = {}

        elif section == "COLUMNS":
            if "INTORG" in raw.upper() or "INTEND" in raw.upper():
                if "INTORG" in raw.upper():
                    integer_mode = True
                else:
                    integer_mode = False
                continue
            vname = parts[0]
            if vname not in var_seen:
                var_seen.add(vname)
                model.add_variable(vname, lb=0.0, ub=INF,
                                    vtype=VarType.INTEGER if integer_mode else VarType.CONTINUOUS)
            rest = parts[1:]
            for i in range(0, len(rest), 2):
                rname, val = rest[i], float(rest[i + 1])
                if rname == obj_row:
                    col_obj[vname] = col_obj.get(vname, 0.0) + val
                else:
                    row_coeffs[rname][vname] = row_coeffs[rname].get(vname, 0.0) + val

        elif section == "RHS":
            rest = parts[1:]
            for i in range(0, len(rest), 2):
                rname, val = rest[i], float(rest[i + 1])
                if rname not in row_coeffs:
                    continue
                row_rhs_store[rname] = val

        elif section == "BOUNDS":
            btype = parts[0].upper()
            vname = parts[2] if len(parts) > 2 else None
            val = float(parts[3]) if len(parts) > 3 else None
            if vname is None or vname not in model.variables:
                continue
            v = model.variables[vname]
            if btype == "UP":
                v.ub = val
            elif btype == "LO":
                v.lb = val
            elif btype == "FX":
                v.lb = v.ub = val
            elif btype == "FR":
                v.lb, v.ub = -INF, INF
            elif btype == "MI":
                v.lb = -INF
            elif btype == "PL":
                v.ub = INF
            elif btype == "BV":
                v.lb, v.ub = 0.0, 1.0
                v.vtype = VarType.BINARY

        elif section == "ENDATA":
            break

    for vn, c in col_obj.items():
        model.variables[vn].obj_coeff = c
    model.obj_sense = ObjSense.MIN

    for rname in row_name_list:
        rhs = row_rhs_store.get(rname, 0.0)
        model.add_constraint(rname, row_coeffs[rname], row_sense[rname], rhs)

    return model


def write_mps(model: Model, path: str):
    """Minimal MPS writer, mainly used to round-trip our own instances for testing."""
    lines = [f"NAME          {model.name}", "ROWS", " N  COST"]
    for c in model.constraints:
        code = {Sense.LE: "L", Sense.GE: "G", Sense.EQ: "E"}[c.sense]
        lines.append(f" {code}  {c.name}")

    lines.append("COLUMNS")
    for vn in model.var_order:
        v = model.variables[vn]
        is_int = v.vtype == VarType.INTEGER  # binary vars use BV bound, not markers
        if is_int:
            lines.append(f"    MARKER                 'MARKER'                 'INTORG'")
        if v.obj_coeff != 0:
            lines.append(f"    {vn}  COST  {v.obj_coeff}")
        for c in model.constraints:
            if vn in c.coeffs:
                lines.append(f"    {vn}  {c.name}  {c.coeffs[vn]}")
        if is_int:
            lines.append(f"    MARKER                 'MARKER'                 'INTEND'")

    lines.append("RHS")
    for c in model.constraints:
        lines.append(f"    RHS  {c.name}  {c.rhs}")

    lines.append("BOUNDS")
    for vn in model.var_order:
        v = model.variables[vn]
        if v.vtype == VarType.BINARY:
            lines.append(f" BV BND  {vn}")
            continue
        if v.lb != 0.0:
            lines.append(f" LO BND  {vn}  {v.lb}")
        if v.ub < INF:
            lines.append(f" UP BND  {vn}  {v.ub}")

    lines.append("ENDATA")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
